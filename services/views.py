# -*- coding: utf-8 -*-
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from django.db.models import F
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend

from attract.models import HomepagePosition
from .models import (
    ServiceCategory, Service,
    ServiceScheduleRule, ServiceTimeSlot,
    ServiceFavorite,
)
from .serializers import (
    ServiceCategorySerializer,
    ServiceCategorySimpleSerializer,
    ServiceCategoryTreeSerializer,
    ServiceCategoryFlatSerializer,
    ServiceCategoryCreateSerializer,
    ServiceListSerializer, ServiceDetailSerializer,
    ServiceTimeSlotSerializer, ServiceScheduleRuleSerializer,
    ServiceFavoriteSerializer,
    MerchantServiceCreateSerializer,
)
from .filters import ServiceFilter, ServiceCategoryFilter
from .pagination import StandardPagination, SmallPagination

from utils.authentication import (
    UserAuthentication, OptionalUserAuthentication,
    MerchantOrSubAuthentication, ManagerAuthentication,
)
from utils.permission import IsUser, IsMerchant, IsManager
from datetime import date as date_cls


# ═══════════════════════════════════════════════════════
# 公开接口（无需认证）
# ═══════════════════════════════════════════════════════

class PublicServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """公开服务接口 —— 无需 token 即可浏览"""

    authentication_classes = [OptionalUserAuthentication]
    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ServiceFilter

    def get_queryset(self):
        return Service.objects.filter(
            status='active',
            merchant__status='active',
        ).select_related('merchant', 'category', 'category__parent')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ServiceDetailSerializer
        return ServiceListSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        Service.objects.filter(pk=instance.pk).update(view_count=F('view_count') + 1)
        serializer = self.get_serializer(instance, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def recommended(self, request):
        """推荐服务"""
        qs = self.get_queryset().filter(is_recommended=True)[:10]
        serializer = ServiceListSerializer(qs, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def hot(self, request):
        """热门服务"""
        qs = self.get_queryset().filter(is_hot=True).order_by('-total_sales')[:10]
        serializer = ServiceListSerializer(qs, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def time_slots(self, request, pk=None):
        """
        GET /services/{id}/time_slots/?date=YYYY-MM-DD

        返回该日期下所有可预约时段:
          - 已落库的时段(他人预约过/商家手动加的)直接展示真实余量
          - 未落库的时段按规则虚拟生成,id=null,前端可正常下单(下单时落库)
        """
        service = self.get_object()

        if service.service_type != Service.ServiceType.APPOINTMENT:
            return Response({'error': '该服务不支持预约选时段'},
                            status=status.HTTP_400_BAD_REQUEST)
        # schedule_type 现在嵌套在 appointment_config 里
        appt_cfg = service.appointment_config or {}
        if appt_cfg.get('schedule_type') != 'customer':
            return Response({'error': '该服务由商家安排时间'},
                            status=status.HTTP_400_BAD_REQUEST)

        date_str = request.query_params.get('date')
        if date_str:
            try:
                target_date = date_cls.fromisoformat(date_str)
            except ValueError:
                return Response({'error': '日期格式错误,应为 YYYY-MM-DD'},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            target_date = timezone.localdate()

        return Response(service.get_available_slots(target_date))



class PublicCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """公开分类接口 —— 无需 token"""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get_queryset(self):
        return ServiceCategory.objects.filter(is_active=True)

    def get_serializer_class(self):
        if self.action == 'tree':
            return ServiceCategoryTreeSerializer
        if self.action == 'options':
            return ServiceCategoryFlatSerializer
        return ServiceCategorySimpleSerializer

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """
        获取分类树结构
        返回嵌套的树形结构，适合导航菜单
        """
        root_categories = ServiceCategory.objects.filter(
            level=1,
            is_active=True,
        ).prefetch_related(
            'children', 'children__children'
        ).order_by('-sort_order', 'id')

        serializer = ServiceCategoryTreeSerializer(root_categories, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def options(self, request):
        """
        获取分类选项（扁平结构）
        适合下拉选择器，带完整路径名
        """
        level = request.query_params.get('level')
        parent_id = request.query_params.get('parent_id')
        only_leaf = request.query_params.get('only_leaf')

        qs = self.get_queryset().order_by('level', '-sort_order', 'id')

        if level:
            qs = qs.filter(level=level)
        if parent_id:
            qs = qs.filter(parent_id=parent_id)

        serializer = ServiceCategoryFlatSerializer(qs, many=True)
        data = serializer.data

        # 只返回叶子节点
        if only_leaf == 'true':
            data = [item for item in data if item['is_leaf']]

        return Response(data)

    @action(detail=False, methods=['get'])
    def hot(self, request):
        """获取热门分类"""
        qs = self.get_queryset().filter(is_hot=True).order_by('-sort_order')[:10]
        serializer = ServiceCategorySimpleSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def children(self, request, pk=None):
        """获取指定分类的子分类"""
        category = self.get_object()
        children = category.children.filter(is_active=True).order_by('-sort_order', 'id')
        serializer = ServiceCategorySimpleSerializer(children, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def services(self, request, pk=None):
        """获取指定分类下的服务（含子分类）"""
        category = self.get_object()

        # 获取该分类及所有子孙分类的ID
        category_ids = [category.id]

        def collect_children_ids(cat):
            for child in cat.children.filter(is_active=True):
                category_ids.append(child.id)
                collect_children_ids(child)

        collect_children_ids(category)

        services = Service.objects.filter(
            category_id__in=category_ids,
            status='active',
            merchant__status='active',
        ).select_related('merchant', 'category').order_by('-sort_order', '-total_sales')[:20]

        serializer = ServiceListSerializer(services, many=True, context={'request': request})
        return Response(serializer.data)


# 兼容旧接口（已废弃，建议使用 PublicCategoryViewSet）
@api_view(['GET'])
def get_service_categories(request, merchant_id=None):
    """
    获取服务分类树（公开）
    注意：merchant_id 参数已废弃，分类现在是全局的
    """
    categories = ServiceCategory.objects.filter(
        is_active=True,
        level=1,  # 只获取一级分类
    ).prefetch_related('children', 'children__children').order_by('-sort_order', 'id')

    return Response(ServiceCategoryTreeSerializer(categories, many=True).data)


# ═══════════════════════════════════════════════════════
# 用户端接口（需要登录）
# ═══════════════════════════════════════════════════════

class ServiceFavoriteViewSet(viewsets.ModelViewSet):
    """用户收藏"""

    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]
    serializer_class = ServiceFavoriteSerializer
    pagination_class = SmallPagination

    def get_queryset(self):
        return ServiceFavorite.objects.filter(
            user=self.request.user,
        ).select_related('service__merchant', 'service__category').order_by('-created_at')

    def create(self, request):
        """添加收藏"""
        service_id = request.data.get('service_id')
        service = get_object_or_404(Service, id=service_id, status='active')

        favorite, created = ServiceFavorite.objects.get_or_create(
            user=request.user,
            service=service,
        )

        if created:
            Service.objects.filter(pk=service_id).update(favorite_count=F('favorite_count') + 1)
            return Response({'message': '收藏成功'}, status=status.HTTP_201_CREATED)
        return Response({'message': '已收藏'})

    @action(detail=False, methods=['delete'])
    def remove(self, request):
        """取消收藏"""
        service_id = request.data.get('service_id')

        deleted, _ = ServiceFavorite.objects.filter(
            user=request.user,
            service_id=service_id,
        ).delete()

        if deleted:
            Service.objects.filter(pk=service_id).update(
                favorite_count=F('favorite_count') - 1,
            )
            return Response({'message': '已取消收藏'})
        return Response({'error': '未收藏该服务'}, status=status.HTTP_400_BAD_REQUEST)


# ═══════════════════════════════════════════════════════
# 商家端接口
# ═══════════════════════════════════════════════════════

class MerchantServiceViewSet(viewsets.ModelViewSet):
    """商家管理自己的服务"""

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ServiceFilter

    def _get_merchant_id(self):
        user = self.request.user
        from merchants.models import Merchant
        return user.id if isinstance(user, Merchant) else user.merchant_id

    def get_queryset(self):
        qs = Service.objects.filter(
            merchant_id=self._get_merchant_id(),
        ).select_related('category', 'category__parent').order_by('-created_at')

        # 兜底：手动处理筛选参数，避免 ServiceFilter 字段对不上时失效
        params = self.request.query_params
        status_val = params.get('status')
        if status_val:
            qs = qs.filter(status=status_val)

        keyword = params.get('keyword')
        if keyword:
            qs = qs.filter(name__icontains=keyword)

        category_id = params.get('category') or params.get('category_id')
        if category_id:
            qs = qs.filter(category_id=category_id)

        return qs

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MerchantServiceCreateSerializer
        if self.action == 'retrieve':
            return ServiceDetailSerializer
        return ServiceListSerializer

    def perform_create(self, serializer):
        serializer.save(merchant_id=self._get_merchant_id())

    # ════════════════════════════════════════════════════════════════
    # ↓↓↓ 新增：重写 create / update,返回完整详情(含 id 和 effective_* 字段)
    # ════════════════════════════════════════════════════════════════

    def create(self, request, *args, **kwargs):
        """
        重写 create:
        - 使用 MerchantServiceCreateSerializer 做写入和校验
        - 用 ServiceDetailSerializer 序列化响应,确保前端拿到 id 和所有计算字段
        """
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_create(write_serializer)

        # 用详情 serializer 重新序列化,返回完整数据
        instance = write_serializer.instance
        read_serializer = ServiceDetailSerializer(
            instance, context=self.get_serializer_context()
        )
        headers = self.get_success_headers(read_serializer.data)
        return Response(
            read_serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def update(self, request, *args, **kwargs):
        """
        重写 update / partial_update:
        - 使用 MerchantServiceCreateSerializer 做写入和校验
        - 用 ServiceDetailSerializer 序列化响应,前端编辑成功后能直接刷新
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        write_serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        # 如果有预取的相关对象在 update 后失效,清理缓存
        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        read_serializer = ServiceDetailSerializer(
            instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data)

    # ════════════════════════════════════════════════════════════════
    # ↑↑↑ 新增结束
    # ════════════════════════════════════════════════════════════════

    def destroy(self, request, *args, **kwargs):
        """删除服务 —— 有进行中订单时拒绝；否则清理广告位后删除"""
        instance = self.get_object()

        from bill.models import ServiceOrder

        ACTIVE_STATUSES = [
            ServiceOrder.Status.PENDING_PAYMENT,
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ACCEPT,
            ServiceOrder.Status.PENDING_ASSIGNMENT,
            ServiceOrder.Status.ASSIGNED,
            ServiceOrder.Status.IN_SERVICE,
            ServiceOrder.Status.PENDING_USE,
            ServiceOrder.Status.PENDING_DELIVERY,
            ServiceOrder.Status.DELIVERING,
            ServiceOrder.Status.SUBSCRIBING,
            ServiceOrder.Status.REFUNDING,
        ]

        active_count = ServiceOrder.objects.filter(
            items__service_id=instance.id,
            status__in=ACTIVE_STATUSES,
        ).distinct().count()

        if active_count > 0:
            return Response(
                {
                    'error': f'该服务有 {active_count} 个进行中的订单，无法删除',
                    'detail': '建议先下架并等待订单全部完成，或考虑下架而不是删除',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service_id = instance.id
        name = instance.name
        instance.delete()

        HomepagePosition.objects.filter(
            target_type=HomepagePosition.TargetType.SERVICE,
            target_id=service_id,
        ).delete()

        return Response({'message': f'已删除「{name}」'}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def categories(self, request):
        """获取可选的服务分类（商家端用）"""
        categories = ServiceCategory.objects.filter(is_active=True).order_by('level', '-sort_order')
        serializer = ServiceCategoryFlatSerializer(categories, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def counts(self, request):
        """各状态服务数量汇总"""
        from django.db.models import Count
        merchant_id = self._get_merchant_id()
        rows = (
            Service.objects.filter(merchant_id=merchant_id)
            .values('status').annotate(cnt=Count('id'))
        )
        counts = {'active': 0, 'inactive': 0, 'draft': 0, 'total': 0}
        for row in rows:
            s = row['status']
            if s in counts:
                counts[s] = row['cnt']
            counts['total'] += row['cnt']
        return Response(counts)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """上架"""
        service = self.get_object()
        service.status = 'active'
        service.save(update_fields=['status', 'updated_at'])
        return Response({'message': '已上架', 'status': service.status})

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """下架 —— 有进行中的订单时拒绝下架"""
        service = self.get_object()

        # 延迟导入避免循环依赖
        from bill.models import ServiceOrder

        ACTIVE_STATUSES = [
            ServiceOrder.Status.PENDING_PAYMENT,
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ACCEPT,
            ServiceOrder.Status.PENDING_ASSIGNMENT,
            ServiceOrder.Status.ASSIGNED,
            ServiceOrder.Status.IN_SERVICE,
            ServiceOrder.Status.PENDING_USE,
            ServiceOrder.Status.PENDING_DELIVERY,
            ServiceOrder.Status.DELIVERING,
            ServiceOrder.Status.SUBSCRIBING,
            ServiceOrder.Status.REFUNDING,
        ]

        # 通过 service_order_item 反查关联的服务订单
        active_orders = ServiceOrder.objects.filter(
            items__service_id=service.id,
            status__in=ACTIVE_STATUSES,
        ).distinct()

        active_count = active_orders.count()
        if active_count > 0:
            # 给出更具体的提示，列出几个订单号方便排查
            sample_order_nos = list(
                active_orders.order_by('-created_at')
                .values_list('order_no', flat=True)[:3]
            )
            return Response(
                {
                    'error': f'该服务有 {active_count} 个进行中的订单，无法下架',
                    'detail': '请等订单完成或取消后再操作',
                    'active_count': active_count,
                    'sample_order_nos': sample_order_nos,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service.status = 'inactive'
        service.save(update_fields=['status', 'updated_at'])

        HomepagePosition.objects.filter(
            target_type=HomepagePosition.TargetType.SERVICE,
            target_id=service.id,
        ).delete()
        return Response({'message': '已下架', 'status': service.status})

    @action(detail=True, methods=['get', 'post'])
    def schedule_rules(self, request, pk=None):
        service = self.get_object()

        if request.method == 'GET':
            rules = service.schedule_rules.filter(is_active=True)
            return Response(ServiceScheduleRuleSerializer(rules, many=True).data)

        serializer = ServiceScheduleRuleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(service=service)

            # 规则变更后,清理未来"还没被预约过"的时段,下次访问按新规则重新生成
            service.time_slots.filter(
                date__gte=timezone.localdate(),
                booked_count=0,
                status=ServiceTimeSlot.Status.AVAILABLE,
            ).delete()

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
# ═══════════════════════════════════════════════════════
# 管理员接口
# ═══════════════════════════════════════════════════════

class AdminServiceViewSet(viewsets.ModelViewSet):
    """管理员 —— 服务审核与管理"""

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = ServiceFilter

    def get_queryset(self):
        return Service.objects.all().select_related(
            'merchant', 'category', 'category__parent',
        ).order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ServiceDetailSerializer
        return ServiceListSerializer

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """审核通过（上架）"""
        service = self.get_object()
        service.status = 'active'
        service.save(update_fields=['status', 'updated_at'])
        return Response({'message': '已上架'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """审核驳回（下架）"""
        service = self.get_object()

        from bill.models import ServiceOrder
        ACTIVE_STATUSES = [
            'pending_payment', 'paid', 'pending_accept',
            'pending_assignment', 'assigned', 'in_service',
            'pending_use', 'pending_delivery', 'delivering',
            'subscribing', 'refunding',
        ]

        active_count = ServiceOrder.objects.filter(
            items__service_id=service.id,
            status__in=ACTIVE_STATUSES,
        ).distinct().count()

        if active_count > 0:
            return Response(
                {
                    'error': f'该服务有 {active_count} 个进行中的订单，无法驳回下架',
                    'active_count': active_count,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service.status = 'inactive'
        service.save(update_fields=['status', 'updated_at'])
        HomepagePosition.objects.filter(
            target_type=HomepagePosition.TargetType.SERVICE,
            target_id=service.id,
        ).delete()
        return Response({'message': '已下架'})

    @action(detail=True, methods=['post'])
    def toggle_recommended(self, request, pk=None):
        """切换推荐状态"""
        service = self.get_object()
        service.is_recommended = not service.is_recommended
        service.save(update_fields=['is_recommended', 'updated_at'])
        return Response({
            'message': '已设为推荐' if service.is_recommended else '已取消推荐',
            'is_recommended': service.is_recommended,
        })

    @action(detail=True, methods=['post'])
    def toggle_hot(self, request, pk=None):
        """切换热门状态"""
        service = self.get_object()
        service.is_hot = not service.is_hot
        service.save(update_fields=['is_hot', 'updated_at'])
        return Response({
            'message': '已设为热门' if service.is_hot else '已取消热门',
            'is_hot': service.is_hot,
        })


class AdminCategoryViewSet(viewsets.ModelViewSet):
    """
    管理员 —— 服务分类管理
    全局分类，支持最多三级
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filter_backends = [DjangoFilterBackend]
    filterset_class = ServiceCategoryFilter

    def get_queryset(self):
        return ServiceCategory.objects.all().select_related('parent').order_by('level', '-sort_order', 'id')

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ServiceCategoryCreateSerializer
        if self.action == 'tree':
            return ServiceCategoryTreeSerializer
        return ServiceCategorySerializer

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """获取分类树（管理端，含禁用的）"""
        include_inactive = request.query_params.get('include_inactive', 'false') == 'true'

        qs = ServiceCategory.objects.filter(level=1)
        if not include_inactive:
            qs = qs.filter(is_active=True)

        qs = qs.prefetch_related('children', 'children__children').order_by('-sort_order', 'id')
        # 把 include_inactive 透传给 serializer，这样禁用分类的子级也能在树里看到
        serializer = ServiceCategoryTreeSerializer(
            qs, many=True, context={'include_inactive': include_inactive}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def options(self, request):
        """获取分类选项（扁平，带路径名）"""
        max_level = request.query_params.get('max_level', 3)
        only_active = request.query_params.get('only_active', 'true') == 'true'

        qs = ServiceCategory.objects.filter(level__lte=max_level)
        if only_active:
            qs = qs.filter(is_active=True)
        qs = qs.order_by('level', '-sort_order', 'id')

        serializer = ServiceCategoryFlatSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """切换启用状态"""
        category = self.get_object()
        category.is_active = not category.is_active
        category.save(update_fields=['is_active', 'updated_at'])
        return Response({
            'message': '已启用' if category.is_active else '已禁用',
            'is_active': category.is_active,
        })

    @action(detail=True, methods=['post'])
    def toggle_hot(self, request, pk=None):
        """切换热门状态"""
        category = self.get_object()
        category.is_hot = not category.is_hot
        category.save(update_fields=['is_hot', 'updated_at'])
        return Response({
            'message': '已设为热门' if category.is_hot else '已取消热门',
            'is_hot': category.is_hot,
        })

    @action(detail=True, methods=['post'])
    def update_sort(self, request, pk=None):
        """更新排序"""
        category = self.get_object()
        sort_order = request.data.get('sort_order', 0)
        category.sort_order = sort_order
        category.save(update_fields=['sort_order', 'updated_at'])
        return Response({'message': '排序已更新', 'sort_order': sort_order})

    @action(detail=False, methods=['post'])
    def batch_update_sort(self, request):
        """批量更新排序"""
        items = request.data.get('items', [])
        for item in items:
            ServiceCategory.objects.filter(id=item.get('id')).update(sort_order=item.get('sort_order', 0))
        return Response({'message': f'已更新 {len(items)} 个分类的排序'})

    @action(detail=True, methods=['get'])
    def services(self, request, pk=None):
        """获取该分类下的服务列表"""
        category = self.get_object()

        # 收集该分类及所有子分类ID
        category_ids = [category.id]
        for child in category.children.all():
            category_ids.append(child.id)
            for grandchild in child.children.all():
                category_ids.append(grandchild.id)

        services = Service.objects.filter(
            category_id__in=category_ids
        ).select_related('merchant').order_by('-created_at')[:50]

        return Response(ServiceListSerializer(services, many=True).data)