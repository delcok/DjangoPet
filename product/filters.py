# goods/filters.py

from math import cos, radians

import django_filters
from django.db.models import Q, F, FloatField, ExpressionWrapper
from django.db.models.functions import Cast, Power, Sqrt

from .models import Goods, GoodsCategory, Brand, MerchantGoodsGroup


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

    ★ 新增：距离支持
    - 传 longitude + latitude 时，会基于【商品所属商家】的坐标
      annotate 出 distance(米)，序列化器可直接输出给前端展示。
    - ordering=distance 按由近到远排序（商家无坐标的排最后）。
    - 不传坐标时 ordering=distance 静默退回默认排序，不报错。

    ⚠️ 声明顺序很重要：longitude/latitude 必须在 ordering 之前声明，
    django-filter 按声明顺序执行，保证排序时 distance 注解已存在。
    """

    # ── ★ 用户坐标（用于距离注解，必须在 ordering 之前）──
    longitude = django_filters.NumberFilter(method='filter_by_location')
    latitude = django_filters.NumberFilter(method='filter_pass')

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

    # ── 排序（★ 改为自定义方法，新增 distance） ──
    # 支持: price/-price, sales/-sales, created/-created,
    #       rating/-rating, sort/-sort, distance
    ordering = django_filters.CharFilter(method='filter_ordering')

    ORDERING_MAP = {
        'price': 'price',
        '-price': '-price',
        'sales': 'sales_count',
        '-sales': '-sales_count',
        'created': 'created_at',
        '-created': '-created_at',
        'rating': 'rating',
        '-rating': '-rating',
        'sort': 'sort_order',
        '-sort': '-sort_order',
    }

    class Meta:
        model = Goods
        fields = []

    # ── ★ 距离注解 ────────────────────────────────────────
    def filter_pass(self, queryset, name, value):
        """latitude 占位，实际在 filter_by_location 中一起处理"""
        return queryset

    def filter_by_location(self, queryset, name, value):
        """
        基于商家坐标 annotate distance(米)。
        商品依附于商家，所以直接用 merchant 的经纬度。
        经度差乘 cos(lat) 修正，与 merchants/filters.py 保持一致。
        """
        lng_raw = value
        lat_raw = self.data.get('latitude')
        if lng_raw in (None, '') or lat_raw in (None, ''):
            return queryset
        try:
            lng = float(lng_raw)
            lat = float(lat_raw)
        except (TypeError, ValueError):
            return queryset

        cos_lat = max(abs(cos(radians(lat))), 1e-6)  # 防极地除零
        lng_f = Cast('merchant__longitude', output_field=FloatField())
        lat_f = Cast('merchant__latitude', output_field=FloatField())

        queryset = queryset.annotate(
            distance=ExpressionWrapper(
                Sqrt(
                    Power((lng_f - lng) * cos_lat, 2) +
                    Power(lat_f - lat, 2)
                ) * 111000,
                output_field=FloatField(),
            )
        )
        # 标记已注解，供 filter_ordering 判断
        self._has_distance = True
        return queryset

    # ── 排序 ──────────────────────────────────────────────
    def filter_ordering(self, queryset, name, value):
        if not value:
            return queryset

        if value == 'distance':
            # 没传坐标时静默退回默认排序（queryset 自带 -sort_order, -created_at）
            if not getattr(self, '_has_distance', False):
                return queryset
            # 商家没填坐标 → distance 为 NULL → 排最后
            return queryset.order_by(
                F('distance').asc(nulls_last=True),
                '-sort_order', '-id',
            )

        field = self.ORDERING_MAP.get(value)
        if field:
            return queryset.order_by(field, '-id')
        return queryset

    # ── 其余过滤 ──────────────────────────────────────────
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