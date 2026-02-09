from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Category, Product, ProductImage, ProductVideo, ProductDetail,
    SpecificationName, SpecificationValue, ProductSpecification, SKU,
    Order, OrderItem, OrderLog, CartItem, ProductFavorite,
    ORDER_STATUS_PENDING_SHIPMENT, ORDER_STATUS_SHIPPED
)


# ==================== 分类管理 ====================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'parent', 'icon_preview', 'sort_order', 'is_active', 'created_at']
    list_filter = ['is_active', 'parent']
    search_fields = ['name']
    list_editable = ['sort_order', 'is_active']
    ordering = ['sort_order', 'id']

    def icon_preview(self, obj):
        if obj.icon_url:
            return format_html('<img src="{}" width="30" height="30" />', obj.icon_url)
        return '-'

    icon_preview.short_description = '图标'


# ==================== 商品管理 ====================

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image_url', 'is_main', 'sort_order']


class ProductVideoInline(admin.TabularInline):
    model = ProductVideo
    extra = 0
    fields = ['video_url', 'cover_url', 'title', 'duration', 'sort_order']


class ProductDetailInline(admin.TabularInline):
    model = ProductDetail
    extra = 0
    fields = ['image_url', 'sort_order']


class SKUInline(admin.TabularInline):
    model = SKU
    extra = 0
    fields = ['sku_code', 'name', 'spec_values', 'price', 'stock', 'is_active']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'cover_preview', 'name', 'category', 'price',
        'original_price', 'stock', 'sales', 'status_display',
        'is_recommended', 'is_new', 'is_hot', 'created_at'
    ]
    list_filter = ['status', 'category', 'is_recommended', 'is_new', 'is_hot', 'pet_type']
    search_fields = ['name', 'subtitle', 'brand']
    list_editable = ['price', 'stock', 'is_recommended', 'is_new', 'is_hot']
    ordering = ['-created_at']
    readonly_fields = ['sales', 'created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'subtitle', 'description', 'category')
        }),
        ('价格库存', {
            'fields': ('price', 'original_price', 'cost_price', 'stock', 'sales')
        }),
        ('媒体', {
            'fields': ('cover_image_url',)
        }),
        ('状态标签', {
            'fields': ('status', 'is_recommended', 'is_new', 'is_hot', 'sort_order')
        }),
        ('宠物属性', {
            'fields': ('pet_type', 'brand')
        }),
        ('运费', {
            'fields': ('freight',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    inlines = [ProductImageInline, ProductVideoInline, ProductDetailInline, SKUInline]

    def cover_preview(self, obj):
        if obj.cover_image_url:
            return format_html(
                '<img src="{}" width="50" height="50" style="object-fit: cover;" />',
                obj.cover_image_url
            )
        return '-'

    cover_preview.short_description = '封面'

    def status_display(self, obj):
        colors = {
            0: 'gray',  # 草稿
            1: 'green',  # 在售
            2: 'orange',  # 下架
            3: 'red',  # 售罄
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color, obj.get_status_display()
        )

    status_display.short_description = '状态'


# ==================== 规格管理 ====================

class SpecificationValueInline(admin.TabularInline):
    model = SpecificationValue
    extra = 1


@admin.register(SpecificationName)
class SpecificationNameAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'sort_order', 'created_at']
    search_fields = ['name']
    inlines = [SpecificationValueInline]


@admin.register(SKU)
class SKUAdmin(admin.ModelAdmin):
    list_display = ['id', 'sku_code', 'product', 'name', 'price', 'stock', 'is_active']
    list_filter = ['is_active', 'product']
    search_fields = ['sku_code', 'name', 'product__name']
    list_editable = ['price', 'stock', 'is_active']


# ==================== 订单管理 ====================

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product_name', 'product_image', 'sku_name', 'spec_values', 'price', 'quantity', 'total_amount']
    can_delete = False


class OrderLogInline(admin.TabularInline):
    model = OrderLog
    extra = 0
    readonly_fields = ['action', 'description', 'operator', 'created_at']
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_no', 'user', 'status_display', 'pay_amount',
        'payment_method_display', 'receiver_name', 'receiver_phone',
        'shipping_no', 'created_at'
    ]
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['order_no', 'receiver_name', 'receiver_phone', 'shipping_no']
    readonly_fields = [
        'order_no', 'user', 'total_amount', 'freight_amount',
        'discount_amount', 'pay_amount', 'payment_time', 'payment_no',
        'shipping_time', 'complete_time', 'created_at', 'updated_at'
    ]
    ordering = ['-created_at']

    fieldsets = (
        ('订单信息', {
            'fields': ('order_no', 'user', 'status', 'remark')
        }),
        ('金额信息', {
            'fields': ('total_amount', 'freight_amount', 'discount_amount', 'pay_amount')
        }),
        ('支付信息', {
            'fields': ('payment_method', 'payment_time', 'payment_no')
        }),
        ('收货信息', {
            'fields': ('receiver_name', 'receiver_phone', 'receiver_province',
                       'receiver_city', 'receiver_district', 'receiver_address')
        }),
        ('物流信息', {
            'fields': ('shipping_company', 'shipping_no', 'shipping_time')
        }),
        ('其他信息', {
            'fields': ('cancel_reason', 'complete_time', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    inlines = [OrderItemInline, OrderLogInline]

    def status_display(self, obj):
        colors = {
            0: 'orange',  # 待支付
            1: 'blue',  # 待发货
            2: 'purple',  # 已发货
            3: 'green',  # 已完成
            4: 'gray',  # 已取消
            5: 'red',  # 退款中
            6: 'darkred',  # 已退款
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color, obj.get_status_display()
        )

    status_display.short_description = '状态'

    def payment_method_display(self, obj):
        if obj.payment_method:
            return obj.get_payment_method_display()
        return '-'

    payment_method_display.short_description = '支付方式'

    actions = ['mark_as_shipped']

    def mark_as_shipped(self, request, queryset):
        """批量标记发货"""
        updated = queryset.filter(status=ORDER_STATUS_PENDING_SHIPMENT).update(
            status=ORDER_STATUS_SHIPPED
        )
        self.message_user(request, f'成功标记 {updated} 个订单为已发货')

    mark_as_shipped.short_description = '标记为已发货'


# ==================== 购物车管理 ====================

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'product', 'sku', 'quantity', 'is_selected', 'created_at']
    list_filter = ['is_selected', 'created_at']
    search_fields = ['user__username', 'product__name']


# ==================== 收藏管理 ====================

@admin.register(ProductFavorite)
class ProductFavoriteAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'product', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'product__name']