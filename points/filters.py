# -*- coding: utf-8 -*-
# @Time    : 2026/5/31 20:05
# @Author  : Delock

# -*- coding: utf-8 -*-
# @Time    : 2026/1/3
# @Author  : Delock
"""
积分模块过滤器

- IntegralProductFilter   商品（C 端列表 + 后台列表共用）
- IntegralOrderFilter     订单（C 端"我的订单" + 后台订单共用）
- PointsTransactionFilter 积分流水（建在钱包 WalletTransaction 上，仅积分币种）
"""

import django_filters
from django.db.models import Q

from .models import IntegralProduct, IntegralOrder
from wallet.models import WalletTransaction


class IntegralProductFilter(django_filters.FilterSet):
    """积分商品过滤器"""

    # 类型：兼容旧 C 端的 ?type=，同时提供 ?product_type=
    type = django_filters.ChoiceFilter(
        field_name='product_type', choices=IntegralProduct.PRODUCT_TYPE_CHOICES
    )
    product_type = django_filters.ChoiceFilter(
        field_name='product_type', choices=IntegralProduct.PRODUCT_TYPE_CHOICES
    )
    status = django_filters.ChoiceFilter(choices=IntegralProduct.STATUS_CHOICES)

    category = django_filters.CharFilter(field_name='category', lookup_expr='exact')
    category_contains = django_filters.CharFilter(field_name='category', lookup_expr='icontains')

    is_hot = django_filters.BooleanFilter()
    is_new = django_filters.BooleanFilter()

    # 积分价格区间
    min_price = django_filters.NumberFilter(field_name='integral_price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='integral_price', lookup_expr='lte')

    # 库存
    min_stock = django_filters.NumberFilter(field_name='stock', lookup_expr='gte')
    in_stock = django_filters.BooleanFilter(method='filter_in_stock')

    # 关键词（名称 / 描述）
    keyword = django_filters.CharFilter(method='filter_keyword')

    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    ordering = django_filters.OrderingFilter(
        fields=(
            ('sort_order', 'sort_order'),
            ('integral_price', 'integral_price'),
            ('sales_count', 'sales_count'),
            ('stock', 'stock'),
            ('created_at', 'created_at'),
        )
    )

    class Meta:
        model = IntegralProduct
        fields = []

    def filter_in_stock(self, queryset, name, value):
        if value:
            return queryset.filter(stock__gt=0)
        return queryset.filter(stock=0)

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )


class IntegralOrderFilter(django_filters.FilterSet):
    """积分订单过滤器"""

    status = django_filters.ChoiceFilter(choices=IntegralOrder.STATUS_CHOICES)
    product = django_filters.NumberFilter(field_name='product_id')
    product_type = django_filters.ChoiceFilter(
        field_name='product__product_type', choices=IntegralProduct.PRODUCT_TYPE_CHOICES
    )
    user_id = django_filters.NumberFilter(field_name='user_id')  # 后台按用户筛选
    order_no = django_filters.CharFilter(field_name='order_no', lookup_expr='icontains')

    has_express = django_filters.BooleanFilter(method='filter_has_express')

    # 积分消耗区间
    min_cost = django_filters.NumberFilter(field_name='integral_cost', lookup_expr='gte')
    max_cost = django_filters.NumberFilter(field_name='integral_cost', lookup_expr='lte')

    # 时间区间
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    completed_after = django_filters.DateTimeFilter(field_name='completed_at', lookup_expr='gte')
    completed_before = django_filters.DateTimeFilter(field_name='completed_at', lookup_expr='lte')

    keyword = django_filters.CharFilter(method='filter_keyword')

    ordering = django_filters.OrderingFilter(
        fields=(
            ('created_at', 'created_at'),
            ('shipped_at', 'shipped_at'),
            ('completed_at', 'completed_at'),
            ('integral_cost', 'integral_cost'),
        )
    )

    class Meta:
        model = IntegralOrder
        fields = []

    def filter_has_express(self, queryset, name, value):
        if value:
            return queryset.exclude(express_no='')
        return queryset.filter(express_no='')

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(order_no__icontains=value) |
            Q(receiver_name__icontains=value) |
            Q(receiver_phone__icontains=value)
        )


class PointsTransactionFilter(django_filters.FilterSet):
    """积分流水过滤器（建在钱包 WalletTransaction 上）

    注意：视图层已固定 currency=points，这里不再暴露币种过滤。
    action 取值见 WalletTransaction.Action（积分相关：exchange / refund_return /
    admin_grant / admin_deduct / order_reward / sign_in / expired ...）。
    """

    action = django_filters.ChoiceFilter(choices=WalletTransaction.Action.choices)
    status = django_filters.ChoiceFilter(choices=WalletTransaction.Status.choices)
    user_id = django_filters.NumberFilter(field_name='user_id')  # 后台按用户筛选

    # 收支方向
    direction = django_filters.ChoiceFilter(
        method='filter_direction',
        choices=[('in', '收入'), ('out', '支出')],
    )
    min_amount = django_filters.NumberFilter(field_name='amount', lookup_expr='gte')
    max_amount = django_filters.NumberFilter(field_name='amount', lookup_expr='lte')

    related_type = django_filters.CharFilter(field_name='related_type', lookup_expr='exact')
    related_id = django_filters.NumberFilter(field_name='related_id')

    keyword = django_filters.CharFilter(field_name='remark', lookup_expr='icontains')

    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    ordering = django_filters.OrderingFilter(
        fields=(
            ('created_at', 'created_at'),
            ('amount', 'amount'),
        )
    )

    class Meta:
        model = WalletTransaction
        fields = []

    def filter_direction(self, queryset, name, value):
        if value == 'in':
            return queryset.filter(amount__gt=0)
        if value == 'out':
            return queryset.filter(amount__lt=0)
        return queryset