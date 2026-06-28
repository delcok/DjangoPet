# -*- coding: utf-8 -*-

import logging
import time
import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# StaffTimeSlot 工具(给 ServiceOrder.force_transfer / OrderTransfer.confirm 共用)
# ════════════════════════════════════════════════════════════════════

def _create_staff_time_slot(order, staff):
    """
    为订单创建员工时段占用。仅对有明确预约时间的订单生效,幂等。
    失败仅记录日志,不抛异常(避免影响主业务事务)。
    """
    if not (order.appointment_date and order.appointment_start and order.appointment_end):
        return
    try:
        from staffs.models import StaffTimeSlot
        StaffTimeSlot.objects.get_or_create(
            staff=staff,
            service_order=order,
            defaults={
                'date':       order.appointment_date,
                'start_time': order.appointment_start,
                'end_time':   order.appointment_end,
                'status':     StaffTimeSlot.Status.BOOKED,
            },
        )
    except Exception:
        logger.exception(
            '创建员工时段失败 order=%s staff=%s',
            getattr(order, 'order_no', None), getattr(staff, 'id', None),
        )


def _cancel_staff_time_slot(order, staff):
    """撤销订单关联的员工时段。幂等,LOCKED 状态时段会被跳过。"""
    try:
        from staffs.models import StaffTimeSlot
        slots = StaffTimeSlot.objects.filter(
            staff=staff, service_order=order,
        ).exclude(status=StaffTimeSlot.Status.CANCELLED)
        for slot in slots:
            try:
                slot.cancel()
            except ValueError:
                logger.warning('员工时段已锁定,无法取消 slot_id=%s', slot.id)
    except Exception:
        logger.exception(
            '取消员工时段失败 order=%s staff=%s',
            getattr(order, 'order_no', None), getattr(staff, 'id', None),
        )


# ────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────

def generate_order_no(prefix='O'):
    """订单号:前缀 + 毫秒时间戳 + 6位随机"""
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{ts}{rand}"


def generate_verify_code(length=8):
    """
    生成 N 位数字核销码,默认 8 位。
    - 8 位 = 1 亿种组合,单商家活跃订单内碰撞概率近乎 0
    - 用 secrets 而不是 random,防止可预测序列被恶意猜测
    - 纯数字方便店员小键盘输入
    """
    import secrets
    return ''.join(secrets.choice('0123456789') for _ in range(length))

def generate_unique_verify_code(merchant_id, length=8, max_attempts=10):
    """
    生成同商家活跃订单内不冲突的核销码。

    ★ 同时检查 ServiceOrder 和 ProductOrder 的活跃码,避免跨表冲突。
    """
    service_active = [
        ServiceOrder.Status.PAID,
        ServiceOrder.Status.PENDING_ASSIGNMENT,
        ServiceOrder.Status.ASSIGNED,
        ServiceOrder.Status.IN_SERVICE,
        ServiceOrder.Status.PENDING_USE,
        ServiceOrder.Status.PENDING_DELIVERY,
    ]
    product_active = [
        ProductOrder.Status.PAID,
        ProductOrder.Status.PENDING_SHIPMENT,
        ProductOrder.Status.SHIPPED,
        ProductOrder.Status.PENDING_PICKUP,
    ]

    for _ in range(max_attempts):
        code = generate_verify_code(length)
        clash = (
            ServiceOrder.objects.filter(
                merchant_id=merchant_id, verify_code=code,
                status__in=service_active,
            ).exists()
            or ProductOrder.objects.filter(
                merchant_id=merchant_id, verify_code=code,
                status__in=product_active,
            ).exists()
        )
        if not clash:
            return code

    raise RuntimeError(
        f'连续 {max_attempts} 次生成核销码均冲突,'
        f'merchant_id={merchant_id},请检查活跃订单数量'
    )
# ════════════════════════════════════════════════════════════════════
# 1. 商品订单 (不变)
# ════════════════════════════════════════════════════════════════════

class ProductOrder(models.Model):
    """
    商品订单
    状态流(快递)      : 待支付 → 已支付 → 待发货 → 已发货 → 已收货 → 已完成
    状态流(到门核销)  : 待支付 → 已支付 → 待发货 → 已发货 → 已核销 → 已完成
    状态流(自提)      : 待支付 → 已支付 → 待发货 → 待自提 → 已核销 → 已完成
    """

    class Status(models.TextChoices):
        PENDING_PAYMENT  = 'pending_payment',  '待支付'
        PAID             = 'paid',             '已支付'
        PENDING_SHIPMENT = 'pending_shipment', '待发货'
        SHIPPED          = 'shipped',          '已发货'
        RECEIVED         = 'received',         '已收货'
        PENDING_PICKUP   = 'pending_pickup',   '待自提'
        VERIFIED         = 'verified',         '已核销'
        COMPLETED        = 'completed',        '已完成'
        CANCELLED        = 'cancelled',        '已取消'
        REFUNDING        = 'refunding',        '退款中'
        REFUNDED         = 'refunded',         '已退款'

    class DeliveryType(models.TextChoices):
        HOME_DELIVERY = 'home_delivery', '送货上门'
        SELF_PICKUP   = 'self_pickup',   '到店自提'

    order_no = models.CharField(max_length=32, unique=True, verbose_name='订单号')
    user = models.ForeignKey(
        'user.User', on_delete=models.CASCADE,
        related_name='product_orders', verbose_name='用户',
    )
    merchant_id = models.PositiveIntegerField(db_index=True, verbose_name='商家ID')
    merchant_name = models.CharField(max_length=50, blank=True, default='', verbose_name='商家名称(快照)')

    # ── 金额 ──
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='商品总金额')
    freight_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name='运费',
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name='优惠金额',
    )
    coin_deduct_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name='金币抵扣金额(快照)',
    )
    coins_deducted = models.PositiveIntegerField(default=0, verbose_name='使用金币数(快照)')
    # ── 优惠券 ──
    user_coupon = models.ForeignKey(
        'campaigns.UserCoupon',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(class)s_orders',
        verbose_name='使用的优惠券',
    )
    coupon_deduct_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name='优惠券抵扣金额',
    )
    pay_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='实付金额')

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING_PAYMENT, db_index=True, verbose_name='订单状态',
    )

    # ── 收货地址快照 ──
    receiver_name = models.CharField(max_length=50, blank=True, default='', verbose_name='收货人')
    receiver_phone = models.CharField(max_length=20, blank=True, default='', verbose_name='收货人电话')
    receiver_address_type = models.CharField(
        max_length=20, blank=True, default='community', verbose_name='地址类型',
    )
    receiver_province = models.CharField(max_length=20, blank=True, default='', verbose_name='省')
    receiver_city = models.CharField(max_length=20, blank=True, default='', verbose_name='市')
    receiver_district = models.CharField(max_length=20, blank=True, default='', verbose_name='区')
    receiver_community = models.CharField(max_length=100, blank=True, default='', verbose_name='小区/社区')
    receiver_building = models.CharField(max_length=30, blank=True, default='', verbose_name='楼栋')
    receiver_unit = models.CharField(max_length=20, blank=True, default='', verbose_name='单元')
    receiver_room = models.CharField(max_length=30, blank=True, default='', verbose_name='门牌号')
    receiver_street = models.CharField(max_length=200, blank=True, default='', verbose_name='街道地址')
    receiver_house_number = models.CharField(max_length=50, blank=True, default='', verbose_name='门牌/房号')
    receiver_address = models.CharField(max_length=200, blank=True, default='', verbose_name='详细地址')
    receiver_access = models.TextField(blank=True, default='', verbose_name='入户说明')

    # ── 配送 ──
    delivery_type = models.CharField(
        max_length=20, choices=DeliveryType.choices,
        default=DeliveryType.HOME_DELIVERY, db_index=True, verbose_name='配送方式',
    )
    pickup_address = models.CharField(max_length=200, blank=True, default='', verbose_name='自提点地址')
    pickup_contact = models.CharField(max_length=50, blank=True, default='', verbose_name='自提点联系电话')
    pickup_deadline = models.DateTimeField(null=True, blank=True, verbose_name='自提截止时间')

    # ── 物流 ──
    shipping_company = models.CharField(max_length=50, blank=True, default='', verbose_name='快递公司')
    shipping_no = models.CharField(max_length=50, blank=True, default='', verbose_name='快递单号')
    shipped_at = models.DateTimeField(null=True, blank=True, verbose_name='发货时间')

    # ── 核销 ──
    verify_code = models.CharField(
        max_length=10, blank=True, default='', db_index=True, verbose_name='核销码',
    )
    verify_expire_at = models.DateTimeField(null=True, blank=True, verbose_name='核销码过期时间')
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name='核销时间')
    verified_by_staff = models.ForeignKey(
        'staffs.Staff', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_product_orders', verbose_name='核销员工',
    )

    # ── 奖励快照 ──
    points_earned = models.PositiveIntegerField(default=0, verbose_name='获得积分(快照)')
    gold_earned = models.PositiveIntegerField(default=0, verbose_name='获得金币(快照)')

    # ── 其他 ──
    remark = models.TextField(blank=True, default='', verbose_name='用户备注')
    cancel_reason = models.CharField(max_length=200, blank=True, default='', verbose_name='取消原因')
    is_reviewed = models.BooleanField(default=False, db_index=True, verbose_name='是否已评价')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='评价时间')
    # ── 用户软删除(仅影响用户自己的列表,不影响商家/对账)──
    user_deleted = models.BooleanField(default=False, db_index=True, verbose_name='用户已删除')
    user_deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='用户删除时间')

    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    # ── 结算 ──
    is_settled = models.BooleanField(default=False, db_index=True, verbose_name='是否已结算')
    settle_due_at = models.DateTimeField(null=True, blank=True, verbose_name='结算到期时间')
    settled_at = models.DateTimeField(null=True, blank=True, verbose_name='实际结算时间')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'product_order'
        verbose_name = '商品订单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', '-created_at']),
            models.Index(fields=['merchant_id', 'status', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['verify_code']),
            models.Index(fields=['delivery_type', 'status', '-created_at']),
            # ★ 新增:同商家未核销的活跃码必须唯一(对齐 ServiceOrder)
            models.Index(
                fields=['merchant_id', 'verify_code'],
                name='prod_order_merchant_code_idx',
                condition=models.Q(verify_code__gt='') & models.Q(verified_at__isnull=True),
            ),
        ]
        # ★ 新增:同商家活跃订单内 verify_code 不能重复
        constraints = [
            models.UniqueConstraint(
                fields=['merchant_id', 'verify_code'],
                condition=models.Q(verify_code__gt='') & models.Q(verified_at__isnull=True),
                name='uniq_active_verify_code_per_product_merchant',
            ),
        ]

    def __str__(self):
        return self.order_no

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = generate_order_no('P')
        super().save(*args, **kwargs)

    @property
    def full_address(self):
        prefix = f"{self.receiver_province}{self.receiver_city}{self.receiver_district}"
        return f"{prefix}{self.receiver_address}" if prefix else self.receiver_address

    @property
    def short_address(self):
        if self.receiver_address_type == 'community':
            parts = [
                self.receiver_community, self.receiver_building,
                self.receiver_unit, self.receiver_room,
            ]
            return ' '.join(p for p in parts if p)
        return self.receiver_address or ''

    @property
    def is_paid(self):
        return self.status not in (self.Status.PENDING_PAYMENT, self.Status.CANCELLED)

    @property
    def can_user_delete(self):
        """用户是否可删除(软删除):仅终态订单"""
        return self.status in (
            self.Status.COMPLETED,
            self.Status.CANCELLED,
            self.Status.REFUNDED,
        )


class ProductOrderItem(models.Model):
    """商品订单明细(快照)"""

    order = models.ForeignKey(
        ProductOrder, on_delete=models.CASCADE, related_name='items', verbose_name='订单',
    )
    product_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='商品ID')
    sku_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='SKU ID')

    product_name = models.CharField(max_length=200, verbose_name='商品名称')
    product_image = models.CharField(max_length=500, blank=True, default='', verbose_name='商品图片')
    sku_text = models.CharField(max_length=200, blank=True, default='', verbose_name='规格描述')

    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='单价')
    quantity = models.PositiveIntegerField(default=1, verbose_name='数量')
    item_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='小计')

    is_reviewed = models.BooleanField(default=False, db_index=True, verbose_name='是否已评价')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='评价时间')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'product_order_item'
        verbose_name = '商品订单明细'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.order.order_no} - {self.product_name}"

    def save(self, *args, **kwargs):
        self.item_amount = self.unit_price * self.quantity
        super().save(*args, **kwargs)


# ════════════════════════════════════════════════════════════════════
# 2. 服务订单 (重构后)
# ════════════════════════════════════════════════════════════════════

class ServiceOrder(models.Model):
    """
    服务订单(4 种 service_type 共用)

    ─────────── 各类型状态流 ───────────

    walk_in 到店制:
        pending_payment → paid → pending_use → completed
        (或 cancelled / refunding / refunded)

    appointment 预约制 + customer (客户选时段):
        pending_payment → paid → assigned(锁了员工时段)
        → in_service → completed (上门/取送)
        或 pending_payment → paid → assigned → in_service → pending_use → completed (到店)

    appointment 预约制 + merchant (商家协商):
        pending_payment → paid → pending_assignment → assigned
        → in_service → completed

    on_demand 按需制:
        pending_payment → paid → pending_accept(自动派单中)
        → assigned → in_service → delivering → completed
        (或 pending_assignment 走商家手动派单)

    scheduled 周期制(订阅):
        pending_payment → paid → subscribing(订阅活跃期)
        → completed (全部 DeliverySchedule 完成)
        每次配送由 DeliverySchedule 单独管理生命周期
    """

    class Status(models.TextChoices):
        PENDING_PAYMENT    = 'pending_payment',    '待支付'
        PAID               = 'paid',               '已支付'
        PENDING_ACCEPT     = 'pending_accept',     '待员工接单'   # on_demand 自动派单中
        PENDING_ASSIGNMENT = 'pending_assignment', '待派单'       # 商家手动派单
        ASSIGNED           = 'assigned',           '已派单'
        IN_SERVICE         = 'in_service',         '服务中'
        PENDING_USE        = 'pending_use',        '待核销'        # 到店服务等用户核销
        VERIFIED           = 'verified',           '已核销'
        PENDING_DELIVERY   = 'pending_delivery',   '待配送'        # on_demand 派单完成等出发
        DELIVERING         = 'delivering',         '配送中'
        SUBSCRIBING        = 'subscribing',        '订阅中'        # ★ 新增:scheduled 订阅活跃期
        COMPLETED          = 'completed',          '已完成'
        CANCELLED          = 'cancelled',          '已取消'
        REFUNDING          = 'refunding',          '退款中'
        REFUNDED           = 'refunded',           '已退款'

    # ════ 基本信息 ════
    order_no = models.CharField(max_length=32, unique=True, verbose_name='订单号')
    user = models.ForeignKey(
        'user.User', on_delete=models.CASCADE,
        related_name='service_orders', verbose_name='用户',
    )
    merchant_id = models.PositiveIntegerField(db_index=True, verbose_name='商家ID')
    merchant_name = models.CharField(max_length=50, blank=True, default='', verbose_name='商家名称(快照)')

    # ════ 服务类型快照 ════
    service_type = models.CharField(
        max_length=20,
        choices=[
            ('walk_in',     '到店制'),
            ('appointment', '预约制'),
            ('on_demand',   '按需制'),
            ('scheduled',   '周期制'),
        ],
        db_index=True, verbose_name='服务类型(快照)',
    )
    service_mode = models.CharField(
        max_length=20,
        choices=[
            ('store',  '到店服务'),
            ('home',   '上门服务'),
            ('pickup', '取送服务'),
        ],
        verbose_name='服务方式(快照)',
    )
    # ★ 仅在 service_type=appointment 时有意义,其他类型留空
    schedule_type = models.CharField(
        max_length=20,
        choices=[
            ('customer', '客户选时段'),
            ('merchant', '商家协商'),
        ],
        blank=True, default='',
        verbose_name='调度类型(快照,仅 appointment 有效)',
    )

    # ════ 金额 ════
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='服务总金额')
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name='优惠金额',
    )
    coin_deduct_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name='金币抵扣金额(快照)',
    )
    coins_deducted = models.PositiveIntegerField(default=0, verbose_name='使用金币数(快照)')
    # ── 优惠券 ──
    user_coupon = models.ForeignKey(
        'campaigns.UserCoupon',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(class)s_orders',
        verbose_name='使用的优惠券',
    )
    coupon_deduct_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name='优惠券抵扣金额',
    )
    deposit_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'), verbose_name='定金',
    )
    pay_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='实付金额')

    # ════ 配置快照(下单时从 service.* 复制,不受后续 service 变更影响) ════
    free_cancel_hours_snapshot = models.PositiveSmallIntegerField(
        default=0, verbose_name='免费取消时限(小时,快照)',
        help_text='下单时从 service.free_cancel_hours 复制',
    )
    delivery_fee_snapshot = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('0.00'),
        verbose_name='配送费(快照)',
        help_text='下单时从 service.effective_delivery_fee 复制',
    )
    points_reward_snapshot = models.PositiveIntegerField(
        default=0, verbose_name='完成赠送积分(快照)',
        help_text='下单时从 service.points_reward 复制',
    )
    urgent_config_snapshot = models.JSONField(
        null=True, blank=True, verbose_name='加急配置(快照)',
        help_text='下单时如果勾选了加急,从 service.urgent_config 复制 + 实际加价金额',
    )
    delivery_config_snapshot = models.JSONField(
        null=True, blank=True, verbose_name='周期配送配置(快照)',
        help_text='仅 scheduled 类型,从 service.delivery_config 完整复制,用于生成 DeliverySchedule',
    )

    # ════ 状态 ════
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING_PAYMENT, db_index=True, verbose_name='订单状态',
    )

    # ════ 地址快照 ════
    receiver_name = models.CharField(max_length=50, blank=True, default='', verbose_name='联系人')
    receiver_phone = models.CharField(max_length=20, blank=True, default='', verbose_name='联系电话')
    receiver_address_type = models.CharField(
        max_length=20, blank=True, default='community', verbose_name='地址类型',
    )
    receiver_province = models.CharField(max_length=20, blank=True, default='', verbose_name='省')
    receiver_city = models.CharField(max_length=20, blank=True, default='', verbose_name='市')
    receiver_district = models.CharField(max_length=20, blank=True, default='', verbose_name='区')
    receiver_community = models.CharField(max_length=100, blank=True, default='', verbose_name='小区/社区')
    receiver_building = models.CharField(max_length=30, blank=True, default='', verbose_name='楼栋')
    receiver_unit = models.CharField(max_length=20, blank=True, default='', verbose_name='单元')
    receiver_room = models.CharField(max_length=30, blank=True, default='', verbose_name='门牌号')
    receiver_street = models.CharField(max_length=200, blank=True, default='', verbose_name='街道地址')
    receiver_house_number = models.CharField(max_length=50, blank=True, default='', verbose_name='门牌/房号')
    receiver_address = models.CharField(max_length=200, blank=True, default='', verbose_name='详细地址')
    receiver_access = models.TextField(blank=True, default='', verbose_name='入户说明')
    receiver_lng = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True, verbose_name='地址经度',
    )
    receiver_lat = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True, verbose_name='地址纬度',
    )

    # ════ 预约时间(仅 appointment 类型用) ════
    appointment_date = models.DateField(null=True, blank=True, verbose_name='预约日期')
    appointment_start = models.TimeField(null=True, blank=True, verbose_name='预约开始时间')
    appointment_end = models.TimeField(null=True, blank=True, verbose_name='预约结束时间')
    # ★ 改为外键
    time_slot = models.ForeignKey(
        'services.ServiceTimeSlot', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders', verbose_name='预约时段',
    )

    # ════ 订阅信息(仅 scheduled 类型用) ════
    subscription_start_date = models.DateField(
        null=True, blank=True, db_index=True, verbose_name='订阅起始日',
    )
    subscription_end_date = models.DateField(
        null=True, blank=True, verbose_name='订阅截止日',
    )
    planned_delivery_count = models.PositiveSmallIntegerField(
        default=0, verbose_name='计划配送总次数',
        help_text='下单时按 cycle + 时长预算,如每周 1 次 × 12 周 = 12 次',
    )
    completed_delivery_count = models.PositiveSmallIntegerField(
        default=0, verbose_name='已完成配送次数',
    )
    is_paused = models.BooleanField(
        default=False, db_index=True, verbose_name='订阅是否暂停中',
    )
    pause_started_at = models.DateTimeField(
        null=True, blank=True, verbose_name='当前暂停开始时间',
    )
    total_paused_days = models.PositiveSmallIntegerField(
        default=0, verbose_name='累计暂停天数',
        help_text='所有暂停时长累加,用于延长订阅截止日',
    )

    # ════ 紧急服务 ════
    is_urgent = models.BooleanField(default=False, verbose_name='是否紧急服务')
    urgent_surcharge = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name='紧急加价金额',
    )

    # ════ 员工派单 ════
    assigned_staff = models.ForeignKey(
        'staffs.Staff', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_orders', verbose_name='指派员工',
    )
    assigned_at = models.DateTimeField(null=True, blank=True, verbose_name='派单时间')

    # ════ 转单 ════
    transfer_count = models.PositiveSmallIntegerField(default=0, verbose_name='累计转单次数')
    max_transfer_count = models.PositiveSmallIntegerField(
        default=3, verbose_name='最大转单次数',
    )

    # ════ 自动派单跟踪 ════
    dispatch_attempt_count = models.PositiveSmallIntegerField(
        default=0, verbose_name='累计派单尝试次数',
    )
    pending_accept_deadline = models.DateTimeField(
        null=True, blank=True, verbose_name='当前候选员工接单截止时间',
    )
    attempted_staff_ids = models.JSONField(
        default=list, blank=True,
        verbose_name='已尝试派单员工ID列表',
    )
    # ★ 新增:派单/配送时效跟踪(on_demand 类型用)
    dispatch_started_at = models.DateTimeField(
        null=True, blank=True, verbose_name='开始派单时间',
        help_text='支付完成后系统启动派单的时刻,用于统计响应时长',
    )
    estimated_arrival_at = models.DateTimeField(
        null=True, blank=True, verbose_name='预计送达/到达时间',
    )
    actual_arrival_at = models.DateTimeField(
        null=True, blank=True, verbose_name='实际送达/到达时间',
    )

    # ════ 核销 ════
    verify_code = models.CharField(
        max_length=10, blank=True, default='', db_index=True, verbose_name='核销码',
    )
    verify_expire_at = models.DateTimeField(null=True, blank=True, verbose_name='核销码过期时间')
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name='核销时间')
    verified_by_staff = models.ForeignKey(
        'staffs.Staff', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_orders', verbose_name='核销员工',
    )

    # ════ 下单附加信息(对应 service.required_info 收集的字段) ════
    extra_info = models.JSONField(
        default=dict, blank=True, verbose_name='下单附加信息',
        help_text='''按 service.required_info 收集,可能含:
        {
            "problem_desc": "...",
            "problem_images": [...],
            "party_size": 4,
            "remark": "..."
        }''',
    )

    # ════ 奖励快照 ════
    points_earned = models.PositiveIntegerField(default=0, verbose_name='获得积分(快照)')
    gold_earned = models.PositiveIntegerField(default=0, verbose_name='获得金币(快照)')

    # ════ 其他 ════
    remark = models.TextField(blank=True, default='', verbose_name='用户备注')
    cancel_reason = models.CharField(max_length=200, blank=True, default='', verbose_name='取消原因')
    is_reviewed = models.BooleanField(default=False, db_index=True, verbose_name='是否已评价')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='评价时间')

    # ── 用户软删除(仅影响用户自己的列表,不影响商家/对账)──
    user_deleted = models.BooleanField(default=False, db_index=True, verbose_name='用户已删除')
    user_deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='用户删除时间')

    # ════ 时间戳 ════
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    service_start_at = models.DateTimeField(null=True, blank=True, verbose_name='服务开始时间')
    service_end_at = models.DateTimeField(null=True, blank=True, verbose_name='服务结束时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    # ── 结算 ──
    is_settled = models.BooleanField(default=False, db_index=True, verbose_name='是否已结算')
    settle_due_at = models.DateTimeField(null=True, blank=True, verbose_name='结算到期时间')
    settled_at = models.DateTimeField(null=True, blank=True, verbose_name='实际结算时间')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_order'
        verbose_name = '服务订单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', '-created_at']),
            models.Index(fields=['merchant_id', 'status', '-created_at']),
            models.Index(fields=['assigned_staff', 'status']),
            models.Index(fields=['status', 'service_type']),
            models.Index(fields=['verify_code']),
            models.Index(fields=['merchant_id', 'status', 'is_urgent', '-created_at']),
            models.Index(fields=['status', 'pending_accept_deadline']),
            models.Index(fields=['service_type', 'status', 'subscription_end_date']),
            # ★ 新增: 同商家未核销的活跃码必须唯一
            models.Index(
                fields=['merchant_id', 'verify_code'],
                name='svc_order_merchant_code_idx',
                condition=models.Q(verify_code__gt='') & models.Q(verified_at__isnull=True),
            ),
        ]
        constraints = [
            # 同商家活跃订单内,verify_code 不能重复
            # condition 排除空码 / 已核销订单,允许复用
            models.UniqueConstraint(
                fields=['merchant_id', 'verify_code'],
                condition=models.Q(verify_code__gt='') & models.Q(verified_at__isnull=True),
                name='uniq_active_verify_code_per_merchant',
            ),
        ]

    def __str__(self):
        return self.order_no

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = generate_order_no('S')
        super().save(*args, **kwargs)

    # ── 派生属性 ─────────────────────────────────────

    @property
    def is_paid(self):
        return self.status not in (self.Status.PENDING_PAYMENT, self.Status.CANCELLED)

    @property
    def can_user_delete(self):
        """用户是否可删除(软删除):仅终态订单"""
        return self.status in (
            self.Status.COMPLETED,
            self.Status.CANCELLED,
            self.Status.REFUNDED,
        )

    @property
    def full_address(self):
        prefix = f"{self.receiver_province}{self.receiver_city}{self.receiver_district}"
        return f"{prefix}{self.receiver_address}" if prefix else self.receiver_address

    @property
    def short_address(self):
        if self.receiver_address_type == 'community':
            parts = [
                self.receiver_community, self.receiver_building,
                self.receiver_unit, self.receiver_room,
            ]
            return ' '.join(p for p in parts if p)
        return self.receiver_address or ''

    @property
    def can_transfer(self) -> bool:
        return self.transfer_count < self.max_transfer_count

    @property
    def is_subscription_active(self) -> bool:
        """订阅是否在活跃期(scheduled 专用)"""
        if self.service_type != 'scheduled':
            return False
        return (
            self.status in (self.Status.PAID, self.Status.SUBSCRIBING)
            and self.completed_delivery_count < self.planned_delivery_count
        )

    @property
    def remaining_delivery_count(self) -> int:
        """剩余配送次数(scheduled 专用)"""
        return max(0, self.planned_delivery_count - self.completed_delivery_count)

    @property
    def effective_subscription_end_date(self):
        """考虑暂停天数后的实际订阅截止日(scheduled 专用)"""
        if not self.subscription_end_date:
            return None
        from datetime import timedelta
        return self.subscription_end_date + timedelta(days=self.total_paused_days or 0)

    # ── 状态推进 ─────────────────────────────────────

    def assign_staff(self, staff):
        """指派员工(派单/转单完成时调用)"""
        self.assigned_staff = staff
        self.assigned_at = timezone.now()
        self.status = self.Status.ASSIGNED
        self.save(update_fields=['assigned_staff', 'assigned_at', 'status', 'updated_at'])

    def force_transfer(self, to_staff, *, initiated_by, reason=''):
        """
        强制改派 — 商家或管理员直接指定新员工,无需对方确认。
        立即生效,递增 transfer_count,创建 CONFIRMED 状态的 OrderTransfer 记录,
        自动撤销旧员工时段、创建新员工时段。
        """
        from django.db import transaction

        with transaction.atomic():
            order = ServiceOrder.objects.select_for_update().get(pk=self.pk)

            if order.status != self.Status.ASSIGNED:
                raise ValueError('只有已派单的订单可改派')
            if not order.can_transfer:
                raise ValueError(f'已达最大转单次数 {order.max_transfer_count}')
            if order.assigned_staff_id == to_staff.id:
                raise ValueError('不能改派给同一员工')

            from_staff = order.assigned_staff
            now = timezone.now()
            sequence = OrderTransfer.objects.filter(order=order).count() + 1

            record = OrderTransfer.objects.create(
                order=order,
                from_staff=from_staff,
                to_staff=to_staff,
                initiated_by=initiated_by,
                transfer_type=OrderTransfer.TransferType.FORCED,
                reason=reason,
                status=OrderTransfer.Status.CONFIRMED,
                sequence=sequence,
                confirm_deadline=now,
                confirmed_at=now,
            )

            order.transfer_count += 1
            order.assigned_staff = to_staff
            order.assigned_at = now
            order.save(update_fields=[
                'transfer_count', 'assigned_staff', 'assigned_at', 'updated_at',
            ])

            self.transfer_count = order.transfer_count
            self.assigned_staff = to_staff
            self.assigned_at = now

            if from_staff:
                _cancel_staff_time_slot(order, from_staff)
            _create_staff_time_slot(order, to_staff)

        return record

    def start_service(self):
        """员工开始服务 → IN_SERVICE"""
        if self.status != self.Status.ASSIGNED:
            raise ValueError(f'只有已派单的订单可开始服务,当前状态:{self.get_status_display()}')
        self.status = self.Status.IN_SERVICE
        self.service_start_at = timezone.now()
        self.save(update_fields=['status', 'service_start_at', 'updated_at'])

    def complete_service(self):
        """
        员工完成服务 → 直接 COMPLETED。

        设计说明:
          - 派给员工的订单(appointment/on_demand),员工是服务完成的权威。
          - 到店服务也一样:客户与员工在现场,员工点完成即视为完成,
            不再需要客户额外出示核销码"证明服务发生过"。
          - 核销码仅用于 walk_in(到店制) — 不派员工的自助核销场景,
            由商户端 verify / verify-by-code 接口处理,不走此方法。
          - scheduled 类型每次配送由 DeliverySchedule.mark_completed() 处理,
            也不走此方法。
        """
        if self.status != self.Status.IN_SERVICE:
            raise ValueError(f'只有服务中的订单可完成,当前状态:{self.get_status_display()}')

        now = timezone.now()
        self.status = self.Status.COMPLETED
        self.service_end_at = now
        self.completed_at = now
        self.save(update_fields=[
            'status', 'service_end_at', 'completed_at', 'updated_at',
        ])

    def verify_order(self, by_staff=None):
        """核销订单 → COMPLETED"""
        allowed = (self.Status.ASSIGNED, self.Status.IN_SERVICE, self.Status.PENDING_USE)
        if self.status not in allowed:
            raise ValueError(f'当前状态({self.get_status_display()})不可核销')

        now = timezone.now()
        self.verified_at = now
        if by_staff:
            self.verified_by_staff = by_staff
        self.status = self.Status.COMPLETED
        self.completed_at = now
        update_fields = ['verified_at', 'status', 'completed_at', 'updated_at']
        if by_staff:
            update_fields.append('verified_by_staff')
        if not self.service_start_at:
            self.service_start_at = now
            update_fields.append('service_start_at')
        if not self.service_end_at:
            self.service_end_at = now
            update_fields.append('service_end_at')
        self.save(update_fields=update_fields)

    # ── 订阅生命周期(scheduled 专用) ─────────────────

    def pause_subscription(self):
        """暂停订阅"""
        if self.service_type != 'scheduled':
            raise ValueError('只有周期制订单可暂停')
        if self.is_paused:
            raise ValueError('订阅已处于暂停状态')
        if self.status not in (self.Status.PAID, self.Status.SUBSCRIBING):
            raise ValueError(f'当前状态({self.get_status_display()})不可暂停')

        cfg = self.delivery_config_snapshot or {}
        if not cfg.get('allow_pause'):
            raise ValueError('该服务不允许暂停')

        self.is_paused = True
        self.pause_started_at = timezone.now()
        self.save(update_fields=['is_paused', 'pause_started_at', 'updated_at'])

    def resume_subscription(self):
        """恢复订阅"""
        if not self.is_paused:
            raise ValueError('订阅未处于暂停状态')
        if not self.pause_started_at:
            raise ValueError('缺少暂停时间记录')

        paused_days = (timezone.now().date() - self.pause_started_at.date()).days
        self.is_paused = False
        self.total_paused_days = (self.total_paused_days or 0) + max(0, paused_days)
        self.pause_started_at = None
        self.save(update_fields=[
            'is_paused', 'total_paused_days', 'pause_started_at', 'updated_at',
        ])

    def maybe_mark_subscription_completed(self):
        """检查所有配送是否完成,如果是则关闭订阅订单。由 DeliverySchedule 完成时调用。"""
        if self.service_type != 'scheduled':
            return
        if self.completed_delivery_count < self.planned_delivery_count:
            return
        if self.status == self.Status.COMPLETED:
            return
        now = timezone.now()
        self.status = self.Status.COMPLETED
        self.completed_at = now
        self.save(update_fields=['status', 'completed_at', 'updated_at'])


class ServiceOrderItem(models.Model):
    """
    服务订单明细(快照)

    ★ spec_key 是稳定标识,即使商家后续改了规格名,也能精确匹配回购买时的规格。
    服务订单通常只有 1 条 item,保留一对多结构以备套餐扩展。
    """

    order = models.ForeignKey(
        ServiceOrder, on_delete=models.CASCADE,
        related_name='items', verbose_name='订单',
    )
    service_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='服务ID',
    )

    # ── 服务快照 ──
    service_name = models.CharField(max_length=200, verbose_name='服务名称')
    service_image = models.CharField(
        max_length=500, blank=True, default='', verbose_name='服务封面图',
    )
    service_type = models.CharField(
        max_length=20, blank=True, default='', verbose_name='服务类型(快照)',
    )
    service_mode = models.CharField(
        max_length=20, blank=True, default='', verbose_name='服务方式(快照)',
    )

    # ── 规格快照 ──
    spec_key = models.CharField(
        max_length=50, blank=True, default='', db_index=True,
        verbose_name='规格 key(稳定标识)',
        help_text='对应 Service.specifications[].key,商家改规格名后仍可精确匹配',
    )
    spec_name = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='规格名称(快照)',
    )
    price_unit = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name='计价单位(快照)',
    )
    duration_minutes = models.PositiveSmallIntegerField(
        default=0, verbose_name='服务时长(分钟)',
    )

    # ── 价格 ──
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='单价',
    )
    quantity = models.PositiveIntegerField(default=1, verbose_name='数量')
    item_amount = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='小计',
    )

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'service_order_item'
        verbose_name = '服务订单明细'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['service_id', 'spec_key']),
        ]

    def __str__(self):
        return f"{self.order.order_no} - {self.service_name}"

    def save(self, *args, **kwargs):
        self.item_amount = self.unit_price * self.quantity
        super().save(*args, **kwargs)


# ════════════════════════════════════════════════════════════════════
# 2-2. 周期配送子记录 (★ 新增,scheduled 类型专用)
# ════════════════════════════════════════════════════════════════════

class DeliverySchedule(models.Model):
    """
    周期制订单的单次配送记录。

    每个 scheduled 类型的 ServiceOrder 下挂 N 条 DeliverySchedule(N = planned_delivery_count),
    按 delivery_config_snapshot 在创建订单时一次性预生成。

    单次生命周期:
        pending → assigned(分配员工) → delivering → completed
        或 skipped(暂停期/跳过日)/ cancelled(订阅取消时批量置)
    """

    class Status(models.TextChoices):
        PENDING    = 'pending',    '待配送'
        ASSIGNED   = 'assigned',   '已分配员工'
        DELIVERING = 'delivering', '配送中'
        COMPLETED  = 'completed',  '已完成'
        SKIPPED    = 'skipped',    '已跳过'
        CANCELLED  = 'cancelled',  '已取消'

    order = models.ForeignKey(
        ServiceOrder, on_delete=models.CASCADE,
        related_name='delivery_schedules',
        verbose_name='订阅订单',
    )
    sequence = models.PositiveSmallIntegerField(
        verbose_name='第 N 次配送',
        help_text='从 1 开始递增,用于排序展示',
    )
    scheduled_date = models.DateField(
        db_index=True, verbose_name='计划配送日期',
    )
    scheduled_window_start = models.TimeField(
        verbose_name='计划配送窗口开始',
        help_text='从 delivery_config.delivery_time_window.start 复制',
    )
    scheduled_window_end = models.TimeField(
        verbose_name='计划配送窗口结束',
    )
    quantity = models.PositiveSmallIntegerField(
        default=1, verbose_name='本次配送数量',
        help_text='从 delivery_config.quantity_per_delivery 复制',
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True, verbose_name='状态',
    )

    # ── 派单(每次配送可分配不同员工) ──
    assigned_staff = models.ForeignKey(
        'staffs.Staff', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='delivery_schedules', verbose_name='配送员',
    )
    assigned_at = models.DateTimeField(null=True, blank=True, verbose_name='派单时间')

    # ── 完成 / 跳过 ──
    actual_delivered_at = models.DateTimeField(
        null=True, blank=True, verbose_name='实际配送完成时间',
    )
    skip_reason = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='跳过原因',
        help_text='如"客户暂停"、"周末跳过"、"节假日"',
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'delivery_schedule'
        verbose_name = '周期配送记录'
        verbose_name_plural = verbose_name
        ordering = ['order', 'sequence']
        unique_together = ['order', 'sequence']
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['scheduled_date', 'status']),
            models.Index(fields=['assigned_staff', 'scheduled_date', 'status']),
        ]

    def __str__(self):
        return f"{self.order.order_no} 第{self.sequence}次 - {self.scheduled_date}"

    def assign(self, staff):
        """分配配送员"""
        if self.status not in (self.Status.PENDING, self.Status.ASSIGNED):
            raise ValueError(f'当前状态({self.get_status_display()})不可分配')
        self.assigned_staff = staff
        self.assigned_at = timezone.now()
        self.status = self.Status.ASSIGNED
        self.save(update_fields=['assigned_staff', 'assigned_at', 'status', 'updated_at'])

    def start_delivering(self):
        """开始配送"""
        if self.status != self.Status.ASSIGNED:
            raise ValueError(f'只有已派单状态可开始配送,当前:{self.get_status_display()}')
        self.status = self.Status.DELIVERING
        self.save(update_fields=['status', 'updated_at'])

    def mark_completed(self, by_staff=None):
        """配送完成"""
        if self.status not in (self.Status.ASSIGNED, self.Status.DELIVERING):
            raise ValueError(f'状态({self.get_status_display()})无法完成')

        from django.db import transaction
        from django.db.models import F

        with transaction.atomic():
            now = timezone.now()
            self.status = self.Status.COMPLETED
            self.actual_delivered_at = now
            if by_staff and not self.assigned_staff_id:
                self.assigned_staff = by_staff
            self.save(update_fields=[
                'status', 'actual_delivered_at', 'assigned_staff', 'updated_at',
            ])

            # 父订单累加完成数(原子更新)
            ServiceOrder.objects.filter(pk=self.order_id).update(
                completed_delivery_count=F('completed_delivery_count') + 1,
            )

            # 检查是否全部完成
            order = ServiceOrder.objects.get(pk=self.order_id)
            order.maybe_mark_subscription_completed()

    def skip(self, reason: str = ''):
        """跳过本次配送(暂停期 / 客户主动跳)"""
        if self.status != self.Status.PENDING:
            raise ValueError('只有待配送状态可跳过')
        self.status = self.Status.SKIPPED
        self.skip_reason = reason or '已跳过'
        self.save(update_fields=['status', 'skip_reason', 'updated_at'])

    def cancel(self, reason: str = ''):
        """取消(订阅取消时由父订单批量调用)"""
        if self.status in (self.Status.COMPLETED, self.Status.CANCELLED):
            return
        self.status = self.Status.CANCELLED
        if reason:
            self.skip_reason = reason[:100]
        self.save(update_fields=['status', 'skip_reason', 'updated_at'])


# ════════════════════════════════════════════════════════════════════
# 3. 转单记录 (不变)
# ════════════════════════════════════════════════════════════════════

class OrderTransfer(models.Model):

    class InitiatedBy(models.TextChoices):
        STAFF    = 'staff',    '员工主动申请'
        SYSTEM   = 'system',   '系统自动转单'
        MERCHANT = 'merchant', '商家手动指派'

    class TransferType(models.TextChoices):
        INITIAL   = 'initial',   '首次派单'
        VOLUNTARY = 'voluntary', '主动转单'
        FORCED    = 'forced',    '强制转派'

    class Status(models.TextChoices):
        PENDING   = 'pending',   '待确认'
        CONFIRMED = 'confirmed', '已确认'
        TIMEOUT   = 'timeout',   '确认超时'
        CANCELLED = 'cancelled', '已取消'

    order = models.ForeignKey(
        ServiceOrder, on_delete=models.CASCADE,
        related_name='transfer_records', verbose_name='服务订单',
    )
    from_staff = models.ForeignKey(
        'staffs.Staff', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transfers_out', verbose_name='转出员工',
    )
    to_staff = models.ForeignKey(
        'staffs.Staff', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transfers_in', verbose_name='接收员工',
    )
    initiated_by = models.CharField(
        max_length=20, choices=InitiatedBy.choices, verbose_name='发起方',
    )
    transfer_type = models.CharField(
        max_length=20, choices=TransferType.choices,
        default=TransferType.VOLUNTARY, verbose_name='转单类型',
    )
    reason = models.CharField(
        max_length=200, blank=True, default='', verbose_name='转单原因',
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True, verbose_name='状态',
    )
    sequence = models.PositiveSmallIntegerField(default=1, verbose_name='第N次转单')
    confirm_deadline = models.DateTimeField(verbose_name='确认截止时间')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='确认时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'order_transfer'
        verbose_name = '转单记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['to_staff', 'status']),
            models.Index(fields=['status', 'confirm_deadline']),
        ]

    def __str__(self):
        return f"订单{self.order.order_no} 第{self.sequence}次转单 → {self.to_staff}"

    def confirm(self):
        """
        接收方确认接单(低层 API,业务推荐用 bill.services.dispatch.staff_accept)。
        transfer_count 语义:仅当 from_staff 非空时才递增。
        """
        from django.db import transaction

        with transaction.atomic():
            rec = OrderTransfer.objects.select_for_update().get(pk=self.pk)
            if rec.status != self.Status.PENDING:
                raise ValueError('只有待确认的转单才能被确认')
            if not rec.to_staff_id:
                raise ValueError('转单接收员工未确定')

            order = ServiceOrder.objects.select_for_update().get(pk=rec.order_id)

            if rec.from_staff_id and not order.can_transfer:
                raise ValueError('已达最大转单次数')

            now = timezone.now()
            rec.status = self.Status.CONFIRMED
            rec.confirmed_at = now
            rec.save(update_fields=['status', 'confirmed_at'])

            had_from_staff = bool(rec.from_staff_id)

            if had_from_staff and rec.from_staff_id != rec.to_staff_id:
                _cancel_staff_time_slot(order, rec.from_staff)

            if had_from_staff:
                order.transfer_count += 1
            order.assigned_staff = rec.to_staff
            order.assigned_at = now
            order.status = ServiceOrder.Status.ASSIGNED
            order.pending_accept_deadline = None
            update_fields = [
                'assigned_staff', 'assigned_at', 'status',
                'pending_accept_deadline', 'updated_at',
            ]
            if had_from_staff:
                update_fields.append('transfer_count')
            order.save(update_fields=update_fields)

            _create_staff_time_slot(order, rec.to_staff)

            self.status = rec.status
            self.confirmed_at = rec.confirmed_at

    def mark_timeout(self):
        if self.status != self.Status.PENDING:
            return
        self.status = self.Status.TIMEOUT
        self.save(update_fields=['status'])

    def cancel(self, reason: str = ''):
        if self.status == self.Status.CANCELLED:
            return
        if self.status != self.Status.PENDING:
            raise ValueError(
                f'当前状态({self.get_status_display()})不可取消,只有待确认状态可取消'
            )
        self.status = self.Status.CANCELLED
        if reason:
            self.reason = (self.reason + ' | 取消: ' + reason)[:200]
        self.save(update_fields=['status', 'reason'])


# ════════════════════════════════════════════════════════════════════
# 4. 订单操作日志 (不变)
# ════════════════════════════════════════════════════════════════════

class OrderLog(models.Model):

    class Action(models.TextChoices):
        CREATE           = 'create',           '创建订单'
        PAY              = 'pay',              '支付成功'
        PAY_FAIL         = 'pay_fail',         '支付失败'
        SHIP             = 'ship',             '商家发货'
        RECEIVE          = 'receive',          '确认收货'
        ASSIGN           = 'assign',           '派单'
        TRANSFER         = 'transfer',         '转单'
        TRANSFER_CONFIRM = 'transfer_confirm', '转单确认'
        TRANSFER_TIMEOUT = 'transfer_timeout', '转单超时'
        SERVICE_START    = 'service_start',    '服务开始'
        VERIFY           = 'verify',           '核销'
        COMPLETE         = 'complete',         '订单完成'
        CANCEL           = 'cancel',           '取消订单'
        REFUND_APPLY     = 'refund_apply',     '申请退款'
        REFUND_APPROVE   = 'refund_approve',   '退款通过'
        REFUND_REJECT    = 'refund_reject',    '退款驳回'
        MODIFY_PRICE     = 'modify_price',     '修改价格'
        COIN_DEDUCT      = 'coin_deduct',      '金币抵扣'
        COIN_GRANT       = 'coin_grant',       '金币发放'
        POINTS_GRANT     = 'points_grant',     '积分发放'
        DELIVERY_DONE    = 'delivery_done',    '配送完成'  # ★ scheduled 子单完成
        SUBSCRIPTION_PAUSE  = 'subscription_pause',  '订阅暂停'  # ★ 新增
        SUBSCRIPTION_RESUME = 'subscription_resume', '订阅恢复'  # ★ 新增
        SYSTEM_AUTO      = 'system_auto',      '系统自动'

    class OperatorType(models.TextChoices):
        USER     = 'user',     '用户'
        STAFF    = 'staff',    '员工'
        MERCHANT = 'merchant', '商家'
        ADMIN    = 'admin',    '管理员'
        SYSTEM   = 'system',   '系统'

    class OrderType(models.TextChoices):
        PRODUCT = 'product', '商品订单'
        SERVICE = 'service', '服务订单'

    order_no = models.CharField(max_length=32, db_index=True, verbose_name='订单号')
    order_type = models.CharField(max_length=20, choices=OrderType.choices, verbose_name='订单类型')
    action = models.CharField(max_length=30, choices=Action.choices, verbose_name='操作')
    description = models.CharField(max_length=300, blank=True, default='', verbose_name='操作描述')
    operator_type = models.CharField(
        max_length=20, choices=OperatorType.choices,
        default=OperatorType.SYSTEM, verbose_name='操作人类型',
    )
    operator_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='操作人ID')
    operator_name = models.CharField(max_length=30, blank=True, default='', verbose_name='操作人名称')
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='操作时间')

    class Meta:
        db_table = 'order_log'
        verbose_name = '订单日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_no', '-created_at']),
            models.Index(fields=['order_type', 'action']),
        ]

    def __str__(self):
        return f"{self.order_no} - {self.get_action_display()}"