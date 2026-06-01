# orders/admin.py

from django.contrib import admin
from .models import (
    ProductOrder, ProductOrderItem,
    ServiceOrder, ServiceOrderItem,
    OrderTransfer, OrderLog,
)


# ── 内联 ──

class ProductOrderItemInline(admin.TabularInline):
    model = ProductOrderItem
    extra = 0
    readonly_fields = ['item_amount']
    fields = [
        'product_id', 'sku_id', 'product_name', 'product_image',
        'sku_text', 'unit_price', 'quantity', 'item_amount',
    ]


class ServiceOrderItemInline(admin.TabularInline):
    model = ServiceOrderItem
    extra = 0
    readonly_fields = ['item_amount']
    fields = [
        'service_id', 'service_name', 'service_image',
        'service_type', 'service_mode', 'spec_name',
        'price_unit', 'duration_minutes',
        'unit_price', 'quantity', 'item_amount',
    ]


class OrderTransferInline(admin.TabularInline):
    model = OrderTransfer
    extra = 0
    readonly_fields = ['created_at', 'confirmed_at']
    fields = [
        'sequence', 'from_staff', 'to_staff',
        'initiated_by', 'transfer_type', 'reason',
        'status', 'confirm_deadline', 'confirmed_at', 'created_at',
    ]


# ══════ 商品订单 ══════

@admin.register(ProductOrder)
class ProductOrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_no', 'user', 'merchant_name', 'pay_amount',
        'status', 'delivery_type',
        'receiver_name', 'receiver_community',
        'paid_at', 'created_at',
    ]
    list_filter = ['status', 'delivery_type', 'created_at']
    search_fields = [
        'order_no', 'merchant_name',
        'receiver_name', 'receiver_phone',
        'receiver_community', 'shipping_no', 'verify_code',
    ]
    list_per_page = 30
    raw_id_fields = ['user', 'verified_by_staff']
    inlines = [ProductOrderItemInline]
    readonly_fields = ['order_no', 'created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('order_no', 'user', 'merchant_id', 'merchant_name', 'status')
        }),
        ('金额', {
            'fields': (
                'total_amount', 'freight_amount', 'discount_amount',
                'coin_deduct_amount', 'coins_deducted', 'pay_amount',
                'points_earned', 'gold_earned',
            )
        }),
        ('配送方式', {
            'fields': (
                'delivery_type',
                'pickup_address', 'pickup_contact', 'pickup_deadline',
            )
        }),
        ('收货地址', {
            'fields': (
                'receiver_name', 'receiver_phone', 'receiver_address_type',
                'receiver_province', 'receiver_city', 'receiver_district',
                'receiver_community', 'receiver_building', 'receiver_unit', 'receiver_room',
                'receiver_street', 'receiver_house_number',
                'receiver_address', 'receiver_access',
            )
        }),
        ('物流', {
            'fields': ('shipping_company', 'shipping_no', 'shipped_at')
        }),
        ('核销', {
            'fields': (
                'verify_code', 'verify_expire_at',
                'verified_at', 'verified_by_staff',
            )
        }),
        ('其他', {
            'fields': ('remark', 'cancel_reason', 'is_reviewed', 'reviewed_at')
        }),
        ('时间', {
            'fields': ('paid_at', 'completed_at', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ══════ 服务订单 ══════

@admin.register(ServiceOrder)
class ServiceOrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_no', 'user', 'merchant_name',
        'service_type', 'service_mode',
        'pay_amount', 'status',
        'receiver_name', 'receiver_community',
        'assigned_staff', 'is_urgent',
        'appointment_date', 'created_at',
    ]
    list_filter = ['status', 'service_type', 'service_mode', 'is_urgent', 'created_at']
    search_fields = [
        'order_no', 'merchant_name',
        'receiver_name', 'receiver_phone',
        'receiver_community', 'verify_code',
    ]
    list_per_page = 30
    raw_id_fields = ['user', 'assigned_staff', 'verified_by_staff']
    inlines = [ServiceOrderItemInline, OrderTransferInline]
    readonly_fields = ['order_no', 'verify_code', 'created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': (
                'order_no', 'user', 'merchant_id', 'merchant_name',
                'service_type', 'service_mode', 'schedule_type', 'status',
            )
        }),
        ('金额', {
            'fields': (
                'total_amount', 'discount_amount',
                'coin_deduct_amount', 'coins_deducted',
                'deposit_amount', 'pay_amount',
                'is_urgent', 'urgent_surcharge',
                'points_earned', 'gold_earned',
            )
        }),
        ('上门地址', {
            'fields': (
                'receiver_name', 'receiver_phone', 'receiver_address_type',
                'receiver_province', 'receiver_city', 'receiver_district',
                'receiver_community', 'receiver_building', 'receiver_unit', 'receiver_room',
                'receiver_street', 'receiver_house_number',
                'receiver_address', 'receiver_access',
                'receiver_lng', 'receiver_lat',
            )
        }),
        ('预约', {
            'fields': (
                'appointment_date', 'appointment_start', 'appointment_end',
                'time_slot_id',
            )
        }),
        ('派单 & 转单', {
            'fields': (
                'assigned_staff', 'assigned_at',
                'transfer_count', 'max_transfer_count',
            )
        }),
        ('核销', {
            'fields': (
                'verify_code', 'verify_expire_at',
                'verified_at', 'verified_by_staff',
            )
        }),
        ('其他', {
            'fields': ('extra_info', 'remark', 'cancel_reason', 'is_reviewed', 'reviewed_at')
        }),
        ('时间', {
            'fields': (
                'paid_at', 'service_start_at', 'service_end_at',
                'completed_at', 'created_at', 'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )


# ══════ 转单记录 ══════

@admin.register(OrderTransfer)
class OrderTransferAdmin(admin.ModelAdmin):
    list_display = [
        'order', 'sequence', 'from_staff', 'to_staff',
        'initiated_by', 'transfer_type', 'status', 'created_at',
    ]
    list_filter = ['status', 'initiated_by', 'transfer_type']
    search_fields = ['order__order_no']
    list_per_page = 30
    raw_id_fields = ['order', 'from_staff', 'to_staff']
    readonly_fields = ['created_at', 'confirmed_at']


# ══════ 订单日志 ══════

@admin.register(OrderLog)
class OrderLogAdmin(admin.ModelAdmin):
    list_display = [
        'order_no', 'order_type', 'action',
        'operator_type', 'operator_name', 'description',
        'created_at',
    ]
    list_filter = ['order_type', 'action', 'operator_type', 'created_at']
    search_fields = ['order_no', 'operator_name', 'description']
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False