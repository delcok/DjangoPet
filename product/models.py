# -*- coding: utf-8 -*-

from django.db import models, transaction
from django.db.models import F


# ============================================================
# 1. 平台商品分类(管理员维护)
# ============================================================
class GoodsCategory(models.Model):
    """
    平台商品分类 —— 仅管理员可创建/编辑。
    支持多级,商家上架商品时选择叶子分类。
    """

    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='children',
        verbose_name='上级分类'
    )
    name = models.CharField(max_length=30, verbose_name='分类名称')
    icon = models.CharField(max_length=500, blank=True, default='', verbose_name='分类图标')
    image = models.CharField(max_length=500, blank=True, default='', verbose_name='分类图片')
    description = models.CharField(max_length=200, blank=True, default='', verbose_name='分类描述')
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='默认佣金率(%)',
        help_text='该分类下的默认抽成比例,商品可单独覆盖'
    )
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='是否启用')
    is_show_home = models.BooleanField(default=False, verbose_name='首页展示')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'goods_category'
        verbose_name = '商品分类'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['parent', 'is_active']),
            models.Index(fields=['is_show_home', 'sort_order']),
        ]

    def __str__(self):
        return self.name

    @property
    def level(self):
        """分类层级(1=一级)"""
        lv, p = 1, self.parent
        while p:
            lv += 1
            p = p.parent
        return lv


# ============================================================
# 2. 商家自定义店铺分组(商家维护)
# ============================================================
class MerchantGoodsGroup(models.Model):
    """商家自定义商品分组 —— 仅控制店铺内展示。"""

    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        related_name='goods_groups',
        verbose_name='所属商家'
    )
    name = models.CharField(max_length=30, verbose_name='分组名称')
    icon = models.CharField(max_length=500, blank=True, default='', verbose_name='分组图标')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    description = models.TextField(blank=True, default='', verbose_name='描述介绍')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_goods_group'
        verbose_name = '商家商品分组'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['merchant', 'is_active']),
        ]

    def __str__(self):
        return f"[{self.merchant.name}] {self.name}"


# ============================================================
# 3. 商品标签(平台级 + 商家级)
# ============================================================
class GoodsTag(models.Model):
    """商品标签。merchant=None 为平台公共标签。"""

    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='goods_tags',
        verbose_name='所属商家',
        help_text='为空表示平台公共标签'
    )
    name = models.CharField(max_length=20, verbose_name='标签名')
    color = models.CharField(max_length=20, default='#FF6B6B', verbose_name='文字颜色')
    bg_color = models.CharField(max_length=20, default='#FFF0F0', verbose_name='背景色')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'goods_tag'
        verbose_name = '商品标签'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['merchant', 'is_active']),
        ]

    def __str__(self):
        return self.name


# ============================================================
# 4. 品牌(管理员维护平台品牌 + 商家可创建私有品牌)
# ============================================================
class Brand(models.Model):
    """品牌。merchant=None 为平台官方品牌。"""

    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='brands',
        verbose_name='所属商家',
        help_text='为空表示平台官方品牌,有值表示商家私有品牌'
    )
    name = models.CharField(max_length=50, verbose_name='品牌名称')
    logo = models.CharField(max_length=500, blank=True, default='', verbose_name='品牌Logo')
    description = models.TextField(blank=True, default='', verbose_name='品牌介绍')
    country = models.CharField(max_length=50, blank=True, default='', verbose_name='所属国家')
    website = models.URLField(max_length=200, blank=True, default='', verbose_name='官网')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    is_recommended = models.BooleanField(default=False, verbose_name='是否推荐')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'goods_brand'
        verbose_name = '品牌'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['merchant', 'is_active']),
        ]

    def __str__(self):
        owner = self.merchant.name if self.merchant_id else '平台'
        return f"[{owner}] {self.name}"

    @property
    def is_official(self):
        return self.merchant_id is None


# ============================================================
# 5. 商品 SPU(标准产品单元)
# ============================================================
class Goods(models.Model):
    """商品 SPU"""

    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('on_sale', '上架中'),
        ('off_sale', '已下架'),
        ('sold_out', '已售罄'),
    ]

    GOODS_TYPE_CHOICES = [
        ('physical', '实物商品'),
        ('virtual', '虚拟商品'),
        ('card', '电子卡券'),
    ]

    # ══════════════════ 1. 归属关联 ══════════════════
    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        related_name='goods',
        verbose_name='所属商家'
    )
    category = models.ForeignKey(
        GoodsCategory,
        on_delete=models.PROTECT,
        related_name='goods',
        verbose_name='商品分类'
    )
    merchant_group = models.ForeignKey(
        MerchantGoodsGroup,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='goods',
        verbose_name='店铺分组'
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='goods',
        verbose_name='品牌'
    )
    tags = models.ManyToManyField(
        GoodsTag, blank=True,
        related_name='goods',
        verbose_name='商品标签'
    )

    # ══════════════════ 2. 基本信息 ══════════════════
    goods_sn = models.CharField(max_length=64, verbose_name='商品编号')
    title = models.CharField(max_length=150, verbose_name='商品名称')
    subtitle = models.CharField(max_length=300, blank=True, default='', verbose_name='副标题')
    keywords = models.CharField(max_length=200, blank=True, default='', verbose_name='搜索关键词')

    main_image = models.CharField(max_length=500, verbose_name='商品主图')
    images = models.JSONField(default=list, blank=True, verbose_name='商品图片列表')
    detail_images = models.JSONField(
        default=list, blank=True,
        verbose_name='商品详情长图',
        help_text='详情区按顺序纵向展示的长图列表'
    )
    video_url = models.CharField(max_length=500, blank=True, default='', verbose_name='商品视频')

    goods_type = models.CharField(
        max_length=20, choices=GOODS_TYPE_CHOICES,
        default='physical', verbose_name='商品类型'
    )

    # ══════════════════ 3. 价格(展示用) ══════════════════
    price = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name='展示价',
        help_text='列表/详情展示用,多SKU时为最低价'
    )
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='原价(划线价)'
    )
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='成本价'
    )

    # ══════════════════ 4. 库存销量 ══════════════════
    total_stock = models.IntegerField(
        default=0, verbose_name='总库存'
    )
    sales_count = models.PositiveIntegerField(
        default=0, verbose_name='总销量'
    )

    # ══════════════════ 5. 详情内容 ══════════════════
    detail = models.TextField(blank=True, default='', verbose_name='商品详情')
    specs_desc = models.TextField(blank=True, default='', verbose_name='规格参数')
    after_service = models.TextField(blank=True, default='', verbose_name='售后说明')

    # ══════════════════ 6. 物流 ══════════════════
    weight = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=0, verbose_name='重量(kg)'
    )

    # ✅ 修复 #A:
    # 1) 原来错误 import:from django.forms import BooleanField — 该类不是数据库字段,
    #    会导致 makemigrations/runserver 报错或字段不入库。
    # 2) 字段没有 default、没有 null=True,必填,会导致老数据迁移失败 / 新建商品强制必填。
    # 3) 默认值与商家端 support_home_delivery=True / support_self_pickup=False 保持一致。
    allow_delivery = models.BooleanField(
        default=True, verbose_name='是否允许配送',
        help_text='False=仅自提'
    )
    allow_pickup = models.BooleanField(
        default=False, verbose_name='是否允许自提',
        help_text='False=仅配送'
    )

    # ══════════════════ 7. 购买限制 ══════════════════
    purchase_limit = models.PositiveSmallIntegerField(
        default=0, verbose_name='限购数量',
        help_text='单用户可购买上限,0=不限'
    )
    purchase_min = models.PositiveSmallIntegerField(
        default=1, verbose_name='起购数量'
    )

    # ══════════════════ 8. 会员折扣 / 金币抵扣 ══════════════════
    allow_member_discount = models.BooleanField(
        default=True, verbose_name='参与会员折扣'
    )
    allow_coin_deduction = models.BooleanField(
        default=True, verbose_name='允许金币抵扣'
    )
    max_coin_deduction = models.PositiveIntegerField(
        default=0, verbose_name='最大可抵扣金币数',
        help_text='0 表示不限制(受平台全局配置约束)'
    )

    # ══════════════════ 9. 统计指标 ══════════════════
    view_count = models.PositiveIntegerField(default=0, verbose_name='浏览量')
    favorite_count = models.PositiveIntegerField(default=0, verbose_name='收藏数')
    rating = models.DecimalField(
        max_digits=3, decimal_places=1,
        default=5.0, verbose_name='评分'
    )
    review_count = models.PositiveIntegerField(default=0, verbose_name='评价数')

    # ══════════════════ 10. 排序与状态 ══════════════════
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序权重')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='draft', db_index=True,
        verbose_name='商品状态'
    )

    # ══════════════════ 11. 首页推荐 ══════════════════
    is_recommended = models.BooleanField(default=False, verbose_name='是否推荐')
    is_hot = models.BooleanField(default=False, verbose_name='是否热门')
    is_new = models.BooleanField(default=False, verbose_name='是否新品')
    is_best = models.BooleanField(default=False, verbose_name='是否精品')

    # ══════════════════ 12. 时间戳 ══════════════════
    published_at = models.DateTimeField(null=True, blank=True, verbose_name='上架时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'goods'
        verbose_name = '商品'
        verbose_name_plural = verbose_name
        ordering = ['-sort_order', '-id']
        unique_together = ['merchant', 'goods_sn']
        indexes = [
            models.Index(fields=['merchant', 'status']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['merchant_group', 'status']),
            models.Index(fields=['status', 'sort_order']),
            models.Index(fields=['status', '-sales_count']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['status', 'is_recommended']),
            models.Index(fields=['status', 'is_hot']),
            models.Index(fields=['status', 'is_new']),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        """✅ 修复 #F: 拒绝同时不允许配送也不允许自提的"死锁"商品"""
        from django.core.exceptions import ValidationError
        if self.allow_delivery is False and self.allow_pickup is False:
            raise ValidationError('配送方式必须至少选择一种(配送/自提)')

    @property
    def is_available(self):
        return self.status == 'on_sale' and self.total_stock > 0

    @property
    def has_multi_sku(self):
        """
        是否多规格。
        ✅ 修复 #B: 列表序列化时优先读 annotated 值,
        避免 N+1 COUNT 查询。
        Queryset 上 annotate(active_sku_count=Count(...,filter=Q(...))) 后,
        这个 property 会自动用 annotation。
        """
        if hasattr(self, '_active_sku_count'):
            return self._active_sku_count > 1
        return self.skus.filter(is_active=True).count() > 1

    def increase_view(self):
        Goods.objects.filter(pk=self.pk).update(
            view_count=F('view_count') + 1
        )

    def sync_stock(self):
        """
        由 SKU 聚合 SPU 维度的展示数据。

        ✅ 修复 #C: 整个聚合过程用 select_for_update + transaction.atomic
        保证并发安全。
        """
        with transaction.atomic():
            # 行锁住自己,避免并发 sync 互相覆盖
            goods = Goods.objects.select_for_update().get(pk=self.pk)
            active_skus = goods.skus.filter(is_active=True)

            total = active_skus.aggregate(total=models.Sum('stock'))['total'] or 0
            sales = active_skus.aggregate(total=models.Sum('sales_count'))['total'] or 0

            goods.total_stock = total
            goods.sales_count = sales

            min_sku = active_skus.filter(stock__gt=0).order_by('price').first()
            if min_sku:
                goods.price = min_sku.price

            # 状态自动流转(不影响 draft / off_sale)
            if goods.status == 'on_sale' and total == 0:
                goods.status = 'sold_out'
            elif goods.status == 'sold_out' and total > 0:
                goods.status = 'on_sale'

            goods.save(update_fields=[
                'total_stock', 'sales_count', 'price', 'status', 'updated_at'
            ])

            # 同步内存中的 self,让调用者拿到最新值
            self.total_stock = goods.total_stock
            self.sales_count = goods.sales_count
            self.price = goods.price
            self.status = goods.status


# ============================================================
# 6. 商品规格名
# ============================================================
class GoodsSpec(models.Model):
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='specs',
        verbose_name='商品'
    )
    name = models.CharField(max_length=30, verbose_name='规格名称')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'goods_spec'
        verbose_name = '商品规格名'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        unique_together = ['goods', 'name']

    def __str__(self):
        return f"{self.goods.title} - {self.name}"


# ============================================================
# 7. 商品规格值
# ============================================================
class GoodsSpecValue(models.Model):
    spec = models.ForeignKey(
        GoodsSpec, on_delete=models.CASCADE,
        related_name='values',
        verbose_name='规格名'
    )
    value = models.CharField(max_length=50, verbose_name='规格值')
    image = models.CharField(
        max_length=500, blank=True, default='',
        verbose_name='规格图片'
    )
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'goods_spec_value'
        verbose_name = '商品规格值'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        unique_together = ['spec', 'value']

    def __str__(self):
        return f"{self.spec.name}: {self.value}"


# ============================================================
# 8. 商品 SKU(库存单元)
# ============================================================
class GoodsSku(models.Model):
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='skus',
        verbose_name='商品'
    )

    sku_sn = models.CharField(
        max_length=64, unique=True,
        verbose_name='SKU编号'
    )

    spec_values = models.JSONField(
        default=list, blank=True,
        verbose_name='规格值组合'
    )
    spec_text = models.CharField(
        max_length=200, blank=True, default='',
        verbose_name='规格文本'
    )

    image = models.CharField(
        max_length=500, blank=True, default='',
        verbose_name='SKU图片'
    )

    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='销售价')
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='原价'
    )
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name='成本价'
    )

    stock = models.IntegerField(default=0, verbose_name='库存')
    stock_warning = models.PositiveIntegerField(
        default=10, verbose_name='库存预警值'
    )
    sales_count = models.PositiveIntegerField(default=0, verbose_name='销量')

    weight = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=0, verbose_name='重量(kg)'
    )

    barcode = models.CharField(
        max_length=64, blank=True, default='',
        verbose_name='条形码'
    )
    max_coin_deduction = models.PositiveIntegerField(
        default=0, verbose_name='最大可抵扣金币数'
    )

    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'goods_sku'
        verbose_name = '商品SKU'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['goods', 'is_active']),
            models.Index(fields=['sku_sn']),
        ]

    def __str__(self):
        return f"{self.goods.title} - {self.spec_text or self.sku_sn}"

    @property
    def is_available(self):
        return self.is_active and self.stock > 0

    @property
    def is_low_stock(self):
        return 0 < self.stock <= self.stock_warning

    def deduct_stock(self, quantity):
        """
        扣减库存(下单时调用)

        ✅ 修复 #D: 原子操作,防止并发超卖。
        用 UPDATE ... WHERE stock >= quantity 的条件更新,
        数据库层保证原子性。
        """
        if quantity <= 0:
            raise ValueError("扣减数量必须大于 0")

        with transaction.atomic():
            updated = GoodsSku.objects.filter(
                pk=self.pk,
                stock__gte=quantity,
                is_active=True,
            ).update(
                stock=F('stock') - quantity,
                sales_count=F('sales_count') + quantity,
            )
            if updated == 0:
                # 重新读取一次状态,给前端明确的错误信息
                fresh = GoodsSku.objects.filter(pk=self.pk).first()
                if fresh is None:
                    raise ValueError("SKU 不存在")
                if not fresh.is_active:
                    raise ValueError("规格已下架")
                raise ValueError(f"库存不足:当前库存 {fresh.stock},需要 {quantity}")

            self.refresh_from_db(fields=['stock', 'sales_count'])

        # sync_stock 内部自带事务+行锁,放事务外避免持锁过久
        self.goods.sync_stock()

    def restore_stock(self, quantity):
        """
        恢复库存(退款/取消订单)

        ✅ 同样用原子 UPDATE。
        sales_count 用 GREATEST 防负数(MySQL/Postgres 都支持)。
        """
        if quantity <= 0:
            return

        with transaction.atomic():
            # sales_count 不能减成负数;用 CASE WHEN 处理
            GoodsSku.objects.filter(pk=self.pk).update(
                stock=F('stock') + quantity,
                sales_count=models.Case(
                    models.When(sales_count__lte=quantity, then=0),
                    default=F('sales_count') - quantity,
                ),
            )
            self.refresh_from_db(fields=['stock', 'sales_count'])

        self.goods.sync_stock()


# ============================================================
# 9. 商品收藏
# ============================================================
class GoodsFavorite(models.Model):
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='goods_favorites',
        verbose_name='用户'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='商品'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'goods_favorite'
        verbose_name = '商品收藏'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'goods']

    def __str__(self):
        return f"{self.user} 收藏 {self.goods.title}"


# ============================================================
# 10. 商品浏览记录
# ============================================================
class GoodsViewHistory(models.Model):
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='goods_view_history',
        verbose_name='用户'
    )
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='view_history',
        verbose_name='商品'
    )
    view_count = models.PositiveIntegerField(default=1, verbose_name='浏览次数')
    last_view_at = models.DateTimeField(auto_now=True, verbose_name='最后浏览时间')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'goods_view_history'
        verbose_name = '浏览记录'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'goods']
        ordering = ['-last_view_at']

    def __str__(self):
        return f"{self.user} 浏览 {self.goods.title}"


# ============================================================
# 11. 购物车
# ============================================================
class GoodsCart(models.Model):
    """
    商品购物车 —— 每条记录 = 用户选中的某个 SKU。
    """

    MAX_ITEMS = 50
    MAX_QUANTITY_PER_SKU = 200

    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='goods_carts',
        verbose_name='用户'
    )
    goods = models.ForeignKey(
        Goods,
        on_delete=models.CASCADE,
        related_name='cart_items',
        verbose_name='商品'
    )
    sku = models.ForeignKey(
        GoodsSku,
        on_delete=models.CASCADE,
        related_name='cart_items',
        verbose_name='SKU'
    )
    merchant = models.ForeignKey(
        'merchants.Merchant',
        on_delete=models.CASCADE,
        related_name='cart_items',
        verbose_name='所属商家'
    )
    quantity = models.PositiveIntegerField(default=1, verbose_name='数量')
    snapshot_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name='加入时单价'
    )
    is_selected = models.BooleanField(default=True, verbose_name='是否勾选')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='加入时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'goods_cart'
        verbose_name = '购物车'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'sku']
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'merchant']),
            models.Index(fields=['user', 'is_selected']),
        ]

    def __str__(self):
        return f"{self.user} - {self.sku} x{self.quantity}"

    @property
    def current_price(self):
        return self.sku.price

    @property
    def subtotal(self):
        return self.current_price * self.quantity

    @property
    def price_dropped(self):
        return self.sku.price < self.snapshot_price

    @property
    def is_valid(self):
        return (
            self.goods.status == 'on_sale'
            and self.sku.is_active
            and self.sku.stock >= self.quantity
        )

    @property
    def invalid_reason(self):
        if self.goods.status == 'off_sale':
            return '商品已下架'
        if self.goods.status == 'sold_out':
            return '商品已售罄'
        if self.goods.status != 'on_sale':
            return '商品不可购买'
        if not self.sku.is_active:
            return '规格已下架'
        if self.sku.stock == 0:
            return '库存不足'
        if self.sku.stock < self.quantity:
            return f'库存仅剩 {self.sku.stock} 件'
        return ''