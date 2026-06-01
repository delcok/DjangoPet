# goods/filters.py

import django_filters
from django.db.models import Q

from .models import Goods, GoodsCategory, Brand,  MerchantGoodsGroup


class GoodsCategoryFilter(django_filters.FilterSet):
    """商品分类过滤器"""
    parent_id = django_filters.NumberFilter(field_name='parent_id')
    is_show_home = django_filters.BooleanFilter()
    keyword = django_filters.CharFilter(field_name='name', lookup_expr='icontains')

    class Meta:
        model = GoodsCategory
        fields = ['parent_id', 'is_active', 'is_show_home']


class BrandFilter(django_filters.FilterSet):
    """品牌过滤器"""
    keyword = django_filters.CharFilter(field_name='name', lookup_expr='icontains')

    class Meta:
        model = Brand
        fields = ['is_active', 'is_recommended']


class GoodsFilter(django_filters.FilterSet):
    """
    商品过滤器 —— 用户端、商家端、管理端共用，
    不同视图通过 queryset 控制可见范围。
    """

    # ── 分类（含子分类递归） ──
    category_id = django_filters.NumberFilter(method='filter_category')

    # ── 店铺分组 ──
    group_id = django_filters.NumberFilter(field_name='merchant_group_id')

    # ── 品牌 ──
    brand_id = django_filters.NumberFilter(field_name='brand_id')

    # ── 商家 ──
    merchant_id = django_filters.NumberFilter(field_name='merchant_id')

    # ── 价格区间 ──
    price_min = django_filters.NumberFilter(field_name='price', lookup_expr='gte')
    price_max = django_filters.NumberFilter(field_name='price', lookup_expr='lte')

    # ── 关键词搜索（标题 + 副标题 + 关键词） ──
    keyword = django_filters.CharFilter(method='filter_keyword')

    # ── 类型 ──
    goods_type = django_filters.CharFilter(field_name='goods_type')

    # ── 推荐标记 ──
    is_recommended = django_filters.BooleanFilter()
    is_hot = django_filters.BooleanFilter()
    is_new = django_filters.BooleanFilter()
    is_best = django_filters.BooleanFilter()

    # ── 状态（商家端/管理端用） ──
    status = django_filters.CharFilter(field_name='status')

    # ── 标签 ──
    tag_id = django_filters.NumberFilter(method='filter_tag')

    # ── 排序 ──
    ordering = django_filters.OrderingFilter(
        fields=(
            ('price', 'price'),
            ('sales_count', 'sales'),
            ('created_at', 'created'),
            ('rating', 'rating'),
            ('sort_order', 'sort'),
        ),
        # 默认按排序权重 + 创建时间倒序
    )

    class Meta:
        model = Goods
        fields = []

    def filter_category(self, queryset, name, value):
        """按分类过滤，包含所有子分类"""
        category_ids = self._get_category_tree_ids(value)
        return queryset.filter(category_id__in=category_ids)

    def filter_keyword(self, queryset, name, value):
        """关键词模糊搜索"""
        return queryset.filter(
            Q(title__icontains=value) |
            Q(subtitle__icontains=value) |
            Q(keywords__icontains=value)
        )

    def filter_tag(self, queryset, name, value):
        """按标签过滤"""
        return queryset.filter(tags__id=value)

    @staticmethod
    def _get_category_tree_ids(category_id):
        """递归获取分类及其所有子分类 ID"""
        ids = [category_id]
        children = list(
            GoodsCategory.objects.filter(
                parent_id=category_id, is_active=True
            ).values_list('id', flat=True)
        )
        for child_id in children:
            ids.extend(GoodsFilter._get_category_tree_ids(child_id))
        return ids


class MerchantGoodsGroupFilter(django_filters.FilterSet):
    """商家店铺分组过滤器"""

    class Meta:
        model = MerchantGoodsGroup
        fields = ['is_active']