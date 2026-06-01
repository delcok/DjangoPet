# -*- coding: utf-8 -*-
from django.db import models
from django.db.models import Avg


class ReviewStatusMixin(models.Model):
    """
    评价状态通用基类
    """
    class Status(models.TextChoices):
        PENDING = 'pending', '待审核'
        APPROVED = 'approved', '已通过'
        REJECTED = 'rejected', '已拒绝'
        HIDDEN = 'hidden', '已隐藏'

    class Meta:
        abstract = True


# ============================================================
# 1. 商品评价
# ============================================================

class ProductReview(ReviewStatusMixin):
    """
    商品整单评价（绑定商品订单）
    - 一笔商品订单一条主评价
    - 具体每个商品的评价拆到 ProductReviewItem
    """

    order = models.OneToOneField(
        'bill.ProductOrder',
        on_delete=models.CASCADE,
        related_name='review',
        verbose_name='商品订单'
    )
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='product_reviews',
        verbose_name='用户'
    )

    merchant_id = models.PositiveIntegerField(
        db_index=True,
        verbose_name='商家ID'
    )
    merchant_name = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='商家名称快照'
    )

    logistics_score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='物流评分'
    )
    service_score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='商家服务评分'
    )
    content = models.TextField(
        blank=True,
        default='',
        verbose_name='整单评价内容'
    )

    is_anonymous = models.BooleanField(
        default=False,
        verbose_name='是否匿名'
    )
    has_images = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='是否有图片'
    )

    status = models.CharField(
        max_length=20,
        choices=ReviewStatusMixin.Status.choices,
        default=ReviewStatusMixin.Status.PENDING,
        db_index=True,
        verbose_name='审核状态'
    )

    replied_content = models.TextField(
        blank=True,
        default='',
        verbose_name='商家回复'
    )
    replied_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='回复时间'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='评价时间'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间'
    )

    class Meta:
        db_table = 'product_review'
        verbose_name = '商品评价'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['merchant_id', 'status', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['has_images', 'status', '-created_at']),
        ]

    def __str__(self):
        return f'商品评价-{self.order.order_no}'

    @property
    def avg_item_score(self):
        data = self.items.aggregate(avg=Avg('score'))
        return data['avg'] or 0

    def sync_has_images(self):
        has_images = self.images.exists() or self.items.filter(has_images=True).exists()
        if self.has_images != has_images:
            self.has_images = has_images
            self.save(update_fields=['has_images', 'updated_at'])


class ProductReviewItem(models.Model):
    """
    商品评价明细（绑定商品订单项）
    - 一条订单项对应一条评价明细
    - 用于商品详情页、SKU维度统计和展示
    """

    review = models.ForeignKey(
        ProductReview,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='商品评价'
    )
    order_item = models.OneToOneField(
        'bill.ProductOrderItem',
        on_delete=models.CASCADE,
        related_name='review_item',
        verbose_name='商品订单项'
    )

    goods = models.ForeignKey(
        'product.Goods',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='review_items',
        verbose_name='商品'
    )
    sku = models.ForeignKey(
        'product.GoodsSku',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='review_items',
        verbose_name='SKU'
    )

    goods_id_snapshot = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='商品ID快照'
    )
    sku_id_snapshot = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='SKU ID快照'
    )
    goods_title = models.CharField(
        max_length=200,
        verbose_name='商品名称快照'
    )
    goods_image = models.CharField(
        max_length=500,
        blank=True,
        default='',
        verbose_name='商品图片快照'
    )
    sku_text = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='规格快照'
    )

    score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='总体评分'
    )
    quality_score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='商品质量评分'
    )
    match_score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='描述相符评分'
    )
    content = models.TextField(
        blank=True,
        default='',
        verbose_name='商品评价内容'
    )

    has_images = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='是否有图片'
    )
    like_count = models.PositiveIntegerField(
        default=0,
        verbose_name='点赞数'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间'
    )

    class Meta:
        db_table = 'product_review_item'
        verbose_name = '商品评价明细'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['goods', '-created_at']),
            models.Index(fields=['sku', '-created_at']),
            models.Index(fields=['goods_id_snapshot', '-created_at']),
            models.Index(fields=['score', '-created_at']),
            models.Index(fields=['has_images', '-created_at']),
        ]

    def __str__(self):
        return f'{self.goods_title} - {self.score}星'

    def sync_has_images(self):
        has_images = self.images.exists()
        if self.has_images != has_images:
            self.has_images = has_images
            self.save(update_fields=['has_images', 'updated_at'])


class ProductReviewImage(models.Model):
    """
    商品评价图片
    - 可以挂在整单评价上
    - 也可以挂在某个商品评价明细上
    """
    review = models.ForeignKey(
        ProductReview,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='商品评价',
        null=True,
        blank=True,
    )
    review_item = models.ForeignKey(
        ProductReviewItem,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='商品评价明细',
        null=True,
        blank=True,
    )
    image = models.CharField(
        max_length=500,
        verbose_name='评价图片'
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='排序'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间'
    )

    class Meta:
        db_table = 'product_review_image'
        verbose_name = '商品评价图片'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['review', 'sort_order']),
            models.Index(fields=['review_item', 'sort_order']),
        ]

    def __str__(self):
        return self.image


# ============================================================
# 2. 服务评价
# ============================================================

class ServiceReview(ReviewStatusMixin):
    """
    服务评价
    - 一笔服务订单一条评价
    - 适合你当前的 ServiceOrder 结构
    - 当前通常一个订单一个服务项，后续如果扩套餐也能继续兼容
    """

    order = models.OneToOneField(
        'bill.ServiceOrder',
        on_delete=models.CASCADE,
        related_name='review',
        verbose_name='服务订单'
    )
    order_item = models.ForeignKey(
        'bill.ServiceOrderItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviews',
        verbose_name='服务订单项'
    )

    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='service_reviews',
        verbose_name='用户'
    )

    merchant_id = models.PositiveIntegerField(
        db_index=True,
        verbose_name='商家ID'
    )
    merchant_name = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='商家名称快照'
    )

    service = models.ForeignKey(
        'services.Service',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviews',
        verbose_name='服务'
    )

    service_id_snapshot = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='服务ID快照'
    )
    service_name = models.CharField(
        max_length=200,
        verbose_name='服务名称快照'
    )
    service_image = models.CharField(
        max_length=500,
        blank=True,
        default='',
        verbose_name='服务图片快照'
    )
    spec_name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='规格快照'
    )

    score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='总体评分'
    )
    attitude_score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='服务态度评分'
    )
    professional_score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='专业能力评分'
    )
    punctuality_score = models.PositiveSmallIntegerField(
        default=5,
        verbose_name='准时评分'
    )
    content = models.TextField(
        blank=True,
        default='',
        verbose_name='评价内容'
    )

    is_anonymous = models.BooleanField(
        default=False,
        verbose_name='是否匿名'
    )
    has_images = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='是否有图片'
    )

    # 员工快照（如果服务有派单员工）
    staff_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='员工ID快照'
    )
    staff_name = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='员工姓名快照'
    )

    # 服务时间快照
    service_start_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='服务开始时间快照'
    )
    service_end_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='服务结束时间快照'
    )

    status = models.CharField(
        max_length=20,
        choices=ReviewStatusMixin.Status.choices,
        default=ReviewStatusMixin.Status.PENDING,
        db_index=True,
        verbose_name='审核状态'
    )

    replied_content = models.TextField(
        blank=True,
        default='',
        verbose_name='商家回复'
    )
    replied_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='回复时间'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='评价时间'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间'
    )

    class Meta:
        db_table = 'service_review'
        verbose_name = '服务评价'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['merchant_id', 'status', '-created_at']),
            models.Index(fields=['service', '-created_at']),
            models.Index(fields=['service_id_snapshot', '-created_at']),
            models.Index(fields=['staff_id', '-created_at']),
            models.Index(fields=['score', '-created_at']),
            models.Index(fields=['has_images', 'status', '-created_at']),
        ]

    def __str__(self):
        return f'服务评价-{self.order.order_no}'

    def sync_has_images(self):
        has_images = self.images.exists()
        if self.has_images != has_images:
            self.has_images = has_images
            self.save(update_fields=['has_images', 'updated_at'])


class ServiceReviewImage(models.Model):
    """
    服务评价图片
    """
    review = models.ForeignKey(
        ServiceReview,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='服务评价'
    )
    image = models.CharField(
        max_length=500,
        verbose_name='评价图片'
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='排序'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间'
    )

    class Meta:
        db_table = 'service_review_image'
        verbose_name = '服务评价图片'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['review', 'sort_order']),
        ]

    def __str__(self):
        return self.image