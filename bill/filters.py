# -*- coding: utf-8 -*-
# @Time    : 2026/4/16 18:25
# @Author  : Delock


import django_filters
from django.db import models as db_models
from .models import ProductOrder, ServiceOrder, OrderLog


# ══════ 通用工具 ══════

class StatusInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """
    支持 ?status=a,b,c 形式的多状态过滤。
    - 单值时与原 CharFilter 行为一致(?status=refunding 仍可用)
    - 多值时翻译为 status__in=[a,b,c]
    - 空值/全空逗号自动跳过过滤
    """
    pass


# ══════ 用户端 ══════

class UserProductOrderFilter(django_filters.FilterSet):
    # 改用 StatusInFilter:既支持单值,也支持 ?status=refunding,refunded
    status = StatusInFilter(field_name='status')
    is_reviewed = django_filters.BooleanFilter(field_name='is_reviewed')
    keyword = django_filters.CharFilter(method='filter_keyword')

    class Meta:
        model = ProductOrder
        fields = ['status', 'is_reviewed']

    def filter_keyword(self, qs, name, value):
        if not value:
            return qs
        return qs.filter(
            db_models.Q(order_no__icontains=value) |
            db_models.Q(merchant_name__icontains=value)
        )


class UserServiceOrderFilter(django_filters.FilterSet):
    # 改用 StatusInFilter:既支持单值,也支持 ?status=refunding,refunded
    status = StatusInFilter(field_name='status')
    service_type = django_filters.CharFilter(field_name='service_type')
    is_reviewed = django_filters.BooleanFilter(field_name='is_reviewed')
    keyword = django_filters.CharFilter(method='filter_keyword')

    class Meta:
        model = ServiceOrder
        fields = ['status', 'service_type', 'is_reviewed']

    def filter_keyword(self, qs, name, value):
        if not value:
            return qs
        return qs.filter(
            db_models.Q(order_no__icontains=value) |
            db_models.Q(merchant_name__icontains=value)
        )


# ══════ 商家端 ══════

class MerchantProductOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(method='filter_status')
    keyword = django_filters.CharFilter(method='filter_keyword')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = ProductOrder
        fields = ['status']

    def filter_status(self, qs, name, value):
        if not value:
            return qs
        statuses = [s.strip() for s in value.split(',') if s.strip()]
        if not statuses:
            return qs
        return qs.filter(status__in=statuses)

    def filter_keyword(self, qs, name, value):
        if not value:
            return qs
        return qs.filter(
            db_models.Q(order_no__icontains=value) |
            db_models.Q(receiver_name__icontains=value) |
            db_models.Q(receiver_phone__icontains=value) |
            db_models.Q(receiver_community__icontains=value)
        )


class MerchantServiceOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(method='filter_status')
    service_type = django_filters.CharFilter(field_name='service_type')
    service_mode = django_filters.CharFilter(field_name='service_mode')
    is_urgent = django_filters.BooleanFilter(field_name='is_urgent')
    assigned_staff = django_filters.NumberFilter(field_name='assigned_staff_id')
    keyword = django_filters.CharFilter(method='filter_keyword')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    appointment_date = django_filters.DateFilter(field_name='appointment_date')

    class Meta:
        model = ServiceOrder
        fields = ['status', 'service_type', 'service_mode', 'is_urgent']

    def filter_status(self, qs, name, value):
        if not value:
            return qs
        statuses = [s.strip() for s in value.split(',') if s.strip()]
        if not statuses:
            return qs
        return qs.filter(status__in=statuses)

    def filter_keyword(self, qs, name, value):
        if not value:
            return qs
        return qs.filter(
            db_models.Q(order_no__icontains=value) |
            db_models.Q(receiver_name__icontains=value) |
            db_models.Q(receiver_phone__icontains=value) |
            db_models.Q(receiver_community__icontains=value)
        )


# ══════ 管理端 ══════

class AdminProductOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status')
    user_id = django_filters.NumberFilter(field_name='user_id')
    merchant_id = django_filters.NumberFilter(field_name='merchant_id')
    keyword = django_filters.CharFilter(method='filter_keyword')
    pay_min = django_filters.NumberFilter(field_name='pay_amount', lookup_expr='gte')
    pay_max = django_filters.NumberFilter(field_name='pay_amount', lookup_expr='lte')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = ProductOrder
        fields = ['status', 'user_id', 'merchant_id']

    def filter_keyword(self, qs, name, value):
        if not value:
            return qs
        return qs.filter(
            db_models.Q(order_no__icontains=value) |
            db_models.Q(merchant_name__icontains=value) |
            db_models.Q(receiver_name__icontains=value) |
            db_models.Q(receiver_phone__icontains=value) |
            db_models.Q(shipping_no__icontains=value)
        )


class AdminServiceOrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(field_name='status')
    service_type = django_filters.CharFilter(field_name='service_type')
    service_mode = django_filters.CharFilter(field_name='service_mode')
    user_id = django_filters.NumberFilter(field_name='user_id')
    merchant_id = django_filters.NumberFilter(field_name='merchant_id')
    assigned_staff = django_filters.NumberFilter(field_name='assigned_staff_id')
    is_urgent = django_filters.BooleanFilter(field_name='is_urgent')
    keyword = django_filters.CharFilter(method='filter_keyword')
    pay_min = django_filters.NumberFilter(field_name='pay_amount', lookup_expr='gte')
    pay_max = django_filters.NumberFilter(field_name='pay_amount', lookup_expr='lte')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    appointment_date = django_filters.DateFilter(field_name='appointment_date')

    class Meta:
        model = ServiceOrder
        fields = ['status', 'service_type', 'service_mode', 'user_id', 'merchant_id', 'is_urgent']

    def filter_keyword(self, qs, name, value):
        if not value:
            return qs
        return qs.filter(
            db_models.Q(order_no__icontains=value) |
            db_models.Q(merchant_name__icontains=value) |
            db_models.Q(receiver_name__icontains=value) |
            db_models.Q(receiver_phone__icontains=value) |
            db_models.Q(verify_code__icontains=value)
        )


# ══════ 日志 ══════

class OrderLogFilter(django_filters.FilterSet):
    order_no = django_filters.CharFilter(field_name='order_no', lookup_expr='exact')
    order_type = django_filters.CharFilter(field_name='order_type')
    action = django_filters.CharFilter(field_name='action')
    operator_type = django_filters.CharFilter(field_name='operator_type')

    class Meta:
        model = OrderLog
        fields = ['order_no', 'order_type', 'action', 'operator_type']