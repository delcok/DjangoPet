"""
商城系统过滤器
"""
import django_filters
from django.db import models
from .models import Product, Order


class ProductFilter(django_filters.FilterSet):
    """商品过滤器"""

    # 价格范围
    min_price = django_filters.NumberFilter(field_name='price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='price', lookup_expr='lte')

    # 分类（支持子分类）
    category = django_filters.NumberFilter(method='filter_category')

    # 关键词搜索
    keyword = django_filters.CharFilter(method='filter_keyword')

    # 宠物类型
    pet_type = django_filters.CharFilter(lookup_expr='icontains')

    # 品牌
    brand = django_filters.CharFilter(lookup_expr='icontains')

    # 标签过滤
    is_recommended = django_filters.BooleanFilter()
    is_new = django_filters.BooleanFilter()
    is_hot = django_filters.BooleanFilter()

    # 状态
    status = django_filters.NumberFilter()

    # 有库存
    in_stock = django_filters.BooleanFilter(method='filter_in_stock')

    class Meta:
        model = Product
        fields = [
            'category', 'status', 'pet_type', 'brand',
            'is_recommended', 'is_new', 'is_hot'
        ]

    def filter_category(self, queryset, name, value):
        """过滤分类，包含子分类"""
        from .models import Category

        try:
            category = Category.objects.get(id=value)
            # 获取所有子分类ID
            category_ids = [value]
            children = category.children.all()
            for child in children:
                category_ids.append(child.id)
                # 如果需要支持更深层级，可以递归获取
                grandchildren = child.children.all()
                category_ids.extend([gc.id for gc in grandchildren])

            return queryset.filter(category_id__in=category_ids)
        except Category.DoesNotExist:
            return queryset.none()

    def filter_keyword(self, queryset, name, value):
        """关键词搜索"""
        return queryset.filter(
            models.Q(name__icontains=value) |
            models.Q(subtitle__icontains=value) |
            models.Q(description__icontains=value) |
            models.Q(brand__icontains=value)
        )

    def filter_in_stock(self, queryset, name, value):
        """过滤有库存商品"""
        if value:
            return queryset.filter(stock__gt=0)
        return queryset


class OrderFilter(django_filters.FilterSet):
    """订单过滤器"""

    # 订单状态
    status = django_filters.NumberFilter()

    # 时间范围
    start_date = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte'
    )
    end_date = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte'
    )

    # 订单号搜索
    order_no = django_filters.CharFilter(lookup_expr='icontains')

    # 收货人
    receiver_name = django_filters.CharFilter(lookup_expr='icontains')
    receiver_phone = django_filters.CharFilter(lookup_expr='icontains')

    # 金额范围
    min_amount = django_filters.NumberFilter(
        field_name='pay_amount',
        lookup_expr='gte'
    )
    max_amount = django_filters.NumberFilter(
        field_name='pay_amount',
        lookup_expr='lte'
    )

    # 支付方式
    payment_method = django_filters.NumberFilter()

    class Meta:
        model = Order
        fields = ['status', 'payment_method', 'order_no']