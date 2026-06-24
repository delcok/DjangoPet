# -*- coding: utf-8 -*-
"""
adoption/views.py — 领养模块视图

权限矩阵:
- C端(小程序):  UserAuthentication + IsActiveUser
  其中宠物浏览用 OptionalUserAuthentication + AllowAny(未登录可逛,登录后多返回收藏/申请状态)
- 后台(管理员): ManagerAuthentication + HasModuleAccess(required_module='adoption')

无 service 层: 状态机/事务在 serializers 内,视图只做编排(查询优化、context 注入、计数)。
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet, ReadOnlyModelViewSet

from user.models import User

from utils.authentication import (ManagerAuthentication,
                                   OptionalUserAuthentication,
                                   UserAuthentication)
from utils.permission import AllowAny, HasModuleAccess, IsActiveUser

from .filters import (AdopterProfileFilter, AdoptionApplicationFilter,
                      AdoptionUpdateFilter, AdoptionUpdateTaskFilter,
                      AdoptionViolationFilter, StrayPetFilter)
from .models import (AdopterProfile, AdoptionApplication, AdoptionUpdate,
                     AdoptionUpdateTask, AdoptionViolation, PetFavorite,
                     PetMedia, StrayPet)
from .pagination import (AdminPagination, StandardPagination,
                         UpdateFeedCursorPagination)
from .serializers import (AdopterProfileAdminSerializer,
                          AdopterProfileSerializer,
                          AdoptionApplicationCreateSerializer,
                          AdoptionUpdateAdminSerializer,
                          AdoptionUpdateCreateSerializer,
                          AdoptionUpdatePublicSerializer,
                          AdoptionUpdateReviewSerializer,
                          AdoptionUpdateStaffCreateSerializer,
                          AdoptionUpdateTaskDetailSerializer,
                          AdoptionViolationCreateSerializer,
                          AdoptionViolationSerializer,
                          ApplicationAdminActionSerializer,
                          ApplicationAdminDetailSerializer,
                          ApplicationAdminListSerializer,
                          ApplicationCancelSerializer,
                          MyApplicationDetailSerializer,
                          MyApplicationListSerializer, PetFavoriteSerializer,
                          PetMediaSerializer, StrayPetAdminSerializer,
                          StrayPetDetailSerializer, StrayPetListSerializer, MyUpdateListSerializer)

# ════════════════════════════════════════════════════════════
# C端 — 小程序
# ════════════════════════════════════════════════════════════

class StrayPetViewSet(ReadOnlyModelViewSet):
    """
    宠物浏览(未登录可逛)
    GET  /pets/                列表(筛选见 StrayPetFilter,?has_quota=true 只看有名额)
    GET  /pets/{id}/           详情(浏览量+1;登录态附带 is_favorited / my_application)
    POST /pets/{id}/favorite/  收藏        DELETE 取消收藏
    GET  /pets/{id}/updates/   "领养后的TA"公开动态流(游标分页)
    """
    # C端可见状态: 草稿/暂停/离世不可见;已领养可见(展示成功案例与领养后动态)
    C_VISIBLE_STATUSES = ('available', 'full', 'handover', 'adopted')

    authentication_classes = [OptionalUserAuthentication]
    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = StrayPetFilter
    ordering_fields = ['created_at', 'favorite_count', 'view_count', 'sort_weight']
    ordering = ['-sort_weight', '-created_at']

    def get_queryset(self):
        qs = StrayPet.objects.filter(
            is_deleted=False, status__in=self.C_VISIBLE_STATUSES)
        if self.action == 'retrieve':
            qs = qs.prefetch_related('media')
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return StrayPetDetailSerializer
        return StrayPetListSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['favorited_pet_ids'] = getattr(self, '_favorited_pet_ids', None)
        ctx['my_application'] = getattr(self, '_my_application', None)
        return ctx

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else queryset
        # 一次性批量查当前页的收藏状态,避免 is_favorited 的 N+1
        if isinstance(request.user, User):
            pet_ids = [pet.id for pet in rows]
            self._favorited_pet_ids = set(
                PetFavorite.objects.filter(
                    user=request.user, pet_id__in=pet_ids
                ).values_list('pet_id', flat=True))
        serializer = self.get_serializer(rows, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # F() 原子自增浏览量,不锁行不丢更新
        StrayPet.objects.filter(pk=instance.pk).update(
            view_count=F('view_count') + 1)
        instance.view_count += 1  # 本次响应即时展示

        if isinstance(request.user, User):
            self._favorited_pet_ids = set(
                PetFavorite.objects.filter(
                    user=request.user, pet=instance
                ).values_list('pet_id', flat=True))
            self._my_application = (
                AdoptionApplication.objects
                .filter(pet=instance, applicant=request.user,
                        status__in=AdoptionApplication.ACTIVE_STATUSES)
                .order_by('-created_at').first())

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post', 'delete'],
            authentication_classes=[UserAuthentication],
            permission_classes=[IsActiveUser])
    def favorite(self, request, pk=None):
        pet = self.get_object()
        if request.method == 'POST':
            with transaction.atomic():
                _, created = PetFavorite.objects.get_or_create(
                    user=request.user, pet=pet)
                if created:
                    StrayPet.objects.filter(pk=pet.pk).update(
                        favorite_count=F('favorite_count') + 1)
            return Response({'favorited': True})
        # DELETE
        with transaction.atomic():
            deleted, _ = PetFavorite.objects.filter(
                user=request.user, pet=pet).delete()
            if deleted:
                # favorite_count__gt=0 防止并发下无符号字段减成负数报错
                StrayPet.objects.filter(pk=pet.pk, favorite_count__gt=0).update(
                    favorite_count=F('favorite_count') - 1)
        return Response({'favorited': False})

    @action(detail=True, methods=['get'])
    def updates(self, request, pk=None):
        """宠物详情页"领养后的TA": 仅公开、非异常、领养完成的动态"""
        pet = self.get_object()
        qs = (AdoptionUpdate.objects
              .filter(application__pet=pet, is_public=True,
                      application__status='completed')
              .exclude(review_status='abnormal')
              .select_related('task', 'application__applicant'))
        paginator = UpdateFeedCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = AdoptionUpdatePublicSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class MyApplicationViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                           mixins.RetrieveModelMixin, GenericViewSet):
    """
    我的领养申请
    POST /applications/              提交申请(状态机入口,逻辑在 Serializer.create)
    GET  /applications/?status=...   我的申请列表
    GET  /applications/{id}/         详情(状态时间线 + 打卡任务)
    POST /applications/{id}/cancel/  自助取消(approved 后不可自助取消)
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdoptionApplicationFilter

    def get_queryset(self):
        # 天然数据隔离: 只能看自己的申请
        qs = (AdoptionApplication.objects
              .filter(applicant=self.request.user)
              .select_related('pet')
              .order_by('-created_at'))
        if self.action == 'retrieve':
            qs = qs.prefetch_related('status_logs', 'update_tasks')
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return AdoptionApplicationCreateSerializer
        if self.action == 'retrieve':
            return MyApplicationDetailSerializer
        return MyApplicationListSerializer

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        application = self.get_object()
        serializer = ApplicationCancelSerializer(
            data=request.data,
            context={'request': request, 'application': application})
        serializer.is_valid(raise_exception=True)
        application = serializer.save()
        return Response(MyApplicationListSerializer(
            application, context=self.get_serializer_context()).data)


class MyUpdateViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                      GenericViewSet):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    pagination_class = StandardPagination

    def get_queryset(self):
        return (AdoptionUpdate.objects
                .filter(application__applicant=self.request.user, source='user')
                .select_related('task', 'application', 'application__pet')  # ← 补 application__pet
                .order_by('-created_at'))

    def get_serializer_class(self):
        if self.action == 'create':
            return AdoptionUpdateCreateSerializer
        return MyUpdateListSerializer   # ← list 用读序列化器


class MyUpdateTaskListView(generics.ListAPIView):
    """GET /my/update-tasks/?status=pending  我的打卡任务(最近截止的排前面)"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    pagination_class = StandardPagination
    serializer_class = AdoptionUpdateTaskDetailSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdoptionUpdateTaskFilter

    def get_queryset(self):
        return (AdoptionUpdateTask.objects
                .filter(application__applicant=self.request.user)
                .select_related('application', 'application__pet')
                .order_by('due_end'))


class MyFavoriteListView(generics.ListAPIView):
    """GET /my/favorites/  我的收藏"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    pagination_class = StandardPagination
    serializer_class = PetFavoriteSerializer

    def get_queryset(self):
        return (PetFavorite.objects
                .filter(user=self.request.user)
                .select_related('pet')
                .order_by('-created_at'))


class MyAdopterProfileView(generics.RetrieveAPIView):
    """GET /my/profile/  我的领养资格(申请页打开时先查,受限直接提示)"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    serializer_class = AdopterProfileSerializer

    def get_object(self):
        profile, _ = AdopterProfile.objects.get_or_create(user=self.request.user)
        # 惰性解禁: 限制到期即恢复(celery beat 也会扫,双保险)
        if (profile.status == 'restricted' and profile.restricted_until
                and timezone.now() >= profile.restricted_until):
            profile.status = 'normal'
            profile.restricted_until = None
            profile.save(update_fields=['status', 'restricted_until', 'updated_at'])
        return profile


# ════════════════════════════════════════════════════════════
# 后台 — 平台管理员(Manager)
# ════════════════════════════════════════════════════════════

class AdminBaseMixin:
    """后台视图公共配置: Manager 认证 + adoption 模块权限"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [HasModuleAccess]
    required_module = 'adoption'
    pagination_class = AdminPagination


class AdminPetViewSet(AdminBaseMixin, ModelViewSet):
    """
    宠物档案管理(增删改查,删除=软删)
    POST   /admin/pets/{id}/add_media/            追加图片/视频
    DELETE /admin/pets/{id}/media/{media_id}/     删除图片/视频
    上下架直接 PATCH status(full/handover/adopted 由流程自动流转,serializer 已拦截手填)
    """
    serializer_class = StrayPetAdminSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = StrayPetFilter
    ordering_fields = ['created_at', 'sort_weight', 'applying_count',
                       'view_count', 'favorite_count', 'adopted_at']
    ordering = ['-created_at']
    queryset = StrayPet.objects.filter(is_deleted=False).prefetch_related('media')

    def perform_destroy(self, instance):
        if instance.applications.filter(
                status__in=AdoptionApplication.ACTIVE_STATUSES).exists():
            raise ValidationError('该宠物存在进行中的申请,请先处理完申请再删除')
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted', 'updated_at'])

    @action(detail=True, methods=['post'])
    def add_media(self, request, pk=None):
        data = request.data.copy()
        data['pet'] = pk
        serializer = PetMediaSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'],
            url_path='media/(?P<media_id>[0-9]+)')
    def remove_media(self, request, pk=None, media_id=None):
        deleted, _ = PetMedia.objects.filter(pet_id=pk, id=media_id).delete()
        if not deleted:
            return Response({'detail': '图片不存在'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminApplicationViewSet(AdminBaseMixin, mixins.ListModelMixin,
                              mixins.RetrieveModelMixin, GenericViewSet):
    """
    申请单审核
    GET  /admin/applications/?pet=123&status=submitted,reviewing,interview
         同宠物的申请并排对比择优(列表内嵌申请人信用画像,可按 ?ordering=-review_score)
    POST /admin/applications/{id}/action/
         body: {"action": "approve", "review_score": 90, "review_note": "..."}
         action ∈ start_review/to_interview/approve/reject/complete/returned
         approve 会自动批量拒绝同宠物其余进行中申请(择优)
    """
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = AdoptionApplicationFilter
    ordering_fields = ['created_at', 'review_score']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = (AdoptionApplication.objects
              .select_related('pet', 'applicant', 'applicant__adopter_profile'))
        if self.action == 'retrieve':
            qs = qs.prefetch_related('status_logs', 'update_tasks')
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ApplicationAdminDetailSerializer
        return ApplicationAdminListSerializer

    @action(detail=True, methods=['post'], url_path='action')
    def do_action(self, request, pk=None):
        application = self.get_object()
        serializer = ApplicationAdminActionSerializer(
            data=request.data,
            context={'request': request, 'application': application})
        serializer.is_valid(raise_exception=True)
        application = serializer.save()
        # 重查一次,返回联动后的最新状态(宠物状态/计数已变)
        application = self.get_queryset().get(pk=application.pk)
        return Response(ApplicationAdminDetailSerializer(
            application, context=self.get_serializer_context()).data)


class AdminUpdateTaskViewSet(AdminBaseMixin, mixins.ListModelMixin,
                             mixins.RetrieveModelMixin, GenericViewSet):
    """
    打卡任务看板
    GET  /admin/update-tasks/?status=overdue   逾期清单(人工跟进入口)
    POST /admin/update-tasks/{id}/exempt/      豁免该期(特殊情况)
    """
    serializer_class = AdoptionUpdateTaskDetailSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdoptionUpdateTaskFilter

    def get_queryset(self):
        return (AdoptionUpdateTask.objects
                .select_related('application', 'application__pet')
                .order_by('due_end'))

    @action(detail=True, methods=['post'])
    def exempt(self, request, pk=None):
        task = self.get_object()
        if task.status not in ('pending', 'overdue'):
            raise ValidationError('当前状态无需豁免')
        task.status = 'exempted'
        task.save(update_fields=['status', 'updated_at'])
        return Response(self.get_serializer(task).data)


class AdminUpdateViewSet(AdminBaseMixin, mixins.CreateModelMixin,
                         mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         GenericViewSet):
    """
    领养动态审查
    GET  /admin/updates/?review_status=pending   待查看队列
    POST /admin/updates/                          回访代录(source=staff,可豁免对应任务)
    POST /admin/updates/{id}/review/              下结论 {"review_status": "normal"|"abnormal"}
                                                  abnormal 触发告警,处罚另走违规接口
    """
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdoptionUpdateFilter

    def get_queryset(self):
        return (AdoptionUpdate.objects
                .select_related('task', 'application__pet',
                                'application__applicant')
                .order_by('-created_at'))

    def get_serializer_class(self):
        if self.action == 'create':
            return AdoptionUpdateStaffCreateSerializer
        return AdoptionUpdateAdminSerializer

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        update = self.get_object()
        serializer = AdoptionUpdateReviewSerializer(
            data=request.data, context={'request': request, 'update': update})
        serializer.is_valid(raise_exception=True)
        update = serializer.save()
        return Response(AdoptionUpdateAdminSerializer(
            update, context=self.get_serializer_context()).data)


class AdminViolationViewSet(AdminBaseMixin, mixins.CreateModelMixin,
                            mixins.ListModelMixin, mixins.RetrieveModelMixin,
                            GenericViewSet):
    """
    违规记录(只增不改,留痕可追溯)
    POST /admin/violations/  记录违规并联动资格处罚(警告扣分/限期限制/永久封禁)
    GET  /admin/violations/?user=123  某用户的违规历史
    """
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdoptionViolationFilter

    def get_queryset(self):
        return (AdoptionViolation.objects
                .select_related('user', 'application', 'operator')
                .order_by('-created_at'))

    def get_serializer_class(self):
        if self.action == 'create':
            return AdoptionViolationCreateSerializer
        return AdoptionViolationSerializer


class AdminAdopterProfileViewSet(AdminBaseMixin, mixins.ListModelMixin,
                                 mixins.RetrieveModelMixin,
                                 mixins.UpdateModelMixin, GenericViewSet):
    """
    领养资格档案(风控看板)
    GET   /admin/profiles/?status=banned&credit_max=60   风险用户筛查
    PATCH /admin/profiles/{id}/   手动调整: 解禁(status=normal)/封禁/改信用分/备注
    """
    serializer_class = AdopterProfileAdminSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = AdopterProfileFilter
    ordering_fields = ['credit_score', 'violation_count', 'updated_at']
    ordering = ['-updated_at']

    def get_queryset(self):
        return AdopterProfile.objects.select_related('user')
