from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Avg

from utils.authentication import UserAuthentication
from utils.permission import IsUser, IsResourceOwner, IsAuthorOrReadOnly, AllowAny, IsServiceProvider
from .models import PetCategory, PetBreed, Pet, PetDiary, PetServiceRecord
from .serializers import (
    PetCategorySerializer, PetBreedSerializer,
    PetListSerializer, PetDetailSerializer,
    PetDiaryListSerializer, PetDiaryDetailSerializer,
    PetServiceRecordListSerializer, PetServiceRecordDetailSerializer,
    PetServiceRecordCreateSerializer
)
from .filters import PetFilter, PetBreedFilter, PetDiaryFilter, PetServiceRecordFilter


class PetCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    宠物大类视图集（只读，公开参考数据）
    list: 获取大类列表（含各大类的品种数 breed_count）
    retrieve: 获取大类详情
    breeds: 获取该大类下的品种列表（/pet/categories/{id}/breeds/）
    """
    serializer_class = PetCategorySerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [AllowAny]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['sort_order', 'created_at']
    ordering = ['sort_order']

    def get_queryset(self):
        # annotate 注入 breed_count，避免序列化器逐个分类 count 品种（N+1）
        return PetCategory.objects.filter(is_active=True).annotate(
            breed_count=Count('breeds', filter=Q(breeds__is_active=True))
        )

    @action(detail=True, methods=['get'])
    def breeds(self, request, pk=None):
        """获取指定大类下的品种（支持 search 关键词，按热门+排序返回）"""
        category = self.get_object()
        qs = category.breeds.filter(is_active=True)

        keyword = request.query_params.get('search')
        if keyword:
            qs = qs.filter(Q(name__icontains=keyword) | Q(alias__icontains=keyword))

        qs = qs.order_by('-is_common', 'sort_order', 'id')

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = PetBreedSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetBreedSerializer(qs, many=True)
        return Response(serializer.data)


class PetBreedViewSet(viewsets.ReadOnlyModelViewSet):
    """
    宠物品种视图集（只读，公开参考数据）
    list: 品种列表（可按 category 过滤、name/alias 搜索）
    retrieve: 品种详情
    """
    queryset = PetBreed.objects.filter(is_active=True).select_related('category')
    serializer_class = PetBreedSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PetBreedFilter
    search_fields = ['name', 'alias']
    ordering_fields = ['sort_order', 'name', 'is_common']
    ordering = ['-is_common', 'sort_order']


class PetViewSet(viewsets.ModelViewSet):
    """
    宠物信息视图集（用户隐私数据，仅主人可见 / 可管理）
    list: 获取当前用户的宠物列表
    retrieve: 获取宠物详情
    create: 创建宠物（快速建档只需 category；品种等可后续完善）
    update/partial_update: 更新宠物信息
    destroy: 删除宠物（软删除）

    权限：IsUser（登录普通用户）+ IsResourceOwner（对象级，认 owner 字段）。
    get_queryset 已限定到本人宠物，IsResourceOwner 在对象级再兜底一层。
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser, IsResourceOwner]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PetFilter
    # breed 已改为外键：搜品种走 breed__name + 自定义 breed_name
    search_fields = ['name', 'breed__name', 'breed_name']
    ordering_fields = ['created_at', 'name', 'birth_date']
    ordering = ['-created_at']

    def get_queryset(self):
        """只返回当前用户的宠物"""
        return Pet.objects.filter(
            owner=self.request.user, is_deleted=False
        ).select_related('category', 'breed')

    def get_serializer_class(self):
        """根据不同操作返回不同的序列化器"""
        if self.action == 'list':
            return PetListSerializer
        return PetDetailSerializer

    def perform_destroy(self, instance):
        """软删除"""
        instance.is_deleted = True
        instance.save(update_fields=['is_deleted', 'updated_at'])

    @action(detail=True, methods=['get'])
    def diaries(self, request, pk=None):
        """获取指定宠物的日记列表"""
        pet = self.get_object()
        diaries = PetDiary.objects.filter(pet=pet)

        # 支持日记类型过滤
        diary_type = request.query_params.get('diary_type')
        if diary_type:
            diaries = diaries.filter(diary_type=diary_type)

        page = self.paginate_queryset(diaries)
        if page is not None:
            serializer = PetDiaryListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetDiaryListSerializer(diaries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def service_records(self, request, pk=None):
        """获取指定宠物的服务记录"""
        pet = self.get_object()
        # 通过订单关联查询服务记录
        records = PetServiceRecord.objects.filter(
            related_order__pets=pet
        ).select_related('related_order', 'related_diary')

        page = self.paginate_queryset(records)
        if page is not None:
            serializer = PetServiceRecordListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetServiceRecordListSerializer(records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取宠物统计信息（用 values+annotate 聚合，避免逐个 pet 查 category 的 N+1）"""
        pets = Pet.objects.filter(owner=request.user, is_deleted=False)

        category_distribution = {
            row['category__name']: row['count']
            for row in pets.values('category__name').annotate(count=Count('id'))
        }
        gender_counts = {
            row['gender']: row['count']
            for row in pets.values('gender').annotate(count=Count('id'))
        }

        return Response({
            'total_pets': pets.count(),
            'category_distribution': category_distribution,
            'gender_distribution': {
                'M': gender_counts.get('M', 0),
                'F': gender_counts.get('F', 0),
                'U': gender_counts.get('U', 0),
            }
        })


class PetDiaryViewSet(viewsets.ModelViewSet):
    """
    宠物日记视图集（仅主人可见；作者本人可写）
    list: 获取日记列表
    retrieve: 获取日记详情
    create: 创建日记
    update/partial_update: 更新日记
    destroy: 删除日记

    权限：IsUser + IsAuthorOrReadOnly（对象级，认 author 字段，读放行）。
    - 可见范围：get_queryset 限定为“自己宠物的日记”（含服务商为自己宠物写的服务日记）；
    - 写权限：仅日记作者本人（IsAuthorOrReadOnly 在对象级强制）；
    - “只能给自己的宠物建日记”：由 PetDiaryDetailSerializer.validate_pet 校验；
    - author：由序列化器 create() 自动写入当前登录用户。
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser, IsAuthorOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PetDiaryFilter
    search_fields = ['title', 'content']
    ordering_fields = ['diary_date', 'created_at']
    ordering = ['-diary_date', '-created_at']

    def get_queryset(self):
        """只返回用户自己宠物的日记"""
        return PetDiary.objects.filter(pet__owner=self.request.user).select_related('pet', 'author')

    def get_serializer_class(self):
        if self.action == 'list':
            return PetDiaryListSerializer
        return PetDiaryDetailSerializer

    @action(detail=False, methods=['get'])
    def my_diaries(self, request):
        """获取当前用户创建（author 为本人）的所有日记"""
        diaries = PetDiary.objects.filter(author=request.user)

        page = self.paginate_queryset(diaries)
        if page is not None:
            serializer = PetDiaryListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetDiaryListSerializer(diaries, many=True)
        return Response(serializer.data)


class PetServiceRecordViewSet(viewsets.ModelViewSet):
    """
    宠物服务记录视图集
    list: 获取服务记录列表
    retrieve: 获取服务记录详情
    create: 创建服务记录（仅服务人员 Staff）
    update/partial_update: 更新服务记录（仅服务人员）
    add_feedback: 客户添加反馈/评分
    my_records / statistics: 服务人员视角

    权限：IsServiceProvider（对象级区分：主人只读+反馈、服务人员可读写）。

    ⚠️ 认证说明：本视图同时服务“宠物主人(User)”和“服务人员(Staff)”两类主体。
    下面只挂了 UserAuthentication —— 如果你的 Staff 走独立认证类（如 StaffAuthentication），
    需要写成：
        authentication_classes = [UserAuthentication, StaffAuthentication]
    否则 Staff 端的 create / my_records / statistics 会因未认证而 401。
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsServiceProvider]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = PetServiceRecordFilter
    ordering_fields = ['actual_start_time', 'created_at', 'rating']
    ordering = ['-actual_start_time']

    def get_queryset(self):
        """
        宠物主人：查看自己宠物的服务记录
        服务人员：查看自己负责订单的服务记录
        """
        user = self.request.user
        return PetServiceRecord.objects.filter(
            Q(related_order__pets__owner=user) |
            Q(related_order__staff=user)
        ).select_related('related_order', 'related_diary').distinct()

    def get_serializer_class(self):
        if self.action == 'create':
            return PetServiceRecordCreateSerializer
        elif self.action == 'list':
            return PetServiceRecordListSerializer
        return PetServiceRecordDetailSerializer

    @action(detail=True, methods=['post'])
    def add_feedback(self, request, pk=None):
        """客户添加反馈和评分（仅订单客户本人）"""
        record = self.get_object()

        # 仅订单客户（User）本人可反馈；用 isinstance 防止跨模型主键数值碰撞
        customer = record.related_order.customer
        if not (isinstance(request.user, type(customer))
                and record.related_order.customer_id == getattr(request.user, 'id', None)):
            return Response(
                {'error': '只有客户可以添加反馈'},
                status=status.HTTP_403_FORBIDDEN
            )

        rating = request.data.get('rating')
        if rating is not None:
            try:
                rating = int(rating)
            except (TypeError, ValueError):
                return Response(
                    {'error': '评分必须是 1-5 的整数'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if rating < 1 or rating > 5:
                return Response(
                    {'error': '评分必须在 1-5 之间'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            record.rating = rating

        feedback = request.data.get('customer_feedback')
        if feedback:
            record.customer_feedback = feedback

        record.save()

        serializer = PetServiceRecordDetailSerializer(record)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def my_records(self, request):
        """服务人员：我负责（related_order.staff 为本人）的服务记录"""
        records = PetServiceRecord.objects.filter(
            related_order__staff=request.user
        ).select_related('related_order', 'related_diary')

        page = self.paginate_queryset(records)
        if page is not None:
            serializer = PetServiceRecordListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetServiceRecordListSerializer(records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """服务人员：服务统计（评分分布 / 平均分用数据库聚合，避免把全部记录拉进内存）"""
        records = PetServiceRecord.objects.filter(related_order__staff=request.user)

        rated = records.exclude(rating__isnull=True)
        rating_counts = {
            str(row['rating']): row['count']
            for row in rated.values('rating').annotate(count=Count('id'))
        }
        avg = rated.aggregate(avg=Avg('rating'))['avg']

        return Response({
            'total_records': records.count(),
            'average_rating': round(avg, 2) if avg is not None else 0,
            'rating_distribution': {
                '5': rating_counts.get('5', 0),
                '4': rating_counts.get('4', 0),
                '3': rating_counts.get('3', 0),
                '2': rating_counts.get('2', 0),
                '1': rating_counts.get('1', 0),
            }
        })