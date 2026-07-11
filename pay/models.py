import time
import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


def generate_payment_no():
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().hex[:6].upper()
    return f"PAY{ts}{rand}"


def generate_refund_no():
    ts = int(time.time() * 1000)
    rand = uuid.uuid4().hex[:6].upper()
    return f"REF{ts}{rand}"


# ============================================================
#  支付单
#
#  职责边界：只记录"这笔钱怎么付的"，不碰商家余额。
#  支付成功后由 payment.services.handle_payment_success() 通知
#  wallet 模块完成结算，payment 本身不 import wallet models。
# ============================================================

class PaymentOrder(models.Model):
    """
    支付记录 —— 每次支付尝试一条记录。
    一个业务订单可能产生多次支付尝试（超时重试），只有一条会成功。

    流程：
    1. 用户点击支付 → 创建 PaymentOrder（pending）
    2. 后端调渠道 API → 拿到支付参数返给前端
    3. 前端调起支付 → 渠道回调 → mark_paid
    4. mark_paid 成功后 → payment.services 调 wallet.services 结算
    5. 超时 → 定时任务 → mark_closed
    """

    CHANNEL_CHOICES = [
        ('wechat_mini', '微信小程序支付'),
        ('wechat_app',  '微信App支付'),
        ('wechat_h5',   '微信H5支付'),
        ('wechat_virtual', '微信小程序虚拟支付'),
        ('alipay',      '支付宝'),
        ('balance',     '余额支付'),
    ]

    STATUS_CHOICES = [
        ('pending', '待支付'),
        ('paid',    '已支付'),
        ('failed',  '支付失败'),
        ('closed',  '已关闭'),
    ]

    # ---------- 标识 ----------
    payment_no = models.CharField(
        max_length=32, unique=True, verbose_name='支付单号'
    )
    # 发给渠道的商户订单号（微信 out_trade_no）
    out_trade_no = models.CharField(
        max_length=64, unique=True, verbose_name='商户订单号'
    )
    # 渠道返回的交易号（微信 transaction_id）
    channel_trade_no = models.CharField(
        max_length=64, blank=True, default='',
        db_index=True, verbose_name='渠道交易号'
    )
    order_type = models.CharField(
        max_length=10,
        choices=[('product', '商品订单'), ('service', '服务订单'), ('recharge', '充值订单')],
        default='product',
        verbose_name='订单类型'
    )

    # ---------- 关联 ----------
    order_no = models.CharField(
        max_length=32, db_index=True, verbose_name='业务订单号'
    )
    user_id = models.PositiveIntegerField(
        db_index=True, verbose_name='用户ID'
    )
    merchant_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='商家ID'
    )

    # ---------- 支付信息 ----------
    channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, verbose_name='支付渠道'
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='支付金额(元)'
    )
    amount_in_cents = models.PositiveIntegerField(
        default=0, verbose_name='支付金额(分)'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='pending', db_index=True, verbose_name='支付状态'
    )

    # ---------- 渠道交互 ----------
    pay_params = models.JSONField(
        null=True, blank=True, verbose_name='返给前端的支付参数'
    )
    callback_raw = models.TextField(
        blank=True, default='', verbose_name='回调原始数据'
    )

    # ---------- 环境信息 ----------
    pay_platform = models.CharField(
        max_length=20, blank=True, default='', verbose_name='发起平台'
    )
    pay_ip = models.GenericIPAddressField(
        null=True, blank=True, verbose_name='支付IP'
    )

    # ---------- 时间 ----------
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付成功时间')
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name='关闭时间')
    expire_at = models.DateTimeField(null=True, blank=True, verbose_name='过期时间')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_orders'
        verbose_name = '支付单'
        verbose_name_plural = '支付单'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_no', '-created_at']),
            models.Index(fields=['user_id', '-created_at']),
            models.Index(fields=['status', 'expire_at']),
        ]

    def __str__(self):
        return f"{self.payment_no} {self.amount}元 {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self.payment_no:
            self.payment_no = generate_payment_no()
        if not self.amount_in_cents and self.amount:
            self.amount_in_cents = int(self.amount * 100)
        super().save(*args, **kwargs)

    @property
    def is_payable(self):
        if self.status != 'pending':
            return False
        if self.expire_at and timezone.now() > self.expire_at:
            return False
        return True

    def mark_paid(self, channel_trade_no, callback_raw=''):
        """
        标记支付成功。
        注意：不在此处触发结算，由 payment.services.handle_payment_success() 负责
        调用 wallet.services.settle_order_income() 完成商家入账。
        """
        self.status = 'paid'
        self.channel_trade_no = channel_trade_no
        self.callback_raw = callback_raw
        self.paid_at = timezone.now()
        self.save(update_fields=[
            'status', 'channel_trade_no', 'callback_raw',
            'paid_at', 'updated_at',
        ])

    def mark_closed(self):
        self.status = 'closed'
        self.closed_at = timezone.now()
        self.save(update_fields=['status', 'closed_at', 'updated_at'])


# ============================================================
#  退款单
#
#  职责边界：只记录"这笔钱怎么退的"，退款成功后由
#  payment.services.handle_refund_success() 通知 wallet 模块
#  做对应的余额扣回，payment 本身不 import wallet models。
# ============================================================

class PaymentRefund(models.Model):
    """退款记录，关联原支付单，支持全额退和部分退。"""

    STATUS_CHOICES = [
        ('pending', '退款中'),
        ('success', '退款成功'),
        ('failed',  '退款失败'),
    ]

    REASON_CHOICES = [
        ('user_cancel',     '用户取消'),
        ('merchant_cancel', '商家取消'),
        ('admin_cancel',    '管理员取消'),
        ('service_issue',   '服务问题'),
        ('product_issue',   '商品问题'),
        ('other',           '其他'),
    ]

    # ---------- 标识 ----------
    refund_no = models.CharField(
        max_length=32, unique=True, verbose_name='退款单号'
    )
    channel_refund_no = models.CharField(
        max_length=64, blank=True, default='', verbose_name='渠道退款号'
    )

    # ---------- 关联 ----------
    payment_order = models.ForeignKey(
        PaymentOrder, on_delete=models.CASCADE,
        related_name='refunds', verbose_name='原支付单'
    )
    order_no = models.CharField(
        max_length=32, db_index=True, verbose_name='业务订单号'
    )
    user_id = models.PositiveIntegerField(verbose_name='用户ID')

    # ---------- 退款信息 ----------
    refund_amount = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='退款金额(元)'
    )
    refund_amount_in_cents = models.PositiveIntegerField(
        default=0, verbose_name='退款金额(分)'
    )
    reason = models.CharField(
        max_length=20, choices=REASON_CHOICES,
        default='other', verbose_name='退款原因'
    )
    reason_detail = models.CharField(
        max_length=200, blank=True, default='', verbose_name='退款原因详情'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='pending', db_index=True, verbose_name='退款状态'
    )
    callback_raw = models.TextField(
        blank=True, default='', verbose_name='退款回调原始数据'
    )

    # ---------- 操作人 ----------
    operator_type = models.CharField(
        max_length=20, blank=True, default='', verbose_name='操作人类型'
    )
    operator_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='操作人ID'
    )

    # ---------- 时间 ----------
    refunded_at = models.DateTimeField(null=True, blank=True, verbose_name='退款成功时间')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_refunds'
        verbose_name = '退款单'
        verbose_name_plural = '退款单'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_no']),
            models.Index(fields=['payment_order', '-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.refund_no} 退款{self.refund_amount}元"

    def save(self, *args, **kwargs):
        if not self.refund_no:
            self.refund_no = generate_refund_no()
        if not self.refund_amount_in_cents and self.refund_amount:
            self.refund_amount_in_cents = int(self.refund_amount * 100)
        super().save(*args, **kwargs)

    def mark_success(self, channel_refund_no='', callback_raw=''):
        """
        标记退款成功。
        商家余额扣回由 payment.services.handle_refund_success() 调
        wallet.services.deduct_merchant_income() 完成。
        """
        self.status = 'success'
        self.channel_refund_no = channel_refund_no
        self.callback_raw = callback_raw
        self.refunded_at = timezone.now()
        self.save(update_fields=[
            'status', 'channel_refund_no', 'callback_raw',
            'refunded_at', 'updated_at',
        ])

    def mark_failed(self, callback_raw=''):
        self.status = 'failed'
        self.callback_raw = callback_raw
        self.save(update_fields=['status', 'callback_raw', 'updated_at'])