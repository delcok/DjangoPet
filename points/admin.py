from django.contrib import admin
from .models import IntegralProduct, IntegralOrder, IntegralRecord, UserIntegralProduct


@admin.register(IntegralProduct)
class IntegralProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'product_type', 'integral_price', 'stock',
                    'sales_count', 'status', 'is_hot', 'created_at']
    list_filter = ['product_type', 'status', 'is_hot', 'is_new']
    search_fields = ['name', 'description']
    list_editable = ['status', 'is_hot']
    ordering = ['-sort_order', '-created_at']


@admin.register(IntegralOrder)
class IntegralOrderAdmin(admin.ModelAdmin):
    list_display = ['order_no', 'user', 'product', 'quantity',
                    'integral_cost', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['order_no', 'user__username', 'user__phone']
    readonly_fields = ['order_no', 'product_snapshot', 'created_at']

    fieldsets = (
        ('订单信息', {
            'fields': ('order_no', 'user', 'product', 'quantity', 'integral_cost', 'status')
        }),
        ('收货信息', {
            'fields': ('receiver_name', 'receiver_phone', 'receiver_address')
        }),
        ('物流信息', {
            'fields': ('express_company', 'express_no')
        }),
        ('备注', {
            'fields': ('user_remark', 'admin_remark')
        }),
    )


@admin.register(IntegralRecord)
class IntegralRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'record_type', 'source', 'amount', 'balance', 'created_at']
    list_filter = ['record_type', 'source', 'created_at']
    search_fields = ['user__username', 'user__phone', 'description']
    readonly_fields = ['user', 'record_type', 'amount', 'balance', 'created_at']


@admin.register(UserIntegralProduct)
class UserIntegralProductAdmin(admin.ModelAdmin):
    list_display = ['user', 'product', 'is_used', 'expired_at', 'created_at']
    list_filter = ['is_used', 'created_at']
    search_fields = ['user__username', 'product__name']