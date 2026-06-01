import django_filters
from django.db.models import Q, F, FloatField, ExpressionWrapper
from django.db.models.functions import Power, Sqrt, Cast
from math import cos, radians

from utils.db import escape_like
from .models import Merchant, MerchantCategory, BusinessDistrict


# ══════════════════════════════════════════════════════════════
# 通用工具
# ══════════════════════════════════════════════════════════════

def _coerce_positive_int(value):
    if value is None:
        return True, None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return False, None
    if v <= 0:
        return False, None
    return True, v


def _collect_descendant_ids(category, *, active_only=True):
    ids = [category.id]
    stack = [category]
    while stack:
        cur = stack.pop()
        qs = cur.children.all()
        if active_only:
            qs = qs.filter(is_active=True)
        for child in qs:
            ids.append(child.id)
            stack.append(child)
    return ids


# ══════════════════════════════════════════════════════════════
# C 端用户 - 商家列表过滤器
# ══════════════════════════════════════════════════════════════

class MerchantUserFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method='filter_keyword')
    category_id = django_filters.NumberFilter(field_name='category_id')
    district_id = django_filters.NumberFilter(field_name='business_district_id')
    rating_min = django_filters.NumberFilter(field_name='rating', lookup_expr='gte')
    is_open = django_filters.BooleanFilter(field_name='is_open')
    has_delivery = django_filters.BooleanFilter(method='filter_has_delivery')
    sort = django_filters.CharFilter(method='filter_sort')
    service_category_id = django_filters.NumberFilter(method='filter_by_service_category')
    goods_category_id = django_filters.NumberFilter(method='filter_by_goods_category')

    class Meta:
        model = Merchant
        fields = ['keyword', 'category_id', 'district_id', 'rating_min', 'is_open']

    def filter_keyword(self, queryset, name, value):
        """✅ 修复 #4: LIKE 通配符转义"""
        if value:
            safe = escape_like(value)
            return queryset.filter(
                Q(name__icontains=safe) | Q(description__icontains=safe)
            )
        return queryset

    def filter_has_delivery(self, queryset, name, value):
        """
        ✅ 修复 #8: 配送方式开关已经独立成 support_home_delivery 字段,
        旧实现用 delivery_range > 0 判断已不准确。
        """
        if value is True:
            return queryset.filter(support_home_delivery=True)
        if value is False:
            return queryset.filter(support_home_delivery=False)
        return queryset

    def filter_sort(self, queryset, name, value):
        """
        ✅ 修复 #10: 只在显式传 sort 时排序,
        否则保留 Model.Meta.ordering 默认值。
        """
        sort_mapping = {
            'rating': '-rating',
            'sales': '-monthly_sales',
            'newest': '-created_at',
        }
        if value in sort_mapping:
            return queryset.order_by(sort_mapping[value], '-id')
        return queryset

    def filter_by_service_category(self, queryset, name, value):
        ok, value = _coerce_positive_int(value)
        if value is None:
            return queryset
        if not ok:
            return queryset.none()

        from services.models import ServiceCategory, Service

        try:
            category = ServiceCategory.objects.get(id=value, is_active=True)
        except ServiceCategory.DoesNotExist:
            return queryset.none()

        category_ids = _collect_descendant_ids(category, active_only=True)

        return queryset.filter(
            services__category_id__in=category_ids,
            services__status=Service.Status.ACTIVE,
        ).distinct()

    def filter_by_goods_category(self, queryset, name, value):
        ok, value = _coerce_positive_int(value)
        if value is None:
            return queryset
        if not ok:
            return queryset.none()

        from product.models import GoodsCategory

        try:
            category = GoodsCategory.objects.get(id=value, is_active=True)
        except GoodsCategory.DoesNotExist:
            return queryset.none()

        category_ids = _collect_descendant_ids(category, active_only=True)

        return queryset.filter(
            goods__category_id__in=category_ids,
            goods__status='on_sale',
        ).distinct()


# ══════════════════════════════════════════════════════════════
# C 端用户 - 附近商家过滤器
# ══════════════════════════════════════════════════════════════

class NearbyMerchantFilter(django_filters.FilterSet):
    """
    附近商家过滤器(基于经纬度计算距离)

    ✅ 修复 #11: 把"触发距离筛选"挂到 longitude 上,
    radius 仅作为可选参数(默认 3000)。
    旧实现必须传 radius 才触发,有 longitude/latitude 也没用。
    """
    longitude = django_filters.NumberFilter(method='filter_by_distance')
    latitude = django_filters.NumberFilter(method='filter_pass')
    radius = django_filters.NumberFilter(method='filter_pass')
    category_id = django_filters.NumberFilter(field_name='category_id')
    keyword = django_filters.CharFilter(method='filter_keyword')
    goods_category_id = django_filters.NumberFilter(method='filter_by_goods_category')
    service_category_id = django_filters.NumberFilter(method='filter_by_service_category')

    class Meta:
        model = Merchant
        fields = ['category_id']

    def filter_pass(self, queryset, name, value):
        """占位,实际在 filter_by_distance 中处理"""
        return queryset

    def filter_keyword(self, queryset, name, value):
        """✅ 修复 #4"""
        if value:
            safe = escape_like(value)
            return queryset.filter(
                Q(name__icontains=safe) | Q(description__icontains=safe)
            )
        return queryset

    def filter_by_distance(self, queryset, name, value):
        """
        按距离筛选

        ✅ 修复 #3: 距离公式中经度差必须乘 cos(lat),
        否则纬度高的地区排序误差很大(北京 ~23%、新疆 ~28%)。
        ✅ 修复 #11: radius 缺省 3000,无需必传
        ✅ 修复:把 DecimalField 经纬度 Cast 成 FloatField,
                解决与 Python float 做减法时 Django 无法推断 output_field 的报错。
        """
        # 此 method 由 longitude 触发,value 就是 longitude
        lng_raw = value
        lat_raw = self.data.get('latitude')
        radius_raw = self.data.get('radius')

        if lng_raw in (None, '') or lat_raw in (None, ''):
            return queryset

        try:
            lng = float(lng_raw)
            lat = float(lat_raw)
            radius = float(radius_raw) if radius_raw not in (None, '') else 3000
        except (TypeError, ValueError):
            return queryset

        if radius <= 0:
            return queryset

        lat_diff = radius / 111000
        cos_lat = abs(cos(radians(lat)))
        cos_lat = max(cos_lat, 1e-6)  # 防极地除零
        lng_diff = radius / (111000 * cos_lat)

        # 矩形粗筛(Python 端先算好,不涉及 ORM 类型推断)
        queryset = queryset.filter(
            longitude__gte=lng - lng_diff,
            longitude__lte=lng + lng_diff,
            latitude__gte=lat - lat_diff,
            latitude__lte=lat + lat_diff,
        )

        # ✅ 距离注解:经度差乘 cos_lat 修正
        # 把 DecimalField 列 Cast 成 FloatField,避免和 Python float 做减法时类型推断失败
        lng_f = Cast('longitude', output_field=FloatField())
        lat_f = Cast('latitude', output_field=FloatField())

        queryset = queryset.annotate(
            distance=ExpressionWrapper(
                Sqrt(
                    Power((lng_f - lng) * cos_lat, 2) +
                    Power(lat_f - lat, 2)
                ) * 111000,
                output_field=FloatField(),
            )
        ).filter(distance__lte=radius).order_by('distance')

        return queryset

    def filter_by_goods_category(self, queryset, name, value):
        ok, value = _coerce_positive_int(value)
        if value is None:
            return queryset
        if not ok:
            return queryset.none()

        from product.models import GoodsCategory

        try:
            category = GoodsCategory.objects.get(id=value, is_active=True)
        except GoodsCategory.DoesNotExist:
            return queryset.none()

        category_ids = _collect_descendant_ids(category, active_only=True)

        return queryset.filter(
            goods__category_id__in=category_ids,
            goods__status='on_sale',
        ).distinct()

    def filter_by_service_category(self, queryset, name, value):
        ok, value = _coerce_positive_int(value)
        if value is None:
            return queryset
        if not ok:
            return queryset.none()

        from services.models import ServiceCategory, Service
        try:
            category = ServiceCategory.objects.get(id=value, is_active=True)
        except ServiceCategory.DoesNotExist:
            return queryset.none()

        category_ids = _collect_descendant_ids(category, active_only=True)
        return queryset.filter(
            services__category_id__in=category_ids,
            services__status=Service.Status.ACTIVE,
        ).distinct()


# ══════════════════════════════════════════════════════════════
# 管理后台 - 商家过滤器
# ══════════════════════════════════════════════════════════════

class MerchantAdminFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method='filter_keyword')
    category_id = django_filters.NumberFilter(field_name='category_id')
    district_id = django_filters.NumberFilter(field_name='business_district_id')
    status = django_filters.ChoiceFilter(choices=Merchant.Status.choices)
    is_open = django_filters.BooleanFilter()
    is_recommended = django_filters.BooleanFilter()
    rating_min = django_filters.NumberFilter(field_name='rating', lookup_expr='gte')
    rating_max = django_filters.NumberFilter(field_name='rating', lookup_expr='lte')
    created_at_start = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_at_end = django_filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    # 新增:管理员可按配送模式筛选
    support_home_delivery = django_filters.BooleanFilter()
    support_self_pickup = django_filters.BooleanFilter()
    freight_mode = django_filters.ChoiceFilter(choices=Merchant.FreightMode.choices)

    class Meta:
        model = Merchant
        fields = [
            'keyword', 'category_id', 'district_id', 'status',
            'is_open', 'is_recommended',
            'rating_min', 'rating_max',
            'created_at_start', 'created_at_end',
            'support_home_delivery', 'support_self_pickup', 'freight_mode',
        ]

    def filter_keyword(self, queryset, name, value):
        """✅ 修复 #4"""
        if value:
            safe = escape_like(value)
            return queryset.filter(
                Q(name__icontains=safe) |
                Q(phone__icontains=safe) |
                Q(contact_name__icontains=safe) |
                Q(address__icontains=safe)
            )
        return queryset


# ══════════════════════════════════════════════════════════════
# 分类 / 商圈 过滤器
# ══════════════════════════════════════════════════════════════

class MerchantCategoryFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    is_active = django_filters.BooleanFilter()

    class Meta:
        model = MerchantCategory
        fields = ['keyword', 'is_active']


class BusinessDistrictFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(method='filter_keyword')
    province = django_filters.CharFilter(field_name='province', lookup_expr='icontains')
    city = django_filters.CharFilter(field_name='city', lookup_expr='icontains')
    district = django_filters.CharFilter(field_name='district', lookup_expr='icontains')
    is_active = django_filters.BooleanFilter()

    class Meta:
        model = BusinessDistrict
        fields = ['keyword', 'province', 'city', 'district', 'is_active']

    def filter_keyword(self, queryset, name, value):
        """✅ 修复 #4"""
        if value:
            safe = escape_like(value)
            return queryset.filter(
                Q(name__icontains=safe) |
                Q(province__icontains=safe) |
                Q(city__icontains=safe) |
                Q(district__icontains=safe) |
                Q(address__icontains=safe)
            )
        return queryset