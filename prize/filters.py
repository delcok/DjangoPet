# -*- coding: utf-8 -*-
# @Time    : 2026/3/12 15:57
# @Author  : Delock

import django_filters
from .models import Prize, UserPrize


class PrizeFilter(django_filters.FilterSet):
    created_at_start = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_at_end = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    start_time_start = django_filters.DateTimeFilter(field_name='start_time', lookup_expr='gte')
    end_time_end = django_filters.DateTimeFilter(field_name='end_time', lookup_expr='lte')

    class Meta:
        model = Prize
        fields = {
            'prize_type': ['exact'],
            'status': ['exact'],
            'need_address': ['exact'],
            'need_appointment': ['exact'],
        }


class UserPrizeFilter(django_filters.FilterSet):
    issued_at_start = django_filters.DateTimeFilter(field_name='issued_at', lookup_expr='gte')
    issued_at_end = django_filters.DateTimeFilter(field_name='issued_at', lookup_expr='lte')
    valid_end_time_start = django_filters.DateTimeFilter(field_name='valid_end_time', lookup_expr='gte')
    valid_end_time_end = django_filters.DateTimeFilter(field_name='valid_end_time', lookup_expr='lte')

    class Meta:
        model = UserPrize
        fields = {
            'status': ['exact'],
            'prize_snapshot_type': ['exact'],
            'source': ['exact'],
            'user': ['exact'],
            'prize': ['exact'],
            'issued_by': ['exact'],
            'handled_by': ['exact'],
            'batch_no': ['exact'],
        }
