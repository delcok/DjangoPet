# -*- coding: utf-8 -*-
"""
钱包模块序列化器
分三个域:用户端 / 商户端 / 管理端

⚠️ 币种约束:
  - 用户钱包:只能是 积分(points) / 金币(gold)
  - 商户钱包:只能是 现金(cash) / 金币(gold)
  Currency enum 三种值共存,但 serializer 层按域限制 choices,防止越权。
"""
from decimal import Decimal
from rest_framework import serializers

from .models import (
    UserWallet, WalletTransaction, WalletStatusLog,
    MerchantWallet, MerchantWalletTransaction,
    WithdrawalRequest, MerchantSettlementConfig,
    Currency,
)


# ════════════════════════════════════════════════════════════════
# 限定 choices(防止用户调现金、商户调积分这种越权)
# ════════════════════════════════════════════════════════════════

USER_CURRENCY_CHOICES = [
    (Currency.POINTS, '积分'),
    (Currency.GOLD,   '金币'),
]

MERCHANT_CURRENCY_CHOICES = [
    (Currency.CASH, '现金'),
    (Currency.GOLD, '金币'),
]


# ════════════════════════════════════════════════════════════════
#                        用户端
# ════════════════════════════════════════════════════════════════

class UserWalletSerializer(serializers.ModelSerializer):
    """用户钱包详情(自己看)"""
    points_available = serializers.IntegerField(read_only=True)
    gold_available   = serializers.IntegerField(read_only=True)
    status_display   = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = UserWallet
        fields = [
            'id', 'status', 'status_display',
            'points_balance', 'points_frozen', 'points_available',
            'points_total_earned', 'points_total_spent', 'points_total_expired',
            'gold_balance', 'gold_frozen', 'gold_available',
            'gold_total_earned', 'gold_total_spent', 'gold_total_expired',
            'last_transaction_at', 'updated_at',
        ]
        read_only_fields = fields


class UserWalletTransactionSerializer(serializers.ModelSerializer):
    """用户流水(自己看,隐藏敏感字段)"""
    action_display   = serializers.CharField(source='get_action_display', read_only=True)
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)
    status_display   = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'currency', 'currency_display',
            'action', 'action_display',
            'amount', 'balance_after',
            'status', 'status_display',
            'related_type', 'related_id',
            'remark', 'expire_at', 'created_at',
        ]
        read_only_fields = fields


class ExpiringPointsSerializer(serializers.Serializer):
    """即将过期的积分(按到期日聚合)"""
    expire_at = serializers.DateTimeField()
    amount = serializers.IntegerField()


# ════════════════════════════════════════════════════════════════
#                        商户端
# ════════════════════════════════════════════════════════════════

class MerchantWalletSerializer(serializers.ModelSerializer):
    """商户钱包详情(同时含现金 + 金币)"""
    available_balance = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    gold_available    = serializers.IntegerField(read_only=True)
    status_display    = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MerchantWallet
        fields = [
            'id', 'status', 'status_display',
            # ─── 现金 ───
            'balance', 'frozen_amount', 'available_balance', 'pending_settlement',
            'total_income', 'total_commission', 'total_refunded',
            'total_withdrawn', 'total_withdraw_fee',
            # ─── 金币 ───
            'gold_balance', 'gold_frozen', 'gold_available',
            'gold_total_earned', 'gold_total_spent', 'gold_total_expired',
            # ─── 元信息 ───
            'last_transaction_at', 'updated_at',
        ]
        read_only_fields = fields


class MerchantWalletTransactionSerializer(serializers.ModelSerializer):
    """商户流水(自己看)"""
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)
    action_display   = serializers.CharField(source='get_action_display', read_only=True)
    status_display   = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MerchantWalletTransaction
        fields = [
            'id',
            'currency', 'currency_display',
            'action', 'action_display',
            'amount', 'balance_after', 'pending_after', 'freeze_delta',
            'status', 'status_display',
            'related_order_no', 'related_type', 'related_id',
            'batch_no', 'remark', 'created_at',
        ]
        read_only_fields = fields


class MerchantSettlementConfigSerializer(serializers.ModelSerializer):
    settlement_cycle_display = serializers.CharField(source='get_settlement_cycle_display', read_only=True)

    class Meta:
        model = MerchantSettlementConfig
        fields = [
            'settlement_cycle', 'settlement_cycle_display',
            'min_withdraw_amount', 'max_withdraw_per_day', 'max_withdraw_times_per_day',
            'withdraw_fee_rate', 'withdraw_fee_fixed',
            'auto_withdraw', 'auto_withdraw_threshold',
        ]
        read_only_fields = fields


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    """提现申请(商户视角)"""
    status_display          = serializers.CharField(source='get_status_display', read_only=True)
    payment_channel_display = serializers.CharField(source='get_payment_channel_display', read_only=True)
    risk_level_display      = serializers.CharField(source='get_risk_level_display', read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            'id', 'withdraw_no',
            'amount', 'fee', 'channel_fee', 'actual_amount',
            'balance_snapshot', 'available_snapshot',
            'bank_name', 'bank_account_name', 'bank_account_no',
            'alipay_account', 'wechat_openid',
            'status', 'status_display',
            'payment_channel', 'payment_channel_display',
            'transfer_no', 'transferred_at', 'completed_at',
            'fail_reason', 'reject_reason',
            'risk_level', 'risk_level_display',
            'retry_count', 'remark',
            'created_at', 'reviewed_at', 'approved_at',
        ]
        read_only_fields = [f for f in fields if f not in ('remark',)]


class WithdrawalCreateSerializer(serializers.Serializer):
    """商户发起提现(只能提现金,金币不参与提现)"""
    AMOUNT_MIN = Decimal('0.01')

    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=AMOUNT_MIN)
    payment_channel = serializers.ChoiceField(choices=WithdrawalRequest.PaymentChannel.choices)

    # 收款信息(根据 channel 校验)
    bank_name         = serializers.CharField(max_length=100, required=False, allow_blank=True)
    bank_account_name = serializers.CharField(max_length=50,  required=False, allow_blank=True)
    bank_account_no   = serializers.CharField(max_length=30,  required=False, allow_blank=True)
    alipay_account    = serializers.CharField(max_length=100, required=False, allow_blank=True)
    wechat_openid     = serializers.CharField(max_length=100, required=False, allow_blank=True)

    remark       = serializers.CharField(max_length=200, required=False, allow_blank=True)
    pay_password = serializers.CharField(max_length=128, required=False, allow_blank=True,
                                         write_only=True, help_text='提现密码(若钱包设置了)')

    def validate(self, attrs):
        ch = attrs['payment_channel']
        PC = WithdrawalRequest.PaymentChannel
        # 银行卡:不在这里强制要求填卡号(view 层会从商户档案补全)
        if ch == PC.ALIPAY and not attrs.get('alipay_account'):
            raise serializers.ValidationError('支付宝代付需要填写 alipay_account')
        if ch == PC.WECHAT and not attrs.get('wechat_openid'):
            raise serializers.ValidationError('微信代付需要填写 wechat_openid')
        return attrs


class WithdrawalCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


# ════════════════════════════════════════════════════════════════
#                        管理端 - 用户钱包(币种限定 积分/金币)
# ════════════════════════════════════════════════════════════════

class AdminUserWalletSerializer(serializers.ModelSerializer):
    """管理员看用户钱包(带用户信息)"""
    user_id          = serializers.IntegerField(read_only=True)
    user_mobile      = serializers.CharField(source='user.mobile',   read_only=True, default='')
    user_nickname    = serializers.CharField(source='user.nickname', read_only=True, default='')
    points_available = serializers.IntegerField(read_only=True)
    gold_available   = serializers.IntegerField(read_only=True)
    status_display   = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = UserWallet
        fields = [
            'id', 'user_id', 'user_mobile', 'user_nickname',
            'status', 'status_display', 'status_reason',
            'points_balance', 'points_frozen', 'points_available',
            'points_total_earned', 'points_total_spent', 'points_total_expired',
            'gold_balance', 'gold_frozen', 'gold_available',
            'gold_total_earned', 'gold_total_spent', 'gold_total_expired',
            'version', 'last_transaction_at', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class AdminUserWalletTransactionSerializer(serializers.ModelSerializer):
    """管理员看用户流水(全字段)"""
    action_display        = serializers.CharField(source='get_action_display',        read_only=True)
    currency_display      = serializers.CharField(source='get_currency_display',      read_only=True)
    status_display        = serializers.CharField(source='get_status_display',        read_only=True)
    operator_role_display = serializers.CharField(source='get_operator_role_display', read_only=True)

    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'wallet', 'user_id',
            'currency', 'currency_display',
            'action', 'action_display',
            'amount', 'balance_after', 'remaining_amount', 'freeze_delta',
            'status', 'status_display', 'reversed_by_tx',
            'operator_id', 'operator_role', 'operator_role_display', 'operator_ip',
            'related_type', 'related_id', 'batch_no', 'remark',
            'idempotent_key', 'expire_at', 'created_at',
        ]
        read_only_fields = fields


class AdminWalletAdjustSerializer(serializers.Serializer):
    """
    管理员调整用户积分/金币
    🔒 只能选积分或金币,不允许选现金
    """
    currency = serializers.ChoiceField(choices=USER_CURRENCY_CHOICES)
    amount = serializers.IntegerField(help_text='正数=发放,负数=扣除')
    remark = serializers.CharField(max_length=200)
    expire_at = serializers.DateTimeField(
        required=False, allow_null=True,
        help_text='仅积分有效,金币忽略',
    )
    batch_no = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')

    def validate_amount(self, value):
        if value == 0:
            raise serializers.ValidationError('调整数量不能为 0')
        return value


class AdminWalletFreezeSerializer(serializers.Serializer):
    """管理员冻结/解冻用户余额(只能积分或金币)"""
    currency = serializers.ChoiceField(choices=USER_CURRENCY_CHOICES)
    amount   = serializers.IntegerField(min_value=1)
    reason   = serializers.CharField(max_length=200)


class AdminWalletStatusChangeSerializer(serializers.Serializer):
    """修改钱包状态"""
    status = serializers.ChoiceField(choices=UserWallet.Status.choices)
    reason = serializers.CharField(max_length=200)


class AdminTransactionReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)


class WalletStatusLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletStatusLog
        fields = ['id', 'old_status', 'new_status', 'reason',
                  'operator_id', 'operator_role', 'operator_ip', 'created_at']
        read_only_fields = fields


# ════════════════════════════════════════════════════════════════
#                        管理端 - 商户钱包(币种限定 现金/金币)
# ════════════════════════════════════════════════════════════════

class AdminMerchantWalletSerializer(serializers.ModelSerializer):
    """管理员看商户钱包(含现金 + 金币)"""
    merchant_id       = serializers.IntegerField(read_only=True)
    merchant_name     = serializers.CharField(source='merchant.name', read_only=True, default='')
    available_balance = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    gold_available    = serializers.IntegerField(read_only=True)
    status_display    = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MerchantWallet
        fields = [
            'id', 'merchant_id', 'merchant_name',
            'status', 'status_display', 'status_reason',
            # ─── 现金 ───
            'balance', 'frozen_amount', 'available_balance', 'pending_settlement',
            'total_income', 'total_commission', 'total_refunded',
            'total_withdrawn', 'total_withdraw_fee',
            # ─── 金币 ───
            'gold_balance', 'gold_frozen', 'gold_available',
            'gold_total_earned', 'gold_total_spent', 'gold_total_expired',
            # ─── 元信息 ───
            'version', 'last_transaction_at', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class AdminMerchantWalletTransactionSerializer(serializers.ModelSerializer):
    """管理员看商户流水(含 currency)"""
    currency_display      = serializers.CharField(source='get_currency_display',      read_only=True)
    action_display        = serializers.CharField(source='get_action_display',        read_only=True)
    status_display        = serializers.CharField(source='get_status_display',        read_only=True)
    operator_role_display = serializers.CharField(source='get_operator_role_display', read_only=True)

    class Meta:
        model = MerchantWalletTransaction
        fields = [
            'id', 'wallet', 'merchant_id',
            'currency', 'currency_display',
            'action', 'action_display',
            'amount', 'balance_after', 'pending_after', 'freeze_delta',
            'status', 'status_display', 'reversed_by_tx',
            'operator_id', 'operator_role', 'operator_role_display', 'operator_ip',
            'related_order_no', 'related_type', 'related_id',
            'batch_no', 'remark', 'idempotent_key', 'created_at',
        ]
        read_only_fields = fields


class AdminMerchantAdjustSerializer(serializers.Serializer):
    """
    管理员对商户钱包人工调整(调增/调减)
    🔒 只能选现金或金币,不允许选积分
    """
    currency = serializers.ChoiceField(choices=MERCHANT_CURRENCY_CHOICES, default=Currency.CASH)
    amount   = serializers.DecimalField(max_digits=14, decimal_places=2,
                                        help_text='正数=调增,负数=调减;金币必须为整数')
    remark   = serializers.CharField(max_length=200)
    batch_no = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if attrs['amount'] == 0:
            raise serializers.ValidationError({'amount': '调整金额不能为 0'})
        # 金币只能是整数
        if attrs['currency'] == Currency.GOLD:
            if attrs['amount'] != attrs['amount'].to_integral_value():
                raise serializers.ValidationError({'amount': '金币必须是整数'})
        return attrs


class AdminMerchantFreezeSerializer(serializers.Serializer):
    """管理员冻结/解冻商户钱包(现金或金币)"""
    currency = serializers.ChoiceField(choices=MERCHANT_CURRENCY_CHOICES, default=Currency.CASH)
    amount   = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    reason   = serializers.CharField(max_length=200)

    def validate(self, attrs):
        if attrs['currency'] == Currency.GOLD:
            if attrs['amount'] != attrs['amount'].to_integral_value():
                raise serializers.ValidationError({'amount': '金币必须是整数'})
        return attrs


class AdminMerchantStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MerchantWallet.Status.choices)
    reason = serializers.CharField(max_length=200)


# ════════════════════════════════════════════════════════════════
#                        管理端 - 提现审核
# ════════════════════════════════════════════════════════════════

class AdminWithdrawalSerializer(serializers.ModelSerializer):
    """管理员看提现(全字段)"""
    merchant_name           = serializers.CharField(source='merchant.name', read_only=True, default='')
    status_display          = serializers.CharField(source='get_status_display',          read_only=True)
    payment_channel_display = serializers.CharField(source='get_payment_channel_display', read_only=True)
    risk_level_display      = serializers.CharField(source='get_risk_level_display',      read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            'id', 'withdraw_no', 'merchant', 'merchant_name', 'wallet',
            'applicant_id', 'applicant_name',
            'amount', 'fee', 'channel_fee', 'actual_amount',
            'balance_snapshot', 'available_snapshot',
            'bank_name', 'bank_account_name', 'bank_account_no',
            'alipay_account', 'wechat_openid',
            'status', 'status_display', 'state_version',
            'reviewed_by', 'reviewer_name', 'reviewed_at',
            'approved_at', 'rejected_at', 'reject_reason',
            'payment_channel', 'payment_channel_display',
            'transfer_no', 'transferred_at', 'completed_at',
            'fail_reason', 'channel_response',
            'retry_count', 'last_retry_at',
            'risk_level', 'risk_level_display', 'risk_tags',
            'remark', 'admin_remark',
            'ip_address', 'batch_no',
            'created_at', 'updated_at',
        ]
        read_only_fields = [f for f in fields if f not in ('admin_remark', 'risk_level', 'risk_tags')]


class AdminWithdrawalApproveSerializer(serializers.Serializer):
    admin_remark = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class AdminWithdrawalRejectSerializer(serializers.Serializer):
    reason       = serializers.CharField(max_length=200)
    admin_remark = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


class AdminWithdrawalProcessingSerializer(serializers.Serializer):
    payment_channel = serializers.ChoiceField(
        choices=WithdrawalRequest.PaymentChannel.choices,
        required=False, allow_null=True,
    )


class AdminWithdrawalSuccessSerializer(serializers.Serializer):
    transfer_no      = serializers.CharField(max_length=128)
    channel_response = serializers.JSONField(required=False, allow_null=True)


class AdminWithdrawalFailedSerializer(serializers.Serializer):
    reason           = serializers.CharField(max_length=200)
    channel_response = serializers.JSONField(required=False, allow_null=True)