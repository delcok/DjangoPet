from django.db import transaction
from rest_framework import serializers

from .models import (
    Category, Product, ProductImage, ProductVideo, ProductDetail,
    SpecificationName, SpecificationValue, SKU,
    Order, OrderItem, OrderLog, CartItem, ProductFavorite,
    PAYMENT_METHOD_CHOICES
)


# ==================== 分类序列化器 ====================

class CategorySerializer(serializers.ModelSerializer):
    """分类序列化器"""
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'parent', 'icon_url', 'sort_order', 'is_active', 'children', 'full_name']

    def get_children(self, obj):
        children = obj.children.filter(is_active=True)
        return CategorySerializer(children, many=True).data


class CategorySimpleSerializer(serializers.ModelSerializer):
    """分类简单序列化器"""

    class Meta:
        model = Category
        fields = ['id', 'name', 'icon_url']


class CategoryAdminSerializer(serializers.ModelSerializer):
    """分类管理序列化器"""

    class Meta:
        model = Category
        fields = '__all__'


# ==================== 商品媒体序列化器 ====================

class ProductImageSerializer(serializers.ModelSerializer):
    """商品图片序列化器"""

    class Meta:
        model = ProductImage
        fields = ['id', 'image_url', 'sort_order', 'is_main']


class ProductVideoSerializer(serializers.ModelSerializer):
    """商品视频序列化器"""

    class Meta:
        model = ProductVideo
        fields = ['id', 'video_url', 'cover_url', 'title', 'duration', 'sort_order']


class ProductDetailImageSerializer(serializers.ModelSerializer):
    """商品详情图序列化器"""

    class Meta:
        model = ProductDetail
        fields = ['id', 'image_url', 'sort_order']


# ==================== SKU和规格序列化器 ====================

class SpecificationValueSerializer(serializers.ModelSerializer):
    """规格值序列化器"""

    class Meta:
        model = SpecificationValue
        fields = ['id', 'value', 'sort_order']


class SpecificationNameSerializer(serializers.ModelSerializer):
    """规格名称序列化器"""
    values = SpecificationValueSerializer(many=True, read_only=True)

    class Meta:
        model = SpecificationName
        fields = ['id', 'name', 'sort_order', 'values']


class SKUSerializer(serializers.ModelSerializer):
    """SKU序列化器"""

    class Meta:
        model = SKU
        fields = [
            'id', 'sku_code', 'name', 'spec_values',
            'price', 'original_price', 'stock', 'image_url', 'is_active'
        ]


class SKUAdminSerializer(serializers.ModelSerializer):
    """SKU管理序列化器"""

    class Meta:
        model = SKU
        fields = '__all__'


# ==================== 商品序列化器 ====================

class ProductListSerializer(serializers.ModelSerializer):
    """商品列表序列化器"""
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'subtitle', 'cover_image_url',
            'price', 'original_price', 'sales', 'stock',
            'category', 'category_name', 'status',
            'is_recommended', 'is_new', 'is_hot', 'is_on_sale',
            'pet_type', 'brand'
        ]


class ProductDetailSerializer(serializers.ModelSerializer):
    """商品详情序列化器"""
    category = CategorySimpleSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    videos = ProductVideoSerializer(many=True, read_only=True)
    detail_images = serializers.SerializerMethodField()
    skus = SKUSerializer(many=True, read_only=True)
    specifications = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'subtitle', 'description', 'cover_image_url',
            'price', 'original_price', 'sales', 'stock', 'freight',
            'category', 'status', 'is_on_sale',
            'is_recommended', 'is_new', 'is_hot',
            'pet_type', 'brand',
            'images', 'videos', 'detail_images', 'skus', 'specifications',
            'is_favorited', 'created_at'
        ]

    def get_detail_images(self, obj):
        images = obj.detail_images.all().order_by('sort_order')
        return [{'id': img.id, 'image_url': img.image_url} for img in images]

    def get_specifications(self, obj):
        """获取商品规格信息"""
        specs = obj.specifications.select_related('spec_name', 'spec_value').all()
        spec_dict = {}
        for spec in specs:
            name = spec.spec_name.name
            if name not in spec_dict:
                spec_dict[name] = {
                    'name': name,
                    'values': []
                }
            spec_dict[name]['values'].append({
                'id': spec.spec_value.id,
                'value': spec.spec_value.value
            })
        return list(spec_dict.values())

    def get_is_favorited(self, obj):
        """检查当前用户是否收藏"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return ProductFavorite.objects.filter(
                user=request.user,
                product=obj
            ).exists()
        return False


class ProductAdminSerializer(serializers.ModelSerializer):
    """商品管理序列化器（创建/更新）"""
    images = ProductImageSerializer(many=True, required=False)
    videos = ProductVideoSerializer(many=True, required=False)
    detail_images = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        write_only=True
    )
    skus = SKUAdminSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = '__all__'

    @transaction.atomic
    def create(self, validated_data):
        images_data = validated_data.pop('images', [])
        videos_data = validated_data.pop('videos', [])
        detail_images_data = validated_data.pop('detail_images', [])
        skus_data = validated_data.pop('skus', [])

        product = Product.objects.create(**validated_data)

        # 创建图片
        for idx, image_data in enumerate(images_data):
            ProductImage.objects.create(
                product=product,
                sort_order=idx,
                **image_data
            )

        # 创建视频
        for idx, video_data in enumerate(videos_data):
            ProductVideo.objects.create(
                product=product,
                sort_order=idx,
                **video_data
            )

        # 创建详情图
        for idx, image_url in enumerate(detail_images_data):
            ProductDetail.objects.create(
                product=product,
                image_url=image_url,
                sort_order=idx
            )

        # 创建SKU
        for sku_data in skus_data:
            SKU.objects.create(product=product, **sku_data)

        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        images_data = validated_data.pop('images', None)
        videos_data = validated_data.pop('videos', None)
        detail_images_data = validated_data.pop('detail_images', None)
        skus_data = validated_data.pop('skus', None)

        # 更新商品基本信息
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # 更新图片（如果提供了新数据则替换）
        if images_data is not None:
            instance.images.all().delete()
            for idx, image_data in enumerate(images_data):
                ProductImage.objects.create(
                    product=instance,
                    sort_order=idx,
                    **image_data
                )

        # 更新视频
        if videos_data is not None:
            instance.videos.all().delete()
            for idx, video_data in enumerate(videos_data):
                ProductVideo.objects.create(
                    product=instance,
                    sort_order=idx,
                    **video_data
                )

        # 更新详情图
        if detail_images_data is not None:
            instance.detail_images.all().delete()
            for idx, image_url in enumerate(detail_images_data):
                ProductDetail.objects.create(
                    product=instance,
                    image_url=image_url,
                    sort_order=idx
                )

        # 更新SKU
        if skus_data is not None:
            instance.skus.all().delete()
            for sku_data in skus_data:
                SKU.objects.create(product=instance, **sku_data)

        return instance


# ==================== 购物车序列化器 ====================

class CartItemSerializer(serializers.ModelSerializer):
    """购物车项序列化器"""
    product_info = serializers.SerializerMethodField()
    sku_info = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = [
            'id', 'product', 'sku', 'quantity', 'is_selected',
            'product_info', 'sku_info', 'subtotal', 'created_at'
        ]
        read_only_fields = ['user']

    def get_product_info(self, obj):
        return {
            'id': obj.product.id,
            'name': obj.product.name,
            'cover_image_url': obj.product.cover_image_url,
            'price': str(obj.product.price),
            'stock': obj.product.stock,
            'is_on_sale': obj.product.is_on_sale
        }

    def get_sku_info(self, obj):
        if obj.sku:
            return {
                'id': obj.sku.id,
                'name': obj.sku.name,
                'spec_values': obj.sku.spec_values,
                'price': str(obj.sku.price),
                'stock': obj.sku.stock,
                'image_url': obj.sku.image_url
            }
        return None

    def get_subtotal(self, obj):
        if obj.sku:
            return str(obj.sku.price * obj.quantity)
        return str(obj.product.price * obj.quantity)


class CartItemCreateSerializer(serializers.ModelSerializer):
    """购物车添加序列化器"""

    class Meta:
        model = CartItem
        fields = ['product', 'sku', 'quantity']

    def validate(self, attrs):
        product = attrs.get('product')
        sku = attrs.get('sku')
        quantity = attrs.get('quantity', 1)

        # 检查商品状态
        if not product.is_on_sale:
            raise serializers.ValidationError('商品已下架或售罄')

        # 检查库存
        stock = sku.stock if sku else product.stock
        if quantity > stock:
            raise serializers.ValidationError(f'库存不足，当前库存：{stock}')

        return attrs

    def create(self, validated_data):
        user = self.context['request'].user
        product = validated_data['product']
        sku = validated_data.get('sku')
        quantity = validated_data.get('quantity', 1)

        # 查找现有购物车项
        cart_item, created = CartItem.objects.get_or_create(
            user=user,
            product=product,
            sku=sku,
            defaults={'quantity': quantity}
        )

        if not created:
            cart_item.quantity += quantity
            cart_item.save()

        return cart_item


# ==================== 订单序列化器 ====================

class OrderItemSerializer(serializers.ModelSerializer):
    """订单商品项序列化器"""

    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'sku', 'product_name', 'product_image',
            'sku_name', 'spec_values', 'price', 'quantity', 'total_amount'
        ]


class OrderListSerializer(serializers.ModelSerializer):
    """订单列表序列化器"""
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_no', 'status', 'status_display',
            'total_amount', 'freight_amount', 'discount_amount', 'pay_amount',
            'items', 'item_count', 'created_at'
        ]

    def get_item_count(self, obj):
        return sum(item.quantity for item in obj.items.all())


class OrderDetailSerializer(serializers.ModelSerializer):
    """订单详情序列化器"""
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(
        source='get_payment_method_display',
        read_only=True
    )
    logs = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_no', 'status', 'status_display',
            'total_amount', 'freight_amount', 'discount_amount', 'pay_amount',
            'payment_method', 'payment_method_display', 'payment_time', 'payment_no',
            'receiver_name', 'receiver_phone', 'receiver_province',
            'receiver_city', 'receiver_district', 'receiver_address', 'full_address',
            'shipping_company', 'shipping_no', 'shipping_time',
            'remark', 'cancel_reason', 'complete_time',
            'items', 'logs', 'created_at', 'updated_at'
        ]

    def get_logs(self, obj):
        logs = obj.logs.all()[:10]
        return [{
            'action': log.action,
            'description': log.description,
            'created_at': log.created_at
        } for log in logs]


class OrderCreateSerializer(serializers.Serializer):
    """订单创建序列化器"""
    cart_item_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text='购物车项ID列表'
    )
    products = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text='直接购买的商品列表 [{"product_id": 1, "sku_id": null, "quantity": 1}]'
    )

    # 收货地址
    receiver_name = serializers.CharField(max_length=50)
    receiver_phone = serializers.CharField(max_length=20)
    receiver_province = serializers.CharField(max_length=50)
    receiver_city = serializers.CharField(max_length=50)
    receiver_district = serializers.CharField(max_length=50)
    receiver_address = serializers.CharField(max_length=200)

    remark = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        cart_item_ids = attrs.get('cart_item_ids', [])
        products = attrs.get('products', [])

        if not cart_item_ids and not products:
            raise serializers.ValidationError('请选择要购买的商品')

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user = self.context['request'].user
        cart_item_ids = validated_data.get('cart_item_ids', [])
        products_data = validated_data.get('products', [])

        order_items = []
        total_amount = 0
        freight_amount = 0

        # 处理购物车商品
        if cart_item_ids:
            cart_items = CartItem.objects.filter(
                id__in=cart_item_ids,
                user=user
            ).select_related('product', 'sku')

            for cart_item in cart_items:
                product = cart_item.product
                sku = cart_item.sku
                quantity = cart_item.quantity

                # 验证商品状态和库存
                if not product.is_on_sale:
                    raise serializers.ValidationError(f'商品 {product.name} 已下架')

                stock = sku.stock if sku else product.stock
                if quantity > stock:
                    raise serializers.ValidationError(f'商品 {product.name} 库存不足')

                price = sku.price if sku else product.price

                order_items.append({
                    'product': product,
                    'sku': sku,
                    'product_name': product.name,
                    'product_image': sku.image_url if sku and sku.image_url else product.cover_image_url,
                    'sku_name': sku.name if sku else '',
                    'spec_values': sku.spec_values if sku else {},
                    'price': price,
                    'quantity': quantity
                })

                total_amount += price * quantity
                freight_amount = max(freight_amount, product.freight)

        # 处理直接购买的商品
        for item_data in products_data:
            product_id = item_data.get('product_id')
            sku_id = item_data.get('sku_id')
            quantity = item_data.get('quantity', 1)

            product = Product.objects.get(id=product_id)
            sku = SKU.objects.get(id=sku_id) if sku_id else None

            if not product.is_on_sale:
                raise serializers.ValidationError(f'商品 {product.name} 已下架')

            stock = sku.stock if sku else product.stock
            if quantity > stock:
                raise serializers.ValidationError(f'商品 {product.name} 库存不足')

            price = sku.price if sku else product.price

            order_items.append({
                'product': product,
                'sku': sku,
                'product_name': product.name,
                'product_image': sku.image_url if sku and sku.image_url else product.cover_image_url,
                'sku_name': sku.name if sku else '',
                'spec_values': sku.spec_values if sku else {},
                'price': price,
                'quantity': quantity
            })

            total_amount += price * quantity
            freight_amount = max(freight_amount, product.freight)

        # 计算实付金额
        pay_amount = total_amount + freight_amount

        # 创建订单
        order = Order.objects.create(
            user=user,
            total_amount=total_amount,
            freight_amount=freight_amount,
            discount_amount=0,
            pay_amount=pay_amount,
            receiver_name=validated_data['receiver_name'],
            receiver_phone=validated_data['receiver_phone'],
            receiver_province=validated_data['receiver_province'],
            receiver_city=validated_data['receiver_city'],
            receiver_district=validated_data['receiver_district'],
            receiver_address=validated_data['receiver_address'],
            remark=validated_data.get('remark', '')
        )

        # 创建订单项
        for item in order_items:
            product = item.pop('product')
            sku = item.pop('sku')

            OrderItem.objects.create(
                order=order,
                product=product,
                sku=sku,
                **item
            )

            # 扣减库存
            if sku:
                sku.stock -= item['quantity']
                sku.save()
            else:
                product.stock -= item['quantity']

            # 增加销量
            product.sales += item['quantity']
            product.save()

        # 删除购物车中已购买的商品
        if cart_item_ids:
            CartItem.objects.filter(id__in=cart_item_ids, user=user).delete()

        # 记录订单日志
        OrderLog.objects.create(
            order=order,
            action='CREATE',
            description='订单创建',
            operator=user
        )

        return order


class OrderPaySerializer(serializers.Serializer):
    """订单支付序列化器"""
    payment_method = serializers.ChoiceField(choices=PAYMENT_METHOD_CHOICES)
    payment_no = serializers.CharField(max_length=64, required=False)


class OrderShipSerializer(serializers.Serializer):
    """订单发货序列化器"""
    shipping_company = serializers.CharField(max_length=50)
    shipping_no = serializers.CharField(max_length=50)


# ==================== 收藏序列化器 ====================

class ProductFavoriteSerializer(serializers.ModelSerializer):
    """商品收藏序列化器"""
    product_info = serializers.SerializerMethodField()

    class Meta:
        model = ProductFavorite
        fields = ['id', 'product', 'product_info', 'created_at']
        read_only_fields = ['user']

    def get_product_info(self, obj):
        return {
            'id': obj.product.id,
            'name': obj.product.name,
            'cover_image_url': obj.product.cover_image_url,
            'price': str(obj.product.price),
            'original_price': str(obj.product.original_price) if obj.product.original_price else None,
            'is_on_sale': obj.product.is_on_sale
        }