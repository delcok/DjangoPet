# goods/admin.py

from django.contrib import admin
from django.utils.safestring import mark_safe

from .models import (
    GoodsCategory, MerchantGoodsGroup, GoodsTag, Brand,
    Goods, GoodsSpec, GoodsSpecValue, GoodsSku,
    GoodsFavorite, GoodsViewHistory, GoodsCart,
)


# ══════════════════════════════════════════════════════════════
# 分类
# ══════════════════════════════════════════════════════════════

@admin.register(GoodsCategory)
class GoodsCategoryAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'parent', 'commission_rate',
        'sort_order', 'is_active', 'is_show_home',
    ]
    list_filter = ['is_active', 'is_show_home', 'parent']
    list_editable = ['sort_order', 'is_active', 'is_show_home']
    search_fields = ['name']
    ordering = ['sort_order', 'id']


# ══════════════════════════════════════════════════════════════
# 商家店铺分组
# ══════════════════════════════════════════════════════════════

@admin.register(MerchantGoodsGroup)
class MerchantGoodsGroupAdmin(admin.ModelAdmin):
    list_display = ['id', 'merchant', 'name', 'sort_order', 'is_active']
    list_filter = ['is_active']
    list_editable = ['sort_order', 'is_active']
    search_fields = ['name', 'merchant__name']
    raw_id_fields = ['merchant']
    ordering = ['sort_order', 'id']


# ══════════════════════════════════════════════════════════════
# 标签
# ══════════════════════════════════════════════════════════════

@admin.register(GoodsTag)
class GoodsTagAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'merchant', 'color', 'bg_color',
        'sort_order', 'is_active',
    ]
    list_filter = ['is_active', ('merchant', admin.EmptyFieldListFilter)]
    list_editable = ['sort_order', 'is_active']
    search_fields = ['name', 'merchant__name']
    raw_id_fields = ['merchant']
    ordering = ['sort_order', 'id']


# ══════════════════════════════════════════════════════════════
# 品牌
# ══════════════════════════════════════════════════════════════

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'merchant', 'country', 'sort_order',
        'is_active', 'is_recommended',
    ]
    list_filter = [
        'is_active', 'is_recommended', 'country',
        ('merchant', admin.EmptyFieldListFilter),
    ]
    list_editable = ['sort_order', 'is_active', 'is_recommended']
    search_fields = ['name', 'merchant__name', 'country']
    raw_id_fields = ['merchant']
    ordering = ['sort_order', 'id']


# ══════════════════════════════════════════════════════════════
# 商品 SPU
# ══════════════════════════════════════════════════════════════

class GoodsSpecInline(admin.TabularInline):
    """规格名内联"""
    model = GoodsSpec
    extra = 0
    show_change_link = True
    fields = ['name', 'sort_order']


class GoodsSkuInline(admin.TabularInline):
    """SKU 内联"""
    model = GoodsSku
    extra = 0
    fields = [
        'sku_sn', 'spec_text', 'image',
        'price', 'original_price', 'cost_price',
        'stock', 'stock_warning', 'sales_count',
        'weight', 'barcode', 'max_coin_deduction',
        'is_active', 'sort_order',
    ]
    readonly_fields = ['sales_count']
    show_change_link = True


@admin.register(Goods)
class GoodsAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'title', 'merchant', 'category', 'brand',
        'price', 'total_stock', 'sales_count',
        # ✅ 新增:配送方式开关一眼可见
        'delivery_badge',
        'status', 'sort_order',
        'is_recommended', 'is_hot', 'is_new', 'is_best',
        'created_at',
    ]
    list_filter = [
        'status', 'goods_type',
        # ✅ 新增:可按配送方式筛选
        'allow_delivery', 'allow_pickup',
        'is_recommended', 'is_hot', 'is_new', 'is_best',
        'allow_member_discount', 'allow_coin_deduction',
        'category', 'brand',
    ]
    list_editable = [
        'sort_order', 'status',
        'is_recommended', 'is_hot', 'is_new', 'is_best',
    ]
    search_fields = ['title', 'goods_sn', 'merchant__name']
    raw_id_fields = [
        'merchant', 'category', 'brand', 'merchant_group',
    ]
    filter_horizontal = ['tags']
    readonly_fields = [
        'price',
        'total_stock',
        'sales_count',
        'view_count', 'favorite_count',
        'review_count', 'rating',
        'created_at', 'updated_at',
    ]
    inlines = [GoodsSpecInline, GoodsSkuInline]
    ordering = ['-sort_order', '-created_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('基本信息', {
            'fields': (
                'merchant', 'goods_sn', 'title', 'subtitle', 'keywords',
                'goods_type', 'category', 'brand', 'merchant_group', 'tags',
            )
        }),
        ('图片 / 视频', {
            'fields': ('main_image', 'images', 'detail_images', 'video_url'),
        }),
        ('价格(展示价由 SKU 自动聚合)', {
            'fields': ('price', 'original_price', 'cost_price'),
        }),
        ('详情', {
            'fields': ('detail', 'specs_desc', 'after_service'),
            'classes': ('collapse',),
        }),
        # ✅ 新增:物流与配送方式
        ('物流与配送方式', {
            'fields': (
                'weight',
                'allow_delivery', 'allow_pickup',
            ),
            'description': (
                '<b>配送方式开关</b>:至少需要开启一项,'
                '否则商品保存时会校验失败,无法销售。<br>'
                '• allow_delivery=False → 仅支持自提<br>'
                '• allow_pickup=False → 仅支持配送<br>'
                '• 两个都为 True → 用户可自选'
            ),
        }),
        ('限购', {
            'fields': ('purchase_limit', 'purchase_min'),
            'classes': ('collapse',),
        }),
        ('会员折扣 / 金币抵扣', {
            'fields': (
                'allow_member_discount',
                'allow_coin_deduction', 'max_coin_deduction',
            ),
        }),
        ('排序与推荐(管理员操作)', {
            'fields': (
                'sort_order',
                'is_recommended', 'is_hot', 'is_new', 'is_best',
            ),
        }),
        ('状态', {
            'fields': ('status', 'published_at'),
        }),
        ('统计(只读)', {
            'fields': (
                'total_stock', 'sales_count',
                'view_count', 'favorite_count',
                'rating', 'review_count',
                'created_at', 'updated_at',
            ),
        }),
    )

    # ✅ 列表里把配送方式渲染成色彩徽章,一眼能看清
    # Django 6 起 format_html 必须带占位符或 kwargs,纯静态 HTML 改用 mark_safe
    @admin.display(description='配送方式', ordering='allow_delivery')
    def delivery_badge(self, obj):
        ad = obj.allow_delivery
        ap = obj.allow_pickup

        if ad and ap:
            return mark_safe(
                '<span style="color:#2D7D3F;font-weight:600">'
                '🚚 配送 + 🏪 自提</span>'
            )
        if ad and not ap:
            return mark_safe(
                '<span style="color:#1976D2;font-weight:600">🚚 仅配送</span>'
            )
        if ap and not ad:
            return mark_safe(
                '<span style="color:#D4A017;font-weight:600">🏪 仅自提</span>'
            )
        # 两个都关 — 异常状态(model.clean 应该已经拦了,但万一脏数据)
        return mark_safe(
            '<span style="color:#E84A3D;font-weight:700">⚠ 都未开启</span>'
        )


# ══════════════════════════════════════════════════════════════
# 规格
# ══════════════════════════════════════════════════════════════

class GoodsSpecValueInline(admin.TabularInline):
    model = GoodsSpecValue
    extra = 0
    fields = ['value', 'image', 'sort_order']


@admin.register(GoodsSpec)
class GoodsSpecAdmin(admin.ModelAdmin):
    list_display = ['id', 'goods', 'name', 'sort_order']
    list_editable = ['sort_order']
    search_fields = ['name', 'goods__title']
    raw_id_fields = ['goods']
    inlines = [GoodsSpecValueInline]
    ordering = ['sort_order', 'id']


@admin.register(GoodsSpecValue)
class GoodsSpecValueAdmin(admin.ModelAdmin):
    list_display = ['id', 'spec', 'value', 'sort_order']
    list_editable = ['sort_order']
    search_fields = ['value', 'spec__name', 'spec__goods__title']
    raw_id_fields = ['spec']
    ordering = ['sort_order', 'id']


# ══════════════════════════════════════════════════════════════
# SKU
# ══════════════════════════════════════════════════════════════

@admin.register(GoodsSku)
class GoodsSkuAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'goods', 'sku_sn', 'spec_text',
        'price', 'stock', 'stock_warning',
        'sales_count', 'is_active', 'sort_order',
    ]
    list_filter = ['is_active']
    list_editable = ['is_active', 'sort_order']
    search_fields = ['sku_sn', 'goods__title', 'spec_text', 'barcode']
    raw_id_fields = ['goods']
    readonly_fields = ['sales_count', 'created_at', 'updated_at']
    ordering = ['sort_order', 'id']


# ══════════════════════════════════════════════════════════════
# 收藏 / 浏览记录
# ══════════════════════════════════════════════════════════════

@admin.register(GoodsFavorite)
class GoodsFavoriteAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'goods', 'created_at']
    search_fields = ['user__phone', 'goods__title']
    raw_id_fields = ['user', 'goods']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(GoodsViewHistory)
class GoodsViewHistoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'goods', 'view_count', 'last_view_at']
    search_fields = ['user__phone', 'goods__title']
    raw_id_fields = ['user', 'goods']
    readonly_fields = ['view_count', 'last_view_at', 'created_at']
    ordering = ['-last_view_at']


# ══════════════════════════════════════════════════════════════
# 购物车
# ══════════════════════════════════════════════════════════════

@admin.register(GoodsCart)
class GoodsCartAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user', 'merchant', 'goods', 'sku',
        'quantity', 'snapshot_price', 'is_selected', 'updated_at',
    ]
    list_filter = ['is_selected', 'merchant']
    search_fields = ['user__phone', 'goods__title', 'sku__sku_sn']
    raw_id_fields = ['user', 'goods', 'sku', 'merchant']
    readonly_fields = ['snapshot_price', 'created_at', 'updated_at']
    ordering = ['-updated_at']