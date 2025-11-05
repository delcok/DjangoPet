# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Delock (Modified by ChatGPT)

from rest_framework import generics, filters
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Min, Max
from .models import ServiceModel, PetType, AdditionalService
from .pagination import CustomPageNumberPagination
from .serializers import (
    ServiceModelSerializer,
    ServiceModelSimpleSerializer,
    PetTypeSerializer,
    AdditionalServiceSerializer,
    AdditionalServiceSimpleSerializer
)
from .filters import ServiceModelFilter, PetTypeFilter, AdditionalServiceFilter


# ==================== 宠物类型视图 ====================

class PetTypeListView(generics.ListAPIView):
    """宠物类型列表视图 - 只读"""
    queryset = PetType.objects.filter(is_active=True)
    serializer_class = PetTypeSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PetTypeFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'base_price', 'sort_order', 'created_at']
    ordering = ['sort_order', 'name']


class PetTypeDetailView(generics.RetrieveAPIView):
    """宠物类型详情视图 - 只读"""
    queryset = PetType.objects.filter(is_active=True)
    serializer_class = PetTypeSerializer
    permission_classes = [AllowAny]


# ==================== 基础服务视图 ====================

class ServiceModelListView(generics.ListAPIView):
    """基础服务列表视图 - 只读"""
    serializer_class = ServiceModelSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ServiceModelFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'base_price', 'sort_order', 'created_at']
    ordering = ['sort_order', '-created_at']

    def get_queryset(self):
        return ServiceModel.objects.filter(is_active=True).prefetch_related('applicable_pets')


class ServiceModelDetailView(generics.RetrieveAPIView):
    """基础服务详情视图 - 只读"""
    serializer_class = ServiceModelSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return ServiceModel.objects.filter(is_active=True).prefetch_related('applicable_pets')


# ==================== 附加服务视图 ====================

class AdditionalServiceListView(generics.ListAPIView):
    """附加服务列表视图 - 只读"""
    serializer_class = AdditionalServiceSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AdditionalServiceFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'price', 'sort_order', 'created_at']
    ordering = ['sort_order', '-created_at']

    def get_queryset(self):
        return AdditionalService.objects.filter(is_active=True).prefetch_related('applicable_pets')


class AdditionalServiceDetailView(generics.RetrieveAPIView):
    """附加服务详情视图 - 只读"""
    serializer_class = AdditionalServiceSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return AdditionalService.objects.filter(is_active=True).prefetch_related('applicable_pets')


# ==================== 宠物类型附加服务视图 ====================

class PetTypeAdditionalServicesView(generics.ListAPIView):
    """根据宠物类型获取可用的附加服务（用于前端单独显示）"""
    serializer_class = AdditionalServiceSimpleSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        """筛选适用于指定宠物类型的附加服务"""
        pet_type_id = self.kwargs.get('pet_type_id')

        try:
            pet_type = PetType.objects.get(id=pet_type_id, is_active=True)
        except PetType.DoesNotExist:
            # 返回空查询集，避免报错
            return AdditionalService.objects.none()

        # 获取所有启用的附加服务
        all_additional = AdditionalService.objects.filter(is_active=True).prefetch_related('applicable_pets')

        # 找出适用于该宠物类型的服务（通用 + 专属）
        applicable_ids = [
            addon.id for addon in all_additional
            if addon.is_applicable_for_pet(pet_type)
        ]

        # 返回筛选后的附加服务
        return AdditionalService.objects.filter(id__in=applicable_ids).prefetch_related('applicable_pets')

# ==================== 宠物类型关联服务视图 ====================

class PetTypeServicesView(generics.ListAPIView):
    """根据宠物类型获取可用的基础服务和附加服务"""
    permission_classes = [AllowAny]

    def list(self, request, *args, **kwargs):
        pet_type_id = self.kwargs.get('pet_type_id')

        try:
            pet_type = PetType.objects.get(id=pet_type_id, is_active=True)
        except PetType.DoesNotExist:
            return Response({
                'error': '宠物类型不存在或已停用',
                'pet_type_id': pet_type_id
            }, status=404)

        # 获取所有活跃的基础服务与附加服务
        base_services = ServiceModel.objects.filter(is_active=True).prefetch_related('applicable_pets')
        add_services = AdditionalService.objects.filter(is_active=True).prefetch_related('applicable_pets')

        # 筛选适用服务（通用 + 专属）
        applicable_base = [srv for srv in base_services if srv.is_applicable_for_pet(pet_type)]
        applicable_add = [srv for srv in add_services if srv.is_applicable_for_pet(pet_type)]

        return Response({
            'pet_type': {
                'id': pet_type.id,
                'name': pet_type.name,
                'base_price': pet_type.base_price,
                'description': pet_type.description,
            },
            # 使用带描述字段的简化序列化器
            'services': ServiceModelSimpleSerializer(applicable_base, many=True).data,
            'additional_services': AdditionalServiceSimpleSerializer(applicable_add, many=True).data,
            'services_count': len(applicable_base),
            'additional_services_count': len(applicable_add),
        })


# ==================== 统计与搜索 ====================

@api_view(['GET'])
@permission_classes([AllowAny])
def service_summary_view(request):
    """服务概要统计信息"""
    total_services = ServiceModel.objects.filter(is_active=True).count()
    total_pet_types = PetType.objects.filter(is_active=True).count()
    total_additional = AdditionalService.objects.filter(is_active=True).count()

    service_prices = ServiceModel.objects.filter(is_active=True).aggregate(min_price=Min('base_price'), max_price=Max('base_price'))
    additional_prices = AdditionalService.objects.filter(is_active=True).aggregate(min_price=Min('price'), max_price=Max('price'))
    pet_type_prices = PetType.objects.filter(is_active=True).aggregate(min_price=Min('base_price'), max_price=Max('base_price'))

    return Response({
        'total_services': total_services,
        'total_pet_types': total_pet_types,
        'total_additional_services': total_additional,
        'price_range': {
            'service_min_price': service_prices['min_price'] or 0,
            'service_max_price': service_prices['max_price'] or 0,
            'additional_min_price': additional_prices['min_price'] or 0,
            'additional_max_price': additional_prices['max_price'] or 0,
            'pet_type_min_price': pet_type_prices['min_price'] or 0,
            'pet_type_max_price': pet_type_prices['max_price'] or 0,
        }
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def search_services_view(request):
    """全局服务搜索 - 带分页"""
    query = request.GET.get('q', '').strip()
    if not query:
        return Response({
            'services': {'results': [], 'count': 0},
            'pet_types': {'results': [], 'count': 0},
            'additional_services': {'results': [], 'count': 0},
            'total_results': 0,
            'query': ''
        })

    paginator = CustomPageNumberPagination()

    # 搜索基础服务、宠物类型、附加服务
    services_qs = ServiceModel.objects.filter(Q(name__icontains=query) | Q(description__icontains=query), is_active=True)
    pet_types_qs = PetType.objects.filter(Q(name__icontains=query) | Q(description__icontains=query), is_active=True)
    additional_qs = AdditionalService.objects.filter(Q(name__icontains=query) | Q(description__icontains=query), is_active=True)

    return Response({
        'services': {
            'results': ServiceModelSimpleSerializer(services_qs, many=True).data,
            'count': services_qs.count(),
        },
        'pet_types': {
            'results': PetTypeSerializer(pet_types_qs, many=True).data,
            'count': pet_types_qs.count(),
        },
        'additional_services': {
            'results': AdditionalServiceSimpleSerializer(additional_qs, many=True).data,
            'count': additional_qs.count(),
        },
        'total_results': services_qs.count() + pet_types_qs.count() + additional_qs.count(),
        'query': query,
    })
