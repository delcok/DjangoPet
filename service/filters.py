# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Delock

from django_filters import rest_framework as filters
from .models import ServiceModel, PetType, AdditionalService


class PetTypeFilter(filters.FilterSet):
    """宠物类型过滤器"""
    name = filters.CharFilter(lookup_expr='icontains', label='宠物类型名称')
    min_price = filters.NumberFilter(field_name='base_price', lookup_expr='gte', label='最低基础价格')
    max_price = filters.NumberFilter(field_name='base_price', lookup_expr='lte', label='最高基础价格')
    price_range = filters.RangeFilter(field_name='base_price', label='基础价格范围')
    created_after = filters.DateFilter(field_name='created_at', lookup_expr='date__gte', label='创建日期从')
    created_before = filters.DateFilter(field_name='created_at', lookup_expr='date__lte', label='创建日期到')

    class Meta:
        model = PetType
        fields = ['name', 'is_active']


class ServiceModelFilter(filters.FilterSet):
    """基础服务过滤器"""
    name = filters.CharFilter(lookup_expr='icontains', label='服务名称')
    min_price = filters.NumberFilter(field_name='base_price', lookup_expr='gte', label='最低价格')
    max_price = filters.NumberFilter(field_name='base_price', lookup_expr='lte', label='最高价格')
    price_range = filters.RangeFilter(field_name='base_price', label='价格范围')
    applicable_pets = filters.ModelMultipleChoiceFilter(
        queryset=PetType.objects.filter(is_active=True),
        label='适用宠物类型'
    )
    has_pets = filters.BooleanFilter(
        method='filter_has_pets',
        label='是否有指定适用宠物'
    )
    created_after = filters.DateFilter(field_name='created_at', lookup_expr='date__gte', label='创建日期从')
    created_before = filters.DateFilter(field_name='created_at', lookup_expr='date__lte', label='创建日期到')

    class Meta:
        model = ServiceModel
        fields = ['name', 'is_active', 'applicable_pets']

    def filter_has_pets(self, queryset, name, value):
        """
        过滤是否有指定适用宠物类型
        True: 有指定宠物类型（专属服务）
        False: 没有指定（通用服务）
        """
        if value is True:
            # 有指定适用宠物的服务
            return queryset.exclude(applicable_pets__isnull=True).distinct()
        elif value is False:
            # 没有指定适用宠物的服务（通用服务）
            return queryset.filter(applicable_pets__isnull=True)
        return queryset


class AdditionalServiceFilter(filters.FilterSet):
    """附加服务过滤器"""
    name = filters.CharFilter(lookup_expr='icontains', label='服务名称')
    min_price = filters.NumberFilter(field_name='price', lookup_expr='gte', label='最低价格')
    max_price = filters.NumberFilter(field_name='price', lookup_expr='lte', label='最高价格')
    price_range = filters.RangeFilter(field_name='price', label='价格范围')
    applicable_pets = filters.ModelMultipleChoiceFilter(
        queryset=PetType.objects.filter(is_active=True),
        label='适用宠物类型'
    )
    has_pets = filters.BooleanFilter(
        method='filter_has_pets',
        label='是否有指定适用宠物'
    )
    created_after = filters.DateFilter(field_name='created_at', lookup_expr='date__gte', label='创建日期从')
    created_before = filters.DateFilter(field_name='created_at', lookup_expr='date__lte', label='创建日期到')

    class Meta:
        model = AdditionalService
        fields = ['name', 'is_active', 'applicable_pets']

    def filter_has_pets(self, queryset, name, value):
        """
        过滤是否有指定适用宠物类型
        True: 有指定宠物类型（专属服务）
        False: 没有指定（通用服务）
        """
        if value is True:
            # 有指定适用宠物的附加服务
            return queryset.exclude(applicable_pets__isnull=True).distinct()
        elif value is False:
            # 没有指定适用宠物的附加服务（通用服务）
            return queryset.filter(applicable_pets__isnull=True)
        return queryset