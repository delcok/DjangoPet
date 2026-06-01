# -*- coding: utf-8 -*-
# @Time    : 2026/4/19 20:49
# @Author  : Delock

# -*- coding: utf-8 -*-
import django_filters

from .models import ProductReview, ServiceReview, ReviewStatusMixin


class ProductReviewFilter(django_filters.FilterSet):
    merchant_id = django_filters.NumberFilter(field_name='merchant_id')
    user_id = django_filters.NumberFilter(field_name='user_id')
    status = django_filters.ChoiceFilter(choices=ReviewStatusMixin.Status.choices)
    has_images = django_filters.BooleanFilter(field_name='has_images')

    # 商品维度筛选
    goods_id = django_filters.NumberFilter(field_name='items__goods_id_snapshot')
    sku_id = django_filters.NumberFilter(field_name='items__sku_id_snapshot')

    created_at_start = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_at_end = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = ProductReview
        fields = [
            'merchant_id', 'user_id', 'status', 'has_images',
            'goods_id', 'sku_id',
            'created_at_start', 'created_at_end',
        ]


class ServiceReviewFilter(django_filters.FilterSet):
    # 核心：按店铺或服务筛选
    merchant_id = django_filters.NumberFilter(field_name='merchant_id')
    service_id = django_filters.NumberFilter(field_name='service_id_snapshot')
    service = django_filters.NumberFilter(field_name='service_id')

    user_id = django_filters.NumberFilter(field_name='user_id')
    staff_id = django_filters.NumberFilter(field_name='staff_id')
    status = django_filters.ChoiceFilter(choices=ReviewStatusMixin.Status.choices)
    has_images = django_filters.BooleanFilter(field_name='has_images')
    score = django_filters.NumberFilter(field_name='score')

    created_at_start = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_at_end = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = ServiceReview
        fields = [
            'merchant_id', 'service_id', 'service',
            'user_id', 'staff_id', 'status',
            'has_images', 'score',
            'created_at_start', 'created_at_end',
        ]