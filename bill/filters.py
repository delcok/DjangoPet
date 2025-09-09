# -*- coding: utf-8 -*-
# @Time    : 2025/8/25 16:48
# @Author  : Delock

import django_filters
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta

from bill.models import Bill, ServiceOrder


class BillFilter(django_filters.FilterSet):
    """账单过滤器"""

    # 日期范围过滤
    start_date = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text='开始日期 (YYYY-MM-DD)'
    )
    end_date = django_filters.DateFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text='结束日期 (YYYY-MM-DD)'
    )

    # 金额范围过滤
    min_amount = django_filters.NumberFilter(
        field_name='amount',
        lookup_expr='gte',
        help_text='最小金额'
    )
    max_amount = django_filters.NumberFilter(
        field_name='amount',
        lookup_expr='lte',
        help_text='最大金额'
    )

    # 时间段快捷过滤
    date_range = django_filters.ChoiceFilter(
        method='filter_by_date_range',
        choices=[
            ('today', '今天'),
            ('yesterday', '昨天'),
            ('week', '本周'),
            ('month', '本月'),
            ('quarter', '本季度'),
            ('year', '本年'),
        ],
        help_text='时间段快捷选择'
    )

    # 模糊搜索
    search = django_filters.CharFilter(
        method='filter_by_search',
        help_text='搜索订单号、描述等'
    )

    class Meta:
        model = Bill
        fields = {
            'transaction_type': ['exact'],
            'payment_method': ['exact'],
            'payment_status': ['exact'],
            'user': ['exact'],
        }

    def filter_by_date_range(self, queryset, name, value):
        """按时间段过滤"""
        now = timezone.now()
        today = now.date()

        if value == 'today':
            return queryset.filter(created_at__date=today)
        elif value == 'yesterday':
            yesterday = today - timedelta(days=1)
            return queryset.filter(created_at__date=yesterday)
        elif value == 'week':
            week_start = today - timedelta(days=today.weekday())
            return queryset.filter(created_at__date__gte=week_start)
        elif value == 'month':
            month_start = today.replace(day=1)
            return queryset.filter(created_at__date__gte=month_start)
        elif value == 'quarter':
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            quarter_start = today.replace(month=quarter_month, day=1)
            return queryset.filter(created_at__date__gte=quarter_start)
        elif value == 'year':
            year_start = today.replace(month=1, day=1)
            return queryset.filter(created_at__date__gte=year_start)

        return queryset

    def filter_by_search(self, queryset, name, value):
        """模糊搜索"""
        return queryset.filter(
            Q(out_trade_no__icontains=value) |
            Q(wechat_transaction_id__icontains=value) |
            Q(description__icontains=value) |
            Q(user__username__icontains=value)
        )


class ServiceOrderFilter(django_filters.FilterSet):
    """服务订单过滤器"""

    # 日期范围过滤
    start_date = django_filters.DateFilter(
        field_name='scheduled_date',
        lookup_expr='gte',
        help_text='预约开始日期 (YYYY-MM-DD)'
    )
    end_date = django_filters.DateFilter(
        field_name='scheduled_date',
        lookup_expr='lte',
        help_text='预约结束日期 (YYYY-MM-DD)'
    )

    # 创建时间范围
    created_start = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        help_text='创建开始时间'
    )
    created_end = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        help_text='创建结束时间'
    )

    # 价格范围过滤
    min_price = django_filters.NumberFilter(
        field_name='total_price',
        lookup_expr='gte',
        help_text='最小价格'
    )
    max_price = django_filters.NumberFilter(
        field_name='total_price',
        lookup_expr='lte',
        help_text='最大价格'
    )

    # 多状态过滤
    status_in = django_filters.BaseInFilter(
        field_name='status',
        help_text='状态列表，用逗号分隔'
    )

    # 时间段快捷过滤
    scheduled_range = django_filters.ChoiceFilter(
        method='filter_by_scheduled_range',
        choices=[
            ('today', '今天'),
            ('tomorrow', '明天'),
            ('week', '本周'),
            ('month', '本月'),
        ],
        help_text='预约时间段快捷选择'
    )

    # 按宠物过滤
    pet = django_filters.NumberFilter(
        field_name='pets',
        help_text='宠物ID'
    )

    # 搜索
    search = django_filters.CharFilter(
        method='filter_by_search',
        help_text='搜索地址、电话、备注等'
    )

    # 是否有员工分配
    has_staff = django_filters.BooleanFilter(
        method='filter_by_staff',
        help_text='是否已分配员工'
    )

    class Meta:
        model = ServiceOrder
        fields = {
            'status': ['exact'],
            'staff': ['exact'],
            'user': ['exact'],
        }

    def filter_by_scheduled_range(self, queryset, name, value):
        """按预约时间段过滤"""
        today = timezone.now().date()

        if value == 'today':
            return queryset.filter(scheduled_date=today)
        elif value == 'tomorrow':
            tomorrow = today + timedelta(days=1)
            return queryset.filter(scheduled_date=tomorrow)
        elif value == 'week':
            week_start = today
            week_end = today + timedelta(days=6)
            return queryset.filter(scheduled_date__range=[week_start, week_end])
        elif value == 'month':
            month_start = today.replace(day=1)
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            month_end = next_month - timedelta(days=1)
            return queryset.filter(scheduled_date__range=[month_start, month_end])

        return queryset

    def filter_by_search(self, queryset, name, value):
        """模糊搜索"""
        return queryset.filter(
            Q(service_address__icontains=value) |
            Q(contact_phone__icontains=value) |
            Q(customer_notes__icontains=value) |
            Q(staff_notes__icontains=value) |
            Q(user__username__icontains=value) |
            Q(staff__name__icontains=value)
        )

    def filter_by_staff(self, queryset, name, value):
        """按是否分配员工过滤"""
        if value:
            return queryset.exclude(staff__isnull=True)
        else:
            return queryset.filter(staff__isnull=True)