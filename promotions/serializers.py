# -*- coding: utf-8 -*-
# promotions/serializers.py

from decimal import Decimal
from rest_framework import serializers
from .models import (
    PaymentActivity, MerchantActivityEnrollment,
    ActivityUserGrant, ActivityMerchantEarn,
)


# ══════════════════════════════════════════════════════════════
# 工具:阶梯校验
# ══════════════════════════════════════════════════════════════

def _validate_tiers(value, field_name='tiers'):
    """阶梯结构校验:[{threshold, reward_coins}, ...]"""
    if not isinstance(value, list):
        raise serializers.ValidationError(f'{field_name} 必须是数组')
    cleaned = []
    for i, t in enumerate(value):
        if not isinstance(t, dict):
            raise serializers.ValidationError(f'{field_name}[{i}] 必须是对象')
        try:
            th = Decimal(str(t.get('threshold', 0)))
            rc = int(t.get('reward_coins', 0))
        except Exception:
            raise serializers.ValidationError(f'{field_name}[{i}] 阶梯字段格式错误')
        if th < 0 or rc < 0:
            raise serializers.ValidationError(f'{field_name}[{i}] 阶梯值必须 ≥ 0')
        cleaned.append({'threshold': float(th), 'reward_coins': rc})
    return cleaned


# ══════════════════════════════════════════════════════════════
# 管理端 - 活动 CRUD
# ══════════════════════════════════════════════════════════════

class PaymentActivitySerializer(serializers.ModelSerializer):
    activity_type_display = serializers.CharField(source='get_activity_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    enrollment_mode_display = serializers.CharField(source='get_enrollment_mode_display', read_only=True)
    is_runnable = serializers.SerializerMethodField()
    pending_enrollment_count = serializers.SerializerMethodField()

    def get_pending_enrollment_count(self, obj):
        return obj.enrollments.filter(
            status=MerchantActivityEnrollment.Status.PENDING,
        ).count()

    class Meta:
        model = PaymentActivity
        fields = [
            'id', 'name', 'description', 'pending_enrollment_count',
            'activity_type', 'activity_type_display',

            'user_reward_enabled',
            'user_reward_type',
            'user_reward_value',
            'user_reward_tiers',

            'merchant_reward_enabled',
            'merchant_reward_type',
            'merchant_reward_value',
            'merchant_reward_tiers',

            'start_time', 'end_time',
            'apply_order_types',

            'enrollment_mode', 'enrollment_mode_display', 'enrollment_audit',

            'per_user_limit', 'total_budget_coins',

            'status', 'status_display', 'is_runnable',
            'user_granted_count', 'user_granted_coins',
            'merchant_earned_count', 'merchant_earned_coins',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'user_granted_count', 'user_granted_coins',
            'merchant_earned_count', 'merchant_earned_coins',
            'created_at', 'updated_at',
        ]

    def get_is_runnable(self, obj):
        return obj.is_runnable()

    def validate_user_reward_tiers(self, value):
        return _validate_tiers(value, 'user_reward_tiers')

    def validate_merchant_reward_tiers(self, value):
        return _validate_tiers(value, 'merchant_reward_tiers')

    def validate_apply_order_types(self, value):
        """订单类型只能是 product / service"""
        if not value:
            return value
        if not isinstance(value, list):
            raise serializers.ValidationError('apply_order_types 必须是数组')
        valid = {'product', 'service'}
        for v in value:
            if v not in valid:
                raise serializers.ValidationError(
                    f'非法订单类型 {v},可选: {sorted(valid)}'
                )
        return value

    def validate(self, attrs):
        activity_type = attrs.get('activity_type') or getattr(self.instance, 'activity_type', None)

        # ── 用户奖励校验 ──
        if attrs.get('user_reward_enabled'):
            utype = attrs.get('user_reward_type')
            if utype == PaymentActivity.RewardType.TIERED and not attrs.get('user_reward_tiers'):
                raise serializers.ValidationError(
                    {'user_reward_tiers': '阶梯类型必须配置阶梯规则'}
                )
            if utype in (PaymentActivity.RewardType.FIXED, PaymentActivity.RewardType.PERCENT):
                val = Decimal(str(attrs.get('user_reward_value', 0)))
                if val <= 0:
                    raise serializers.ValidationError(
                        {'user_reward_value': 'fixed / percent 类型必须填写大于 0 的奖励数值'}
                    )
                if utype == PaymentActivity.RewardType.PERCENT and val > 100:
                    raise serializers.ValidationError(
                        {'user_reward_value': '百分比不能超过 100'}
                    )

        # ── 商家奖励校验 ──
        if attrs.get('merchant_reward_enabled'):
            mtype = attrs.get('merchant_reward_type')
            if mtype == PaymentActivity.RewardType.TIERED and not attrs.get('merchant_reward_tiers'):
                raise serializers.ValidationError(
                    {'merchant_reward_tiers': '阶梯类型必须配置阶梯规则'}
                )
            if mtype in (PaymentActivity.RewardType.FIXED, PaymentActivity.RewardType.PERCENT):
                val = Decimal(str(attrs.get('merchant_reward_value', 0)))
                if val <= 0:
                    raise serializers.ValidationError(
                        {'merchant_reward_value': 'fixed / percent 类型必须填写大于 0 的奖励数值'}
                    )
                if mtype == PaymentActivity.RewardType.PERCENT and val > 100:
                    raise serializers.ValidationError(
                        {'merchant_reward_value': '百分比不能超过 100'}
                    )

        # ── 充值活动:不允许商家奖励 / 不应限定订单类型 / 商家加入方式应是 ALL ──
        if activity_type == PaymentActivity.ActivityType.RECHARGE:
            if attrs.get('merchant_reward_enabled'):
                raise serializers.ValidationError(
                    {'merchant_reward_enabled': '充值类活动不支持商家奖励'}
                )
            if attrs.get('apply_order_types'):
                raise serializers.ValidationError(
                    {'apply_order_types': '充值类活动无订单类型概念,请置空'}
                )
            mode = attrs.get('enrollment_mode')
            if mode and mode != PaymentActivity.EnrollmentMode.ALL:
                raise serializers.ValidationError(
                    {'enrollment_mode': '充值类活动不涉及商家,加入方式应为 all'}
                )

        # ── 时间校验 ──
        s, e = attrs.get('start_time'), attrs.get('end_time')
        if s and e and s >= e:
            raise serializers.ValidationError({'end_time': '结束时间必须晚于开始时间'})

        return attrs


# ══════════════════════════════════════════════════════════════
# 报名记录 & 审核
# ══════════════════════════════════════════════════════════════

class MerchantActivityEnrollmentSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    activity_name = serializers.CharField(source='activity.name', read_only=True)
    activity_type = serializers.CharField(source='activity.activity_type', read_only=True)
    activity_status = serializers.CharField(source='activity.status', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MerchantActivityEnrollment
        fields = [
            'id', 'activity', 'activity_name', 'activity_type', 'activity_status',
            'merchant', 'merchant_name',
            'status', 'status_display',
            'apply_remark', 'audit_remark', 'audited_by_id', 'audited_at',
            'user_granted_count', 'user_granted_coins', 'merchant_earned_coins',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'audited_by_id', 'audited_at',
            'user_granted_count', 'user_granted_coins', 'merchant_earned_coins',
            'created_at', 'updated_at',
        ]


class EnrollmentAuditSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[('approve', '通过'), ('reject', '拒绝')])
    remark = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')


# ══════════════════════════════════════════════════════════════
# 流水记录(只读)
# ══════════════════════════════════════════════════════════════

class ActivityUserGrantSerializer(serializers.ModelSerializer):
    activity_name = serializers.CharField(source='activity.name', read_only=True)

    class Meta:
        model = ActivityUserGrant
        fields = [
            'id', 'activity', 'activity_name',
            'user_id', 'merchant_id',
            'payment_no', 'order_no',
            'trigger_amount', 'reward_coins',
            'is_revoked', 'revoked_at', 'created_at',
        ]


class ActivityMerchantEarnSerializer(serializers.ModelSerializer):
    activity_name = serializers.CharField(source='activity.name', read_only=True)
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    frozen_status_display = serializers.CharField(source='get_frozen_status_display', read_only=True)

    class Meta:
        model = ActivityMerchantEarn
        fields = [
            'id', 'activity', 'activity_name',
            'merchant', 'merchant_name',
            'order_no', 'order_type',
            'trigger_amount', 'earned_coins',
            'frozen_status', 'frozen_status_display', 'unfrozen_at',
            'is_revoked', 'revoked_at', 'created_at',
        ]


# ══════════════════════════════════════════════════════════════
# 充值相关
# ══════════════════════════════════════════════════════════════

class CreateRechargeSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal('0.01'),
    )
    channel = serializers.CharField(max_length=20, default='wechat_mini')
    openid = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')


class WalletRechargeSerializer(serializers.ModelSerializer):
    class Meta:
        from wallet.models import WalletRecharge
        model = WalletRecharge
        fields = [
            'id', 'recharge_no', 'amount',
            'face_coins', 'bonus_coins', 'activity_id',
            'status', 'paid_at', 'created_at',
        ]
        read_only_fields = fields