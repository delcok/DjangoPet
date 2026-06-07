import django_filters
from django.db.models import Q, F, FloatField, ExpressionWrapper, Min
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
    is_recommended = django_filters.BooleanFilter(field_name='is_recommended')      # ✅ 平台推荐
    has_delivery = django_filters.BooleanFilter(method='filter_has_delivery')
    service_mode = django_filters.CharFilter(method='filter_service_mode')          # ✅ 上门/到店
    support_urgent = django_filters.BooleanFilter(method='filter_support_urgent')   # ✅ 支持紧急

    # ⚠️ 分类过滤器必须声明在 sort 之前:sort=price_* 要用到分类约束去 annotate 价格
    service_category_id = django_filters.NumberFilter(method='filter_by_service_category')
    goods_category_id = django_filters.NumberFilter(method='filter_by_goods_category')
    sort = django_filters.CharFilter(method='filter_sort')

    # 说明:price_min / price_max / is_hot 不单独声明字段,而是在"分类关系"里和分类约束
    #   写进【同一个 .filter()】,保证命中的是同一条 goods / service 行,
    #   否则会对关系产生第二次 JOIN,把"该分类下 >=300 的商品"放宽成"有任意 >=300 的商品"。

    class Meta:
        model = Merchant
        fields = ['keyword', 'category_id', 'district_id', 'rating_min', 'is_open']

    # ── 基础过滤 ──────────────────────────────────────────────
    def filter_keyword(self, queryset, name, value):
        if value:
            safe = escape_like(value)
            return queryset.filter(
                Q(name__icontains=safe) | Q(description__icontains=safe)
            )
        return queryset

    def filter_has_delivery(self, queryset, name, value):
        if value is True:
            return queryset.filter(support_home_delivery=True)
        if value is False:
            return queryset.filter(support_home_delivery=False)
        return queryset

    def filter_service_mode(self, queryset, name, value):
        # 服务模式(传了 service_category_id)交给服务关系处理,scope 到所选分类内的服务行
        if self.data.get('service_category_id'):
            return queryset
        # 商品模式/无服务分类:退化为按商家配送能力近似(上门=送货上门,到店=到店自提)
        if value == 'home':
            return queryset.filter(support_home_delivery=True)
        if value == 'store':
            return queryset.filter(support_self_pickup=True)
        return queryset

    def filter_support_urgent(self, queryset, name, value):
        if value is not True:
            return queryset
        # 服务模式交给服务关系(scope 到所选分类)
        if self.data.get('service_category_id'):
            return queryset
        # 否则:商家是否有任意一个支持加急的在售服务
        from services.models import Service
        return queryset.filter(
            services__status=Service.Status.ACTIVE,
            services__urgent_config__isnull=False,
        ).distinct()

    # ── 共享参数读取 ──────────────────────────────────────────
    def _read_price_range(self):
        def _num(key):
            raw = self.data.get(key)
            if raw in (None, ''):
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        return _num('price_min'), _num('price_max')

    def _wants_hot(self):
        return str(self.data.get('is_hot', '')).lower() in ('1', 'true')

    def _wants_urgent(self):
        return str(self.data.get('support_urgent', '')).lower() in ('1', 'true')

    def _service_mode_value(self):
        v = self.data.get('service_mode')
        return v if v in ('home', 'store', 'pickup') else None

    # ── 商品关系:分类 + 价格 + 热门(同一个 Q)──────────────────
    def _apply_goods_relation(self, queryset, category_ids):
        cond = Q(goods__category_id__in=category_ids, goods__status='on_sale')
        pmin, pmax = self._read_price_range()
        if pmin is not None:
            cond &= Q(goods__price__gte=pmin)
        if pmax is not None:
            cond &= Q(goods__price__lte=pmax)
        if self._wants_hot():
            cond &= Q(goods__is_hot=True)
        return queryset.filter(cond).distinct()

    # ── 服务关系:分类 + 价格 + 热门 + 服务方式 + 加急(同一个 Q)──
    def _apply_service_relation(self, queryset, category_ids):
        from services.models import Service
        cond = Q(services__category_id__in=category_ids,
                 services__status=Service.Status.ACTIVE)
        pmin, pmax = self._read_price_range()
        if pmin is not None:
            cond &= Q(services__price__gte=pmin)
        if pmax is not None:
            cond &= Q(services__price__lte=pmax)
        if self._wants_hot():
            cond &= Q(services__is_hot=True)
        mode = self._service_mode_value()
        if mode:
            cond &= Q(services__service_mode=mode)
        if self._wants_urgent():
            # 支持加急 = urgent_config 非空(与 ServiceListSerializer.get_support_urgent 一致)
            cond &= Q(services__urgent_config__isnull=False)
        return queryset.filter(cond).distinct()

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
        self._goods_category_ids = category_ids   # 供 sort=price_* 使用
        return self._apply_goods_relation(queryset, category_ids)

    def filter_by_service_category(self, queryset, name, value):
        ok, value = _coerce_positive_int(value)
        if value is None:
            return queryset
        if not ok:
            return queryset.none()
        from services.models import ServiceCategory
        try:
            category = ServiceCategory.objects.get(id=value, is_active=True)
        except ServiceCategory.DoesNotExist:
            return queryset.none()
        category_ids = _collect_descendant_ids(category, active_only=True)
        self._service_category_ids = category_ids
        return self._apply_service_relation(queryset, category_ids)

    # ── 排序 ──────────────────────────────────────────────────
    def filter_sort(self, queryset, name, value):
        if value == 'distance':
            return self._sort_by_distance(queryset)
        if value in ('price_asc', 'price_desc'):
            return self._sort_by_price(queryset, descending=(value == 'price_desc'))
        mapping = {
            'rating': '-rating',
            'sales': '-monthly_sales',
            'newest': '-created_at',
        }
        if value in mapping:
            return queryset.order_by(mapping[value], '-id')
        return queryset

    def _sort_by_distance(self, queryset):
        lng_raw = self.data.get('longitude')
        lat_raw = self.data.get('latitude')
        if lng_raw in (None, '') or lat_raw in (None, ''):
            return queryset
        try:
            lng, lat = float(lng_raw), float(lat_raw)
        except (TypeError, ValueError):
            return queryset
        cos_lat = max(abs(cos(radians(lat))), 1e-6)   # 经度差按纬度修正,防高纬误差
        lng_f = Cast('longitude', output_field=FloatField())
        lat_f = Cast('latitude', output_field=FloatField())
        return queryset.annotate(
            _distance=ExpressionWrapper(
                Sqrt(Power((lng_f - lng) * cos_lat, 2) + Power(lat_f - lat, 2)) * 111000,
                output_field=FloatField(),
            )
        ).order_by(F('_distance').asc(nulls_last=True))   # 无坐标商家排最后

    def _sort_by_price(self, queryset, descending):
        goods_ids = getattr(self, '_goods_category_ids', None)
        service_ids = getattr(self, '_service_category_ids', None)
        if goods_ids is not None:
            queryset = queryset.annotate(
                _min_price=Min('goods__price', filter=Q(
                    goods__category_id__in=goods_ids,
                    goods__status='on_sale',
                ))
            )
        elif service_ids is not None:
            from services.models import Service
            queryset = queryset.annotate(
                _min_price=Min('services__price', filter=Q(
                    services__category_id__in=service_ids,
                    services__status=Service.Status.ACTIVE,
                ))
            )
        else:
            return queryset   # 没有分类上下文,无法按商品/服务价排序
        order = (F('_min_price').desc(nulls_last=True) if descending
                 else F('_min_price').asc(nulls_last=True))
        return queryset.order_by(order)
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