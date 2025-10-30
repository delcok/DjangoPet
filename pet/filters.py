# -*- coding: utf-8 -*-
# @Time    : 2025/10/20 18:53
# @Author  : Delock

import django_filters
from django.db.models import Q
from .models import Pet, PetDiary, PetServiceRecord


class PetFilter(django_filters.FilterSet):
    """宠物过滤器"""

    # 分类过滤
    category = django_filters.NumberFilter(field_name='category__id')
    category_name = django_filters.CharFilter(
        field_name='category__name',
        lookup_expr='icontains'
    )

    # 性别过滤
    gender = django_filters.ChoiceFilter(choices=Pet.GENDER_CHOICES)

    # 年龄范围过滤（按出生日期计算）
    min_age_months = django_filters.NumberFilter(method='filter_min_age')
    max_age_months = django_filters.NumberFilter(method='filter_max_age')

    # 体重范围过滤
    min_weight = django_filters.NumberFilter(field_name='weight', lookup_expr='gte')
    max_weight = django_filters.NumberFilter(field_name='weight', lookup_expr='lte')

    # 品种过滤
    breed = django_filters.CharFilter(lookup_expr='icontains')

    # 日期范围过滤
    created_after = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte'
    )
    created_before = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte'
    )

    # 出生日期范围
    birth_after = django_filters.DateFilter(
        field_name='birth_date',
        lookup_expr='gte'
    )
    birth_before = django_filters.DateFilter(
        field_name='birth_date',
        lookup_expr='lte'
    )

    # 综合搜索
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Pet
        fields = [
            'category', 'gender', 'breed',
            'min_weight', 'max_weight'
        ]

    def filter_min_age(self, queryset, name, value):
        """过滤最小年龄（月）"""
        from datetime import date
        from dateutil.relativedelta import relativedelta

        # 计算对应的出生日期
        max_birth_date = date.today() - relativedelta(months=int(value))
        return queryset.filter(birth_date__lte=max_birth_date)

    def filter_max_age(self, queryset, name, value):
        """过滤最大年龄（月）"""
        from datetime import date
        from dateutil.relativedelta import relativedelta

        # 计算对应的出生日期
        min_birth_date = date.today() - relativedelta(months=int(value))
        return queryset.filter(birth_date__gte=min_birth_date)

    def filter_search(self, queryset, name, value):
        """综合搜索：名称、品种、颜色"""
        return queryset.filter(
            Q(name__icontains=value) |
            Q(breed__icontains=value) |
            Q(color__icontains=value)
        )


class PetDiaryFilter(django_filters.FilterSet):
    """宠物日记过滤器"""

    # 宠物过滤
    pet = django_filters.NumberFilter(field_name='pet__id')
    pet_name = django_filters.CharFilter(
        field_name='pet__name',
        lookup_expr='icontains'
    )

    # 作者过滤
    author = django_filters.NumberFilter(field_name='author__id')
    author_name = django_filters.CharFilter(
        field_name='author__username',
        lookup_expr='icontains'
    )

    # 日记类型
    diary_type = django_filters.ChoiceFilter(
        choices=PetDiary.DIARY_TYPE_CHOICES
    )

    # 日期范围过滤
    diary_date_after = django_filters.DateFilter(
        field_name='diary_date',
        lookup_expr='gte'
    )
    diary_date_before = django_filters.DateFilter(
        field_name='diary_date',
        lookup_expr='lte'
    )

    # 创建时间范围
    created_after = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte'
    )
    created_before = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte'
    )

    # 是否有图片/视频
    has_images = django_filters.BooleanFilter(method='filter_has_images')
    has_videos = django_filters.BooleanFilter(method='filter_has_videos')

    # 综合搜索
    search = django_filters.CharFilter(method='filter_search')

    # 年月过滤
    year = django_filters.NumberFilter(field_name='diary_date__year')
    month = django_filters.NumberFilter(field_name='diary_date__month')

    class Meta:
        model = PetDiary
        fields = [
            'pet', 'author', 'diary_type',
            'year', 'month'
        ]

    def filter_has_images(self, queryset, name, value):
        """过滤是否有图片"""
        if value:
            return queryset.exclude(images__isnull=True).exclude(images=[])
        return queryset.filter(Q(images__isnull=True) | Q(images=[]))

    def filter_has_videos(self, queryset, name, value):
        """过滤是否有视频"""
        if value:
            return queryset.exclude(videos__isnull=True).exclude(videos=[])
        return queryset.filter(Q(videos__isnull=True) | Q(videos=[]))

    def filter_search(self, queryset, name, value):
        """综合搜索：标题、内容"""
        return queryset.filter(
            Q(title__icontains=value) |
            Q(content__icontains=value)
        )


class PetServiceRecordFilter(django_filters.FilterSet):
    """宠物服务记录过滤器"""

    # 订单过滤
    order = django_filters.NumberFilter(field_name='related_order__id')
    order_number = django_filters.CharFilter(
        field_name='related_order__order_number',
        lookup_expr='icontains'
    )

    # 宠物过滤
    pet = django_filters.NumberFilter(method='filter_pet')

    # 服务提供者过滤
    provider = django_filters.NumberFilter(field_name='related_order__staff__id')
    provider_name = django_filters.CharFilter(
        field_name='related_order__staff__username',
        lookup_expr='icontains'
    )

    # 客户过滤
    customer = django_filters.NumberFilter(field_name='related_order__customer__id')

    # 评分过滤
    rating = django_filters.NumberFilter()
    min_rating = django_filters.NumberFilter(
        field_name='rating',
        lookup_expr='gte'
    )
    max_rating = django_filters.NumberFilter(
        field_name='rating',
        lookup_expr='lte'
    )
    has_rating = django_filters.BooleanFilter(method='filter_has_rating')

    # 时间范围过滤
    start_after = django_filters.DateTimeFilter(
        field_name='actual_start_time',
        lookup_expr='gte'
    )
    start_before = django_filters.DateTimeFilter(
        field_name='actual_start_time',
        lookup_expr='lte'
    )

    end_after = django_filters.DateTimeFilter(
        field_name='actual_end_time',
        lookup_expr='gte'
    )
    end_before = django_filters.DateTimeFilter(
        field_name='actual_end_time',
        lookup_expr='lte'
    )

    # 服务日期过滤（按日期）
    service_date = django_filters.DateFilter(
        field_name='actual_start_time__date'
    )

    # 时长范围
    min_duration = django_filters.NumberFilter(
        field_name='actual_duration',
        lookup_expr='gte'
    )
    max_duration = django_filters.NumberFilter(
        field_name='actual_duration',
        lookup_expr='lte'
    )

    # 是否有反馈
    has_feedback = django_filters.BooleanFilter(method='filter_has_feedback')

    # 是否有日记关联
    has_diary = django_filters.BooleanFilter(method='filter_has_diary')

    # 年月过滤
    year = django_filters.NumberFilter(field_name='actual_start_time__year')
    month = django_filters.NumberFilter(field_name='actual_start_time__month')

    class Meta:
        model = PetServiceRecord
        fields = [
            'order', 'rating', 'year', 'month'
        ]

    def filter_pet(self, queryset, name, value):
        """通过宠物ID过滤"""
        return queryset.filter(related_order__pets__id=value)

    def filter_has_rating(self, queryset, name, value):
        """过滤是否有评分"""
        if value:
            return queryset.exclude(rating__isnull=True)
        return queryset.filter(rating__isnull=True)

    def filter_has_feedback(self, queryset, name, value):
        """过滤是否有客户反馈"""
        if value:
            return queryset.exclude(
                Q(customer_feedback__isnull=True) | Q(customer_feedback='')
            )
        return queryset.filter(
            Q(customer_feedback__isnull=True) | Q(customer_feedback='')
        )

    def filter_has_diary(self, queryset, name, value):
        """过滤是否有关联日记"""
        if value:
            return queryset.exclude(related_diary__isnull=True)
        return queryset.filter(related_diary__isnull=True)