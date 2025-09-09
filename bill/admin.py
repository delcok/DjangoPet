# -*- coding: utf-8 -*-
# @Time    : 2025/8/25 16:55
# @Author  : Delock

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from bill.models import Bill, ServiceOrder


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    """账单管理界面"""

    list_display = [
        'out_trade_no', 'user_link', 'transaction_type_badge',
        'amount', 'payment_method_badge', 'payment_status_badge',
        'created_at'
    ]
    list_filter = [
        'transaction_type', 'payment_method', 'payment_status',
        'created_at'
    ]
    search_fields = [
        'out_trade_no', 'wechat_transaction_id', 'description',
        'user__username', 'user__phone'
    ]
    readonly_fields = [
        'out_trade_no', 'wechat_transaction_id', 'created_at'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('out_trade_no', 'wechat_transaction_id', 'user')
        }),
        ('交易信息', {
            'fields': ('transaction_type', 'amount', 'payment_method', 'payment_status')
        }),
        ('描述信息', {
            'fields': ('description',)
        }),
        ('时间信息', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def user_link(self, obj):
        """用户链接"""
        if obj.user:
            url = reverse('admin:user_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.username)
        return '-'

    user_link.short_description = '用户'

    def transaction_type_badge(self, obj):
        """交易类型徽章"""
        colors = {
            'payment': 'green',
            'refund': 'orange',
            'recharge': 'blue'
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )

    transaction_type_badge.short_description = '交易类型'

    def payment_method_badge(self, obj):
        """支付方式徽章"""
        return format_html(
            '<span class="badge">{}</span>',
            obj.get_payment_method_display()
        )

    payment_method_badge.short_description = '支付方式'

    def payment_status_badge(self, obj):
        """支付状态徽章"""
        colors = {
            'pending': '#ffc107',
            'completed': '#28a745',
            'failed': '#dc3545'
        }
        color = colors.get(obj.payment_status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 12px;">{}</span>',
            color,
            obj.get_payment_status_display()
        )

    payment_status_badge.short_description = '支付状态'

    def get_queryset(self, request):
        """优化查询"""
        return super().get_queryset(request).select_related('user')


@admin.register(ServiceOrder)
class ServiceOrderAdmin(admin.ModelAdmin):
    """服务订单管理界面"""

    list_display = [
        'id', 'user_link', 'staff_link', 'scheduled_datetime',
        'total_price', 'status_badge', 'pets_count', 'created_at'
    ]
    list_filter = [
        'status', 'scheduled_date', 'created_at', 'staff'
    ]
    search_fields = [
        'service_address', 'contact_phone', 'customer_notes',
        'user__username', 'staff__name'
    ]
    readonly_fields = [
        'total_price', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'scheduled_date'
    ordering = ['-created_at']
    filter_horizontal = ['pets']

    fieldsets = (
        ('基本信息', {
            'fields': ('bill', 'user', 'staff')
        }),
        ('宠物信息', {
            'fields': ('pets',)
        }),
        ('预约信息', {
            'fields': (
                'scheduled_date', 'scheduled_time', 'duration_minutes',
                'service_address', 'contact_phone'
            )
        }),
        ('价格信息', {
            'fields': ('base_price', 'additional_price', 'total_price')
        }),
        ('状态和备注', {
            'fields': ('status', 'customer_notes', 'staff_notes')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def user_link(self, obj):
        """用户链接"""
        if obj.user:
            url = reverse('admin:user_user_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.username)
        return '-'

    user_link.short_description = '用户'

    def staff_link(self, obj):
        """员工链接"""
        if obj.staff:
            # 假设有Staff模型的admin
            return format_html('<span style="color: green;">{}</span>', obj.staff.name)
        return format_html('<span style="color: red;">未分配</span>')

    staff_link.short_description = '员工'

    def scheduled_datetime(self, obj):
        """预约时间"""
        return f"{obj.scheduled_date} {obj.scheduled_time}"

    scheduled_datetime.short_description = '预约时间'

    def status_badge(self, obj):
        """状态徽章"""
        colors = {
            'pending': '#ffc107',
            'confirmed': '#17a2b8',
            'in_progress': '#007bff',
            'completed': '#28a745',
            'cancelled': '#dc3545'
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 12px;">{}</span>',
            color,
            obj.get_status_display()
        )

    status_badge.short_description = '状态'

    def pets_count(self, obj):
        """宠物数量"""
        count = obj.pets.count()
        if count > 0:
            pets_names = ', '.join([pet.name for pet in obj.pets.all()[:3]])
            if count > 3:
                pets_names += f' 等{count}只'
            return format_html(
                '<span title="{}">{} 只</span>',
                pets_names,
                count
            )
        return '0 只'

    pets_count.short_description = '宠物'

    def get_queryset(self, request):
        """优化查询"""
        return super().get_queryset(request).select_related(
            'user', 'staff', 'bill'
        ).prefetch_related('pets')

    actions = ['confirm_orders', 'cancel_orders']

    def confirm_orders(self, request, queryset):
        """批量确认订单"""
        updated = queryset.filter(status='pending').update(status='confirmed')
        self.message_user(request, f'成功确认 {updated} 个订单')

    confirm_orders.short_description = '确认选中的订单'

    def cancel_orders(self, request, queryset):
        """批量取消订单"""
        updated = queryset.filter(
            status__in=['pending', 'confirmed']
        ).update(status='cancelled')
        self.message_user(request, f'成功取消 {updated} 个订单')

    cancel_orders.short_description = '取消选中的订单'