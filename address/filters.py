# -*- coding: utf-8 -*-
# @Time    : 2026/4/16 17:07
# @Author  : Delock
import django_filters
from .models import UserAddress


class UserAddressFilter(django_filters.FilterSet):
    """
    用户端地址筛选
    - tag: 按标签筛选（家/公司/学校）
    - address_type: 按地址类型筛选
    - keyword: 模糊搜索小区名/街道/收货人
    """
    keyword = django_filters.CharFilter(method='filter_keyword', label='关键词搜索')
    tag = django_filters.CharFilter(field_name='tag', lookup_expr='exact')
    address_type = django_filters.CharFilter(field_name='address_type', lookup_expr='exact')
    is_default = django_filters.BooleanFilter(field_name='is_default')

    class Meta:
        model = UserAddress
        fields = ['tag', 'address_type', 'is_default']

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        from django.db import models
        return queryset.filter(
            models.Q(receiver_name__icontains=value) |
            models.Q(community__icontains=value) |
            models.Q(building__icontains=value) |
            models.Q(street__icontains=value) |
            models.Q(detail_address__icontains=value)
        )


class UserAddressAdminFilter(django_filters.FilterSet):
    """
    管理端地址筛选
    - keyword: 搜索收货人/手机号/小区名/街道
    - user_id: 按用户ID精确筛选
    - address_type: 按地址类型
    - community: 按小区名模糊搜索
    - created_after / created_before: 时间范围
    """
    keyword = django_filters.CharFilter(method='filter_keyword', label='关键词搜索')
    user_id = django_filters.NumberFilter(field_name='user_id', lookup_expr='exact')
    address_type = django_filters.CharFilter(field_name='address_type', lookup_expr='exact')
    community = django_filters.CharFilter(field_name='community', lookup_expr='icontains')
    tag = django_filters.CharFilter(field_name='tag', lookup_expr='exact')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = UserAddress
        fields = ['user_id', 'address_type', 'community', 'tag']

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        from django.db import models
        return queryset.filter(
            models.Q(receiver_name__icontains=value) |
            models.Q(receiver_phone__icontains=value) |
            models.Q(community__icontains=value) |
            models.Q(building__icontains=value) |
            models.Q(street__icontains=value) |
            models.Q(detail_address__icontains=value)
        )