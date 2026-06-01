# -*- coding: utf-8 -*-
# @Time    : 2026/4/17
# @Author  : Delock

import django_filters
from django.db.models import Q
from .models import User, UserDevice, UserLoginLog


class UserFilter(django_filters.FilterSet):
    """
    用户筛选器（管理员后台）
    覆盖：关键词搜索、状态、VIP、等级、社交统计、注册渠道、时间范围、排序
    """

    # ---------- 关键词搜索（ID / 用户名 / 手机 / 邮箱 / 简介） ----------
    keyword = django_filters.CharFilter(method='filter_keyword', label='关键词')

    # ---------- 基础信息 ----------
    username = django_filters.CharFilter(field_name='username', lookup_expr='icontains')
    phone = django_filters.CharFilter(field_name='phone', lookup_expr='icontains')
    email = django_filters.CharFilter(field_name='email', lookup_expr='icontains')
    gender = django_filters.ChoiceFilter(choices=User.GENDER_CHOICES)

    # ---------- 状态 ----------
    is_active = django_filters.BooleanFilter()
    is_banned = django_filters.BooleanFilter()
    is_verified = django_filters.BooleanFilter()
    is_vip = django_filters.BooleanFilter()
    is_public = django_filters.BooleanFilter()
    has_password = django_filters.BooleanFilter(method='filter_has_password')

    # ---------- VIP ----------
    vip_level = django_filters.NumberFilter()
    vip_level_min = django_filters.NumberFilter(field_name='vip_level', lookup_expr='gte')
    vip_level_max = django_filters.NumberFilter(field_name='vip_level', lookup_expr='lte')
    vip_expired_after = django_filters.DateTimeFilter(field_name='vip_expired_at', lookup_expr='gte')
    vip_expired_before = django_filters.DateTimeFilter(field_name='vip_expired_at', lookup_expr='lte')
    vip_expired = django_filters.BooleanFilter(method='filter_vip_expired', label='VIP是否已过期')

    # ---------- 用户等级 / 经验值 ----------
    level = django_filters.NumberFilter()
    level_min = django_filters.NumberFilter(field_name='level', lookup_expr='gte')
    level_max = django_filters.NumberFilter(field_name='level', lookup_expr='lte')
    exp_min = django_filters.NumberFilter(field_name='exp', lookup_expr='gte')
    exp_max = django_filters.NumberFilter(field_name='exp', lookup_expr='lte')

    # ---------- ★ 社交统计（宠物端特有，商城没有） ----------
    followers_min = django_filters.NumberFilter(field_name='followers_count', lookup_expr='gte')
    followers_max = django_filters.NumberFilter(field_name='followers_count', lookup_expr='lte')
    following_min = django_filters.NumberFilter(field_name='following_count', lookup_expr='gte')
    posts_min = django_filters.NumberFilter(field_name='posts_count', lookup_expr='gte')
    likes_min = django_filters.NumberFilter(field_name='likes_received', lookup_expr='gte')

    # ---------- 注册渠道 / 邀请 ----------
    register_channel = django_filters.ChoiceFilter(choices=User.CHANNEL_CHOICES)
    invite_code = django_filters.CharFilter(lookup_expr='exact')
    invited_by = django_filters.NumberFilter(field_name='invited_by_id')
    has_inviter = django_filters.BooleanFilter(method='filter_has_inviter')

    # ---------- 时间范围 ----------
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    last_login_after = django_filters.DateTimeFilter(field_name='last_login', lookup_expr='gte')
    last_login_before = django_filters.DateTimeFilter(field_name='last_login', lookup_expr='lte')
    last_active_after = django_filters.DateTimeFilter(field_name='last_active_at', lookup_expr='gte')
    last_active_before = django_filters.DateTimeFilter(field_name='last_active_at', lookup_expr='lte')

    # ---------- 三方登录绑定 ----------
    provider = django_filters.CharFilter(method='filter_provider', label='已绑定渠道')

    # ---------- 排序 ----------
    ordering = django_filters.OrderingFilter(
        fields=(
            ('id', 'id'),
            ('created_at', 'created_at'),
            ('last_login', 'last_login'),
            ('last_active_at', 'last_active_at'),
            ('level', 'level'),
            ('exp', 'exp'),
            ('vip_level', 'vip_level'),
            ('vip_expired_at', 'vip_expired_at'),
            # ★ 社交维度排序
            ('followers_count', 'followers_count'),
            ('following_count', 'following_count'),
            ('posts_count', 'posts_count'),
            ('likes_received', 'likes_received'),
        )
    )

    class Meta:
        model = User
        fields = []

    # ---------- 自定义方法 ----------
    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        value = value.strip()
        if value.isdigit():
            return queryset.filter(
                Q(id=value) | Q(phone__icontains=value) | Q(username__icontains=value)
            )
        return queryset.filter(
            Q(username__icontains=value)
            | Q(phone__icontains=value)
            | Q(email__icontains=value)
            | Q(bio__icontains=value)
        )

    def filter_has_password(self, queryset, name, value):
        if value is True:
            return queryset.exclude(_password='')
        if value is False:
            return queryset.filter(_password='')
        return queryset

    def filter_has_inviter(self, queryset, name, value):
        if value is True:
            return queryset.filter(invited_by__isnull=False)
        if value is False:
            return queryset.filter(invited_by__isnull=True)
        return queryset

    def filter_vip_expired(self, queryset, name, value):
        from django.utils import timezone
        now = timezone.now()
        if value is True:
            return queryset.filter(is_vip=True, vip_expired_at__lt=now)
        if value is False:
            return queryset.filter(
                Q(is_vip=False) | Q(vip_expired_at__gte=now) | Q(vip_expired_at__isnull=True)
            )
        return queryset

    def filter_provider(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(auth_providers__provider=value).distinct()


class UserLoginLogFilter(django_filters.FilterSet):
    """登录日志筛选器"""

    user_id = django_filters.NumberFilter(field_name='user_id')
    phone = django_filters.CharFilter(field_name='user__phone', lookup_expr='icontains')
    username = django_filters.CharFilter(field_name='user__username', lookup_expr='icontains')
    login_method = django_filters.ChoiceFilter(choices=UserLoginLog.LOGIN_METHOD_CHOICES)
    platform = django_filters.CharFilter()
    ip_address = django_filters.CharFilter()
    is_success = django_filters.BooleanFilter()

    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    ordering = django_filters.OrderingFilter(
        fields=(('created_at', 'created_at'),)
    )

    class Meta:
        model = UserLoginLog
        fields = []


class UserDeviceFilter(django_filters.FilterSet):
    """用户设备筛选器"""

    user_id = django_filters.NumberFilter(field_name='user_id')
    platform = django_filters.ChoiceFilter(choices=UserDevice.PLATFORM_CHOICES)
    device_brand = django_filters.CharFilter(lookup_expr='icontains')
    device_model = django_filters.CharFilter(lookup_expr='icontains')
    channel = django_filters.CharFilter(lookup_expr='icontains')
    is_active = django_filters.BooleanFilter()

    last_active_after = django_filters.DateTimeFilter(field_name='last_active_at', lookup_expr='gte')
    last_active_before = django_filters.DateTimeFilter(field_name='last_active_at', lookup_expr='lte')

    class Meta:
        model = UserDevice
        fields = []