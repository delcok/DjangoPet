# -*- coding: utf-8 -*-
# @Time    : 2026/6/7 16:24
# @Author  : Delock

# -*- coding: utf-8 -*-
"""
adoption/filters.py — 领养模块过滤器

依赖: pip install django-filter
settings: INSTALLED_APPS += ['django_filters']
视图配合: filter_backends = [DjangoFilterBackend, OrderingFilter]

排序交给 DRF 的 OrderingFilter,在视图上声明:
    StrayPet:  ordering_fields = ['created_at', 'favorite_count', 'view_count', 'sort_weight']
    Application: ordering_fields = ['created_at', 'review_score']
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as filters

from .models import (
    AdopterProfile, AdoptionApplication, AdoptionUpdate, AdoptionUpdateTask,
    AdoptionViolation, StrayPet,
)


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    """支持逗号分隔多选: ?species=cat,dog"""
    pass


# ============================================================
# 宠物筛选(C端列表页 + 后台)
# ============================================================
class StrayPetFilter(filters.FilterSet):
    species = CharInFilter(field_name='species', lookup_expr='in')
    gender = filters.CharFilter(field_name='gender')
    size = CharInFilter(field_name='size', lookup_expr='in')
    province = filters.CharFilter(field_name='province')
    city = filters.CharFilter(field_name='city')
    district = filters.CharFilter(field_name='district')
    # C端视图 queryset 已限定可见状态,status 筛选主要给后台用
    status = CharInFilter(field_name='status', lookup_expr='in')

    is_sterilized = filters.BooleanFilter(field_name='is_sterilized')
    is_vaccinated = filters.BooleanFilter(field_name='is_vaccinated')
    good_with_kids = filters.BooleanFilter(field_name='good_with_kids')
    good_with_pets = filters.BooleanFilter(field_name='good_with_pets')

    # 只看还有名额的: ?has_quota=true
    has_quota = filters.BooleanFilter(method='filter_has_quota')

    # 年龄区间(岁),基于预估出生日期换算
    age_min = filters.NumberFilter(method='filter_age_min')
    age_max = filters.NumberFilter(method='filter_age_max')

    # 关键词: 昵称/品种/毛色/救助故事
    keyword = filters.CharFilter(method='filter_keyword')

    created_after = filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = StrayPet
        fields = []  # 全部用上方显式声明,避免误开放内部字段

    def filter_has_quota(self, queryset, name, value):
        if value:
            return queryset.filter(status='available')
        return queryset

    def filter_age_min(self, queryset, name, value):
        # 年龄 >= N 岁 → 出生日期 <= 今天 - N年(无出生日期的不参与年龄筛选)
        cutoff = timezone.now().date() - timedelta(days=int(float(value) * 365))
        return queryset.filter(birth_date_est__lte=cutoff)

    def filter_age_max(self, queryset, name, value):
        cutoff = timezone.now().date() - timedelta(days=int(float(value) * 365))
        return queryset.filter(birth_date_est__gte=cutoff)

    def filter_keyword(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value) | Q(breed__icontains=value) |
            Q(color__icontains=value) | Q(rescue_story__icontains=value))


# ============================================================
# 申请单筛选(主要后台用;C端"我的申请"按 status 即可)
# ============================================================
class AdoptionApplicationFilter(filters.FilterSet):
    status = CharInFilter(field_name='status', lookup_expr='in')
    pet = filters.NumberFilter(field_name='pet_id')
    applicant = filters.NumberFilter(field_name='applicant_id')
    housing_type = filters.CharFilter(field_name='housing_type')
    has_experience = filters.BooleanFilter(field_name='has_experience')

    score_min = filters.NumberFilter(field_name='review_score', lookup_expr='gte')
    score_max = filters.NumberFilter(field_name='review_score', lookup_expr='lte')

    # 后台快捷搜索: 单号/姓名/电话
    keyword = filters.CharFilter(method='filter_keyword')

    created_after = filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = AdoptionApplication
        fields = []

    def filter_keyword(self, queryset, name, value):
        return queryset.filter(
            Q(application_no__icontains=value) |
            Q(real_name__icontains=value) |
            Q(phone__icontains=value))


# ============================================================
# 打卡任务筛选(后台逾期看板 + C端我的任务)
# ============================================================
class AdoptionUpdateTaskFilter(filters.FilterSet):
    application = filters.NumberFilter(field_name='application_id')
    status = CharInFilter(field_name='status', lookup_expr='in')
    due_after = filters.DateTimeFilter(field_name='due_end', lookup_expr='gte')
    due_before = filters.DateTimeFilter(field_name='due_end', lookup_expr='lte')

    class Meta:
        model = AdoptionUpdateTask
        fields = []


# ============================================================
# 领养动态筛选(宠物详情页"领养后的TA" + 后台审查队列)
# ============================================================
class AdoptionUpdateFilter(filters.FilterSet):
    # 宠物详情页动态流: ?pet=123
    pet = filters.NumberFilter(field_name='application__pet_id')
    application = filters.NumberFilter(field_name='application_id')
    source = filters.CharFilter(field_name='source')
    review_status = CharInFilter(field_name='review_status', lookup_expr='in')
    is_public = filters.BooleanFilter(field_name='is_public')

    class Meta:
        model = AdoptionUpdate
        fields = []


# ============================================================
# 违规记录筛选(后台)
# ============================================================
class AdoptionViolationFilter(filters.FilterSet):
    user = filters.NumberFilter(field_name='user_id')
    violation_type = CharInFilter(field_name='violation_type', lookup_expr='in')
    penalty = filters.CharFilter(field_name='penalty')
    is_system = filters.BooleanFilter(field_name='is_system')
    created_after = filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = AdoptionViolation
        fields = []


# ============================================================
# 领养资格档案筛选(后台风控看板)
# ============================================================
class AdopterProfileFilter(filters.FilterSet):
    status = CharInFilter(field_name='status', lookup_expr='in')
    credit_min = filters.NumberFilter(field_name='credit_score', lookup_expr='gte')
    credit_max = filters.NumberFilter(field_name='credit_score', lookup_expr='lte')
    # 按手机号/用户名查人
    keyword = filters.CharFilter(method='filter_keyword')

    class Meta:
        model = AdopterProfile
        fields = []

    def filter_keyword(self, queryset, name, value):
        return queryset.filter(
            Q(user__phone__icontains=value) |
            Q(user__username__icontains=value))