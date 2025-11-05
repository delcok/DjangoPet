from django.db import models

from staff.models import Staff
from user.models import User
from service.models import ServiceModel, AdditionalService  # 导入服务模型


class Bill(models.Model):
    # 支付方式选择
    PAYMENT_CHOICES = [
        ('alipay', 'Alipay'),
        ('wechat', 'WeChat'),
        ('unionpay', 'UnionPay'),
        ('zhifubao', '支护宝'),
        ('other', 'Other'),
    ]

    # 交易类型
    TRANSACTION_TYPE_CHOICES = [
        ('payment', 'Payment'),  # 用户付款
        ('refund', 'Refund'),  # 用户退款
        ('recharge', 'Recharge'),  # 用户充值
    ]

    # 交易状态
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),  # 待处理
        ('completed', 'Completed'),  # 完成
        ('failed', 'Failed'),  # 失败
    ]

    out_trade_no = models.CharField(max_length=50, unique=True, db_index=True)  # 商户订单号
    wechat_transaction_id = models.CharField(max_length=50, null=True, blank=True)  # 微信订单号
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_bills", null=True, blank=True)  # 用户
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)  # 交易类型
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # 金额（元）
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)  # 支付方式
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')  # 交易状态
    created_at = models.DateTimeField(auto_now_add=True)  # 创建时间
    description = models.TextField(null=True, blank=True)  # 账单描述

    def __str__(self):
        return f"{self.transaction_type} - {self.out_trade_no}"


class ServiceOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', '待确认'),
        ('confirmed', '已确认'),
        ('in_progress', '服务中'),
        ('completed', '已完成'),
        ('cancelled', '已取消'),
    ]

    bill = models.OneToOneField(Bill, on_delete=models.CASCADE, related_name='service_order', verbose_name='账单')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='service_orders', verbose_name='用户')
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='service_orders', verbose_name='员工',
                              blank=True, null=True)
    pets = models.ManyToManyField("pet.Pet", verbose_name='服务宠物')

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

    # 地址信息
    service_address = models.TextField(verbose_name='服务地址')
    contact_phone = models.CharField(max_length=20, verbose_name='联系电话')

    # 价格信息
    base_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='基础服务价格')
    additional_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='附加服务价格')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='总价格')

    # 状态和备注
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='订单状态')
    customer_notes = models.TextField(blank=True, verbose_name='客户备注')
    staff_notes = models.TextField(blank=True, verbose_name='员工备注')

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '服务订单'
        verbose_name_plural = '服务订单'
        ordering = ['-created_at']

    def __str__(self):
        return f"订单#{self.id} - {self.user.username} - {self.scheduled_date}"

    def save(self, *args, **kwargs):
        # 自动计算总价格
        self.total_price = self.base_price + self.additional_price
        super().save(*args, **kwargs)

    def calculate_total_price(self):
        """
        计算订单总价格（基础服务 + 所有附加服务）
        注意：此方法需要在订单保存后且附加服务关联后调用
        """
        base_price = self.base_service.base_price if self.base_service else 0
        additional_price = sum(service.price for service in self.additional_services.all())
        return base_price + additional_price

    def update_prices(self):
        """
        更新订单价格字段
        在添加/修改服务后调用此方法来同步价格
        """
        self.base_price = self.base_service.base_price if self.base_service else 0
        self.additional_price = sum(service.price for service in self.additional_services.all())
        self.total_price = self.base_price + self.additional_price
        self.save()