from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid

from staff.models import Staff
from user.models import User


class BaseModel(models.Model):
    """基础模型，包含通用字段"""
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        abstract = True


# ==================== 商品分类 ====================

class Category(BaseModel):
    """商品分类"""
    name = models.CharField('分类名称', max_length=50)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='父分类'
    )
    icon_url = models.URLField('分类图标URL', max_length=500, blank=True)
    sort_order = models.IntegerField('排序', default=0)
    is_active = models.BooleanField('是否启用', default=True)

    class Meta:
        verbose_name = '商品分类'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name

    @property
    def full_name(self):
        """获取完整分类路径"""
        if self.parent:
            return f"{self.parent.full_name} > {self.name}"
        return self.name


# ==================== 商品状态选项 ====================

PRODUCT_STATUS_DRAFT = 0
PRODUCT_STATUS_ON_SALE = 1
PRODUCT_STATUS_OFF_SALE = 2
PRODUCT_STATUS_SOLD_OUT = 3

PRODUCT_STATUS_CHOICES = [
    (PRODUCT_STATUS_DRAFT, '草稿'),
    (PRODUCT_STATUS_ON_SALE, '在售'),
    (PRODUCT_STATUS_OFF_SALE, '下架'),
    (PRODUCT_STATUS_SOLD_OUT, '售罄'),
]


# ==================== 商品相关 ====================

class Product(BaseModel):
    """商品"""

    # 基本信息
    name = models.CharField('商品名称', max_length=200)
    subtitle = models.CharField('副标题', max_length=300, blank=True)
    description = models.TextField('商品详情', blank=True)

    # 分类
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products',
        verbose_name='商品分类'
    )

    # 价格信息
    price = models.DecimalField(
        '销售价格',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    original_price = models.DecimalField(
        '原价',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    cost_price = models.DecimalField(
        '成本价',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    # 库存
    stock = models.IntegerField('库存', default=0, validators=[MinValueValidator(0)])
    sales = models.IntegerField('销量', default=0, validators=[MinValueValidator(0)])

    # 封面图（主图）
    cover_image_url = models.URLField('封面图URL', max_length=500)

    # 状态
    status = models.IntegerField(
        '商品状态',
        choices=PRODUCT_STATUS_CHOICES,
        default=PRODUCT_STATUS_DRAFT
    )

    # 排序和推荐
    sort_order = models.IntegerField('排序', default=0)
    is_recommended = models.BooleanField('是否推荐', default=False)
    is_new = models.BooleanField('是否新品', default=False)
    is_hot = models.BooleanField('是否热销', default=False)

    # 宠物相关属性
    pet_type = models.CharField(
        '适用宠物类型',
        max_length=50,
        blank=True,
        help_text='如：猫、狗、通用等'
    )
    brand = models.CharField('品牌', max_length=100, blank=True)

    # 运费
    freight = models.DecimalField(
        '运费',
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )

    class Meta:
        verbose_name = '商品'
        verbose_name_plural = verbose_name
        ordering = ['-sort_order', '-created_at']

    def __str__(self):
        return self.name

    @property
    def is_on_sale(self):
        """是否在售"""
        return self.status == PRODUCT_STATUS_ON_SALE and self.stock > 0


class ProductImage(BaseModel):
    """商品图片"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='商品'
    )
    image_url = models.URLField('图片URL', max_length=500)
    sort_order = models.IntegerField('排序', default=0)
    is_main = models.BooleanField('是否主图', default=False)

    class Meta:
        verbose_name = '商品图片'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.product.name} - 图片{self.id}"


class ProductVideo(BaseModel):
    """商品视频"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='videos',
        verbose_name='商品'
    )
    video_url = models.URLField('视频URL', max_length=500)
    cover_url = models.URLField('视频封面URL', max_length=500, blank=True)
    title = models.CharField('视频标题', max_length=100, blank=True)
    duration = models.IntegerField('视频时长(秒)', null=True, blank=True)
    sort_order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '商品视频'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.product.name} - 视频{self.id}"


class ProductDetail(BaseModel):
    """商品详情图（富文本中的图片）"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='detail_images',
        verbose_name='商品'
    )
    image_url = models.URLField('详情图URL', max_length=500)
    sort_order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '商品详情图'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']


# ==================== SKU规格相关 ====================

class SpecificationName(BaseModel):
    """规格名称（如：颜色、尺寸、口味）"""
    name = models.CharField('规格名称', max_length=50)
    sort_order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '规格名称'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class SpecificationValue(BaseModel):
    """规格值（如：红色、XL、鸡肉味）"""
    spec_name = models.ForeignKey(
        SpecificationName,
        on_delete=models.CASCADE,
        related_name='values',
        verbose_name='规格名称'
    )
    value = models.CharField('规格值', max_length=50)
    sort_order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '规格值'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.spec_name.name}: {self.value}"


class ProductSpecification(BaseModel):
    """商品规格关联"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='specifications',
        verbose_name='商品'
    )
    spec_name = models.ForeignKey(
        SpecificationName,
        on_delete=models.CASCADE,
        verbose_name='规格名称'
    )
    spec_value = models.ForeignKey(
        SpecificationValue,
        on_delete=models.CASCADE,
        verbose_name='规格值'
    )

    class Meta:
        verbose_name = '商品规格'
        verbose_name_plural = verbose_name
        unique_together = ['product', 'spec_name', 'spec_value']


class SKU(BaseModel):
    """商品SKU（库存量单位）"""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='skus',
        verbose_name='商品'
    )
    sku_code = models.CharField('SKU编码', max_length=50, unique=True)
    name = models.CharField('SKU名称', max_length=200)

    # 规格值组合，JSON格式存储，如：{"颜色": "红色", "尺寸": "XL"}
    spec_values = models.JSONField('规格值组合', default=dict)

    # 价格和库存
    price = models.DecimalField(
        '销售价格',
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    original_price = models.DecimalField(
        '原价',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    cost_price = models.DecimalField(
        '成本价',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    stock = models.IntegerField('库存', default=0, validators=[MinValueValidator(0)])

    # SKU图片
    image_url = models.URLField('SKU图片URL', max_length=500, blank=True)

    is_active = models.BooleanField('是否启用', default=True)

    class Meta:
        verbose_name = 'SKU'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.product.name} - {self.name}"


# ==================== 订单状态选项 ====================

ORDER_STATUS_PENDING_PAYMENT = 0
ORDER_STATUS_PENDING_SHIPMENT = 1
ORDER_STATUS_SHIPPED = 2
ORDER_STATUS_COMPLETED = 3
ORDER_STATUS_CANCELLED = 4
ORDER_STATUS_REFUNDING = 5
ORDER_STATUS_REFUNDED = 6

ORDER_STATUS_CHOICES = [
    (ORDER_STATUS_PENDING_PAYMENT, '待支付'),
    (ORDER_STATUS_PENDING_SHIPMENT, '待发货'),
    (ORDER_STATUS_SHIPPED, '已发货'),
    (ORDER_STATUS_COMPLETED, '已完成'),
    (ORDER_STATUS_CANCELLED, '已取消'),
    (ORDER_STATUS_REFUNDING, '退款中'),
    (ORDER_STATUS_REFUNDED, '已退款'),
]

PAYMENT_METHOD_WECHAT = 1
PAYMENT_METHOD_ALIPAY = 2
PAYMENT_METHOD_BALANCE = 3

PAYMENT_METHOD_CHOICES = [
    (PAYMENT_METHOD_WECHAT, '微信支付'),
    (PAYMENT_METHOD_ALIPAY, '支付宝'),
    (PAYMENT_METHOD_BALANCE, '余额支付'),
]


# ==================== 订单相关 ====================

class Order(BaseModel):
    """订单"""

    # 订单号
    order_no = models.CharField('订单号', max_length=32, unique=True)


    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="mall_orders",
        verbose_name='用户'
    )

    # 订单状态
    status = models.IntegerField(
        '订单状态',
        choices=ORDER_STATUS_CHOICES,
        default=ORDER_STATUS_PENDING_PAYMENT
    )

    # 金额信息
    total_amount = models.DecimalField('商品总金额', max_digits=10, decimal_places=2)
    freight_amount = models.DecimalField('运费', max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField('优惠金额', max_digits=10, decimal_places=2, default=Decimal('0.00'))
    pay_amount = models.DecimalField('实付金额', max_digits=10, decimal_places=2)

    # 支付信息
    payment_method = models.IntegerField(
        '支付方式',
        choices=PAYMENT_METHOD_CHOICES,
        null=True,
        blank=True
    )
    payment_time = models.DateTimeField('支付时间', null=True, blank=True)
    payment_no = models.CharField('支付流水号', max_length=64, blank=True)

    # 收货地址（冗余存储，防止地址修改影响历史订单）
    receiver_name = models.CharField('收货人姓名', max_length=50)
    receiver_phone = models.CharField('收货人电话', max_length=20)
    receiver_province = models.CharField('省', max_length=50)
    receiver_city = models.CharField('市', max_length=50)
    receiver_district = models.CharField('区/县', max_length=50)
    receiver_address = models.CharField('详细地址', max_length=200)

    # 物流信息
    shipping_company = models.CharField('快递公司', max_length=50, blank=True)
    shipping_no = models.CharField('快递单号', max_length=50, blank=True)
    shipping_time = models.DateTimeField('发货时间', null=True, blank=True)

    # 其他
    remark = models.TextField('订单备注', blank=True)
    cancel_reason = models.CharField('取消原因', max_length=200, blank=True)
    complete_time = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        verbose_name = '订单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.order_no

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = self.generate_order_no()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_order_no():
        """生成订单号"""
        import time
        return f"{int(time.time() * 1000)}{uuid.uuid4().hex[:8].upper()}"

    @property
    def full_address(self):
        """完整收货地址"""
        return f"{self.receiver_province}{self.receiver_city}{self.receiver_district}{self.receiver_address}"


class OrderItem(BaseModel):
    """订单商品项"""
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='订单'
    )

    # 商品信息（冗余存储）
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='商品'
    )
    sku = models.ForeignKey(
        SKU,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='SKU'
    )

    # 快照信息（防止商品信息变更影响历史订单）
    product_name = models.CharField('商品名称', max_length=200)
    product_image = models.URLField('商品图片', max_length=500)
    sku_name = models.CharField('SKU名称', max_length=200, blank=True)
    spec_values = models.JSONField('规格值', default=dict)

    # 价格和数量
    price = models.DecimalField('单价', max_digits=10, decimal_places=2)
    quantity = models.IntegerField('数量', validators=[MinValueValidator(1)])
    total_amount = models.DecimalField('小计', max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = '订单商品'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.order.order_no} - {self.product_name}"

    def save(self, *args, **kwargs):
        self.total_amount = self.price * self.quantity
        super().save(*args, **kwargs)


class OrderLog(BaseModel):
    """订单操作日志"""
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='logs',
        verbose_name='订单'
    )
    action = models.CharField('操作', max_length=50)
    description = models.CharField('操作描述', max_length=200)
    operator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='操作人'
    )

    class Meta:
        verbose_name = '订单日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_no} - {self.action}"


# ==================== 购物车 ====================

class CartItem(BaseModel):
    """购物车项"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="cart_items",
        verbose_name='用户'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name='商品'
    )
    sku = models.ForeignKey(
        SKU,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name='SKU'
    )
    quantity = models.IntegerField('数量', default=1, validators=[MinValueValidator(1)])
    is_selected = models.BooleanField('是否选中', default=True)

    class Meta:
        verbose_name = '购物车'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'product', 'sku']

    def __str__(self):
        return f"{self.user} - {self.product.name}"


# ==================== 商品收藏 ====================

class ProductFavorite(BaseModel):
    """商品收藏"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="product_favorites",
        verbose_name='用户'
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='商品'
    )

    class Meta:
        verbose_name = '商品收藏'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'product']

    def __str__(self):
        return f"{self.user} - {self.product.name}"