# -*- coding: utf-8 -*-
# bill/serializers.py
"""
订单序列化器
- 用户端: 创建、查看自己的订单(支持 4 种 service_type)
- 商家端: 处理订单(发货、派单、核销等)
- 管理端: 完整读写(投诉后修改金额/状态等)
- 员工端: 查看自己接的单
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import (
    ProductOrder, ProductOrderItem,
    ServiceOrder, ServiceOrderItem,
    DeliverySchedule,
    OrderTransfer, OrderLog,
)

logger = logging.getLogger(__name__)

# ── 地址快照字段(两种订单共用) ──
_RECEIVER_FIELDS = [
    'receiver_name', 'receiver_phone', 'receiver_address_type',
    'receiver_province', 'receiver_city', 'receiver_district',
    'receiver_community', 'receiver_building', 'receiver_unit', 'receiver_room',
    'receiver_street', 'receiver_house_number',
    'receiver_address', 'receiver_access',
]

_SERVICE_RECEIVER_FIELDS = _RECEIVER_FIELDS + ['receiver_lng', 'receiver_lat']

# ── 金币抵扣字段 ──
_COIN_FIELDS = ['coin_deduct_amount', 'coins_deducted']

# ── 服务配置快照字段(详情接口需要返回这些给前端) ──
_SERVICE_SNAPSHOT_FIELDS = [
    'free_cancel_hours_snapshot', 'delivery_fee_snapshot',
    'points_reward_snapshot',
    'urgent_config_snapshot', 'delivery_config_snapshot',
]

# ── 订阅相关字段 ──
_SUBSCRIPTION_FIELDS = [
    'subscription_start_date', 'subscription_end_date',
    'planned_delivery_count', 'completed_delivery_count',
    'is_paused', 'pause_started_at', 'total_paused_days',
]


# ══════════════════════════════════════════════════════════════
# 优惠券校验工具（商品/服务订单创建共用）
# ══════════════════════════════════════════════════════════════

def validate_and_calc_coupon(user, merchant_id, total_amount, coupon_id):
    """
    校验用户选的优惠券，返回 (coupon_instance, deduct_amount)。
    coupon_id 为空时返回 (None, 0)。

    校验规则：
      1. 券属于该用户、状态 unused、未过期、已生效
      2. 券的 merchant_id 为空（平台券）或等于 merchant_id（商家券只能在本店用）
      3. 满足最低消费门槛
    """
    if not coupon_id:
        return None, Decimal('0')

    from campaigns.models import UserCoupon
    try:
        coupon = UserCoupon.objects.select_related('coupon_template').get(
            id=coupon_id, user=user,
        )
    except UserCoupon.DoesNotExist:
        raise serializers.ValidationError({'user_coupon_id': '优惠券不存在'})

    # 状态
    if coupon.status != 'unused':
        raise serializers.ValidationError({'user_coupon_id': '该券已使用或已作废'})
    if coupon.is_expired:
        raise serializers.ValidationError({'user_coupon_id': '该券已过期'})

    # 生效时间
    now = timezone.now()
    if coupon.valid_from and now < coupon.valid_from:
        raise serializers.ValidationError({'user_coupon_id': '该券尚未生效'})

    # ★ 商户归属：merchant_id 非空的券只能在该商家使用
    if coupon.merchant_id is not None and coupon.merchant_id != merchant_id:
        raise serializers.ValidationError({'user_coupon_id': '该券仅限在指定商家使用'})

    # 最低消费
    if coupon.snapshot_min_consumption and total_amount < coupon.snapshot_min_consumption:
        raise serializers.ValidationError({
            'user_coupon_id': f'需满 ¥{coupon.snapshot_min_consumption} 才可使用',
        })

    # 计算抵扣
    tpl_type = coupon.coupon_template.coupon_type
    if tpl_type == 'cash':
        deduct = min(coupon.snapshot_face_value or Decimal('0'), total_amount)
    elif tpl_type == 'discount':
        rate = coupon.snapshot_discount_rate or Decimal('1')
        deduct = (total_amount * (1 - rate)).quantize(Decimal('0.01'))
        deduct = min(deduct, total_amount)
    else:
        deduct = Decimal('0')

    return coupon, deduct


def lock_coupon(coupon, order):
    """
    原子锁定券（防并发）。在 create 的 transaction.atomic 内调用。
    """
    if coupon is None:
        return
    from campaigns.models import UserCoupon
    updated = UserCoupon.objects.filter(
        id=coupon.id, status='unused',
    ).update(status='used', used_at=timezone.now())
    if not updated:
        raise serializers.ValidationError({'user_coupon_id': '券已被使用，请刷新重试'})
    order.user_coupon = coupon
    order.save(update_fields=['user_coupon'])


def return_coupon(order):
    """取消/退款时退还优惠券。幂等。"""
    if not getattr(order, 'user_coupon_id', None):
        return
    try:
        from campaigns.models import UserCoupon
        UserCoupon.objects.filter(
            id=order.user_coupon_id, status='used',
        ).update(status='unused', used_at=None)
    except Exception:
        logger.exception('退还优惠券失败 order_no=%s coupon_id=%s',
                         order.order_no, order.user_coupon_id)

# ══════════════════════════════════════════════════════════════
# 周期配送日期生成工具(scheduled 类型用)
# ══════════════════════════════════════════════════════════════

def _step_date(d, cycle):
    """按周期推进到下一个候选日期"""
    if cycle == 'daily':
        return d + timedelta(days=1)
    if cycle == 'weekly':
        return d + timedelta(weeks=1)
    if cycle == 'biweekly':
        return d + timedelta(weeks=2)
    if cycle == 'monthly':
        # 简单按月推进:处理月末日子超界(如 1/31 → 2/28)
        year, month, day = d.year, d.month + 1, d.day
        if month > 12:
            year += 1
            month = 1
        # 计算该月的最大天数
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        return d.replace(year=year, month=month, day=min(day, max_day))
    raise ValueError(f'未知配送周期: {cycle}')


def generate_delivery_dates(start_date, cycle, count, skip_weekdays=None):
    """
    根据周期生成 count 个配送日期。
    skip_weekdays: 跳过的星期列表(1=周一...7=周日),如 [6,7] 跳过周末。

    返回长度可能小于 count(如果遇到跳过日,会继续往后推直到凑够 count)
    """
    skip = set(skip_weekdays or [])
    dates = []
    cur = start_date
    # 安全上限,避免恶意配置导致死循环
    safety_limit = count * 4 + 365
    while len(dates) < count and safety_limit > 0:
        if cur.isoweekday() not in skip:
            dates.append(cur)
        cur = _step_date(cur, cycle)
        safety_limit -= 1
    return dates


# ══════════════════════════════════════════════════════════════
# 订单明细(子项)
# ══════════════════════════════════════════════════════════════

class ProductOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductOrderItem
        fields = [
            'id', 'product_id', 'sku_id',
            'product_name', 'product_image', 'sku_text',
            'unit_price', 'quantity', 'item_amount',
            'is_reviewed',
        ]
        read_only_fields = ['id', 'item_amount', 'is_reviewed']


class ServiceOrderItemSerializer(serializers.ModelSerializer):
    """服务订单明细 - 含 spec_key 稳定标识"""
    class Meta:
        model = ServiceOrderItem
        fields = [
            'id', 'service_id',
            'service_name', 'service_image', 'service_type', 'service_mode',
            'spec_key', 'spec_name',
            'price_unit', 'duration_minutes',
            'unit_price', 'quantity', 'item_amount',
        ]
        read_only_fields = ['id', 'item_amount']
        extra_kwargs = {
            # 这些字段在创建订单时由后端从 service+spec 快照,前端不需要传
            'service_name':     {'required': False, 'default': ''},
            'service_image':    {'required': False, 'default': ''},
            'service_type':     {'required': False, 'default': ''},
            'service_mode':     {'required': False, 'default': ''},
            'spec_name':        {'required': False, 'default': ''},
            'price_unit':       {'required': False, 'default': ''},
            'duration_minutes': {'required': False, 'default': 0},
            'unit_price':       {'required': False},
            'service_id':       {'required': True},
            'spec_key':         {'required': False, 'default': ''},
        }


# ══════════════════════════════════════════════════════════════
# 周期配送子记录
# ══════════════════════════════════════════════════════════════

class DeliveryScheduleSerializer(serializers.ModelSerializer):
    """周期配送单次记录"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    staff_name = serializers.CharField(source='assigned_staff.name', read_only=True, default='')

    class Meta:
        model = DeliverySchedule
        fields = [
            'id', 'sequence', 'scheduled_date',
            'scheduled_window_start', 'scheduled_window_end',
            'quantity',
            'status', 'status_display',
            'assigned_staff', 'staff_name', 'assigned_at',
            'actual_delivered_at', 'skip_reason',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # 整体只读,操作走专用 action


# ══════════════════════════════════════════════════════════════
# 转单记录 / 操作日志
# ══════════════════════════════════════════════════════════════

class OrderTransferSerializer(serializers.ModelSerializer):
    initiated_by_display  = serializers.CharField(source='get_initiated_by_display',  read_only=True)
    transfer_type_display = serializers.CharField(source='get_transfer_type_display', read_only=True)
    status_display        = serializers.CharField(source='get_status_display',        read_only=True)
    from_staff_name = serializers.CharField(source='from_staff.name', read_only=True, default='')
    to_staff_name   = serializers.CharField(source='to_staff.name',   read_only=True, default='')

    class Meta:
        model = OrderTransfer
        fields = [
            'id', 'sequence',
            'from_staff_name', 'to_staff_name',
            'initiated_by', 'initiated_by_display',
            'transfer_type', 'transfer_type_display',
            'reason',
            'status', 'status_display',
            'confirm_deadline', 'confirmed_at',
            'created_at',
        ]


class OrderLogSerializer(serializers.ModelSerializer):
    action_display        = serializers.CharField(source='get_action_display',        read_only=True)
    operator_type_display = serializers.CharField(source='get_operator_type_display', read_only=True)

    class Meta:
        model = OrderLog
        fields = [
            'id', 'order_no', 'order_type',
            'action', 'action_display', 'description',
            'operator_type', 'operator_type_display',
            'operator_id', 'operator_name',
            'created_at',
        ]


# ══════════════════════════════════════════════════════════════
# 日志工具
# ══════════════════════════════════════════════════════════════

def create_order_log(order_no, order_type, action,
                     request=None, operator_type='system',
                     operator_id=None, operator_name='', description=''):
    """在已有事务中写入订单操作日志"""
    if request and not operator_id:
        user = request.user
        operator_id = getattr(user, 'id', None)
        operator_name = operator_name or (
            getattr(user, 'name', '')
            or getattr(user, 'nickname', '')
            or str(operator_id or '')
        )
    OrderLog.objects.create(
        order_no=order_no,
        order_type=order_type,
        action=action,
        operator_type=operator_type,
        operator_id=operator_id,
        operator_name=operator_name,
        description=description,
    )


# ══════════════════════════════════════════════════════════════
# 用户端 — 商品订单 (不变)
# ══════════════════════════════════════════════════════════════

class UserProductOrderListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ProductOrderItemSerializer(many=True, read_only=True)
    short_address  = serializers.CharField(read_only=True)

    class Meta:
        model = ProductOrder
        fields = [
            'id', 'order_no', 'merchant_id', 'merchant_name',
            'total_amount', 'freight_amount', 'discount_amount', 'pay_amount',
            'status', 'status_display',
            'delivery_type',
            'short_address', 'receiver_name',
            'pickup_address',
            'items', 'is_reviewed',
            'created_at',
        ]


class UserProductOrderDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ProductOrderItemSerializer(many=True, read_only=True)
    full_address   = serializers.CharField(read_only=True)
    short_address  = serializers.CharField(read_only=True)

    class Meta:
        model = ProductOrder
        fields = [
            'id', 'order_no', 'merchant_id', 'merchant_name',
            'total_amount', 'freight_amount', 'discount_amount',
        ] + _COIN_FIELDS + [
            'pay_amount',
            'status', 'status_display',
        ] + _RECEIVER_FIELDS + [
            'full_address', 'short_address',
            'delivery_type', 'pickup_address', 'pickup_contact', 'pickup_deadline',
            'shipping_company', 'shipping_no', 'shipped_at',
            'verify_code', 'verify_expire_at', 'verified_at',
            'points_earned', 'gold_earned',
            'remark', 'cancel_reason',
            'is_reviewed', 'reviewed_at',
            'paid_at', 'completed_at', 'created_at',
            'items', 'user_coupon_id', 'coupon_deduct_amount'
        ]


class UserProductOrderCreateSerializer(serializers.ModelSerializer):
    items = ProductOrderItemSerializer(many=True)
    address_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True,
    )
    user_coupon_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True, default=None,
    )

    class Meta:
        model = ProductOrder
        fields = [
            'id', 'order_no', 'status', 'created_at',
            'merchant_id', 'merchant_name',
            'total_amount', 'freight_amount', 'discount_amount',
        ] + _COIN_FIELDS + [
            'coupon_deduct_amount', 'pay_amount',
        ] + _RECEIVER_FIELDS + [
            'delivery_type', 'pickup_address', 'pickup_contact', 'pickup_deadline',
            'remark', 'items', 'address_id', 'user_coupon_id',
        ]
        read_only_fields = ['id', 'order_no', 'status', 'created_at', 'coupon_deduct_amount']
        extra_kwargs = {
            'freight_amount':     {'default': Decimal('0.00')},
            'discount_amount':    {'default': Decimal('0.00')},
            'coin_deduct_amount': {'default': Decimal('0.00')},
            'coins_deducted':     {'default': 0},
            'pickup_address':     {'default': ''},
            'pickup_contact':     {'default': ''},
            'pickup_deadline':    {'required': False},
        }

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('订单至少包含一件商品')
        return value

    def validate(self, attrs):
        from decimal import Decimal
        from merchants.models import Merchant
        from product.models import GoodsSku

        # ─ 1) 商家加载 ─
        merchant = Merchant.objects.filter(id=attrs.get('merchant_id')).first()
        if not merchant:
            raise serializers.ValidationError({'merchant_id': '商家不存在'})

        delivery_type = attrs.get('delivery_type', 'home_delivery')

        # ─ 2) 收货人/电话 校验 ─
        if delivery_type == 'home_delivery':
            if not attrs.get('receiver_name'):
                raise serializers.ValidationError({'receiver_name': '送货上门必须填写收货人'})
            if not attrs.get('receiver_phone'):
                raise serializers.ValidationError({'receiver_phone': '送货上门必须填写收货人电话'})

        # ─ 3) 自提：用商家信息强制覆盖 ─
        if delivery_type == 'self_pickup':
            attrs['pickup_address'] = (
                    getattr(merchant, 'full_address', '') or merchant.address or ''
            )
            attrs['pickup_contact'] = merchant.contact_phone or ''
            if not attrs['pickup_address']:
                raise serializers.ValidationError({'pickup_address': '商家未设置地址，暂时无法自提'})

        # ─ 4) SKU 校验 + 装配运费入参 + 收集金币配置 ─
        items_for_calc = []
        coin_rules = []          # ★★★ 每个 item 的金币抵扣配置
        for item in attrs['items']:
            sku = (GoodsSku.objects
                   .select_related('goods')
                   .filter(id=item['sku_id']).first())
            if not sku:
                raise serializers.ValidationError({'items': f"SKU {item['sku_id']} 不存在"})
            goods = sku.goods
            items_for_calc.append({
                'goods': goods,
                'quantity': item['quantity'],
                'price': sku.price,
            })
            # ★★★ SKU 的 max 为 0 时沿用 SPU 的 max;SPU 的 max 为 0 表示不限
            sku_max = sku.max_coin_deduction or 0
            spu_max = goods.max_coin_deduction or 0
            coin_rules.append({
                'title': goods.title,
                'allow': bool(goods.allow_coin_deduction),
                'effective_max': sku_max if sku_max > 0 else spu_max,  # 0=不限
            })

        # ─ 5) 收货坐标 ─
        receiver_lat = receiver_lng = None
        address_id = attrs.pop('address_id', None)
        if delivery_type == 'home_delivery' and address_id:
            from address.models import UserAddress
            addr = UserAddress.objects.filter(
                id=address_id, user=self.context['request'].user
            ).first()
            if addr:
                receiver_lat = addr.latitude
                receiver_lng = addr.longitude

        # ─ 6) 后端重算运费 + 自提优惠 ─
        fr = merchant.calc_freight(
            items=items_for_calc,
            delivery_type=delivery_type,
            receiver_lat=receiver_lat,
            receiver_lng=receiver_lng,
        )
        if not fr['ok']:
            raise serializers.ValidationError({'delivery_type': fr['error']})

        attrs['freight_amount'] = fr['freight']
        front_discount = Decimal(str(attrs.get('discount_amount') or 0))
        attrs['discount_amount'] = front_discount + fr['goods_discount']

        # ─ 7) 金币校验 ─
        coin_deduct = Decimal(str(attrs.get('coin_deduct_amount') or 0))
        coins = attrs.get('coins_deducted', 0)
        if Decimal(coins) != coin_deduct:
            raise serializers.ValidationError({'coins_deducted': '金币数与抵扣金额必须一致(1金币=1元)'})

        total = Decimal(str(attrs['total_amount']))
        if coin_deduct > total:
            raise serializers.ValidationError({'coin_deduct_amount': '金币抵扣不能超过商品总额'})

        # ─ 7.1) ★★★ allow_coin_deduction / max_coin_deduction 强制校验 ─
        coins_int = int(coins or 0)
        if coins_int > 0:
            # (a) 任一商品关闭了「允许金币抵扣」→ 整单拒绝
            blocked = next((r['title'] for r in coin_rules if not r['allow']), None)
            if blocked:
                raise serializers.ValidationError({
                    'coins_deducted': f'商品「{blocked}」不支持金币抵扣',
                })
            # (b) 上限:任一商品 effective_max=0 视为不限;
            #     全部有限时,上限取各商品上限之和(与前端单值口径一致,不乘数量)
            if all(r['effective_max'] > 0 for r in coin_rules):
                order_cap = sum(r['effective_max'] for r in coin_rules)
                if coins_int > order_cap:
                    raise serializers.ValidationError({
                        'coins_deducted': f'本单最多可抵扣 {order_cap} 金币',
                    })

        # ─ 8) ★ 优惠券校验 ─
        coupon, coupon_deduct = validate_and_calc_coupon(
            user=self.context['request'].user,
            merchant_id=attrs['merchant_id'],
            total_amount=total,
            coupon_id=attrs.pop('user_coupon_id', None),
        )
        attrs['_user_coupon'] = coupon
        attrs['coupon_deduct_amount'] = coupon_deduct

        # ─ 9) 后端重算 pay_amount ─
        pay_amount = max(
            Decimal('0'),
            total + attrs['freight_amount']
                  - attrs['discount_amount']
                  - coin_deduct
                  - coupon_deduct
        )
        attrs['pay_amount'] = pay_amount

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop('address_id', None)
        coupon = validated_data.pop('_user_coupon', None)
        items_data = validated_data.pop('items')
        user = self.context['request'].user
        validated_data['user'] = user

        coins = validated_data.get('coins_deducted', 0)
        if coins > 0:
            from wallet.models import UserWallet
            wallet, _ = UserWallet.objects.get_or_create(user=user)
            if wallet.gold_available < coins:
                raise serializers.ValidationError(
                    {'coins_deducted': f'金币余额不足，当前可用 {wallet.gold_available}'}
                )

        order = ProductOrder.objects.create(**validated_data)

        # ★ 锁定优惠券
        lock_coupon(coupon, order)

        ProductOrderItem.objects.bulk_create([
            ProductOrderItem(
                order=order,
                item_amount=Decimal(str(item['unit_price'])) * item['quantity'],
                **item,
            )
            for item in items_data
        ])

        create_order_log(
            order.order_no, 'product', 'create',
            request=self.context['request'], operator_type='user',
            description='用户创建商品订单',
        )
        return order
# ══════════════════════════════════════════════════════════════
# 用户端 — 服务订单(查看)
# ══════════════════════════════════════════════════════════════

class UserServiceOrderListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ServiceOrderItemSerializer(many=True, read_only=True)
    short_address  = serializers.CharField(read_only=True)

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no', 'merchant_id', 'merchant_name',
            'service_type', 'service_mode',
            'total_amount', 'discount_amount', 'pay_amount',
            'status', 'status_display',
            'short_address', 'receiver_name',
            'appointment_date', 'appointment_start', 'appointment_end',
            'is_urgent',
            # 周期订单进度展示
            'planned_delivery_count', 'completed_delivery_count', 'is_paused',
            'items', 'is_reviewed',
            'created_at',
        ]


class UserServiceOrderDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ServiceOrderItemSerializer(many=True, read_only=True)
    full_address   = serializers.CharField(read_only=True)
    short_address  = serializers.CharField(read_only=True)
    staff_name = serializers.CharField(source='assigned_staff.name', read_only=True, default='')
    # 派生
    remaining_delivery_count = serializers.IntegerField(read_only=True)
    effective_subscription_end_date = serializers.DateField(read_only=True)
    # 周期订单子单
    delivery_schedules = DeliveryScheduleSerializer(many=True, read_only=True)
    refundable_on_breach = serializers.SerializerMethodField()

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no', 'merchant_id', 'merchant_name',
            'service_type', 'service_mode', 'schedule_type',
            'total_amount', 'discount_amount', 'user_coupon_id', 'coupon_deduct_amount'
        ] + _COIN_FIELDS + [
            'deposit_amount', 'pay_amount',
            'status', 'status_display',
        ] + _SERVICE_SNAPSHOT_FIELDS + _SERVICE_RECEIVER_FIELDS + [
            'full_address', 'short_address',
            'appointment_date', 'appointment_start', 'appointment_end',
            'is_urgent', 'urgent_surcharge',
            'staff_name', 'assigned_at',
            # 周期订阅
        ] + _SUBSCRIPTION_FIELDS + [
            'remaining_delivery_count', 'effective_subscription_end_date',
            'delivery_schedules',
            # on_demand 时效
            'dispatch_started_at', 'estimated_arrival_at', 'actual_arrival_at',
            # 核销
            'verify_code', 'verify_expire_at', 'verified_at',
            'extra_info', 'points_earned', 'gold_earned',
            'remark', 'cancel_reason',
            'is_reviewed', 'reviewed_at',
            'paid_at', 'service_start_at', 'service_end_at',
            'completed_at', 'created_at',
            'items', 'refundable_on_breach',
        ]

    def get_refundable_on_breach(self, obj):
        """
        违约取消能退多少钱(已付款 - 定金)。
        仅在订单仍可取消的状态下返回数值,其他状态返回 None。
        """
        cancellable_statuses = (
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ACCEPT,
            ServiceOrder.Status.PENDING_ASSIGNMENT,
            ServiceOrder.Status.ASSIGNED,
        )
        if obj.status not in cancellable_statuses:
            return None
        deposit = Decimal(obj.deposit_amount or 0)
        pay = Decimal(obj.pay_amount or 0)
        return str(max(Decimal('0'), pay - deposit))

# ══════════════════════════════════════════════════════════════
# 用户端 — 服务订单 (创建,按 service_type 分发)
# ══════════════════════════════════════════════════════════════

class UserServiceOrderCreateSerializer(serializers.ModelSerializer):
    """
    创建服务订单。按 service_type 分发。
    """

    items = ServiceOrderItemSerializer(many=True)

    subscription_duration_days = serializers.IntegerField(
        required=False, write_only=True, min_value=1,
        help_text='订阅天数，默认取 service.delivery_config.min_duration_days'
    )
    user_coupon_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True, default=None,
    )

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no', 'status', 'created_at',
            'merchant_id', 'merchant_name',
            'service_type', 'service_mode', 'schedule_type',
            'total_amount', 'discount_amount',
        ] + _COIN_FIELDS + [
            'coupon_deduct_amount', 'deposit_amount', 'pay_amount',
        ] + _SERVICE_RECEIVER_FIELDS + [
            'appointment_date', 'appointment_start', 'appointment_end',
            'subscription_start_date', 'subscription_duration_days',
            'is_urgent',
            'extra_info', 'remark', 'items', 'user_coupon_id',
        ]
        read_only_fields = ['id', 'order_no', 'status', 'created_at', 'coupon_deduct_amount']
        extra_kwargs = {
            'discount_amount':    {'default': Decimal('0.00')},
            'coin_deduct_amount': {'default': Decimal('0.00')},
            'coins_deducted':     {'default': 0},
            'deposit_amount':     {'default': Decimal('0.00')},
            'schedule_type':      {'required': False, 'allow_blank': True},
        }

    # ─── 校验 ─────────────────────────────────────────────

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError('订单至少包含一个服务项')
        if len(value) > 1:
            raise serializers.ValidationError('服务订单暂只支持单个服务项')
        return value

    def validate(self, attrs):
        # ─ 1. 加载 service + spec ─
        service, spec = self._resolve_service_and_spec(attrs)
        attrs['_service'] = service
        attrs['_spec'] = spec

        # ─ 2. service_type / mode 一致性 ─
        if service.service_type != attrs.get('service_type'):
            raise serializers.ValidationError({
                'service_type': f'与服务实际类型不符，应为 {service.service_type}'
            })
        if service.service_mode != attrs.get('service_mode'):
            raise serializers.ValidationError({
                'service_mode': f'与服务实际方式不符，应为 {service.service_mode}'
            })

        # ─ 3. required_info 必填检查 ─
        required = service.required_info or []
        extra = attrs.get('extra_info') or {}
        for key in required:
            if key == 'address':
                if not attrs.get('receiver_address') and not attrs.get('receiver_community'):
                    raise serializers.ValidationError({
                        'receiver_address': '该服务要求填写地址',
                    })
            elif key == 'contact_phone':
                if not attrs.get('receiver_phone'):
                    raise serializers.ValidationError({
                        'receiver_phone': '该服务要求填写联系电话',
                    })
            else:
                if key not in extra or extra.get(key) in (None, '', []):
                    raise serializers.ValidationError({
                        'extra_info': f'该服务要求填写 {key}',
                    })

        # ─ 4. 按类型分发 ─
        st = attrs.get('service_type')
        if st == 'walk_in':
            self._validate_walk_in(attrs, service)
        elif st == 'appointment':
            self._validate_appointment(attrs, service, spec)
        elif st == 'on_demand':
            self._validate_on_demand(attrs, service)
        elif st == 'scheduled':
            self._validate_scheduled(attrs, service)
        else:
            raise serializers.ValidationError({'service_type': f'未知服务类型: {st}'})

        # ─ ★ 4.5 距离/服务范围校验(硬拦截,防止前端绕过) ─
        self._validate_service_range(attrs, service)

        # ─ 5. ★ 优惠券校验 ─
        coupon, coupon_deduct = validate_and_calc_coupon(
            user=self.context['request'].user,
            merchant_id=attrs['merchant_id'],
            total_amount=attrs.get('total_amount', Decimal('0')),
            coupon_id=attrs.pop('user_coupon_id', None),
        )
        attrs['_user_coupon'] = coupon
        attrs['coupon_deduct_amount'] = coupon_deduct

        # ─ ★ 5.5 金币抵扣规则校验(规格/服务级) ─
        self._validate_coin_deduction(attrs, service, spec)

        # ─ 6. ★ 提前应用服务快照(让 _validate_amounts 拿到 delivery_fee/urgent_surcharge) ─
        self._apply_service_snapshots(attrs, service, spec)

        # ─ 7. 通用金额校验 + 重算 pay_amount ─
        self._validate_amounts(attrs)

        return attrs

    def _resolve_service_and_spec(self, attrs):
        from services.models import Service

        items = self.initial_data.get('items') or []
        if not items:
            raise serializers.ValidationError({'items': '订单缺少服务项'})

        service_id = items[0].get('service_id')
        spec_key = (items[0].get('spec_key') or '').strip()

        if not service_id:
            raise serializers.ValidationError({'items': '缺少 service_id'})

        merchant_id = attrs.get('merchant_id')
        try:
            service = Service.objects.get(id=service_id, merchant_id=merchant_id)
        except Service.DoesNotExist:
            raise serializers.ValidationError({'items': '服务不存在或与商家不匹配'})

        if service.status != Service.Status.ACTIVE:
            raise serializers.ValidationError({'items': '该服务已下架，无法下单'})

        spec = None
        specs = service.specifications or []
        if spec_key:
            spec = next((s for s in specs if s.get('key') == spec_key), None)
            if not spec:
                raise serializers.ValidationError({
                    'items': f'规格 {spec_key} 不存在或已被删除',
                })
        elif specs:
            spec = specs[0]

        return service, spec

    def _enforce_single_quantity(self, service_type_label):
        """
        预约制 / 按需制:一次下单数量必须为 1。
        防止前端绕过直接调接口下单大数量。
        """
        items = self.initial_data.get('items') or []
        for item in items:
            qty = int(item.get('quantity') or 1)
            if qty != 1:
                raise serializers.ValidationError({
                    'items': f'{service_type_label}服务一次只能下 1 份,如需多份请分别下单',
                })

    def _validate_walk_in(self, attrs, service):
        if attrs.get('service_mode') != 'store':
            raise serializers.ValidationError({
                'service_mode': '到店制服务方式必须是 store',
            })

    def _validate_appointment(self, attrs, service, spec):
        self._enforce_single_quantity('预约制')
        if not attrs.get('appointment_date'):
            raise serializers.ValidationError({
                'appointment_date': '预约制必须选择预约日期',
            })

        schedule_type = (service.appointment_config or {}).get('schedule_type', 'customer')
        attrs['schedule_type'] = schedule_type

        if schedule_type == 'customer':
            if not attrs.get('appointment_start'):
                raise serializers.ValidationError({
                    'appointment_start': '客户选时段模式必须指定开始时间',
                })
            if not attrs.get('appointment_end'):
                raise serializers.ValidationError({
                    'appointment_end': '客户选时段模式必须指定结束时间',
                })

        if attrs.get('service_mode') in ('home', 'pickup'):
            self._require_address(attrs)

    def _validate_on_demand(self, attrs, service):
        self._enforce_single_quantity('按需制')
        if attrs.get('appointment_date'):
            raise serializers.ValidationError({
                'appointment_date': '按需制服务不需要预约日期',
            })
        if attrs.get('service_mode') not in ('home', 'pickup'):
            raise serializers.ValidationError({
                'service_mode': '按需制服务方式必须是 home 或 pickup',
            })
        self._require_address(attrs)

    def _validate_scheduled(self, attrs, service):
        if not attrs.get('subscription_start_date'):
            raise serializers.ValidationError({
                'subscription_start_date': '周期制必须填写订阅起始日',
            })
        if attrs['subscription_start_date'] < timezone.now().date():
            raise serializers.ValidationError({
                'subscription_start_date': '订阅起始日不能早于今天',
            })
        if attrs.get('service_mode') not in ('home', 'pickup'):
            raise serializers.ValidationError({
                'service_mode': '周期制服务方式必须是 home 或 pickup',
            })
        self._require_address(attrs)

        cfg = service.delivery_config or {}
        if not cfg or not cfg.get('cycle'):
            raise serializers.ValidationError({
                'items': '该服务未正确配置周期参数，无法下单',
            })

    def _require_address(self, attrs):
        if not attrs.get('receiver_phone'):
            raise serializers.ValidationError({
                'receiver_phone': '上门/取送服务必须填写联系电话',
            })
        has_addr = (
            attrs.get('receiver_address')
            or attrs.get('receiver_community')
            or attrs.get('receiver_street')
        )
        if not has_addr:
            raise serializers.ValidationError({
                'receiver_address': '上门/取送服务必须填写完整地址',
            })

    # ★ 新增:服务范围校验(距离硬拦截)
    def _validate_service_range(self, attrs, service):
        """
        校验收货坐标是否在商家服务半径内。
        触发条件(三选一即触发):
          ① service.required_info 包含 'address'(商家显式要求)
          ② service_mode 是 home / pickup
          ③ service_type 是 on_demand / scheduled(模型强制)
        """
        required = service.required_info or []
        service_mode = attrs.get('service_mode')
        service_type = attrs.get('service_type')

        need_address = (
            'address' in required
            or service_mode in ('home', 'pickup')
            or service_type in ('on_demand', 'scheduled')
        )
        if not need_address:
            return

        # 服务半径(米),<=0 视为商家未限制,跳过
        radius = getattr(service, 'effective_radius_meters', 0) or 0
        if radius <= 0:
            return

        lat = attrs.get('receiver_lat')
        lng = attrs.get('receiver_lng')
        if lat is None or lng is None:
            raise serializers.ValidationError({
                'receiver_address': '所选地址缺少定位坐标,请重新选择或编辑地址',
            })

        merchant = service.merchant
        check = merchant.check_service_range(
            lat=lat,
            lng=lng,
            radius_meters=radius,
        )
        if not check['ok']:
            raise serializers.ValidationError({'receiver_address': check['error']})

        # 把距离写入 extra_info,后续派单/统计可用
        if check.get('distance_km') is not None:
            extra = dict(attrs.get('extra_info') or {})
            extra['distance_km'] = check['distance_km']
            extra['service_radius_meters'] = check['radius_meters']
            attrs['extra_info'] = extra

    def _validate_coin_deduction(self, attrs, service, spec):
        """
        ★ 按「服务 / 规格」级规则校验金币抵扣。
        规则来源 service.get_spec_coin_rule(spec_key):
            - 多规格:spec 上 allow/max 非 null 时覆盖,否则沿用 service 级
            - 单规格 / 无 spec:直接用 service 级
            - allow=False 时 max 恒为 0
        """
        coins = int(attrs.get('coins_deducted', 0) or 0)
        if coins <= 0:
            return  # 没用金币,跳过规则校验

        spec_key = spec.get('key') if spec else None
        rule = service.get_spec_coin_rule(spec_key)

        if not rule['allow_coin_deduction']:
            raise serializers.ValidationError({
                'coins_deducted': '该服务/规格不支持金币抵扣',
            })

        max_ded = rule['max_coin_deduction']
        if max_ded > 0 and coins > max_ded:
            raise serializers.ValidationError({
                'coins_deducted': f'该服务/规格单笔最多抵扣 {max_ded} 金币',
            })

    def _validate_amounts(self, attrs):
        """
        重算 pay_amount。

        口径约定(重要,前后端必须一致):
          ① 前端 detail.vue 传来的 total_amount 已包含 urgent_surcharge,
             后端不再单独加,否则会把加急费算两次。
          ② deposit_amount 在"一次付清+违约扣定金"模型下,
             不参与 pay_amount 计算,仅作为违约时的扣款上限标记。
          ③ 公式:pay_amount = total + delivery_fee - discount - coin - coupon
        """
        # ── 金币一致性 ──
        coin_deduct = attrs.get('coin_deduct_amount', Decimal('0'))
        coins = attrs.get('coins_deducted', 0)
        if Decimal(coins) != coin_deduct:
            raise serializers.ValidationError({
                'coins_deducted': '金币数与抵扣金额必须一致(1金币=1元)',
            })

        total = attrs.get('total_amount', Decimal('0'))
        discount = attrs.get('discount_amount', Decimal('0'))
        delivery_fee = Decimal(str(attrs.get('delivery_fee_snapshot') or 0))
        coupon_deduct = attrs.get('coupon_deduct_amount', Decimal('0'))

        if coin_deduct > total:
            raise serializers.ValidationError({
                'coin_deduct_amount': '金币抵扣不能超过服务总额',
            })

        # ★ 关键修复:
        #   - 不再 + urgent_surcharge(前端 total_amount 已含)
        #   - 不再 - deposit(定金是违约扣款标记,不是抵扣项)
        pay_amount = max(
            Decimal('0'),
            total + delivery_fee
            - discount
            - coin_deduct
            - coupon_deduct,
        )
        attrs['pay_amount'] = pay_amount

    # ─── 创建 ─────────────────────────────────────────────
    @transaction.atomic
    def create(self, validated_data):
        service = validated_data.pop('_service')
        spec = validated_data.pop('_spec', None)
        items_data = validated_data.pop('items')
        sub_duration = validated_data.pop('subscription_duration_days', None)
        coupon = validated_data.pop('_user_coupon', None)

        user = self.context['request'].user
        validated_data['user'] = user

        # ─ 1. 金币余额校验 ─
        coins = validated_data.get('coins_deducted', 0)
        if coins > 0:
            from wallet.models import UserWallet
            wallet, _ = UserWallet.objects.get_or_create(user=user)
            if wallet.gold_available < coins:
                raise serializers.ValidationError({
                    'coins_deducted': f'金币余额不足，当前可用 {wallet.gold_available}'
                })

        # ─ 2. 按类型做下单前特殊处理 ─
        #    (服务快照已在 validate 阶段写入 validated_data,此处不再重复)
        st = validated_data.get('service_type')
        if st == 'appointment' and validated_data.get('schedule_type') == 'customer':
            self._book_time_slot(validated_data, service, spec)

        if st == 'scheduled':
            self._prepare_subscription(validated_data, service, sub_duration)

        # ─ 3. 创建订单 ─
        order = ServiceOrder.objects.create(**validated_data)

        # ─ 4. ★ 锁定优惠券 ─
        lock_coupon(coupon, order)

        # ─ 5. 创建订单明细 ─
        self._create_items(order, items_data, service, spec)

        # ─ 6. scheduled：批量生成 DeliverySchedule ─
        if st == 'scheduled':
            self._create_delivery_schedules(order, service)

        # ─ 7. 日志 ─
        create_order_log(
            order.order_no, 'service', 'create',
            request=self.context['request'], operator_type='user',
            description=f'用户创建{order.get_service_type_display()}订单',
        )
        return order

    def _apply_service_snapshots(self, data, service, spec):
        data['free_cancel_hours_snapshot'] = service.free_cancel_hours or 0
        data['delivery_fee_snapshot'] = service.effective_delivery_fee or Decimal('0.00')
        data['points_reward_snapshot'] = service.points_reward or 0

        if data.get('is_urgent'):
            urgent_cfg = service.urgent_config or {}
            surcharge = Decimal(str(urgent_cfg.get('surcharge', '0')))
            if not data.get('urgent_surcharge') or data['urgent_surcharge'] <= 0:
                data['urgent_surcharge'] = surcharge
            data['urgent_config_snapshot'] = {
                'surcharge': str(data['urgent_surcharge']),
                'response_minutes': urgent_cfg.get('response_minutes', 30),
            }

        if service.service_type == 'scheduled':
            data['delivery_config_snapshot'] = service.delivery_config or {}

    def _book_time_slot(self, validated_data, service, spec):
        from services.models import ServiceTimeSlot

        appointment_date = validated_data['appointment_date']
        start_time = validated_data['appointment_start']
        end_time = validated_data['appointment_end']

        available = service.get_available_slots(appointment_date)

        def _norm(t):
            s = t.strftime('%H:%M:%S') if hasattr(t, 'strftime') else str(t)
            return s if len(s) == 8 else f'{s}:00'

        start_norm = _norm(start_time)
        end_norm = _norm(end_time)

        matched = next(
            (s for s in available
             if s['start_time'] == start_norm and s['end_time'] == end_norm),
            None,
        )
        if not matched:
            raise serializers.ValidationError({
                'appointment_start': '该时段不在排班范围内，请重新选择',
            })

        slot, _ = ServiceTimeSlot.objects.get_or_create(
            service=service,
            date=appointment_date,
            start_time=start_norm,
            defaults={
                'end_time': end_norm,
                'capacity': matched['capacity'],
                'rule_id':  matched.get('rule_id'),
            },
        )
        slot = ServiceTimeSlot.objects.select_for_update().get(pk=slot.pk)

        if not slot.is_bookable:
            raise serializers.ValidationError({
                'appointment_start': '该时段已被预约满，请重新选择',
            })

        slot.book()
        validated_data['time_slot_id'] = slot.id

    def _prepare_subscription(self, validated_data, service, sub_duration_days):
        cfg = service.delivery_config or {}
        cycle = cfg.get('cycle', 'daily')
        skip_weekdays = cfg.get('skip_weekdays') or []
        min_days = int(cfg.get('min_duration_days') or 30)

        duration_days = max(int(sub_duration_days or min_days), min_days)

        start_date = validated_data['subscription_start_date']
        end_date = start_date + timedelta(days=duration_days - 1)

        if cycle == 'daily':
            estimate = duration_days
        elif cycle == 'weekly':
            estimate = duration_days // 7 + (1 if duration_days % 7 else 0)
        elif cycle == 'biweekly':
            estimate = duration_days // 14 + (1 if duration_days % 14 else 0)
        elif cycle == 'monthly':
            estimate = duration_days // 30 + (1 if duration_days % 30 else 0)
        else:
            estimate = duration_days

        skip_ratio = len(skip_weekdays) / 7 if skip_weekdays else 0
        planned = max(1, int(round(estimate * (1 - skip_ratio))))

        validated_data['subscription_end_date'] = end_date
        validated_data['planned_delivery_count'] = planned

    def _create_items(self, order, items_data, service, spec):
        items_to_create = []
        for item in items_data:
            quantity = item.get('quantity', 1)
            unit_price = item.get('unit_price')
            if spec:
                unit_price = Decimal(str(spec.get('price', '0')))
            elif unit_price is None:
                unit_price = service.price or Decimal('0.00')
            else:
                unit_price = Decimal(str(unit_price))

            items_to_create.append(ServiceOrderItem(
                order=order,
                service_id=service.id,
                service_name=service.name,
                service_image=service.cover_image or '',
                service_type=service.service_type,
                service_mode=service.service_mode,
                spec_key=(spec.get('key') if spec else '') or '',
                spec_name=(spec.get('name') if spec else '') or '',
                price_unit=(spec.get('unit') if spec else service.price_unit) or '',
                duration_minutes=(
                    (spec.get('duration_minutes') if spec else None)
                    or service.default_duration_minutes
                    or 0
                ),
                unit_price=unit_price,
                quantity=quantity,
                item_amount=unit_price * quantity,
            ))
        ServiceOrderItem.objects.bulk_create(items_to_create)

    def _create_delivery_schedules(self, order, service):
        cfg = order.delivery_config_snapshot or {}
        cycle = cfg.get('cycle', 'daily')
        skip_weekdays = cfg.get('skip_weekdays') or []
        window = cfg.get('delivery_time_window') or {'start': '07:00', 'end': '09:00'}
        qpd = int(cfg.get('quantity_per_delivery') or 1)

        dates = generate_delivery_dates(
            start_date=order.subscription_start_date,
            cycle=cycle,
            count=order.planned_delivery_count,
            skip_weekdays=skip_weekdays,
        )

        if len(dates) < order.planned_delivery_count:
            order.planned_delivery_count = len(dates)
            order.save(update_fields=['planned_delivery_count', 'updated_at'])

        from datetime import time as _time
        def _parse_time(s):
            if isinstance(s, str):
                parts = s.split(':')
                return _time(int(parts[0]), int(parts[1]))
            return s

        start_t = _parse_time(window.get('start', '07:00'))
        end_t = _parse_time(window.get('end', '09:00'))

        DeliverySchedule.objects.bulk_create([
            DeliverySchedule(
                order=order,
                sequence=i + 1,
                scheduled_date=d,
                scheduled_window_start=start_t,
                scheduled_window_end=end_t,
                quantity=qpd,
                status=DeliverySchedule.Status.PENDING,
            )
            for i, d in enumerate(dates)
        ])

        if dates:
            order.subscription_end_date = dates[-1]
            order.save(update_fields=['subscription_end_date', 'updated_at'])

# ══════════════════════════════════════════════════════════════
# 用户端 — 通用操作
# ══════════════════════════════════════════════════════════════

class OrderCancelSerializer(serializers.Serializer):
    cancel_reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )


class RefundApplySerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=[
        ('user_cancel',   '用户取消'),
        ('service_issue', '服务问题'),
        ('product_issue', '商品问题'),
        ('other',         '其他'),
    ])
    reason_detail = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )


class ConfirmReceiveSerializer(serializers.Serializer):
    pass


# ──── 新增:订阅相关 ──────────────────────────────────────────

class SubscriptionPauseSerializer(serializers.Serializer):
    """暂停订阅"""
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )


class DeliveryScheduleSkipSerializer(serializers.Serializer):
    """跳过某次配送"""
    reason = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default='',
    )


# ══════════════════════════════════════════════════════════════
# 商家端 — 商品订单 (不变)
# ══════════════════════════════════════════════════════════════

class MerchantProductOrderListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    short_address  = serializers.CharField(read_only=True)
    items_summary  = serializers.SerializerMethodField()

    class Meta:
        model = ProductOrder
        fields = [
            'id', 'order_no', 'user_id',
            'total_amount', 'freight_amount', 'pay_amount',
            'status', 'status_display',
            'receiver_name', 'receiver_phone', 'short_address',
            'delivery_type', 'pickup_address',
            'items_summary',
            'paid_at', 'created_at',
        ]

    def get_items_summary(self, obj):
        first = obj.items.first()
        count = obj.items.count()
        if not first:
            return ''
        return f"{first.product_name} 等{count}件" if count > 1 else first.product_name


class MerchantProductOrderDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ProductOrderItemSerializer(many=True, read_only=True)
    full_address   = serializers.CharField(read_only=True)
    short_address  = serializers.CharField(read_only=True)

    class Meta:
        model = ProductOrder
        fields = [
            'id', 'order_no','merchant_name', 'user_id',
            'total_amount', 'freight_amount', 'discount_amount', 'user_coupon_id', 'coupon_deduct_amount',
        ] + _COIN_FIELDS + [
            'pay_amount',
            'status', 'status_display',
        ] + _RECEIVER_FIELDS + [
            'full_address', 'short_address',
            'delivery_type', 'pickup_address', 'pickup_contact', 'pickup_deadline',
            'shipping_company', 'shipping_no', 'shipped_at',
            'verify_code', 'verify_expire_at', 'verified_at', 'verified_by_staff_id',
            'remark', 'cancel_reason',
            'paid_at', 'completed_at', 'created_at',
            'items',
        ]


class ShipSerializer(serializers.Serializer):
    shipping_company = serializers.CharField(max_length=50)
    shipping_no = serializers.CharField(max_length=50)


# ══════════════════════════════════════════════════════════════
# 商家端 — 服务订单
# ══════════════════════════════════════════════════════════════

class MerchantServiceOrderListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    short_address  = serializers.CharField(read_only=True)
    staff_name     = serializers.CharField(source='assigned_staff.name', read_only=True, default='')
    items_summary  = serializers.SerializerMethodField()

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no', 'user_id',
            'service_type', 'service_mode',
            'total_amount', 'pay_amount',
            'status', 'status_display',
            'receiver_name', 'receiver_phone', 'short_address',
            'appointment_date', 'appointment_start', 'appointment_end',
            'is_urgent', 'staff_name',
            # 周期订单展示进度
            'planned_delivery_count', 'completed_delivery_count', 'is_paused',
            'items_summary',
            'paid_at', 'created_at',
        ]

    def get_items_summary(self, obj):
        first = obj.items.first()
        return first.service_name if first else ''


class MerchantServiceOrderDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ServiceOrderItemSerializer(many=True, read_only=True)
    full_address   = serializers.CharField(read_only=True)
    short_address  = serializers.CharField(read_only=True)
    staff_name     = serializers.CharField(source='assigned_staff.name', read_only=True, default='')
    transfer_records = OrderTransferSerializer(many=True, read_only=True)
    delivery_schedules = DeliveryScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no', 'user_id',
            'service_type', 'service_mode', 'schedule_type',
            'total_amount', 'discount_amount', 'user_coupon_id', 'coupon_deduct_amount',
        ] + _COIN_FIELDS + [
            'deposit_amount', 'pay_amount',
            'status', 'status_display',
        ] + _SERVICE_SNAPSHOT_FIELDS + _SERVICE_RECEIVER_FIELDS + [
            'full_address', 'short_address',
            'appointment_date', 'appointment_start', 'appointment_end',
            'is_urgent', 'urgent_surcharge',
            'assigned_staff_id', 'staff_name', 'assigned_at',
            'transfer_count', 'max_transfer_count',
        ] + _SUBSCRIPTION_FIELDS + [
            'delivery_schedules',
            'dispatch_started_at', 'estimated_arrival_at', 'actual_arrival_at',
            'verify_code', 'verify_expire_at', 'verified_at',
            'extra_info', 'remark', 'cancel_reason',
            'paid_at', 'service_start_at', 'service_end_at',
            'completed_at', 'created_at',
            'items', 'transfer_records',
        ]


class AssignStaffSerializer(serializers.Serializer):
    """商家派单 / 强制改派(共用)"""
    staff_id = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )
    force_urgent = serializers.BooleanField(required=False, default=False)


class VerifyOrderSerializer(serializers.Serializer):
    verify_code = serializers.CharField(max_length=10, required=False)
    order_no    = serializers.CharField(max_length=32, required=False)

    def validate(self, attrs):
        if not attrs.get('verify_code') and not attrs.get('order_no'):
            raise serializers.ValidationError('verify_code 或 order_no 至少提供一个')
        return attrs


class RefundHandleSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )

    def validate(self, attrs):
        if attrs['action'] == 'reject' and not attrs.get('reason'):
            raise serializers.ValidationError({'reason': '驳回退款必须填写原因'})
        return attrs


# ══════════════════════════════════════════════════════════════
# 商家端 — 配送日程操作(scheduled 专用)
# ══════════════════════════════════════════════════════════════

class DeliveryScheduleAssignSerializer(serializers.Serializer):
    """给某次配送指派员工"""
    staff_id = serializers.IntegerField(min_value=1)


# ══════════════════════════════════════════════════════════════
# 商家 / 员工 — 转单
# ══════════════════════════════════════════════════════════════

class TransferRequestSerializer(serializers.Serializer):
    to_staff_id = serializers.IntegerField(
        min_value=1, required=False, allow_null=True,
    )
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )
    confirm_timeout_minutes = serializers.IntegerField(
        min_value=1, max_value=1440, required=False, default=15,
    )


class TransferCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )


class TransferActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['accept', 'reject'])
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default='',
    )


class StaffPendingTransferSerializer(serializers.ModelSerializer):
    """员工端 待接单/转单列表项"""
    order_no       = serializers.CharField(source='order.order_no', read_only=True)
    order_id       = serializers.IntegerField(source='order.id', read_only=True)
    service_name   = serializers.SerializerMethodField()
    appointment    = serializers.SerializerMethodField()
    pay_amount     = serializers.DecimalField(
        source='order.pay_amount', max_digits=10, decimal_places=2, read_only=True,
    )
    is_urgent      = serializers.BooleanField(source='order.is_urgent', read_only=True)
    receiver_name  = serializers.CharField(source='order.receiver_name', read_only=True)
    receiver_phone = serializers.CharField(source='order.receiver_phone', read_only=True)
    short_address  = serializers.CharField(source='order.short_address', read_only=True)
    from_staff_name = serializers.CharField(
        source='from_staff.name', read_only=True, default='',
    )
    transfer_type_display = serializers.CharField(
        source='get_transfer_type_display', read_only=True,
    )
    seconds_left = serializers.SerializerMethodField()

    class Meta:
        model = OrderTransfer
        fields = [
            'id', 'sequence',
            'order_id', 'order_no',
            'service_name', 'appointment',
            'pay_amount', 'is_urgent',
            'receiver_name', 'receiver_phone', 'short_address',
            'from_staff_name',
            'transfer_type', 'transfer_type_display',
            'reason',
            'confirm_deadline', 'seconds_left',
            'created_at',
        ]

    def get_service_name(self, obj):
        item = obj.order.items.first()
        return item.service_name if item else ''

    def get_appointment(self, obj):
        o = obj.order
        if not o.appointment_date:
            return ''
        start = o.appointment_start.strftime('%H:%M') if o.appointment_start else ''
        end = o.appointment_end.strftime('%H:%M') if o.appointment_end else ''
        if start and end:
            return f'{o.appointment_date} {start}-{end}'
        return f'{o.appointment_date}'

    def get_seconds_left(self, obj):
        if not obj.confirm_deadline:
            return 0
        delta = (obj.confirm_deadline - timezone.now()).total_seconds()
        return max(0, int(delta))


# ══════════════════════════════════════════════════════════════
# 管理端 — 商品订单
# ══════════════════════════════════════════════════════════════

class AdminProductOrderListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items_count    = serializers.SerializerMethodField()
    short_address  = serializers.CharField(read_only=True)

    class Meta:
        model = ProductOrder
        fields = [
            'id', 'order_no', 'user_id', 'merchant_id', 'merchant_name',
            'total_amount', 'freight_amount', 'discount_amount', 'pay_amount',
            'status', 'status_display',
            'receiver_name', 'receiver_phone', 'short_address',
            'items_count',
            'paid_at', 'completed_at', 'created_at',
        ]

    def get_items_count(self, obj):
        return obj.items.count()


class AdminProductOrderDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ProductOrderItemSerializer(many=True, read_only=True)
    full_address   = serializers.CharField(read_only=True)
    short_address  = serializers.CharField(read_only=True)

    class Meta:
        model = ProductOrder
        fields = [
            'id', 'order_no', 'user_id', 'merchant_id', 'merchant_name',
            'total_amount', 'freight_amount', 'discount_amount', 'user_coupon_id', 'coupon_deduct_amount',
        ] + _COIN_FIELDS + [
            'pay_amount',
            'status', 'status_display',
        ] + _RECEIVER_FIELDS + [
            'full_address', 'short_address',
            'delivery_type', 'pickup_address', 'pickup_contact', 'pickup_deadline',
            'shipping_company', 'shipping_no', 'shipped_at',
            'verify_code', 'verify_expire_at', 'verified_at', 'verified_by_staff_id',
            'points_earned', 'gold_earned',
            'remark', 'cancel_reason',
            'is_reviewed', 'reviewed_at',
            'paid_at', 'completed_at', 'created_at', 'updated_at',
            'items',
        ]


class AdminProductOrderUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductOrder
        fields = [
            'total_amount', 'freight_amount', 'discount_amount',
        ] + _COIN_FIELDS + [
            'pay_amount', 'status',
        ] + _RECEIVER_FIELDS + [
            'delivery_type', 'pickup_address', 'pickup_contact', 'pickup_deadline',
            'shipping_company', 'shipping_no',
            'verify_code',
            'points_earned', 'gold_earned',
            'remark', 'cancel_reason',
        ]

    def validate_pay_amount(self, value):
        if value < Decimal('0'):
            raise serializers.ValidationError('实付金额不能为负')
        return value

    def validate_status(self, value):
        valid = {s.value for s in ProductOrder.Status}
        if value not in valid:
            raise serializers.ValidationError(f'无效状态,可选值:{valid}')
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        old_status = instance.status
        old_pay = instance.pay_amount
        order = super().update(instance, validated_data)

        changes = []
        if order.status != old_status:
            changes.append(f'状态: {old_status}→{order.status}')
        if order.pay_amount != old_pay:
            changes.append(f'实付: {old_pay}→{order.pay_amount}')
        if changes:
            create_order_log(
                order.order_no, 'product', 'modify_price',
                request=self.context.get('request'), operator_type='admin',
                description='管理员修改: ' + ', '.join(changes),
            )
        return order


# ══════════════════════════════════════════════════════════════
# 管理端 — 服务订单
# ══════════════════════════════════════════════════════════════

class AdminServiceOrderListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    short_address  = serializers.CharField(read_only=True)
    staff_name = serializers.CharField(source='assigned_staff.name', read_only=True, default='')

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no', 'user_id', 'merchant_id', 'merchant_name',
            'service_type', 'service_mode',
            'total_amount', 'discount_amount', 'pay_amount',
            'status', 'status_display',
            'receiver_name', 'receiver_phone', 'short_address',
            'is_urgent', 'staff_name',
            'appointment_date',
            'planned_delivery_count', 'completed_delivery_count',
            'paid_at', 'completed_at', 'created_at',
        ]


class AdminServiceOrderDetailSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items          = ServiceOrderItemSerializer(many=True, read_only=True)
    full_address   = serializers.CharField(read_only=True)
    short_address  = serializers.CharField(read_only=True)
    staff_name     = serializers.CharField(source='assigned_staff.name', read_only=True, default='')
    transfer_records = OrderTransferSerializer(many=True, read_only=True)
    delivery_schedules = DeliveryScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no', 'user_id', 'merchant_id', 'merchant_name',
            'service_type', 'service_mode', 'schedule_type',
            'total_amount', 'discount_amount', 'user_coupon_id', 'coupon_deduct_amount',
        ] + _COIN_FIELDS + [
            'deposit_amount', 'urgent_surcharge', 'pay_amount',
            'status', 'status_display',
        ] + _SERVICE_SNAPSHOT_FIELDS + _SERVICE_RECEIVER_FIELDS + [
            'full_address', 'short_address',
            'appointment_date', 'appointment_start', 'appointment_end',
            'is_urgent',
            'assigned_staff_id', 'staff_name', 'assigned_at',
            'transfer_count', 'max_transfer_count',
        ] + _SUBSCRIPTION_FIELDS + [
            'delivery_schedules',
            'dispatch_started_at', 'estimated_arrival_at', 'actual_arrival_at',
            'verify_code', 'verify_expire_at', 'verified_at',
            'verified_by_staff_id',
            'extra_info', 'points_earned', 'gold_earned',
            'remark', 'cancel_reason',
            'is_reviewed', 'reviewed_at',
            'paid_at', 'service_start_at', 'service_end_at',
            'completed_at', 'created_at', 'updated_at',
            'items', 'transfer_records',
        ]


class AdminServiceOrderUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceOrder
        fields = [
            'total_amount', 'discount_amount',
        ] + _COIN_FIELDS + [
            'deposit_amount', 'urgent_surcharge', 'pay_amount',
            'status',
        ] + _SERVICE_RECEIVER_FIELDS + [
            'appointment_date', 'appointment_start', 'appointment_end',
            'assigned_staff', 'max_transfer_count',
            'points_earned', 'gold_earned',
            'remark', 'cancel_reason',
        ]

    def validate_pay_amount(self, value):
        if value < Decimal('0'):
            raise serializers.ValidationError('实付金额不能为负')
        return value

    def validate_status(self, value):
        valid = {s.value for s in ServiceOrder.Status}
        if value not in valid:
            raise serializers.ValidationError(f'无效状态,可选值:{valid}')
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        old_status = instance.status
        old_pay = instance.pay_amount
        order = super().update(instance, validated_data)

        changes = []
        if order.status != old_status:
            changes.append(f'状态: {old_status}→{order.status}')
        if order.pay_amount != old_pay:
            changes.append(f'实付: {old_pay}→{order.pay_amount}')
        if changes:
            create_order_log(
                order.order_no, 'service', 'modify_price',
                request=self.context.get('request'), operator_type='admin',
                description='管理员修改: ' + ', '.join(changes),
            )
        return order


# ══════════════════════════════════════════════════════════════
# 管理端 — 强制操作
# ══════════════════════════════════════════════════════════════

class AdminForceStatusSerializer(serializers.Serializer):
    status = serializers.CharField(max_length=20)
    reason = serializers.CharField(max_length=300)

    def validate_status(self, value):
        valid = (
            {s.value for s in ProductOrder.Status}
            | {s.value for s in ServiceOrder.Status}
        )
        if value not in valid:
            raise serializers.ValidationError('无效状态值')
        return value


class AdminAdjustAmountSerializer(serializers.Serializer):
    pay_amount      = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    discount_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    freight_amount  = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    reason          = serializers.CharField(max_length=300)

    def validate(self, attrs):
        if not any(k in attrs for k in ('pay_amount', 'discount_amount', 'freight_amount')):
            raise serializers.ValidationError('至少修改一项金额')
        for key in ('pay_amount', 'discount_amount', 'freight_amount'):
            val = attrs.get(key)
            if val is not None and val < Decimal('0'):
                raise serializers.ValidationError({key: '金额不能为负'})
        return attrs


# ══════════════════════════════════════════════════════════════
# 员工端 — 服务订单 (修复重复定义)
# ══════════════════════════════════════════════════════════════

class StaffServiceOrderListSerializer(serializers.ModelSerializer):
    """员工端 — 我接的订单列表"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    short_address  = serializers.CharField(read_only=True)
    items_summary  = serializers.SerializerMethodField()

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no',
            'service_type', 'service_mode',
            'pay_amount',
            'status', 'status_display',
            'receiver_name', 'receiver_phone', 'short_address',
            'appointment_date', 'appointment_start', 'appointment_end',
            'is_urgent', 'urgent_surcharge',
            'items_summary',
            'assigned_at', 'created_at',
        ]

    def get_items_summary(self, obj):
        first = obj.items.first()
        return first.service_name if first else ''


class StaffServiceOrderDetailSerializer(serializers.ModelSerializer):
    """
    员工端 — 服务订单详情
    含:客户联系方式、完整地址、预约时间、服务项、特殊要求、转单历史
    不含:商家内部信息、金币抵扣明细
    """
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items = ServiceOrderItemSerializer(many=True, read_only=True)
    full_address = serializers.CharField(read_only=True)
    short_address = serializers.CharField(read_only=True)
    transfer_records = OrderTransferSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'order_no',
            'service_type', 'service_mode', 'schedule_type',
            'total_amount', 'pay_amount',
            'status', 'status_display',
        ] + _SERVICE_RECEIVER_FIELDS + [
            'full_address', 'short_address',
            'appointment_date', 'appointment_start', 'appointment_end',
            'is_urgent', 'urgent_surcharge',
            'assigned_at',
            'transfer_count', 'max_transfer_count',
            'verify_code', 'verify_expire_at', 'verified_at',
            'extra_info', 'remark',
            'paid_at', 'service_start_at', 'service_end_at',
            'completed_at', 'created_at',
            'items', 'transfer_records',
        ]