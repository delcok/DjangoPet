# -*- coding: utf-8 -*-
# payment/serializers.py
"""
支付/退款序列化器

用户端：
  - PaymentOrderListSerializer / PaymentOrderDetailSerializer
  - CreatePaymentSerializer
  - QueryPaymentSerializer
  - RefundListSerializer / RefundDetailSerializer

商家/管理端：
  - ApproveRefundSerializer    审批通过 → 创建 PaymentRefund + 调微信退款
  - RejectRefundSerializer     审批拒绝 → 把订单状态从 REFUNDING 撤回
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import PaymentOrder, PaymentRefund, generate_payment_no


# ══════════════════════════════════════════════════════════════
# 工具：根据 order_type + order_no 找业务订单
# ══════════════════════════════════════════════════════════════

def get_business_order(order_no, order_type):
    """
    懒导入避免循环依赖。返回 (order, OrderModel) 元组。
    业务订单在 bill 应用下：bill.models.ProductOrder / ServiceOrder
    """
    if order_type == 'product':
        from bill.models import ProductOrder
        try:
            return ProductOrder.objects.get(order_no=order_no), ProductOrder
        except ProductOrder.DoesNotExist:
            return None, ProductOrder
    elif order_type == 'service':
        from bill.models import ServiceOrder
        try:
            return ServiceOrder.objects.get(order_no=order_no), ServiceOrder
        except ServiceOrder.DoesNotExist:
            return None, ServiceOrder
    elif order_type == 'recharge':
        # ★ 充值订单:WalletRecharge 用 recharge_no 作为查询键
        from wallet.models import WalletRecharge
        try:
            return WalletRecharge.objects.get(recharge_no=order_no), WalletRecharge
        except WalletRecharge.DoesNotExist:
            return None, WalletRecharge
    return None, None


# ══════════════════════════════════════════════════════════════
# 支付单 — 列表 / 详情
# ══════════════════════════════════════════════════════════════

class PaymentOrderListSerializer(serializers.ModelSerializer):
    channel_display    = serializers.CharField(source='get_channel_display',    read_only=True)
    status_display     = serializers.CharField(source='get_status_display',     read_only=True)
    order_type_display = serializers.CharField(source='get_order_type_display', read_only=True)

    class Meta:
        model = PaymentOrder
        fields = [
            'id', 'payment_no', 'out_trade_no',
            'order_no', 'order_type', 'order_type_display',
            'channel', 'channel_display',
            'amount', 'status', 'status_display',
            'created_at', 'paid_at',
        ]


class PaymentOrderDetailSerializer(serializers.ModelSerializer):
    channel_display    = serializers.CharField(source='get_channel_display',    read_only=True)
    status_display     = serializers.CharField(source='get_status_display',     read_only=True)
    order_type_display = serializers.CharField(source='get_order_type_display', read_only=True)

    class Meta:
        model = PaymentOrder
        fields = [
            'id', 'payment_no', 'out_trade_no', 'channel_trade_no',
            'order_no', 'order_type', 'order_type_display',
            'user_id', 'merchant_id',
            'channel', 'channel_display',
            'amount', 'amount_in_cents',
            'status', 'status_display',
            'pay_params', 'pay_platform', 'pay_ip',
            'paid_at', 'closed_at', 'expire_at',
            'created_at', 'updated_at',
        ]


# ══════════════════════════════════════════════════════════════
# 创建支付
# ══════════════════════════════════════════════════════════════

class CreatePaymentSerializer(serializers.Serializer):
    """
    入参：
      order_no     业务订单号
      order_type   product / service
      channel      wechat_mini / wechat_app / wechat_h5 / alipay / balance
      openid       微信小程序/JSAPI 必填
      pay_platform 发起平台标识（可选）
    """
    order_no = serializers.CharField(max_length=32)
    order_type = serializers.ChoiceField(
        choices=[('product', '商品订单'), ('service', '服务订单'),('recharge', '充值订单')],
    )
    channel = serializers.ChoiceField(choices=PaymentOrder.CHANNEL_CHOICES)
    openid = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default='',
    )
    pay_platform = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default='',
    )

    def validate(self, attrs):
        order_no   = attrs['order_no']
        order_type = attrs['order_type']
        user       = self.context['request'].user

        # 1) 找业务订单
        order, OrderModel = get_business_order(order_no, order_type)
        if order is None:
            raise serializers.ValidationError({'order_no': '业务订单不存在'})

        # 2) 归属校验
        if order.user_id != user.id:
            raise serializers.ValidationError({'order_no': '无权操作此订单'})

        # 3) 状态校验：必须是待支付
        if order.status != OrderModel.Status.PENDING_PAYMENT:
            raise serializers.ValidationError(
                {'order_no': f'订单状态为 {order.get_status_display()}，无法发起支付'}
            )

        # 4) 微信渠道必传 openid（小程序/H5 都用 JSAPI）
        if attrs['channel'] in ('wechat_mini', 'wechat_h5') and not attrs.get('openid'):
            raise serializers.ValidationError({'openid': '微信支付必须传 openid'})

        # 5) 已存在有效的待支付支付单 → 复用
        existing = (PaymentOrder.objects
                    .filter(order_no=order_no, status='pending')
                    .order_by('-created_at')
                    .first())
        if existing and existing.is_payable:
            attrs['_existing'] = existing

        attrs['_order'] = order
        return attrs

    def create(self, validated_data):
        # 命中可复用支付单
        existing = validated_data.get('_existing')
        if existing:
            return existing

        order   = validated_data['_order']
        user    = self.context['request'].user
        request = self.context.get('request')

        pay_ip = None
        if request is not None:
            xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
            pay_ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

        # payment_no 与 out_trade_no 保持一致
        payment_no = generate_payment_no()
        return PaymentOrder.objects.create(
            payment_no=payment_no,
            out_trade_no=payment_no,
            order_no=order.order_no,
            order_type=validated_data['order_type'],
            user_id=user.id,
            merchant_id=getattr(order, 'merchant_id', None),
            channel=validated_data['channel'],
            amount=order.pay_amount,
            status='pending',
            pay_platform=validated_data.get('pay_platform', ''),
            pay_ip=pay_ip,
            expire_at=timezone.now() + timedelta(minutes=15),
        )


# ══════════════════════════════════════════════════════════════
# 查询支付
# ══════════════════════════════════════════════════════════════

class QueryPaymentSerializer(serializers.Serializer):
    out_trade_no = serializers.CharField(max_length=64)

    def validate_out_trade_no(self, value):
        user = self.context['request'].user
        try:
            payment = PaymentOrder.objects.get(out_trade_no=value)
        except PaymentOrder.DoesNotExist:
            raise serializers.ValidationError('支付单不存在')
        if payment.user_id != user.id:
            raise serializers.ValidationError('无权查询此支付单')
        self.payment = payment
        return value


# ══════════════════════════════════════════════════════════════
# 退款单 — 列表 / 详情
# ══════════════════════════════════════════════════════════════

class RefundListSerializer(serializers.ModelSerializer):
    status_display  = serializers.CharField(source='get_status_display',  read_only=True)
    reason_display  = serializers.CharField(source='get_reason_display',  read_only=True)
    payment_no      = serializers.CharField(source='payment_order.payment_no', read_only=True)
    order_type      = serializers.CharField(source='payment_order.order_type', read_only=True)

    class Meta:
        model = PaymentRefund
        fields = [
            'id', 'refund_no', 'channel_refund_no',
            'payment_no', 'order_no', 'order_type', 'user_id',
            'refund_amount', 'reason', 'reason_display',
            'status', 'status_display',
            'operator_type', 'operator_id',
            'refunded_at', 'created_at',
        ]


class RefundDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    payment_no     = serializers.CharField(source='payment_order.payment_no', read_only=True)
    order_type     = serializers.CharField(source='payment_order.order_type', read_only=True)
    merchant_id    = serializers.IntegerField(source='payment_order.merchant_id', read_only=True)

    class Meta:
        model = PaymentRefund
        fields = [
            'id', 'refund_no', 'channel_refund_no',
            'payment_order', 'payment_no',
            'order_no', 'order_type', 'user_id', 'merchant_id',
            'refund_amount', 'refund_amount_in_cents',
            'reason', 'reason_display', 'reason_detail',
            'status', 'status_display',
            'operator_type', 'operator_id',
            'callback_raw',
            'refunded_at', 'created_at', 'updated_at',
        ]


# ══════════════════════════════════════════════════════════════
# 退款审批 —— 同意
# ══════════════════════════════════════════════════════════════

class ApproveRefundSerializer(serializers.Serializer):
    """
    商家/管理员审批通过：创建 PaymentRefund 并发起微信退款。

    入参：
      order_no       业务订单号
      order_type     product / service
      refund_amount  退款金额（不传则全额退）
      reason         退款原因枚举（reason_choices）
      reason_detail  原因详情（可选）

    校验：
      - 订单状态必须是 REFUNDING
      - 找到原 PaymentOrder（status=paid 且有 channel_trade_no）
      - 退款金额 + 历史成功退款 ≤ 原支付金额
    """
    order_no = serializers.CharField(max_length=32)
    order_type = serializers.ChoiceField(
        choices=[('product', '商品订单'), ('service', '服务订单'),
            ('recharge', '充值订单')],
    )
    refund_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, min_value=Decimal('0.01'),
    )
    reason = serializers.ChoiceField(
        choices=PaymentRefund.REASON_CHOICES, default='user_cancel',
    )
    reason_detail = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )

    def __init__(self, *args, **kwargs):
        # operator_type 由调用方传：'merchant' / 'admin'
        self.operator_type = kwargs.pop('operator_type', '')
        super().__init__(*args, **kwargs)

    def validate(self, attrs):
        order, OrderModel = get_business_order(attrs['order_no'], attrs['order_type'])
        if order is None:
            raise serializers.ValidationError({'order_no': '业务订单不存在'})

        # 商家权限校验：只能审批本店订单
        request = self.context.get('request')
        merchant_id_filter = self.context.get('merchant_id_filter')
        if merchant_id_filter is not None:
            if getattr(order, 'merchant_id', None) != merchant_id_filter:
                raise serializers.ValidationError({'order_no': '无权操作此订单'})

        # 订单必须是退款中
        if order.status != OrderModel.Status.REFUNDING:
            raise serializers.ValidationError(
                {'order_no': f'订单状态为 {order.get_status_display()}，未处于退款中'}
            )

        # 找原支付单：必须 paid，且拿到了微信交易号
        original = (PaymentOrder.objects
                    .filter(order_no=order.order_no, status='paid')
                    .order_by('-created_at')
                    .first())
        if original is None:
            raise serializers.ValidationError({'order_no': '未找到已支付的支付单'})
        if not original.channel_trade_no:
            raise serializers.ValidationError({'order_no': '原支付单缺少微信交易号，无法退款'})

        # 校验退款金额
        refund_amount = attrs.get('refund_amount') or original.amount

        # 累计已成功退款金额（含进行中）
        refunded_sum = (PaymentRefund.objects
                        .filter(payment_order=original,
                                status__in=['pending', 'success'])
                        .aggregate(total=Sum('refund_amount'))['total'] or Decimal('0'))
        remaining = original.amount - refunded_sum
        if refund_amount > remaining:
            raise serializers.ValidationError(
                {'refund_amount': f'剩余可退金额 ¥{remaining}，本次退款 ¥{refund_amount} 超出'}
            )

        attrs['refund_amount'] = refund_amount
        attrs['_order']        = order
        attrs['_OrderModel']   = OrderModel
        attrs['_original']     = original
        return attrs


# ══════════════════════════════════════════════════════════════
# 退款审批 —— 拒绝
# ══════════════════════════════════════════════════════════════

class RejectRefundSerializer(serializers.Serializer):
    """
    商家/管理员审批拒绝：把订单状态从 REFUNDING 撤回。

    入参：
      order_no
      order_type
      reject_reason  拒绝原因（必填）
      revert_status  撤回到的状态（默认 PAID；可选 SHIPPED/RECEIVED 等）
    """
    order_no = serializers.CharField(max_length=32)
    order_type = serializers.ChoiceField(
        choices=[('product', '商品订单'), ('service', '服务订单'),
            ('recharge', '充值订单')],
    )
    reject_reason = serializers.CharField(max_length=200)
    revert_status = serializers.CharField(max_length=30, required=False, default='paid')

    def validate(self, attrs):
        order, OrderModel = get_business_order(attrs['order_no'], attrs['order_type'])
        if order is None:
            raise serializers.ValidationError({'order_no': '业务订单不存在'})

        # 商家权限：只能审批本店订单
        merchant_id_filter = self.context.get('merchant_id_filter')
        if merchant_id_filter is not None:
            if getattr(order, 'merchant_id', None) != merchant_id_filter:
                raise serializers.ValidationError({'order_no': '无权操作此订单'})

        if order.status != OrderModel.Status.REFUNDING:
            raise serializers.ValidationError(
                {'order_no': f'订单状态为 {order.get_status_display()}，未处于退款中'}
            )

        # 校验目标状态合法
        valid_statuses = {c[0] for c in OrderModel.Status.choices}
        if attrs['revert_status'] not in valid_statuses:
            raise serializers.ValidationError(
                {'revert_status': f'非法状态，可选: {sorted(valid_statuses)}'}
            )

        attrs['_order']      = order
        attrs['_OrderModel'] = OrderModel
        return attrs