from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from user.models import User, UserAddress


class IntegralProduct(models.Model):
    """
    积分商品模型
    """
    PRODUCT_TYPE_CHOICES = [
        ('virtual', '虚拟物品'),
        ('physical', '实物商品'),
    ]

    STATUS_CHOICES = [
        ('on_sale', '上架中'),
        ('off_sale', '已下架'),
        ('sold_out', '已售罄'),
    ]

    # 基本信息
    name = models.CharField(max_length=100, verbose_name='商品名称')
    description = models.TextField(verbose_name='商品描述')
    cover_image = models.URLField(max_length=500, verbose_name='封面图片')
    images = models.JSONField(default=list, verbose_name='商品图片列表')

    # 分类
    product_type = models.CharField(
        max_length=10,
        choices=PRODUCT_TYPE_CHOICES,
        verbose_name='商品类型'
    )
    category = models.CharField(max_length=50, blank=True, verbose_name='商品分类')

    # 积分相关
    integral_price = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        verbose_name='积分价格'
    )
    original_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='原价（参考）'
    )

    # 库存
    stock = models.PositiveIntegerField(default=0, verbose_name='库存数量')
    total_stock = models.PositiveIntegerField(default=0, verbose_name='总库存')
    sales_count = models.PositiveIntegerField(default=0, verbose_name='销量')

    # 限购
    limit_per_user = models.PositiveIntegerField(
        default=0,
        verbose_name='每人限购数量（0为不限）'
    )

    # 状态
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='on_sale',
        verbose_name='商品状态'
    )

    # 排序和展示
    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    is_hot = models.BooleanField(default=False, verbose_name='热门推荐')
    is_new = models.BooleanField(default=False, verbose_name='新品')

    # 虚拟物品特有字段
    virtual_content = models.TextField(
        blank=True,
        verbose_name='虚拟物品内容（如优惠券码、卡密等）'
    )
    validity_days = models.PositiveIntegerField(
        default=0,
        verbose_name='有效天数（0为永久）'
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'integral_products'
        verbose_name = '积分商品'
        verbose_name_plural = '积分商品'
        ordering = ['-sort_order', '-created_at']
        indexes = [
            models.Index(fields=['product_type', 'status']),
            models.Index(fields=['-sort_order']),
            models.Index(fields=['is_hot', 'is_new']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_product_type_display()})"

    @property
    def is_available(self):
        """检查商品是否可兑换"""
        return self.status == 'on_sale' and self.stock > 0

    def reduce_stock(self, quantity=1):
        """减少库存"""
        if self.stock >= quantity:
            self.stock -= quantity
            self.sales_count += quantity
            if self.stock == 0:
                self.status = 'sold_out'
            self.save(update_fields=['stock', 'sales_count', 'status'])
            return True
        return False

    def restore_stock(self, quantity=1):
        """恢复库存"""
        self.stock += quantity
        if self.status == 'sold_out':
            self.status = 'on_sale'
        self.save(update_fields=['stock', 'status'])


class IntegralOrder(models.Model):
    """
    积分订单模型
    """
    STATUS_CHOICES = [
        ('pending', '待发货'),
        ('shipped', '已发货'),
        ('completed', '已完成'),
        ('cancelled', '已取消'),
    ]

    # 订单信息
    order_no = models.CharField(max_length=32, unique=True, verbose_name='订单号')
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='integral_orders',
        verbose_name='用户'
    )
    product = models.ForeignKey(
        IntegralProduct,
        on_delete=models.PROTECT,
        verbose_name='商品'
    )

    # 商品快照
    product_snapshot = models.JSONField(verbose_name='商品快照')
    quantity = models.PositiveIntegerField(default=1, verbose_name='数量')
    integral_cost = models.PositiveIntegerField(verbose_name='消耗积分')

    # 收货信息（仅实物商品）
    address = models.ForeignKey(
        UserAddress,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='收货地址'
    )
    receiver_name = models.CharField(max_length=30, blank=True, verbose_name='收货人')
    receiver_phone = models.CharField(max_length=17, blank=True, verbose_name='联系电话')
    receiver_address = models.CharField(max_length=300, blank=True, verbose_name='收货地址')

    # 物流信息
    express_company = models.CharField(max_length=50, blank=True, verbose_name='快递公司')
    express_no = models.CharField(max_length=50, blank=True, verbose_name='快递单号')

    # 状态
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='订单状态'
    )

    # 备注
    user_remark = models.CharField(max_length=200, blank=True, verbose_name='用户备注')
    admin_remark = models.CharField(max_length=200, blank=True, verbose_name='管理员备注')

    # 时间记录
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    shipped_at = models.DateTimeField(null=True, blank=True, verbose_name='发货时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name='取消时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'integral_orders'
        verbose_name = '积分订单'
        verbose_name_plural = '积分订单'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_no']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"{self.order_no} - {self.user.display_name}"

    def generate_order_no(self):
        """生成订单号"""
        import time
        timestamp = int(time.time() * 1000)
        return f"INT{timestamp}{self.user.id:06d}"

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = self.generate_order_no()
        super().save(*args, **kwargs)


class IntegralRecord(models.Model):
    """
    积分变动记录
    """
    RECORD_TYPE_CHOICES = [
        ('earn', '获得'),
        ('consume', '消耗'),
        ('refund', '退还'),
        ('admin_adjust', '管理员调整'),
    ]

    SOURCE_CHOICES = [
        ('exchange', '兑换商品'),
        ('refund', '订单退款'),
        ('sign_in', '签到奖励'),
        ('task', '任务奖励'),
        ('post', '发帖奖励'),
        ('comment', '评论奖励'),
        ('share', '分享奖励'),
        ('invite', '邀请奖励'),
        ('admin', '管理员操作'),
        ('other', '其他'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='integral_records',
        verbose_name='用户'
    )
    record_type = models.CharField(
        max_length=15,
        choices=RECORD_TYPE_CHOICES,
        verbose_name='记录类型'
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        verbose_name='来源'
    )
    amount = models.IntegerField(verbose_name='积分变动数量')
    balance = models.IntegerField(verbose_name='变动后余额')

    # 关联订单
    order = models.ForeignKey(
        IntegralOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='关联订单'
    )

    description = models.CharField(max_length=200, verbose_name='描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'integral_records'
        verbose_name = '积分记录'
        verbose_name_plural = '积分记录'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['record_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.display_name} - {self.get_record_type_display()} {self.amount}"


class UserIntegralProduct(models.Model):
    """
    用户拥有的虚拟商品
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='virtual_products',
        verbose_name='用户'
    )
    product = models.ForeignKey(
        IntegralProduct,
        on_delete=models.PROTECT,
        verbose_name='商品'
    )
    order = models.ForeignKey(
        IntegralOrder,
        on_delete=models.PROTECT,
        verbose_name='订单'
    )

    # 虚拟物品信息
    content = models.TextField(verbose_name='虚拟物品内容')
    code = models.CharField(max_length=100, blank=True, verbose_name='兑换码/卡密')

    # 状态
    is_used = models.BooleanField(default=False, verbose_name='是否已使用')
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='使用时间')

    # 有效期
    expired_at = models.DateTimeField(null=True, blank=True, verbose_name='过期时间')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='获得时间')

    class Meta:
        db_table = 'user_integral_products'
        verbose_name = '用户虚拟商品'
        verbose_name_plural = '用户虚拟商品'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['is_used']),
        ]

    def __str__(self):
        return f"{self.user.display_name} - {self.product.name}"

    @property
    def is_expired(self):
        """检查是否过期"""
        if self.expired_at:
            return timezone.now() > self.expired_at
        return False

    def use(self):
        """使用虚拟商品"""
        if not self.is_used and not self.is_expired:
            self.is_used = True
            self.used_at = timezone.now()
            self.save(update_fields=['is_used', 'used_at'])
            return True
        return False