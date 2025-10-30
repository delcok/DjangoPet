from rest_framework import generics, filters
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from .models import ServiceModel, PetType, AdditionalService
from .pagination import CustomPageNumberPagination
from .serializers import (
    ServiceModelSerializer,
    PetTypeSerializer,
    AdditionalServiceSerializer,
    AdditionalServiceSimpleSerializer
)
from .filters import ServiceModelFilter, PetTypeFilter, AdditionalServiceFilter


class ServiceModelListView(generics.ListAPIView):
    """基础服务列表视图 - 只读"""
    queryset = ServiceModel.objects.filter(is_active=True)
    serializer_class = ServiceModelSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ServiceModelFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'base_price', 'created_at']
    ordering = ['-created_at']


class ServiceModelDetailView(generics.RetrieveAPIView):
    """基础服务详情视图 - 只读"""
    queryset = ServiceModel.objects.filter(is_active=True)
    serializer_class = ServiceModelSerializer


class PetTypeListView(generics.ListAPIView):
    """宠物类型列表视图 - 只读"""
    queryset = PetType.objects.filter(is_active=True)
    serializer_class = PetTypeSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PetTypeFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'base_price', 'created_at']
    ordering = ['name']


class PetTypeDetailView(generics.RetrieveAPIView):
    """宠物类型详情视图 - 只读"""
    queryset = PetType.objects.filter(is_active=True)
    serializer_class = PetTypeSerializer


class AdditionalServiceListView(generics.ListAPIView):
    """附加服务列表视图 - 只读"""
    queryset = AdditionalService.objects.filter(is_active=True).prefetch_related('applicable_pets')
    serializer_class = AdditionalServiceSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AdditionalServiceFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'price', 'created_at']
    ordering = ['-created_at']


class AdditionalServiceDetailView(generics.RetrieveAPIView):
    """附加服务详情视图 - 只读"""
    queryset = AdditionalService.objects.filter(is_active=True).prefetch_related('applicable_pets')
    serializer_class = AdditionalServiceSerializer


class PetTypeServiceView(generics.ListAPIView):
    """根据宠物类型获取可用的附加服务"""
    serializer_class = AdditionalServiceSimpleSerializer

    def get_queryset(self):
        pet_type_id = self.kwargs.get('pet_type_id')
        return AdditionalService.objects.filter(
            is_active=True,
            applicable_pets__id=pet_type_id
        ).prefetch_related('applicable_pets')


@api_view(['GET'])
@permission_classes([AllowAny])
def service_summary_view(request):
    """服务概要统计信息"""
    data = {
        'total_services': ServiceModel.objects.filter(is_active=True).count(),
        'total_pet_types': PetType.objects.filter(is_active=True).count(),
        'total_additional_services': AdditionalService.objects.filter(is_active=True).count(),
        'price_range': {
            'service_min_price': ServiceModel.objects.filter(is_active=True).aggregate(
                min_price=min('base_price')
            )['min_price'] or 0,
            'service_max_price': ServiceModel.objects.filter(is_active=True).aggregate(
                max_price=max('base_price')
            )['max_price'] or 0,
            'additional_min_price': AdditionalService.objects.filter(is_active=True).aggregate(
                min_price=min('price')
            )['min_price'] or 0,
            'additional_max_price': AdditionalService.objects.filter(is_active=True).aggregate(
                max_price=max('price')
            )['max_price'] or 0,
        }
    }
    return Response(data)


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
            'total_results': 0
        })

    # 创建分页器
    paginator = CustomPageNumberPagination()

    # 搜索基础服务
    services_qs = ServiceModel.objects.filter(
        Q(name__icontains=query) | Q(description__icontains=query),
        is_active=True
    )

    # 搜索宠物类型
    pet_types_qs = PetType.objects.filter(
        Q(name__icontains=query) | Q(description__icontains=query),
        is_active=True
    )

    # 搜索附加服务
    additional_services_qs = AdditionalService.objects.filter(
        Q(name__icontains=query) | Q(description__icontains=query),
        is_active=True
    ).prefetch_related('applicable_pets')

    # 分页处理
    services_page = paginator.paginate_queryset(services_qs, request)
    pet_types_page = paginator.paginate_queryset(pet_types_qs, request)
    additional_services_page = paginator.paginate_queryset(additional_services_qs, request)

    # 序列化数据
    services_data = ServiceModelSerializer(services_page or services_qs, many=True).data
    pet_types_data = PetTypeSerializer(pet_types_page or pet_types_qs, many=True).data
    additional_services_data = AdditionalServiceSimpleSerializer(
        additional_services_page or additional_services_qs, many=True
    ).data

    return Response({
        'services': {
            'results': services_data,
            'count': services_qs.count(),
            'pagination_info': paginator.get_paginated_response(services_data).data.get(
                'pagination') if services_page else None
        },
        'pet_types': {
            'results': pet_types_data,
            'count': pet_types_qs.count(),
            'pagination_info': paginator.get_paginated_response(pet_types_data).data.get(
                'pagination') if pet_types_page else None
        },
        'additional_services': {
            'results': additional_services_data,
            'count': additional_services_qs.count(),
            'pagination_info': paginator.get_paginated_response(additional_services_data).data.get(
                'pagination') if additional_services_page else None
        },
        'total_results': services_qs.count() + pet_types_qs.count() + additional_services_qs.count(),
        'query': query
    })