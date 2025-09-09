from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from .models import Banner
from .serializers import BannerListSerializer, BannerCreateSerializer, BannerSerializer


class BannerViewSet(viewsets.ModelViewSet):
    """轮播图视图集"""

    queryset = Banner.objects.filter(is_active=True)
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = ['type', 'is_active']
    ordering_fields = ['sort_order', 'created_at', 'updated_at']
    ordering = ['sort_order', 'created_at']  # 默认按排序字段排序
    search_fields = ['title', 'description']

    def get_serializer_class(self):
        """根据不同动作返回不同的序列化器"""
        if self.action == 'list':
            return BannerListSerializer
        elif self.action == 'create':
            return BannerCreateSerializer
        return BannerSerializer

    def get_queryset(self):
        """重写 queryset，支持更复杂的筛选"""
        queryset = super().get_queryset()

        # 支持按类型过滤
        banner_type = self.request.query_params.get('type', None)
        if banner_type:
            queryset = queryset.filter(type=banner_type)

        # 支持按是否启用过滤
        is_active = self.request.query_params.get('is_active', None)
        if is_active is not None:
            is_active = is_active.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(is_active=is_active)

        return queryset

    def list(self, request, *args, **kwargs):
        """获取轮播图列表"""
        queryset = self.filter_queryset(self.get_queryset())

        # 分页处理
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        # 返回成功响应
        return Response({
            'code': 200,
            'message': '获取成功',
            'data': serializer.data,
            'total': queryset.count()
        })

    def create(self, request, *args, **kwargs):
        """创建轮播图"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # 返回完整的轮播图信息
        instance = serializer.instance
        response_serializer = BannerSerializer(instance)
        headers = self.get_success_headers(serializer.data)

        return Response({
            'code': 201,
            'message': '创建成功',
            'data': response_serializer.data
        }, status=status.HTTP_201_CREATED, headers=headers)

    def retrieve(self, request, *args, **kwargs):
        """获取轮播图详情"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'code': 200,
            'message': '获取成功',
            'data': serializer.data
        })

    def update(self, request, *args, **kwargs):
        """更新轮播图"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response({
            'code': 200,
            'message': '更新成功',
            'data': serializer.data
        })

    def destroy(self, request, *args, **kwargs):
        """删除轮播图（软删除）"""
        instance = self.get_object()
        # 软删除：设置为不激活而不是真正删除
        instance.is_active = False
        instance.save()

        return Response({
            'code': 200,
            'message': '删除成功'
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def by_type(self, request):
        """按类型获取轮播图"""
        banner_type = request.query_params.get('type')
        if not banner_type:
            return Response({
                'code': 400,
                'message': '请提供type参数',
                'data': []
            }, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.get_queryset().filter(type=banner_type)
        serializer = BannerListSerializer(queryset, many=True)

        return Response({
            'code': 200,
            'message': '获取成功',
            'data': serializer.data,
            'total': queryset.count()
        })

    @action(detail=False, methods=['get'])
    def types(self, request):
        """获取所有轮播图类型"""
        # 获取数据库中实际存在的类型
        existing_types = Banner.objects.filter(is_active=True).values_list('type', flat=True).distinct()

        # 获取所有可选择的类型
        all_types = [{'value': choice[0], 'label': choice[1]} for choice in Banner.TYPE_CHOICES]

        return Response({
            'code': 200,
            'message': '获取成功',
            'data': {
                'all_types': all_types,
                'existing_types': list(existing_types)
            }
        })

    @action(detail=True, methods=['patch'])
    def update_sort_order(self, request, pk=None):
        """更新排序"""
        banner = self.get_object()
        sort_order = request.data.get('sort_order')

        if sort_order is None:
            return Response({
                'code': 400,
                'message': '请提供sort_order参数',
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            sort_order = int(sort_order)
            if sort_order < 0:
                return Response({
                    'code': 400,
                    'message': '排序值不能为负数',
                }, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({
                'code': 400,
                'message': '排序值必须是整数',
            }, status=status.HTTP_400_BAD_REQUEST)

        banner.sort_order = sort_order
        banner.save()

        serializer = BannerSerializer(banner)
        return Response({
            'code': 200,
            'message': '排序更新成功',
            'data': serializer.data
        })

    @action(detail=True, methods=['patch'])
    def toggle_active(self, request, pk=None):
        """切换启用状态"""
        banner = self.get_object()
        banner.is_active = not banner.is_active
        banner.save()

        serializer = BannerSerializer(banner)
        return Response({
            'code': 200,
            'message': f'已{"启用" if banner.is_active else "禁用"}',
            'data': serializer.data
        })

    @action(detail=False, methods=['post'])
    def batch_update_sort(self, request):
        """批量更新排序"""
        sort_data = request.data.get('sort_data', [])

        if not sort_data:
            return Response({
                'code': 400,
                'message': '请提供排序数据',
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            updated_count = 0
            for item in sort_data:
                banner_id = item.get('id')
                sort_order = item.get('sort_order')

                if banner_id and sort_order is not None:
                    Banner.objects.filter(id=banner_id).update(sort_order=sort_order)
                    updated_count += 1

            return Response({
                'code': 200,
                'message': f'批量更新成功，共更新{updated_count}条记录',
            })

        except Exception as e:
            return Response({
                'code': 500,
                'message': f'批量更新失败: {str(e)}',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)