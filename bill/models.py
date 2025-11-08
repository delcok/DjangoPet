# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Modified for better order flow

from django.db import models
from django.core.validators import MinValueValidator
from staff.models import Staff
from user.models import User
from service.models import ServiceModel, AdditionalService


class ServiceOrder(models.Model):
    """服务订单 - 先创建服务订单，后创建支付订单"""
    STATUS_CHOICES = [
        ('draft', '待支付'),  # 新增：创建后待支付状态
        ('paid', '已支付'),  # 新增：支付成功后的状态
        ('confirmed', '已确认'),  # 支付后商家确认
        ('assigned', '已分配'),  # 分配给员工
        ('in_progress', '服务中'),
        ('completed', '已完成'),
        ('cancelled', '已取消'),
        ('refunded', '已退款'),  # 新增：退款状态
    ]

    # 用户和员工
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='service_orders', verbose_name='用户')
    staff = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        related_name='service_orders',
        verbose_name='服务员工',
        blank=True,
        null=True
    )

    # 服务宠物
    pets = models.ManyToManyField("pet.Pet", verbose_name='服务宠物')

    # 服务内容
    base_service = models.ForeignKey(
        ServiceModel,
        on_delete=models.PROTECT,
        related_name='orders',
        verbose_name='基础服务'
    )
    additional_services = models.ManyToManyField(
        AdditionalService,
        blank=True,
        related_name='orders',
        verbose_name='附加服务'
    )

    # 服务时间
    scheduled_date = models.DateField(verbose_name='预约日期')
    scheduled_time = models.TimeField(verbose_name='预约时间')
    duration_minutes = models.PositiveIntegerField(default=60, verbose_name='预计时长（分钟）')

    province = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    city = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    district = models.CharField(max_length=10, blank=True, null=True, db_index=True)

    # 地址信息
    service_address = models.TextField(verbose_name='服务地址')
    contact_phone = models.CharField(max_length=20, verbose_name='联系电话')
    contact_name = models.CharField(max_length=50, verbose_name='联系人', blank=True)

    # 价格信息（创建订单时计算并保存）
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='基础服务价格',
        validators=[MinValueValidator(0)]
    )
    additional_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='附加服务价格',
        validators=[MinValueValidator(0)]
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='总价格',
        validators=[MinValueValidator(0)]
    )

    # 优惠信息（可选）
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='优惠金额',
        validators=[MinValueValidator(0)]
    )
    final_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='最终支付价格',
        validators=[MinValueValidator(0)]
    )

    # 状态和备注
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name='订单状态',
        db_index=True
    )
    customer_notes = models.TextField(blank=True, verbose_name='客户备注')
    staff_notes = models.TextField(blank=True, verbose_name='员工备注')
    cancel_reason = models.TextField(blank=True, verbose_name='取消原因')

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')

    class Meta:
        verbose_name = '服务订单'
        verbose_name_plural = '服务订单'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['scheduled_date', 'scheduled_time']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"订单#{self.id} - {self.user.username} - {self.scheduled_date}"

    def calculate_prices(self):
        """
        计算订单价格
        注意：此方法只能在对象已保存且多对多关系已设置后调用
        """
        # 基础服务价格
        self.base_price = self.base_service.base_price if self.base_service else 0

        # 附加服务总价
        # 修复：检查对象是否已保存（有 pk），才能访问多对多关系
        if self.pk:
            self.additional_price = sum(
                service.price for service in self.additional_services.all()
            )
        else:
            # 如果对象还没保存，additional_price 应该已经在创建时设置了
            pass

        # 总价
        self.total_price = self.base_price + self.additional_price

        # 最终价格（考虑优惠）
        self.final_price = max(0, self.total_price - self.discount_amount)

        return self.final_price

    def save(self, *args, **kwargs):
        """
        保存方法
        修复：不在新建订单时自动调用 calculate_prices()
        因为创建时多对多关系还未设置，会导致错误
        """
        # 移除自动计算价格的逻辑，改为在 serializer 中手动计算
        # 只确保最终价格的一致性
        if self.total_price is not None and self.discount_amount is not None:
            self.final_price = max(0, self.total_price - self.discount_amount)

        super().save(*args, **kwargs)

    def can_cancel(self):
        """检查订单是否可以取消"""
        return self.status in ['draft', 'paid', 'confirmed']

    def can_refund(self):
        """检查订单是否可以退款"""
        return self.status in ['paid', 'confirmed', 'assigned']


class Bill(models.Model):
    """账单/支付订单 - 基于服务订单创建"""

    # 支付方式
    PAYMENT_CHOICES = [
        ('wechat', '微信支付'),
        ('alipay', '支付宝'),
        ('balance', '余额支付'),
        ('cash', '现金支付'),
        ('other', '其他'),
    ]

    # 交易类型
    TRANSACTION_TYPE_CHOICES = [
        ('payment', '订单支付'),  # 服务订单支付
        ('refund', '订单退款'),  # 服务订单退款
        ('recharge', '余额充值'),  # 用户充值
        ('withdraw', '余额提现'),  # 用户提现
    ]

    # 支付状态
    PAYMENT_STATUS_CHOICES = [
        ('pending', '待支付'),
        ('processing', '处理中'),  # 支付处理中
        ('success', '支付成功'),
        ('failed', '支付失败'),
        ('cancelled', '已取消'),
        ('refunded', '已退款'),
    ]

    # 订单号
    out_trade_no = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name='商户订单号'
    )
    third_party_no = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name='第三方订单号',
        help_text='微信/支付宝等第三方支付订单号'
    )

    # 关联
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bills",
        verbose_name='用户'
    )
    service_order = models.ForeignKey(
        ServiceOrder,
        on_delete=models.CASCADE,
        related_name='bills',
        verbose_name='服务订单',
        null=True,
        blank=True,
        help_text='关联的服务订单（充值等操作可能没有服务订单）'
    )

    # 交易信息
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPE_CHOICES,
        verbose_name='交易类型',
        db_index=True
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='交易金额',
        validators=[MinValueValidator(0)],
        help_text='单位：元'
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_CHOICES,
        verbose_name='支付方式'
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending',
        verbose_name='支付状态',
        db_index=True
    )

    # 附加信息
    description = models.TextField(
        null=True,
        blank=True,
        verbose_name='账单描述'
    )
    failure_reason = models.TextField(
        null=True,
        blank=True,
        verbose_name='失败原因'
    )

    # 退款相关
    refund_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='退款金额',
        validators=[MinValueValidator(0)]
    )
    refund_reason = models.TextField(
        blank=True,
        verbose_name='退款原因'
    )
    original_bill = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='refund_bills',
        verbose_name='原支付订单',
        help_text='如果是退款订单，关联原支付订单'
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    expired_at = models.DateTimeField(null=True, blank=True, verbose_name='过期时间')

    class Meta:
        verbose_name = '支付订单'
        verbose_name_plural = '支付订单'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'payment_status']),
            models.Index(fields=['service_order', 'payment_status']),
            models.Index(fields=['out_trade_no']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.out_trade_no} - ¥{self.amount}"

    @classmethod
    def generate_trade_no(cls, prefix='PAY'):
        """生成唯一的商户订单号"""
        import uuid
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_id = str(uuid.uuid4())[:8].upper()
        return f"{prefix}{timestamp}{unique_id}"

    def save(self, *args, **kwargs):
        # 自动生成订单号
        if not self.out_trade_no:
            prefix_map = {
                'payment': 'PAY',
                'refund': 'REF',
                'recharge': 'RCG',
                'withdraw': 'WTD',
            }
            prefix = prefix_map.get(self.transaction_type, 'BIL')
            self.out_trade_no = self.generate_trade_no(prefix)

        super().save(*args, **kwargs)

    def mark_as_paid(self, third_party_no=None):
        """标记为已支付"""
        from django.utils import timezone

        self.payment_status = 'success'
        self.paid_at = timezone.now()
        if third_party_no:
            self.third_party_no = third_party_no
        self.save()

        # 如果有关联的服务订单，更新其状态
        if self.service_order and self.transaction_type == 'payment':
            self.service_order.status = 'paid'
            self.service_order.paid_at = self.paid_at
            self.service_order.save()

    def mark_as_failed(self, reason=None):
        """标记为支付失败"""
        self.payment_status = 'failed'
        if reason:
            self.failure_reason = reason
        self.save()