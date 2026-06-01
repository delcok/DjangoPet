# goods/serializers.py

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from .models import (
    GoodsCategory, MerchantGoodsGroup, GoodsTag, Brand,
    Goods, GoodsSpec, GoodsSpecValue, GoodsSku,
    GoodsFavorite, GoodsCart,
)


# ══════════════════════════════════════════════════════════════
# 分类
# ══════════════════════════════════════════════════════════════

class GoodsCategoryTreeSerializer(serializers.ModelSerializer):
    """商品分类（带子分类树）"""
    children = serializers.SerializerMethodField()

    class Meta:
        model = GoodsCategory
        fields = [
            'id', 'parent', 'name', 'icon', 'image',
            'description', 'sort_order', 'is_show_home',
            'children',
        ]

    def get_children(self, obj):
        children = obj.children.filter(is_active=True).order_by('sort_order', 'id')
        return GoodsCategoryTreeSerializer(children, many=True).data


class GoodsCategorySimpleSerializer(serializers.ModelSerializer):
    """分类简略信息（用于商品列表中内嵌）"""

    class Meta:
        model = GoodsCategory
        fields = ['id', 'name', 'icon']


class GoodsCategoryAdminSerializer(serializers.ModelSerializer):
    """管理端 - 分类 CRUD"""

    class Meta:
        model = GoodsCategory
        fields = [
            'id', 'parent', 'name', 'icon', 'image',
            'description', 'commission_rate',
            'sort_order', 'is_active', 'is_show_home',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ══════════════════════════════════════════════════════════════
# 商家店铺分组
# ══════════════════════════════════════════════════════════════

class MerchantGoodsGroupSerializer(serializers.ModelSerializer):
    """商家端 - 店铺分组 CRUD"""
    goods_count = serializers.SerializerMethodField()

    class Meta:
        model = MerchantGoodsGroup
        fields = [
            'id', 'name', 'icon', 'sort_order', 'is_active',
            'description', 'goods_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_goods_count(self, obj):
        """该分组下的商品数量"""
        return obj.goods.count()


# ══════════════════════════════════════════════════════════════
# 标签
# ══════════════════════════════════════════════════════════════

class GoodsTagSerializer(serializers.ModelSerializer):
    """商品标签"""

    class Meta:
        model = GoodsTag
        fields = [
            'id', 'name', 'color', 'bg_color',
            'sort_order', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ══════════════════════════════════════════════════════════════
# 品牌
# ══════════════════════════════════════════════════════════════

class BrandSerializer(serializers.ModelSerializer):
    """品牌"""

    class Meta:
        model = Brand
        fields = [
            'id', 'name', 'logo', 'description',
            'country', 'website',
            'sort_order', 'is_active', 'is_recommended',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class BrandSimpleSerializer(serializers.ModelSerializer):
    """品牌简略（商品列表中内嵌 / 下拉选择）"""
    is_official = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = ['id', 'name', 'logo', 'is_official']

    def get_is_official(self, obj):
        return obj.merchant_id is None


class MerchantBrandSerializer(serializers.ModelSerializer):
    """商家端 - 私有品牌 CRUD"""
    is_official = serializers.SerializerMethodField()
    goods_count = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = [
            'id', 'name', 'logo', 'description',
            'country', 'website',
            'sort_order', 'is_active', 'is_recommended',
            'is_official', 'goods_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_official', 'goods_count',
                            'created_at', 'updated_at']

    def get_is_official(self, obj):
        return obj.merchant_id is None

    def get_goods_count(self, obj):
        """该品牌下的商品数量（仅当前商家自己的商品）"""
        merchant_id = obj.merchant_id
        if not merchant_id:
            return obj.goods.count()
        return obj.goods.filter(merchant_id=merchant_id).count()

    def validate_name(self, value):
        name = (value or '').strip()
        if not name:
            raise serializers.ValidationError('品牌名称不能为空')
        # 同商家下品牌名唯一
        request = self.context.get('request')
        if request:
            from utils.permission import get_merchant_id_from_request
            merchant_id = get_merchant_id_from_request(request)
            qs = Brand.objects.filter(merchant_id=merchant_id, name=name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError('该品牌名称已存在')
        return name

# ══════════════════════════════════════════════════════════════
# 规格
# ══════════════════════════════════════════════════════════════

class GoodsSpecValueSerializer(serializers.ModelSerializer):
    """规格值"""

    class Meta:
        model = GoodsSpecValue
        fields = ['id', 'value', 'image', 'sort_order']
        read_only_fields = ['id']


class GoodsSpecSerializer(serializers.ModelSerializer):
    """规格名（带规格值列表）"""
    values = GoodsSpecValueSerializer(many=True, read_only=True)

    class Meta:
        model = GoodsSpec
        fields = ['id', 'name', 'sort_order', 'values']
        read_only_fields = ['id']


class GoodsSpecCreateSerializer(serializers.ModelSerializer):
    """商家端 - 创建规格名"""

    class Meta:
        model = GoodsSpec
        fields = ['id', 'name', 'sort_order']
        read_only_fields = ['id']


class GoodsSpecValueCreateSerializer(serializers.ModelSerializer):
    """商家端 - 创建规格值"""

    class Meta:
        model = GoodsSpecValue
        fields = ['id', 'value', 'image', 'sort_order']
        read_only_fields = ['id']


# ══════════════════════════════════════════════════════════════
# SKU
# ══════════════════════════════════════════════════════════════

class GoodsSkuSerializer(serializers.ModelSerializer):
    """SKU 详情（商家端）"""
    is_low_stock = serializers.BooleanField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = GoodsSku
        fields = [
            'id', 'sku_sn', 'spec_values', 'spec_text', 'image',
            'price', 'original_price', 'cost_price',
            'stock', 'stock_warning', 'sales_count',
            'weight', 'barcode',
            'is_active', 'sort_order',
            'is_low_stock', 'is_available',
        ]
        read_only_fields = ['id', 'sales_count']


class GoodsSkuCreateSerializer(serializers.ModelSerializer):
    """商家端 - 创建/更新 SKU"""

    class Meta:
        model = GoodsSku
        fields = [
            'id', 'sku_sn', 'spec_values', 'spec_text', 'image',
            'price', 'original_price', 'cost_price',
            'stock', 'stock_warning',
            'weight', 'barcode',
            'is_active', 'sort_order', 'max_coin_deduction',
        ]
        read_only_fields = ['id']

    def validate_sku_sn(self, value):
        """编辑时排除自身"""
        qs = GoodsSku.objects.filter(sku_sn=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('SKU编号已存在')
        return value


class GoodsSkuSimpleSerializer(serializers.ModelSerializer):
    """SKU 简略（用户端商品详情中展示，不含成本价）"""

    class Meta:
        model = GoodsSku
        fields = [
            'id', 'sku_sn', 'spec_values', 'spec_text', 'image',
            'price', 'original_price', 'stock',
            'is_active',
        ]


# ══════════════════════════════════════════════════════════════
# 商品 SPU —— 用户端
# ══════════════════════════════════════════════════════════════

class GoodsListSerializer(serializers.ModelSerializer):
    """用户端 - 商品列表"""
    category = GoodsCategorySimpleSerializer(read_only=True)
    brand = BrandSimpleSerializer(read_only=True)
    tags = GoodsTagSerializer(many=True, read_only=True)
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    group_name = serializers.CharField(
        source='merchant_group.name', read_only=True, default=''
    )

    class Meta:
        model = Goods
        fields = [
            'id', 'goods_sn', 'title', 'subtitle',
            'main_image', 'goods_type',
            'price', 'original_price',
            'sales_count', 'rating', 'review_count',
            'category', 'brand', 'tags',
            'merchant', 'merchant_name',
            'merchant_group', 'group_name',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'created_at', 'detail_images'
        ]


class GoodsDetailSerializer(serializers.ModelSerializer):
    """
    用户端 - 商品详情（含规格 + SKU）
    金币赠送/抵扣规则已改走全局配置，不再在此字段中返回
    运费模板待实现
    """
    category = GoodsCategorySimpleSerializer(read_only=True)
    brand = BrandSimpleSerializer(read_only=True)
    tags = GoodsTagSerializer(many=True, read_only=True)
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_logo = serializers.CharField(source='merchant.logo', read_only=True)
    merchant_support_home_delivery = serializers.BooleanField(
        source='merchant.support_home_delivery', read_only=True
    )
    merchant_support_self_pickup = serializers.BooleanField(
        source='merchant.support_self_pickup', read_only=True
    )
    merchant_pickup_address = serializers.CharField(
        source='merchant.full_address', read_only=True
    )
    merchant_pickup_contact = serializers.CharField(
        source='merchant.contact_phone', read_only=True
    )
    merchant_pickup_note = serializers.CharField(
        source='merchant.pickup_note', read_only=True
    )
    specs = GoodsSpecSerializer(many=True, read_only=True)
    skus = serializers.SerializerMethodField()
    has_multi_sku = serializers.BooleanField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = Goods
        fields = [
            'id', 'goods_sn', 'title', 'subtitle', 'keywords',
            'main_image', 'images', 'video_url', 'goods_type',
            'price', 'original_price',
            'total_stock', 'sales_count',
            'detail', 'specs_desc', 'after_service',
            'weight',
            'merchant_support_home_delivery',
            'merchant_support_self_pickup',
            'merchant_pickup_address',
            'merchant_pickup_contact',
            'merchant_pickup_note',
            'purchase_limit', 'purchase_min',
            'allow_member_discount',
            'allow_coin_deduction', 'max_coin_deduction',
            'rating', 'review_count', 'view_count', 'favorite_count',
            'category', 'brand', 'tags',
            'allow_delivery', 'allow_pickup',
            'merchant', 'merchant_name', 'merchant_logo',
            'merchant_group',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'specs', 'skus',
            'has_multi_sku', 'is_available',
            'is_favorited',
            'published_at', 'created_at', 'detail_images'
        ]

    def get_skus(self, obj):
        skus = obj.skus.filter(is_active=True).order_by('sort_order', 'id')
        return GoodsSkuSimpleSerializer(skus, many=True).data

    def get_is_favorited(self, obj):
        """是否已被当前登录用户收藏 —— 未登录返回 False"""
        request = self.context.get('request')
        if not request:
            return False
        user = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        # 只对真实用户(User)生效;商家/管理员调进来不算
        from user.models import User
        if not isinstance(user, User):
            return False
        return GoodsFavorite.objects.filter(user=user, goods=obj).exists()


# ══════════════════════════════════════════════════════════════
# 商品 SPU —— 商家端
# ══════════════════════════════════════════════════════════════

class MerchantGoodsListSerializer(serializers.ModelSerializer):
    """商家端 - 商品列表"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    group_name = serializers.CharField(
        source='merchant_group.name', read_only=True, default=''
    )
    sku_count = serializers.SerializerMethodField()
    has_multi_sku = serializers.BooleanField(read_only=True)

    class Meta:
        model = Goods
        fields = [
            'id', 'goods_sn', 'title', 'main_image',
            'goods_type', 'status',
            'price', 'original_price', 'cost_price',
            'total_stock', 'sales_count',
            'category', 'category_name',
            'merchant_group', 'group_name',
            'sort_order',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'sku_count', 'has_multi_sku',
            'published_at', 'created_at', 'updated_at', 'detail_images'
        ]

    def get_sku_count(self, obj):
        return obj.skus.filter(is_active=True).count()


class MerchantGoodsDetailSerializer(serializers.ModelSerializer):
    """
    商家端 - 商品详情（含全部 SKU + 规格）
    已移除：volume、points_mode、points_value、points_deduct_max、freight_template_id
    已更名：is_member_discount → allow_member_discount
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    brand_name = serializers.CharField(
        source='brand.name', read_only=True, default=''
    )
    group_name = serializers.CharField(
        source='merchant_group.name', read_only=True, default=''
    )
    tags = GoodsTagSerializer(many=True, read_only=True)
    specs = GoodsSpecSerializer(many=True, read_only=True)
    skus = GoodsSkuSerializer(many=True, read_only=True)
    has_multi_sku = serializers.BooleanField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Goods
        fields = [
            'id', 'goods_sn', 'title', 'subtitle', 'keywords',
            'main_image', 'images', 'video_url', 'goods_type',
            'price', 'original_price', 'cost_price',
            'total_stock', 'sales_count',
            'detail', 'specs_desc', 'after_service',
            'weight',
            'purchase_limit', 'purchase_min',
            'allow_member_discount',
            'allow_delivery', 'allow_pickup',  # ★ 新增
            'allow_coin_deduction', 'max_coin_deduction',  # ★ 顺便也把这俩加上,前端会用
            'view_count', 'favorite_count', 'rating', 'review_count',
            'sort_order', 'status',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'category', 'category_name',
            'brand', 'brand_name',
            'merchant_group', 'group_name',
            'tags', 'specs', 'skus',
            'has_multi_sku', 'is_available',
            'published_at', 'created_at', 'updated_at', 'detail_images',
        ]


class MerchantGoodsCreateSerializer(serializers.ModelSerializer):
    """
    商家端 - 创建商品
    商品编号（goods_sn）商户内唯一，不同商家可以用相同编号
    """
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model = Goods
        fields = [
            'id',
            'goods_sn', 'title', 'subtitle', 'keywords',
            'main_image', 'images', 'video_url', 'goods_type',
            'price', 'original_price', 'cost_price',
            'detail', 'specs_desc', 'after_service',
            'weight',
            'purchase_limit', 'purchase_min',
            'allow_member_discount',
            'allow_delivery', 'allow_pickup',          # ★ 新增
            'category', 'brand', 'merchant_group',
            'tag_ids',
            'status',
            'allow_coin_deduction', 'max_coin_deduction',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'sort_order', 'detail_images',
        ]

    def validate_goods_sn(self, value):
        merchant = self.context.get('merchant')
        if not merchant:
            return value
        if Goods.objects.filter(merchant=merchant, goods_sn=value).exists():
            raise serializers.ValidationError('商品编号在您的店铺中已存在')
        return value

    def validate_status(self, value):
        if value not in ('draft', 'on_sale'):
            raise serializers.ValidationError('只能设为草稿或上架')
        return value

    def validate_merchant_group(self, value):
        merchant = self.context.get('merchant')
        if value and merchant and value.merchant_id != merchant.id:
            raise serializers.ValidationError('店铺分组不属于当前商家')
        return value

    def validate(self, attrs):
        """★ 新增: 强制至少开启一种配送方式"""
        allow_delivery = attrs.get('allow_delivery', True)
        allow_pickup = attrs.get('allow_pickup', False)
        if not allow_delivery and not allow_pickup:
            raise serializers.ValidationError({
                'allow_delivery': '配送方式必须至少选择一种(配送上门 / 到店自提)'
            })
        return attrs

    def create(self, validated_data):
        tag_ids = validated_data.pop('tag_ids', [])
        merchant = self.context['merchant']
        validated_data['merchant'] = merchant

        if validated_data.get('status') == 'on_sale':
            validated_data['published_at'] = timezone.now()

        goods = Goods.objects.create(**validated_data)

        if tag_ids:
            valid_tags = GoodsTag.objects.filter(
                id__in=tag_ids, is_active=True
            ).filter(
                Q(merchant__isnull=True) |
                Q(merchant=merchant)
            )
            goods.tags.set(valid_tags)

        return goods

class MerchantGoodsUpdateSerializer(serializers.ModelSerializer):
    """商家端 - 更新商品"""
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model = Goods
        fields = [
            'id',
            'goods_sn',
            'title', 'subtitle', 'keywords',
            'main_image', 'images', 'video_url', 'goods_type',
            'price', 'original_price', 'cost_price',
            'detail', 'specs_desc', 'after_service',
            'weight',
            'purchase_limit', 'purchase_min',
            'allow_member_discount',
            'allow_delivery', 'allow_pickup',          # ★ 新增
            'category', 'brand', 'merchant_group',
            'tag_ids',
            'status',
            'allow_coin_deduction', 'max_coin_deduction',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'sort_order', 'detail_images',
        ]
        read_only_fields = ['id']

    def validate_goods_sn(self, value):
        merchant = self.context.get('merchant')
        if not merchant:
            return value
        qs = Goods.objects.filter(merchant=merchant, goods_sn=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('商品编号在您的店铺中已存在')
        return value

    def validate_status(self, value):
        if value not in ('draft', 'on_sale', 'off_sale'):
            raise serializers.ValidationError('状态值不合法')
        return value

    def validate_merchant_group(self, value):
        merchant = self.context.get('merchant')
        if value and merchant and value.merchant_id != merchant.id:
            raise serializers.ValidationError('店铺分组不属于当前商家')
        return value

    def validate(self, attrs):
        """
        ★ 新增: 配送方式至少开启一种
        注意要兼容 PATCH(部分更新)的场景 —— 用 attrs 没传时回退到 instance 的当前值
        """
        instance = self.instance
        allow_delivery = attrs.get(
            'allow_delivery',
            instance.allow_delivery if instance else True
        )
        allow_pickup = attrs.get(
            'allow_pickup',
            instance.allow_pickup if instance else False
        )
        if not allow_delivery and not allow_pickup:
            raise serializers.ValidationError({
                'allow_delivery': '配送方式必须至少选择一种(配送上门 / 到店自提)'
            })
        return attrs

    def update(self, instance, validated_data):
        tag_ids = validated_data.pop('tag_ids', None)

        new_status = validated_data.get('status')
        if new_status == 'on_sale' and instance.status != 'on_sale':
            validated_data['published_at'] = timezone.now()

        instance = super().update(instance, validated_data)

        if tag_ids is not None:
            merchant = self.context['merchant']
            valid_tags = GoodsTag.objects.filter(
                id__in=tag_ids, is_active=True
            ).filter(
                Q(merchant__isnull=True) | Q(merchant=merchant)
            )
            instance.tags.set(valid_tags)

        return instance

# ══════════════════════════════════════════════════════════════
# 商品 SPU —— 管理端
# ══════════════════════════════════════════════════════════════

class AdminGoodsListSerializer(serializers.ModelSerializer):
    """管理端 - 商品列表"""
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Goods
        fields = [
            'id', 'goods_sn', 'title', 'main_image',
            'goods_type', 'status',
            'price', 'total_stock', 'sales_count',
            'merchant', 'merchant_name',
            'category', 'category_name',
            'sort_order',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'created_at', 'detail_images'
        ]


class AdminGoodsUpdateSerializer(serializers.ModelSerializer):
    """管理端 - 管理员可调整排序和推荐标记"""

    class Meta:
        model = Goods
        fields = [
            'sort_order',
            'is_recommended', 'is_hot', 'is_new', 'is_best',
            'status', 'detail_images'
        ]


class AdminGoodsBatchSortSerializer(serializers.Serializer):
    """管理端 - 批量排序"""
    items = serializers.ListField(
        child=serializers.DictField(),
        help_text='[{"id": 1, "sort_order": 100}, ...]'
    )

    def validate_items(self, value):
        for item in value:
            if 'id' not in item or 'sort_order' not in item:
                raise serializers.ValidationError(
                    '每项需包含 id 和 sort_order'
                )
        return value


# ══════════════════════════════════════════════════════════════
# 收藏
# ══════════════════════════════════════════════════════════════

class GoodsFavoriteSerializer(serializers.ModelSerializer):
    """用户收藏"""
    goods_title = serializers.CharField(source='goods.title', read_only=True)
    goods_image = serializers.CharField(source='goods.main_image', read_only=True)
    goods_price = serializers.DecimalField(
        source='goods.price', read_only=True,
        max_digits=10, decimal_places=2
    )

    class Meta:
        model = GoodsFavorite
        fields = [
            'id', 'goods', 'goods_title', 'goods_image',
            'goods_price', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

# ══════════════════════════════════════════════════════════════
# 购物车
# ══════════════════════════════════════════════════════════════

class CartItemSerializer(serializers.ModelSerializer):
    """购物车项(用户端展示)"""

    # 商品信息
    goods_title = serializers.CharField(source='goods.title', read_only=True)
    goods_main_image = serializers.CharField(source='goods.main_image', read_only=True)
    goods_status = serializers.CharField(source='goods.status', read_only=True)

    # ★ 商品级配送开关
    allow_delivery = serializers.BooleanField(source='goods.allow_delivery', read_only=True)
    allow_pickup = serializers.BooleanField(source='goods.allow_pickup', read_only=True)

    # SKU 信息
    sku_spec_text = serializers.CharField(source='sku.spec_text', read_only=True)
    sku_image = serializers.CharField(source='sku.image', read_only=True)
    sku_stock = serializers.IntegerField(source='sku.stock', read_only=True)
    sku_is_active = serializers.BooleanField(source='sku.is_active', read_only=True)

    current_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    original_price = serializers.DecimalField(
        source='sku.original_price', read_only=True,
        max_digits=10, decimal_places=2, allow_null=True,
    )
    subtotal = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    # 商家信息
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_logo = serializers.CharField(
        source='merchant.logo', read_only=True, default=''
    )

    # 状态
    is_valid = serializers.BooleanField(read_only=True)
    invalid_reason = serializers.CharField(read_only=True)
    price_dropped = serializers.BooleanField(read_only=True)

    class Meta:
        model = GoodsCart
        fields = [
            'id',
            'goods', 'goods_title', 'goods_main_image', 'goods_status',
            'allow_delivery', 'allow_pickup',
            'sku', 'sku_spec_text', 'sku_image', 'sku_stock', 'sku_is_active',
            'current_price', 'original_price', 'snapshot_price',
            'quantity', 'subtotal', 'is_selected',
            'merchant', 'merchant_name', 'merchant_logo',
            'is_valid', 'invalid_reason', 'price_dropped',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'goods', 'merchant', 'snapshot_price',
            'created_at', 'updated_at',
        ]

class CartAddSerializer(serializers.Serializer):
    """加入购物车"""
    sku = serializers.PrimaryKeyRelatedField(
        queryset=GoodsSku.objects.filter(is_active=True),
    )
    quantity = serializers.IntegerField(min_value=1, default=1)

    def validate_sku(self, sku):
        if sku.goods.status != 'on_sale':
            raise serializers.ValidationError('商品不可购买')
        return sku

    def validate(self, attrs):
        sku = attrs['sku']
        quantity = attrs['quantity']
        goods = sku.goods

        if quantity > sku.stock:
            raise serializers.ValidationError(f'库存不足,当前库存 {sku.stock}')
        if quantity > GoodsCart.MAX_QUANTITY_PER_SKU:
            raise serializers.ValidationError(
                f'单个商品最多 {GoodsCart.MAX_QUANTITY_PER_SKU} 件'
            )
        if goods.purchase_limit and quantity > goods.purchase_limit:
            raise serializers.ValidationError(f'该商品单用户限购 {goods.purchase_limit} 件')
        if quantity < goods.purchase_min:
            raise serializers.ValidationError(f'最少购买 {goods.purchase_min} 件')
        return attrs


class CartUpdateSerializer(serializers.ModelSerializer):
    """修改购物车项(数量/勾选状态)"""

    class Meta:
        model = GoodsCart
        fields = ['quantity', 'is_selected']

    def validate_quantity(self, quantity):
        if quantity < 1:
            raise serializers.ValidationError('数量必须 >= 1')
        if quantity > GoodsCart.MAX_QUANTITY_PER_SKU:
            raise serializers.ValidationError(
                f'单个商品最多 {GoodsCart.MAX_QUANTITY_PER_SKU} 件'
            )
        sku = self.instance.sku
        goods = self.instance.goods
        if quantity > sku.stock:
            raise serializers.ValidationError(f'库存仅剩 {sku.stock}')
        if goods.purchase_limit and quantity > goods.purchase_limit:
            raise serializers.ValidationError(f'该商品单用户限购 {goods.purchase_limit} 件')
        return quantity