# -*- coding: utf-8 -*-

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    UserWallet, WalletTransaction, WalletStatusLog,
    MerchantWallet, MerchantWalletTransaction,
    WithdrawalRequest, MerchantSettlementConfig,
    PointsRule,
)


# ════════════════════════════════════════════════════════════════
#                        公共 Mixin
# ════════════════════════════════════════════════════════════════

class ReadOnlyAdminMixin:
    """只读：不能新增、不能删除、全字段只读"""
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # 允许进入详情页查看，但所有字段都是 readonly
        return True

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]


class NoDeleteMixin:
    """允许修改但禁止删除（资金类数据不应物理删除）"""
    def has_delete_permission(self, request, obj=None):
        return False


# ════════════════════════════════════════════════════════════════
#                        用户钱包
# ════════════════════════════════════════════════════════════════

class WalletStatusLogInline(admin.TabularInline):
    """用户钱包详情页内联展示状态变更历史"""
    model = WalletStatusLog
    extra = 0
    can_delete = False
    readonly_fields = ['old_status', 'new_status', 'reason',
                       'operator_id', 'operator_role', 'operator_ip', 'created_at']
    fields = readonly_fields
    ordering = ['-created_at']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(UserWallet)
class UserWalletAdmin(NoDeleteMixin, admin.ModelAdmin):
    list_display = [
        'id', 'user_link', 'status_colored',
        'points_balance', 'points_frozen', 'points_available_display',
        'gold_balance', 'gold_frozen',
        'last_transaction_at', 'updated_at',
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['user__mobile', 'user__username', 'user__nickname', 'id']
    ordering = ['-updated_at']
    date_hierarchy = 'created_at'
    list_per_page = 30

    # 所有余额/统计字段强制只读！
    readonly_fields = [
        'user', 'version', 'last_transaction_at', 'created_at', 'updated_at',
        # 积分
        'points_balance', 'points_total_earned', 'points_total_spent',
        'points_total_expired', 'points_frozen',
        # 金币
        'gold_balance', 'gold_total_earned', 'gold_total_spent',
        'gold_total_expired', 'gold_frozen',
    ]

    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'status', 'status_reason',
                       'version', 'last_transaction_at', 'created_at', 'updated_at')
        }),
        ('积分', {
            'fields': ('points_balance', 'points_frozen',
                       'points_total_earned', 'points_total_spent', 'points_total_expired')
        }),
        ('金币', {
            'fields': ('gold_balance', 'gold_frozen',
                       'gold_total_earned', 'gold_total_spent', 'gold_total_expired')
        }),
    )

    inlines = [WalletStatusLogInline]

    def has_add_permission(self, request):
        # 钱包应该由 User 创建时触发，不在 admin 里手动建
        return False

    # ───── 自定义列 ─────

    @admin.display(description='用户', ordering='user_id')
    def user_link(self, obj):
        if not obj.user_id:
            return '-'
        return format_html(
            '<a href="/admin/user/user/{}/change/">#{} {}</a>',
            obj.user_id, obj.user_id,
            getattr(obj.user, 'nickname', '') or getattr(obj.user, 'mobile', ''),
        )

    @admin.display(description='状态', ordering='status')
    def status_colored(self, obj):
        colors = {'active': 'green', 'suspended': 'orange', 'frozen': 'red'}
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'), obj.get_status_display()
        )

    @admin.display(description='可用积分')
    def points_available_display(self, obj):
        return obj.points_available


# ════════════════════════════════════════════════════════════════
#                        用户钱包流水
# ════════════════════════════════════════════════════════════════

@admin.register(WalletTransaction)
class WalletTransactionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    """流水完全只读：不能在 admin 里新增/改/删"""

    list_display = [
        'id', 'wallet_link', 'user_id',
        'currency', 'action',
        'amount_colored', 'balance_after', 'remaining_amount',
        'status', 'operator_role', 'created_at',
    ]
    list_filter = ['currency', 'action', 'status', 'operator_role', 'created_at']
    search_fields = ['wallet__id', 'user_id', 'remark',
                     'idempotent_key', 'batch_no', 'related_id']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    list_per_page = 50
    list_select_related = ['wallet']

    fieldsets = (
        ('关联', {'fields': ('wallet', 'user_id', 'related_type', 'related_id', 'batch_no')}),
        ('变动', {'fields': ('currency', 'action', 'amount', 'balance_after',
                           'remaining_amount', 'freeze_delta', 'expire_at')}),
        ('状态', {'fields': ('status', 'reversed_by_tx')}),
        ('操作人', {'fields': ('operator_id', 'operator_role', 'operator_ip')}),
        ('元信息', {'fields': ('remark', 'idempotent_key', 'created_at')}),
    )

    @admin.display(description='钱包')
    def wallet_link(self, obj):
        url = reverse('admin:wallet_userwallet_change', args=[obj.wallet_id])
        return format_html('<a href="{}">#{}</a>', url, obj.wallet_id)

    @admin.display(description='金额', ordering='amount')
    def amount_colored(self, obj):
        color = 'green' if obj.amount > 0 else ('red' if obj.amount < 0 else 'gray')
        sign = '+' if obj.amount > 0 else ''
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}{}</span>',
            color, sign, obj.amount,
        )


# ════════════════════════════════════════════════════════════════
#                        钱包状态变更日志
# ════════════════════════════════════════════════════════════════

@admin.register(WalletStatusLog)
class WalletStatusLogAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['id', 'wallet', 'old_status', 'new_status',
                    'operator_id', 'operator_role', 'created_at']
    list_filter = ['old_status', 'new_status', 'operator_role', 'created_at']
    search_fields = ['wallet__id', 'reason', 'operator_id']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'


# ════════════════════════════════════════════════════════════════
#                        积分规则（可编辑）
# ════════════════════════════════════════════════════════════════

@admin.register(PointsRule)
class PointsRuleAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'scope_display', 'trigger', 'calc_type',
                    'value', 'expire_days', 'is_active', 'priority', 'updated_at']
    list_filter = ['is_active', 'trigger', 'calc_type']
    search_fields = ['name', 'merchant_id']
    ordering = ['-priority', '-updated_at']
    list_editable = ['is_active', 'priority']

    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']

    fieldsets = (
        ('基本', {'fields': ('name', 'merchant_id', 'trigger', 'is_active', 'priority')}),
        ('计算', {'fields': ('calc_type', 'value', 'rule_config',
                           'max_points_per_tx', 'daily_cap', 'expire_days')}),
        ('有效期', {'fields': ('start_at', 'end_at')}),
        ('元信息', {'fields': ('created_by', 'updated_by', 'created_at', 'updated_at')}),
    )

    @admin.display(description='作用范围')
    def scope_display(self, obj):
        return f'商家#{obj.merchant_id}' if obj.merchant_id else '全局'

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user if hasattr(request.user, 'id') else None
        obj.updated_by = request.user if hasattr(request.user, 'id') else None
        super().save_model(request, obj, form, change)


# ════════════════════════════════════════════════════════════════
#                        商户钱包
# ════════════════════════════════════════════════════════════════

@admin.register(MerchantWallet)
class MerchantWalletAdmin(NoDeleteMixin, admin.ModelAdmin):
    list_display = [
        'id', 'merchant_link', 'status_colored',
        'balance', 'frozen_amount', 'available_balance_display',
        'pending_settlement', 'total_income', 'total_withdrawn',
        'last_transaction_at',
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['merchant__name', 'merchant__id', 'id']
    ordering = ['-updated_at']
    list_per_page = 30

    # 余额/统计全部只读
    readonly_fields = [
        'merchant', 'version', 'last_transaction_at', 'created_at', 'updated_at',
        'balance', 'frozen_amount', 'pending_settlement',
        'total_income', 'total_commission', 'total_refunded',
        'total_withdrawn', 'total_withdraw_fee',
        'pay_password',  # 密码永远不在 admin 显示/修改
    ]

    fieldsets = (
        ('基本', {
            'fields': ('merchant', 'status', 'status_reason',
                       'version', 'last_transaction_at', 'created_at', 'updated_at')
        }),
        ('余额', {
            'fields': ('balance', 'frozen_amount', 'pending_settlement')
        }),
        ('累计统计', {
            'fields': ('total_income', 'total_commission', 'total_refunded',
                       'total_withdrawn', 'total_withdraw_fee')
        }),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description='商家', ordering='merchant_id')
    def merchant_link(self, obj):
        if not obj.merchant_id:
            return '-'
        return format_html(
            '<a href="/admin/merchants/merchant/{}/change/">#{} {}</a>',
            obj.merchant_id, obj.merchant_id,
            getattr(obj.merchant, 'name', ''),
        )

    @admin.display(description='状态', ordering='status')
    def status_colored(self, obj):
        colors = {'active': 'green', 'suspended': 'orange', 'frozen': 'red'}
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'), obj.get_status_display()
        )

    @admin.display(description='可提现余额')
    def available_balance_display(self, obj):
        return obj.available_balance


# ════════════════════════════════════════════════════════════════
#                        商户钱包流水
# ════════════════════════════════════════════════════════════════

@admin.register(MerchantWalletTransaction)
class MerchantWalletTransactionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        'id', 'wallet_link', 'merchant_id',
        'action', 'amount_colored', 'balance_after', 'pending_after',
        'status', 'related_order_no', 'operator_role', 'created_at',
    ]
    list_filter = ['action', 'status', 'operator_role', 'created_at']
    search_fields = ['wallet__id', 'merchant_id', 'remark',
                     'related_order_no', 'idempotent_key', 'batch_no']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    list_per_page = 50
    list_select_related = ['wallet']

    fieldsets = (
        ('关联', {'fields': ('wallet', 'merchant_id', 'related_order_no',
                           'related_type', 'related_id', 'batch_no')}),
        ('变动', {'fields': ('action', 'amount', 'balance_after',
                           'pending_after', 'freeze_delta')}),
        ('状态', {'fields': ('status', 'reversed_by_tx')}),
        ('操作人', {'fields': ('operator_id', 'operator_role', 'operator_ip')}),
        ('元信息', {'fields': ('remark', 'idempotent_key', 'created_at')}),
    )

    @admin.display(description='钱包')
    def wallet_link(self, obj):
        url = reverse('admin:wallet_merchantwallet_change', args=[obj.wallet_id])
        return format_html('<a href="{}">#{}</a>', url, obj.wallet_id)

    @admin.display(description='金额', ordering='amount')
    def amount_colored(self, obj):
        color = 'green' if obj.amount > 0 else ('red' if obj.amount < 0 else 'gray')
        sign = '+' if obj.amount > 0 else ''
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}{}</span>',
            color, sign, obj.amount,
        )


# ════════════════════════════════════════════════════════════════
#                        商户提现申请
# ════════════════════════════════════════════════════════════════

@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(NoDeleteMixin, admin.ModelAdmin):
    """
    提现只读查看，所有状态流转必须走 API（审核/拒绝/打款等）。
    admin 只能修改风险标签、管理员备注这类辅助字段。
    """

    list_display = [
        'withdraw_no', 'merchant_name_display', 'amount', 'fee', 'actual_amount',
        'status_colored', 'risk_level_colored', 'payment_channel',
        'retry_count', 'applicant_name', 'created_at',
    ]
    list_filter = ['status', 'risk_level', 'payment_channel', 'created_at']
    search_fields = ['withdraw_no', 'merchant__name', 'transfer_no',
                     'bank_account_no', 'alipay_account', 'wechat_openid',
                     'applicant_name', 'batch_no']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    list_per_page = 30
    list_select_related = ['merchant', 'wallet']

    # 允许管理员改的只有这些
    editable_fields = ['risk_level', 'risk_tags', 'admin_remark']

    fieldsets = (
        ('单据', {
            'fields': ('withdraw_no', 'merchant', 'wallet',
                       'applicant_id', 'applicant_name', 'created_at', 'updated_at')
        }),
        ('金额', {
            'fields': ('amount', 'fee', 'channel_fee', 'actual_amount',
                       'balance_snapshot', 'available_snapshot')
        }),
        ('收款信息', {
            'fields': ('bank_name', 'bank_account_name', 'bank_account_no',
                       'alipay_account', 'wechat_openid'),
            'classes': ('collapse',),
        }),
        ('状态流转（只读，请走 API）', {
            'fields': ('status', 'state_version',
                       'reviewed_by', 'reviewer_name',
                       'reviewed_at', 'approved_at', 'rejected_at', 'reject_reason'),
        }),
        ('打款', {
            'fields': ('payment_channel', 'transfer_no',
                       'transferred_at', 'completed_at',
                       'fail_reason', 'channel_response',
                       'retry_count', 'last_retry_at'),
        }),
        ('风控（可编辑）', {
            'fields': ('risk_level', 'risk_tags', 'admin_remark'),
        }),
        ('其它', {
            'fields': ('remark', 'ip_address', 'batch_no'),
            'classes': ('collapse',),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        """除 editable_fields 外，其他全部只读"""
        all_fields = [f.name for f in self.model._meta.fields]
        return [f for f in all_fields if f not in self.editable_fields]

    def has_add_permission(self, request):
        # 提现必须由商户通过 API 发起
        return False

    @admin.display(description='商家', ordering='merchant__name')
    def merchant_name_display(self, obj):
        return getattr(obj.merchant, 'name', f'#{obj.merchant_id}')

    @admin.display(description='状态', ordering='status')
    def status_colored(self, obj):
        colors = {
            'pending':    '#666',
            'approved':   '#1890ff',
            'processing': '#faad14',
            'success':    'green',
            'rejected':   'red',
            'failed':     'red',
            'cancelled':  '#999',
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'), obj.get_status_display()
        )

    @admin.display(description='风险', ordering='risk_level')
    def risk_level_colored(self, obj):
        colors = {'low': 'green', 'medium': 'orange', 'high': 'red'}
        return format_html(
            '<span style="color: {};">{}</span>',
            colors.get(obj.risk_level, 'black'), obj.get_risk_level_display()
        )


# ════════════════════════════════════════════════════════════════
#                        商户结算配置（可编辑）
# ════════════════════════════════════════════════════════════════

@admin.register(MerchantSettlementConfig)
class MerchantSettlementConfigAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'merchant', 'settlement_cycle',
        'min_withdraw_amount', 'max_withdraw_per_day', 'max_withdraw_times_per_day',
        'withdraw_fee_rate', 'withdraw_fee_fixed',
        'auto_withdraw', 'updated_at',
    ]
    list_filter = ['settlement_cycle', 'auto_withdraw']
    search_fields = ['merchant__name', 'merchant__id']
    ordering = ['-updated_at']
    readonly_fields = ['created_at', 'updated_at']
    autocomplete_fields = ['merchant']

    fieldsets = (
        ('商家', {'fields': ('merchant',)}),
        ('结算', {'fields': ('settlement_cycle',)}),
        ('提现限额', {
            'fields': ('min_withdraw_amount', 'max_withdraw_per_day',
                       'max_withdraw_times_per_day')
        }),
        ('手续费', {'fields': ('withdraw_fee_rate', 'withdraw_fee_fixed')}),
        ('自动提现', {'fields': ('auto_withdraw', 'auto_withdraw_threshold')}),
        ('元信息', {'fields': ('created_at', 'updated_at')}),
    )


# ════════════════════════════════════════════════════════════════
#           Admin 站点个性化（可选）
# ════════════════════════════════════════════════════════════════

admin.site.site_header = '运营后台'
admin.site.site_title  = '运营后台'
admin.site.index_title = '管理首页'