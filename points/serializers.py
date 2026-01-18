# -*- coding: utf-8 -*-
# @Time    : 2026/1/3 18:54
# @Author  : Delock

from rest_framework import serializers
from .models import (
    IntegralProduct, IntegralOrder, IntegralRecord,
    UserIntegralProduct, User, UserAddress
)


class IntegralProductListSerializer(serializers.ModelSerializer):
    """积分商品列表序列化器"""

    class Meta:
        model = IntegralProduct
        fields = [
            'id', 'name', 'cover_image', 'product_type', 'category',
            'integral_price', 'original_price', 'stock', 'sales_count',
            'is_hot', 'is_new', 'status'
        ]


class IntegralProductDetailSerializer(serializers.ModelSerializer):
    """积分商品详情序列化器"""

    user_exchange_count = serializers.SerializerMethodField()
    can_exchange = serializers.SerializerMethodField()

    class Meta:
        model = IntegralProduct
        fields = [
            'id', 'name', 'description', 'cover_image', 'images',
            'product_type', 'category', 'integral_price', 'original_price',
            'stock', 'sales_count', 'limit_per_user', 'status',
            'validity_days', 'is_hot', 'is_new',
            'user_exchange_count', 'can_exchange', 'created_at'
        ]

    def get_user_exchange_count(self, obj):
        """获取用户已兑换数量"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return IntegralOrder.objects.filter(
                user=request.user,
                product=obj,
                status__in=['pending', 'shipped', 'completed']
            ).count()
        return 0

    def get_can_exchange(self, obj):
        """检查用户是否可以兑换"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        user = request.user

        # 检查库存
        if not obj.is_available:
            return False

        # 检查积分
        if user.integral < obj.integral_price:
            return False

        # 检查限购
        if obj.limit_per_user > 0:
            exchanged_count = self.get_user_exchange_count(obj)
            if exchanged_count >= obj.limit_per_user:
                return False

        return True


class IntegralOrderCreateSerializer(serializers.Serializer):
    """创建积分订单序列化器"""

    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(default=1, min_value=1, max_value=10)
    address_id = serializers.IntegerField(required=False, allow_null=True)
    user_remark = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_product_id(self, value):
        try:
            product = IntegralProduct.objects.get(id=value)
            if not product.is_available:
                raise serializers.ValidationError("商品已下架或库存不足")
            return value
        except IntegralProduct.DoesNotExist:
            raise serializers.ValidationError("商品不存在")

    def validate(self, attrs):
        product = IntegralProduct.objects.get(id=attrs['product_id'])
        user = self.context['request'].user
        quantity = attrs.get('quantity', 1)

        # 验证库存
        if product.stock < quantity:
            raise serializers.ValidationError("库存不足")

        # 验证积分
        total_integral = product.integral_price * quantity
        if user.integral < total_integral:
            raise serializers.ValidationError("积分不足")

        # 验证限购
        if product.limit_per_user > 0:
            exchanged_count = IntegralOrder.objects.filter(
                user=user,
                product=product,
                status__in=['pending', 'shipped', 'completed']
            ).count()
            if exchanged_count + quantity > product.limit_per_user:
                raise serializers.ValidationError(f"超过限购数量，每人限购{product.limit_per_user}件")

        # 实物商品必须提供地址
        if product.product_type == 'physical':
            address_id = attrs.get('address_id')
            if not address_id:
                raise serializers.ValidationError("实物商品必须提供收货地址")

            try:
                address = UserAddress.objects.get(id=address_id, user=user)
                attrs['address'] = address
            except UserAddress.DoesNotExist:
                raise serializers.ValidationError("收货地址不存在")

        attrs['product'] = product
        attrs['total_integral'] = total_integral
        return attrs


class UserAddressSerializer(serializers.ModelSerializer):
    """用户地址序列化器"""

    class Meta:
        model = UserAddress
        fields = [
            'id', 'receiver_name', 'receiver_phone', 'province',
            'city', 'district', 'detail_address', 'is_default',
            'tag', 'created_at'
        ]


class IntegralOrderSerializer(serializers.ModelSerializer):
    """积分订单序列化器"""

    product_info = IntegralProductListSerializer(source='product', read_only=True)
    address_info = UserAddressSerializer(source='address', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = IntegralOrder
        fields = [
            'id', 'order_no', 'product_info', 'product_snapshot',
            'quantity', 'integral_cost', 'status', 'status_display',
            'address_info', 'receiver_name', 'receiver_phone', 'receiver_address',
            'express_company', 'express_no', 'user_remark',
            'created_at', 'shipped_at', 'completed_at'
        ]


class IntegralRecordSerializer(serializers.ModelSerializer):
    """积分记录序列化器"""

    record_type_display = serializers.CharField(source='get_record_type_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model = IntegralRecord
        fields = [
            'id', 'record_type', 'record_type_display', 'source',
            'source_display', 'amount', 'balance', 'description', 'created_at'
        ]


class UserIntegralProductSerializer(serializers.ModelSerializer):
    """用户虚拟商品序列化器"""

    product_info = IntegralProductListSerializer(source='product', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = UserIntegralProduct
        fields = [
            'id', 'product_info', 'content', 'code',
            'is_used', 'used_at', 'expired_at', 'is_expired', 'created_at'
        ]