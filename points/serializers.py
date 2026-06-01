# -*- coding: utf-8 -*-
# @Time    : 2026/1/3 18:54
# @Author  : Delock

from rest_framework import serializers
from .models import (
    IntegralProduct, IntegralOrder, IntegralRecord,
    UserIntegralProduct, User, UserAddress
)
from wallet.models import WalletTransaction


def points_balance_of(user):
    """读取用户钱包的积分余额（钱包不存在时按 0 处理）。

    积分已迁移到 UserWallet(user.wallet).points_balance，
    原先散落各处的 user.integral 统一改走这里。
    """
    wallet = getattr(user, 'wallet', None)
    return wallet.points_balance if wallet is not None else 0


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

        # 检查积分（改读钱包余额）
        if points_balance_of(user) < obj.integral_price:
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

        # 验证积分（改读钱包余额）
        total_integral = product.integral_price * quantity
        if points_balance_of(user) < total_integral:
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
    """积分记录序列化器（旧的 IntegralRecord 模型；积分迁入钱包后已不再使用，保留以兼容历史引用）"""

    record_type_display = serializers.CharField(source='get_record_type_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)

    class Meta:
        model = IntegralRecord
        fields = [
            'id', 'record_type', 'record_type_display', 'source',
            'source_display', 'amount', 'balance', 'description', 'created_at'
        ]


class PointsTransactionSerializer(serializers.ModelSerializer):
    """积分流水序列化器（基于钱包 WalletTransaction，仅积分币种）

    替代原 IntegralRecordSerializer 作为“我的积分流水 / 后台积分流水”的输出。
    """

    action_display = serializers.CharField(source='get_action_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'user_id', 'action', 'action_display',
            'amount', 'balance_after',
            'status', 'status_display',
            'related_type', 'related_id', 'remark', 'created_at',
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


# ==========================================================================
# 平台后台（Manager）序列化器
# ==========================================================================

class IntegralProductAdminSerializer(serializers.ModelSerializer):
    """积分商品管理序列化器（平台后台）

    全字段可写，便于后台增删改商品；销量、时间戳保持只读。
    不读取 request.user，可安全用于 ManagerAuthentication 下的接口。
    """
    product_type_display = serializers.CharField(source='get_product_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = IntegralProduct
        fields = [
            'id', 'name', 'description', 'cover_image', 'images',
            'product_type', 'product_type_display', 'category',
            'integral_price', 'original_price',
            'stock', 'total_stock', 'sales_count',
            'limit_per_user', 'status', 'status_display',
            'sort_order', 'is_hot', 'is_new',
            'virtual_content', 'validity_days',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'sales_count', 'created_at', 'updated_at']


class IntegralOrderAdminSerializer(serializers.ModelSerializer):
    """积分订单管理序列化器（平台后台）

    在用户版基础上补充下单用户信息，便于后台识别；纯展示用，
    状态流转（发货/完成/取消）走 AdminIntegralOrderViewSet 的动作接口。
    """
    user_info = serializers.SerializerMethodField()
    product_info = IntegralProductListSerializer(source='product', read_only=True)
    address_info = UserAddressSerializer(source='address', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = IntegralOrder
        fields = [
            'id', 'order_no', 'user_info', 'product_info', 'product_snapshot',
            'quantity', 'integral_cost', 'status', 'status_display',
            'address_info', 'receiver_name', 'receiver_phone', 'receiver_address',
            'express_company', 'express_no', 'user_remark', 'admin_remark',
            'created_at', 'shipped_at', 'completed_at', 'cancelled_at',
        ]

    def get_user_info(self, obj):
        user = obj.user
        return {
            'id': user.id,
            'display_name': getattr(user, 'display_name', None) or getattr(user, 'username', None),
        }