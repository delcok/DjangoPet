# -*- coding: utf-8 -*-
"""
反馈过滤器
"""
import django_filters
from django.db.models import Q

from .models import Feedback


class FeedbackFilter(django_filters.FilterSet):
    """反馈过滤器（用户端 / 管理端共用）"""

    feedback_type = django_filters.CharFilter(field_name='feedback_type', lookup_expr='exact')
    status = django_filters.CharFilter(field_name='status', lookup_expr='exact')
    keyword = django_filters.CharFilter(method='filter_keyword', label='关键词（内容/联系方式/回复）')
    has_reply = django_filters.BooleanFilter(method='filter_has_reply', label='是否已回复')
    created_after = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = Feedback
        fields = ['feedback_type', 'status']

    def filter_keyword(self, queryset, name, value):
        return queryset.filter(
            Q(content__icontains=value) |
            Q(contact_info__icontains=value) |
            Q(reply__icontains=value)
        )

    def filter_has_reply(self, queryset, name, value):
        # 同时兼容 reply 为 NULL 和空字符串两种“未回复”
        if value:
            return queryset.exclude(reply__isnull=True).exclude(reply__exact='')
        return queryset.filter(Q(reply__isnull=True) | Q(reply__exact=''))
