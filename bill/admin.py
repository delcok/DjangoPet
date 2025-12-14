# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Modified for better order flow

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import ServiceOrder, Bill


class PetServiceRecordInline(admin.StackedInline):
    """服务记录内联编辑"""
    from pet.models import PetServiceRecord
    model = PetServiceRecord
    extra = 0
    max_num = 1
    can_delete = False

    fieldsets = (
        ('服务时间', {
            'fields': ('actual_start_time', 'actual_end_time', 'actual_duration')
        }),
        ('宠物状况', {
            'fields': ('pet_condition_before', 'pet_condition_after', 'pet_behavior_notes')
        }),
        ('服务结果', {
            'fields': ('service_summary', 'professional_recommendations', 'next_service_suggestion')
        }),
        ('媒体记录', {
            'fields': ('before_images', 'after_images', 'process_videos'),
            'classes': ('collapse',)
        }),
        ('客户反馈', {
            'fields': ('customer_feedback', 'rating')
        }),
        ('其他', {
            'fields': ('special_notes', 'related_diary'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['actual_duration']
    autocomplete_fields = ['related_diary']

    verbose_name = '服务记录'
    verbose_name_plural = '服务记录'


@admin.register(ServiceOrder)
class ServiceOrderAdmin(admin.ModelAdmin):
    """服务订单管理"""

    list_display = [
        'id', 'user_info', 'base_service_info', 'pets_count',
        'scheduled_datetime', 'status_badge', 'price_info',
        'has_service_record', 'created_at'
    ]
    list_filter = ['status', 'scheduled_date', 'created_at', 'province', 'city']
    search_fields = ['user__username', 'contact_phone', 'contact_name', 'service_address']
    readonly_fields = [
        'base_price', 'additional_price', 'total_price', 'final_price',
        'created_at', 'updated_at', 'paid_at', 'completed_at'
    ]

    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'staff', 'status')
        }),
        ('服务内容', {
            'fields': ('base_service', 'additional_services', 'pets')
        }),
        ('服务时间', {
            'fields': ('scheduled_date', 'scheduled_time', 'duration_minutes')
        }),
        ('地址信息', {
            'fields': (
                'province', 'city', 'district',
                'service_address', 'contact_phone', 'contact_name'
            )
        }),
        ('价格信息', {
            'fields': (
                'base_price', 'additional_price', 'total_price',
                'discount_amount', 'final_price'
            )
        }),
        ('备注信息', {
            'fields': ('customer_notes', 'staff_notes', 'cancel_reason'),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at', 'paid_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )

    filter_horizontal = ['pets', 'additional_services']

    # 添加服务记录内联
    inlines = [PetServiceRecordInline]

    def user_info(self, obj):
        """用户信息"""
        return format_html(
            '<strong>{}</strong><br/><small>{}</small>',
            obj.user.username,
            obj.contact_phone
        )

    user_info.short_description = '用户信息'

    def base_service_info(self, obj):
        """基础服务信息"""
        return format_html(
            '{}<br/><small>¥{}</small>',
            obj.base_service.name,
            obj.base_price
        )

    base_service_info.short_description = '基础服务'

    def pets_count(self, obj):
        """宠物数量"""
        count = obj.pets.count()
        pets_names = ', '.join([pet.name or '未命名' for pet in obj.pets.all()[:3]])
        if count > 3:
            pets_names += '...'
        return format_html(
            '<span title="{}">{} 只</span>',
            pets_names,
            count
        )

    pets_count.short_description = '宠物'

    def scheduled_datetime(self, obj):
        """预约时间"""
        return format_html(
            '{}<br/><small>{}</small>',
            obj.scheduled_date,
            obj.scheduled_time
        )

    scheduled_datetime.short_description = '预约时间'

    def status_badge(self, obj):
        """状态徽章"""
        status_colors = {
            'draft': '#6c757d',  # 灰色
            'paid': '#17a2b8',  # 青色
            'confirmed': '#007bff',  # 蓝色
            'assigned': '#ffc107',  # 黄色
            'in_progress': '#fd7e14',  # 橙色
            'completed': '#28a745',  # 绿色
            'cancelled': '#dc3545',  # 红色
            'refunded': '#6f42c1',  # 紫色
        }
        color = status_colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 12px;">{}</span>',
            color,
            obj.get_status_display()
        )

    status_badge.short_description = '状态'

    def price_info(self, obj):
        """价格信息"""
        if obj.discount_amount > 0:
            return format_html(
                '<span style="text-decoration: line-through; color: #999;">¥{}</span><br/>'
                '<strong style="color: #dc3545;">¥{}</strong>',
                obj.total_price,
                obj.final_price
            )
        else:
            return format_html(
                '<strong>¥{}</strong>',
                obj.final_price
            )

    price_info.short_description = '价格'

    def has_service_record(self, obj):
        """是否有服务记录"""
        has_record = hasattr(obj, 'service_record') and obj.service_record is not None
        return format_html(
            '<span style="color: {};">{}</span>',
            '#52c41a' if has_record else '#d9d9d9',
            '✓' if has_record else '✗'
        )

    has_service_record.short_description = '服务记录'

    def get_queryset(self, request):
        """优化查询"""
        queryset = super().get_queryset(request)
        return queryset.select_related(
            'user', 'staff', 'base_service', 'service_record'
        ).prefetch_related('pets', 'additional_services')


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    """账单管理"""

    list_display = [
        'out_trade_no', 'user_info', 'transaction_info',
        'amount_display', 'payment_method_display',
        'status_badge', 'created_at'
    ]
    list_filter = [
        'transaction_type', 'payment_method', 'payment_status',
        'created_at', 'paid_at'
    ]
    search_fields = [
        'out_trade_no', 'third_party_no',
        'user__username', 'description'
    ]
    readonly_fields = [
        'out_trade_no', 'created_at', 'updated_at', 'paid_at'
    ]

    fieldsets = (
        ('订单信息', {
            'fields': ('out_trade_no', 'third_party_no', 'service_order')
        }),
        ('用户信息', {
            'fields': ('user',)
        }),
        ('交易信息', {
            'fields': (
                'transaction_type', 'amount', 'payment_method',
                'payment_status', 'description'
            )
        }),
        ('退款信息', {
            'fields': ('refund_amount', 'refund_reason', 'original_bill'),
            'classes': ('collapse',)
        }),
        ('失败信息', {
            'fields': ('failure_reason',),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at', 'paid_at', 'expired_at'),
            'classes': ('collapse',)
        }),
    )

    def user_info(self, obj):
        """用户信息"""
        return format_html(
            '<strong>{}</strong>',
            obj.user.username
        )

    user_info.short_description = '用户'

    def transaction_info(self, obj):
        """交易信息"""
        if obj.service_order:
            return format_html(
                '{}<br/><small>订单#{}</small>',
                obj.get_transaction_type_display(),
                obj.service_order.id
            )
        else:
            return obj.get_transaction_type_display()

    transaction_info.short_description = '交易类型'

    def amount_display(self, obj):
        """金额显示"""
        if obj.transaction_type == 'refund':
            return format_html(
                '<strong style="color: #dc3545;">-¥{}</strong>',
                obj.amount
            )
        else:
            return format_html(
                '<strong style="color: #28a745;">¥{}</strong>',
                obj.amount
            )

    amount_display.short_description = '金额'

    def payment_method_display(self, obj):
        """支付方式"""
        icons = {
            'wechat': '💚',
            'alipay': '💙',
            'balance': '💰',
            'cash': '💵',
            'other': '❓'
        }
        icon = icons.get(obj.payment_method, '❓')
        return format_html(
            '{} {}',
            icon,
            obj.get_payment_method_display()
        )

    payment_method_display.short_description = '支付方式'

    def status_badge(self, obj):
        """状态徽章"""
        status_colors = {
            'pending': '#ffc107',  # 黄色
            'processing': '#17a2b8',  # 青色
            'success': '#28a745',  # 绿色
            'failed': '#dc3545',  # 红色
            'cancelled': '#6c757d',  # 灰色
            'refunded': '#6f42c1',  # 紫色
        }
        color = status_colors.get(obj.payment_status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 12px;">{}</span>',
            color,
            obj.get_payment_status_display()
        )

    status_badge.short_description = '支付状态'

    def get_queryset(self, request):
        """优化查询"""
        queryset = super().get_queryset(request)
        return queryset.select_related('user', 'service_order', 'original_bill')

    actions = ['mark_as_success', 'mark_as_failed']

    def mark_as_success(self, request, queryset):
        """批量标记为成功"""
        count = 0
        for bill in queryset.filter(payment_status='pending'):
            bill.mark_as_paid()
            count += 1
        self.message_user(request, '成功标记 {} 条账单为已支付'.format(count))

    mark_as_success.short_description = '标记为支付成功'

    def mark_as_failed(self, request, queryset):
        """批量标记为失败"""
        count = queryset.filter(payment_status='pending').update(
            payment_status='failed',
            failure_reason='管理员手动标记为失败'
        )
        self.message_user(request, '成功标记 {} 条账单为支付失败'.format(count))

    mark_as_failed.short_description = '标记为支付失败'