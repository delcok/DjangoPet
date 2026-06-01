# -*- coding: utf-8 -*-
"""
服务模块过滤器

适配新版 model:
- schedule_type 已迁入 appointment_config JSON  → 用方法过滤器查询 JSON 路径
- support_urgent 已迁入 urgent_config 是否存在 → 用方法过滤器查询 isnull
- support_auto_dispatch 同理(若需要可补)
"""

import django_filters
from django.db.models import Q

from .models import Service, ServiceCategory


class ServiceFilter(django_filters.FilterSet):
    """服务筛选器"""

    # ─── 关键词搜索 ───
    keyword = django_filters.CharFilter(method='filter_keyword')

    # ─── 关联筛选 ───
    merchant_id = django_filters.NumberFilter(field_name='merchant_id')
    category_id = django_filters.NumberFilter(method='filter_category')  # 支持父分类

    # ─── 类型筛选 ───
    service_type = django_filters.ChoiceFilter(choices=Service.ServiceType.choices)
    service_mode = django_filters.ChoiceFilter(choices=Service.ServiceMode.choices)
    # schedule_type 现在嵌套在 appointment_config 里,用方法过滤器查 JSON
    schedule_type = django_filters.CharFilter(method='filter_schedule_type')

    # ─── 价格区间 ───
    price_min = django_filters.NumberFilter(field_name='price', lookup_expr='gte')
    price_max = django_filters.NumberFilter(field_name='price', lookup_expr='lte')

    # ─── 布尔筛选 ───
    is_recommended = django_filters.BooleanFilter()
    is_hot = django_filters.BooleanFilter()
    # support_urgent 由 urgent_config 是否存在决定
    support_urgent = django_filters.BooleanFilter(method='filter_support_urgent')
    # 是否需要指派员工(派单类服务筛选用)
    require_staff = django_filters.BooleanFilter(field_name='require_staff')

    # ─── 排序 ───
    ordering = django_filters.OrderingFilter(
        fields=(
            ('sort_order', 'sort'),
            ('price', 'price'),
            ('total_sales', 'sales'),
            ('rating', 'rating'),
            ('created_at', 'newest'),
        )
    )

    class Meta:
        model = Service
        fields = ['merchant_id', 'category_id', 'service_type', 'service_mode', 'status']

    # ──────────── 方法过滤器 ────────────

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) |
            Q(subtitle__icontains=value) |
            Q(description__icontains=value) |
            Q(merchant__name__icontains=value)
        )

    def filter_category(self, queryset, name, value):
        """
        按分类筛选,支持父分类(自动包含所有子孙分类下的服务)
        """
        if not value:
            return queryset
        try:
            category = ServiceCategory.objects.get(id=value)
        except ServiceCategory.DoesNotExist:
            return queryset.none()

        category_ids = [category.id]

        def collect_children(cat):
            for child in cat.children.filter(is_active=True):
                category_ids.append(child.id)
                collect_children(child)

        collect_children(category)
        return queryset.filter(category_id__in=category_ids)

    def filter_schedule_type(self, queryset, name, value):
        """
        schedule_type 现在存放在 appointment_config JSON 里
        查询路径: appointment_config -> 'schedule_type'
        Django 4+ JSONField __ 路径查询所有支持的 DB 都能用
        """
        if not value:
            return queryset
        return queryset.filter(appointment_config__schedule_type=value)

    def filter_support_urgent(self, queryset, name, value):
        """
        是否支持加急 = urgent_config 是否非空
        """
        if value is True:
            return queryset.filter(urgent_config__isnull=False)
        if value is False:
            return queryset.filter(urgent_config__isnull=True)
        return queryset


class ServiceCategoryFilter(django_filters.FilterSet):
    """服务分类筛选器"""

    # 层级
    level = django_filters.NumberFilter(field_name='level')
    # 父分类
    parent_id = django_filters.NumberFilter(field_name='parent_id')
    # 只看顶级
    root_only = django_filters.BooleanFilter(method='filter_root_only')
    # 状态
    is_active = django_filters.BooleanFilter(field_name='is_active')
    is_hot = django_filters.BooleanFilter(field_name='is_hot')
    # 关键词
    keyword = django_filters.CharFilter(method='filter_keyword')

    class Meta:
        model = ServiceCategory
        fields = ['level', 'parent_id', 'is_active', 'is_hot']

    def filter_root_only(self, queryset, name, value):
        if value:
            return queryset.filter(parent__isnull=True)
        return queryset

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value)
        )