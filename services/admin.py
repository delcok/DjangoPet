# -*- coding: utf-8 -*-
"""
服务模块 Admin

设计要点:
- 按"基础 / 类型方式 / 价格规格 / 商家覆盖 / 类型专属 config / 员工 / 统计"分组
- 类型专属的 4 个 config JSON 用 collapse 折叠,避免一打开就铺满屏
- list_display 增加 effective_xxx 派生列,方便后台一眼看出实际生效值
- readonly_fields 包含所有统计字段,防误改
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    ServiceCategory,
    Service,
    ServiceScheduleRule,
    ServiceTimeSlot,
    ServiceFavorite,
)


# ═══════════════════════════════════════════════════════════════════════
# 服务分类
# ═══════════════════════════════════════════════════════════════════════

@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'level', 'parent', 'service_count',
        'is_hot', 'is_active', 'sort_order',
    )
    list_filter = ('level', 'is_active', 'is_hot')
    search_fields = ('name', 'description')
    list_editable = ('is_hot', 'is_active', 'sort_order')
    readonly_fields = ('level', 'service_count', 'created_at', 'updated_at')
    autocomplete_fields = ('parent',)
    ordering = ('-sort_order', 'id')

    fieldsets = (
        ('基础', {
            'fields': ('name', 'parent', 'level', 'description'),
        }),
        ('展示', {
            'fields': ('icon', 'image', 'sort_order', 'is_active', 'is_hot'),
        }),
        ('统计', {
            'fields': ('service_count', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ═══════════════════════════════════════════════════════════════════════
# 排班规则(内联到 Service)
# ═══════════════════════════════════════════════════════════════════════

class ServiceScheduleRuleInline(admin.TabularInline):
    model = ServiceScheduleRule
    extra = 0
    fields = (
        'weekdays', 'start_time', 'end_time',
        'slot_granularity_minutes', 'parallel_capacity', 'is_active',
    )


# ═══════════════════════════════════════════════════════════════════════
# 服务
# ═══════════════════════════════════════════════════════════════════════

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'merchant', 'category',
        'service_type', 'service_mode',
        'price', 'price_unit',
        'status', 'is_recommended', 'is_hot',
        'total_sales', 'rating',
        'created_at',
    )
    list_filter = (
        'service_type', 'service_mode', 'status',
        'is_recommended', 'is_hot',
        'require_staff', 'auto_confirm',
        'category',
    )
    search_fields = (
        'name', 'subtitle', 'description',
        'merchant__name', 'category__name',
    )
    list_editable = ('status', 'is_recommended', 'is_hot')
    autocomplete_fields = ('merchant', 'category', 'staff_members')
    inlines = [ServiceScheduleRuleInline]
    ordering = ('-created_at',)
    list_per_page = 30

    readonly_fields = (
        # 统计
        'total_sales', 'view_count', 'favorite_count',
        'order_count', 'review_count', 'rating',
        # 派生展示
        'effective_business_hours_display',
        'effective_radius_display',
        'effective_delivery_fee_display',
        'effective_min_order_amount_display',
        # 时间戳
        'created_at', 'updated_at',
    )

    fieldsets = (
        ('基础信息', {
            'fields': (
                'merchant', 'category',
                'name', 'subtitle', 'description', 'service_notice',
                'cover_image', 'images', 'detail_images', 'detail_content',
            ),
        }),
        ('类型与方式', {
            'fields': ('service_type', 'service_mode'),
            'description': (
                '<b>类型与方式约束:</b><br>'
                'walk_in 到店制 → 仅 store<br>'
                'appointment 预约制 → store / home / pickup<br>'
                'on_demand 按需制 → home / pickup<br>'
                'scheduled 周期制 → home / pickup'
            ),
        }),
        ('价格与库存', {
            'fields': (
                ('price', 'original_price'),
                ('price_unit', 'deposit_amount'),
                ('allow_coin_deduction', 'max_coin_deduction', 'points_reward'),
                ('min_quantity', 'max_quantity', 'stock'),
            ),
        }),
        ('规格(时长真源)', {
            'fields': ('specifications', 'default_duration_minutes'),
            'description': (
                '多规格时,每个 spec 自带 duration_minutes;<br>'
                '单规格(specifications=[])时,appointment 类型需填 default_duration_minutes'
            ),
        }),
        ('员工', {
            'fields': (
                'require_staff', 'allow_choose_staff', 'staff_members',
            ),
        }),
        ('通用订单约束', {
            'fields': (
                'free_cancel_hours',
                'max_daily_orders', 'max_concurrent_orders',
                'auto_confirm', 'required_info',
            ),
            'classes': ('collapse',),
        }),
        ('商家级覆盖(留空=继承商家)', {
            'fields': (
                'business_hours_override', 'effective_business_hours_display',
                'service_radius_override', 'effective_radius_display',
                'delivery_fee_override', 'effective_delivery_fee_display',
                'free_delivery_threshold_override',
                'min_order_amount_override', 'effective_min_order_amount_display',
            ),
            'classes': ('collapse',),
            'description': '所有 *_override 字段留空表示沿用 merchant 上的同名字段',
        }),
        ('类型专属配置(按 service_type 填,其他留 null)', {
            'fields': (
                'appointment_config',
                'dispatch_config',
                'urgent_config',
                'delivery_config',
            ),
            'classes': ('collapse',),
            'description': (
                '<b>四个 config 互斥使用:</b><br>'
                'appointment → appointment_config(必填) + 可选 dispatch / urgent<br>'
                'on_demand → dispatch_config(必填) + 可选 urgent<br>'
                'scheduled → delivery_config(必填)<br>'
                'walk_in → 全部为 null'
            ),
        }),
        ('展示与推荐', {
            'fields': ('sort_order', 'is_recommended', 'is_hot', 'status'),
        }),
        ('统计(只读)', {
            'fields': (
                'total_sales', 'view_count', 'favorite_count',
                'order_count', 'review_count', 'rating',
                'created_at', 'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    # ─────────── effective_* 派生展示 ───────────

    @admin.display(description='实际营业时间')
    def effective_business_hours_display(self, obj):
        if not obj.pk:
            return '—'
        v = obj.effective_business_hours
        if not v:
            return format_html('<span style="color:#999">未配置</span>')
        return format_html('<code>{}</code>', v)

    @admin.display(description='实际服务半径(米)')
    def effective_radius_display(self, obj):
        if not obj.pk:
            return '—'
        v = obj.effective_radius_meters
        source = '(覆盖)' if obj.service_radius_override is not None else '(继承商家)'
        return format_html('{} <span style="color:#999">{}</span>', v, source)

    @admin.display(description='实际配送费')
    def effective_delivery_fee_display(self, obj):
        if not obj.pk:
            return '—'
        v = obj.effective_delivery_fee
        source = '(覆盖)' if obj.delivery_fee_override is not None else '(继承商家)'
        return format_html('¥{} <span style="color:#999">{}</span>', v, source)

    @admin.display(description='实际起送金额')
    def effective_min_order_amount_display(self, obj):
        if not obj.pk:
            return '—'
        v = obj.effective_min_order_amount
        source = '(覆盖)' if obj.min_order_amount_override is not None else '(继承商家)'
        return format_html('¥{} <span style="color:#999">{}</span>', v, source)


# ═══════════════════════════════════════════════════════════════════════
# 排班规则(独立管理)
# ═══════════════════════════════════════════════════════════════════════

@admin.register(ServiceScheduleRule)
class ServiceScheduleRuleAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'service', 'weekdays',
        'start_time', 'end_time',
        'slot_granularity_minutes', 'parallel_capacity',
        'is_active',
    )
    list_filter = ('is_active',)
    search_fields = ('service__name', 'service__merchant__name')
    autocomplete_fields = ('service',)


# ═══════════════════════════════════════════════════════════════════════
# 可预约时段(运营查询用,通常不直接编辑)
# ═══════════════════════════════════════════════════════════════════════

@admin.register(ServiceTimeSlot)
class ServiceTimeSlotAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'service', 'date',
        'start_time', 'end_time',
        'capacity', 'booked_count', 'remaining_display',
        'status',
    )
    list_filter = ('status', 'date')
    search_fields = ('service__name',)
    autocomplete_fields = ('service', 'rule')
    date_hierarchy = 'date'
    readonly_fields = ('booked_count', 'created_at', 'updated_at')

    @admin.display(description='剩余')
    def remaining_display(self, obj):
        r = obj.remaining
        color = '#16a34a' if r > 0 else '#dc2626'
        return format_html('<span style="color:{}">{}</span>', color, r)


# ═══════════════════════════════════════════════════════════════════════
# 收藏(运营查询用)
# ═══════════════════════════════════════════════════════════════════════

@admin.register(ServiceFavorite)
class ServiceFavoriteAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'service', 'created_at')
    search_fields = ('user__phone', 'service__name')
    autocomplete_fields = ('user', 'service')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'