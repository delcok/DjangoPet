# -*- coding: utf-8 -*-
# @Time    : 2025/8/25 16:30
# @Author  : Delock

from rest_framework import serializers
from decimal import Decimal
from bill.models import Bill, ServiceOrder
from pet.models import Pet
from service.models import ServiceModel, AdditionalService


class BillSerializer(serializers.ModelSerializer):
    """账单序列化器"""
    user_info = serializers.SerializerMethodField()
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)

    class Meta:
        model = Bill
        fields = [
            'id', 'out_trade_no', 'wechat_transaction_id', 'user', 'user_info',
            'transaction_type', 'transaction_type_display', 'amount', 'payment_method',
            'payment_method_display', 'payment_status', 'payment_status_display',
            'created_at', 'description'
        ]
        read_only_fields = ['id', 'out_trade_no', 'wechat_transaction_id', 'created_at']

    def get_user_info(self, obj):
        """获取用户基本信息"""
        if obj.user:
            return {
                'id': obj.user.id,
                'username': obj.user.username,
                'phone': getattr(obj.user, 'phone', ''),
            }
        return None


class BillCreateSerializer(serializers.ModelSerializer):
    """创建账单序列化器"""

    class Meta:
        model = Bill
        fields = ['transaction_type', 'amount', 'payment_method', 'description']

    def validate_amount(self, value):
        """验证金额"""
        if value <= 0:
            raise serializers.ValidationError("金额必须大于0")
        return value


class ServiceOrderPetSerializer(serializers.ModelSerializer):
    """服务订单中的宠物信息序列化器"""

    class Meta:
        model = Pet
        fields = ['id', 'name', 'breed', 'age', 'weight']


class BaseServiceSerializer(serializers.ModelSerializer):
    """基础服务序列化器"""

    class Meta:
        model = ServiceModel
        fields = ['id', 'name', 'base_price', 'description', 'icon']


class AdditionalServiceSerializer(serializers.ModelSerializer):
    """附加服务序列化器"""

    class Meta:
        model = AdditionalService
        fields = ['id', 'name', 'price', 'description', 'icon']


class ServiceOrderSerializer(serializers.ModelSerializer):
    """服务订单序列化器"""
    user_info = serializers.SerializerMethodField()
    staff_info = serializers.SerializerMethodField()
    pets_info = ServiceOrderPetSerializer(source='pets', many=True, read_only=True)
    bill_info = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    # 新增服务信息
    base_service_info = BaseServiceSerializer(source='base_service', read_only=True)
    additional_services_info = AdditionalServiceSerializer(source='additional_services', many=True, read_only=True)

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'bill', 'bill_info', 'user', 'user_info', 'staff', 'staff_info',
            'pets', 'pets_info',
            'base_service', 'base_service_info',  # 新增
            'additional_services', 'additional_services_info',  # 新增
            'scheduled_date', 'scheduled_time', 'duration_minutes',
            'service_address', 'contact_phone', 'base_price', 'additional_price',
            'total_price', 'status', 'status_display', 'customer_notes', 'staff_notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'total_price', 'created_at', 'updated_at']

    def get_user_info(self, obj):
        """获取用户基本信息"""
        if obj.user:
            return {
                'id': obj.user.id,
                'username': obj.user.username,
                'phone': getattr(obj.user, 'phone', ''),
            }
        return None

    def get_staff_info(self, obj):
        """获取员工基本信息"""
        if obj.staff:
            return {
                'id': obj.staff.id,
                'name': obj.staff.name,
                'phone': getattr(obj.staff, 'phone', ''),
            }
        return None

    def get_bill_info(self, obj):
        """获取账单基本信息"""
        if obj.bill:
            return {
                'id': obj.bill.id,
                'out_trade_no': obj.bill.out_trade_no,
                'amount': obj.bill.amount,
                'payment_status': obj.bill.payment_status,
                'payment_status_display': obj.bill.get_payment_status_display(),
            }
        return None


class ServiceOrderCreateSerializer(serializers.ModelSerializer):
    """创建服务订单序列化器"""
    pets = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.all(),
        many=True,
        help_text="宠物ID列表"
    )
    base_service = serializers.PrimaryKeyRelatedField(
        queryset=ServiceModel.objects.filter(is_active=True),
        help_text="基础服务ID"
    )
    additional_services = serializers.PrimaryKeyRelatedField(
        queryset=AdditionalService.objects.filter(is_active=True),
        many=True,
        required=False,
        help_text="附加服务ID列表"
    )

    class Meta:
        model = ServiceOrder
        fields = [
            'base_service', 'additional_services',  # 新增
            'scheduled_date', 'scheduled_time', 'duration_minutes',
            'service_address', 'contact_phone',
            'customer_notes', 'pets'
        ]

    def validate_pets(self, value):
        """验证宠物是否属于当前用户"""
        user = self.context['request'].user
        for pet in value:
            if pet.owner != user:
                raise serializers.ValidationError(f"宠物 {pet.name} 不属于当前用户")
        return value

    def validate_base_service(self, value):
        """验证基础服务是否激活"""
        if not value.is_active:
            raise serializers.ValidationError("该基础服务已停用")
        return value

    def validate_additional_services(self, value):
        """验证附加服务是否激活"""
        for service in value:
            if not service.is_active:
                raise serializers.ValidationError(f"附加服务 {service.name} 已停用")
        return value

    def create(self, validated_data):
        """创建订单并自动计算价格"""
        additional_services = validated_data.pop('additional_services', [])
        pets = validated_data.pop('pets', [])

        # 计算价格
        base_service = validated_data['base_service']
        base_price = base_service.base_price
        additional_price = sum(service.price for service in additional_services)

        # 创建订单
        order = ServiceOrder.objects.create(
            **validated_data,
            base_price=base_price,
            additional_price=additional_price,
            total_price=base_price + additional_price
        )

        # 关联宠物
        order.pets.set(pets)

        # 关联附加服务
        if additional_services:
            order.additional_services.set(additional_services)

        return order


class ServiceOrderUpdateSerializer(serializers.ModelSerializer):
    """更新服务订单序列化器"""
    additional_services = serializers.PrimaryKeyRelatedField(
        queryset=AdditionalService.objects.filter(is_active=True),
        many=True,
        required=False,
        help_text="附加服务ID列表"
    )

    class Meta:
        model = ServiceOrder
        fields = [
            'staff', 'scheduled_date', 'scheduled_time', 'duration_minutes',
            'service_address', 'contact_phone', 'status', 'customer_notes',
            'staff_notes', 'additional_services'  # 允许更新附加服务
        ]

    def validate_status(self, value):
        """验证状态变更"""
        instance = self.instance
        if instance:
            # 定义状态变更规则
            allowed_transitions = {
                'pending': ['confirmed', 'cancelled'],
                'confirmed': ['in_progress', 'cancelled'],
                'in_progress': ['completed'],
                'completed': [],  # 已完成的订单不能再变更状态
                'cancelled': [],  # 已取消的订单不能再变更状态
            }

            current_status = instance.status
            if value not in allowed_transitions.get(current_status, []):
                raise serializers.ValidationError(
                    f"订单状态不能从 {current_status} 变更为 {value}"
                )
        return value

    def update(self, instance, validated_data):
        """更新订单并重新计算价格"""
        additional_services = validated_data.pop('additional_services', None)

        # 更新基本字段
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # 如果更新了附加服务,重新计算价格
        if additional_services is not None:
            instance.additional_services.set(additional_services)
            instance.update_prices()  # 使用模型中的方法重新计算价格

        instance.save()
        return instance


class ServiceOrderSimpleSerializer(serializers.ModelSerializer):
    """简单的服务订单序列化器（用于列表展示）"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    pets_count = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    base_service_name = serializers.CharField(source='base_service.name', read_only=True)
    additional_services_count = serializers.SerializerMethodField()

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'user_name', 'pets_count', 'base_service_name',
            'additional_services_count', 'scheduled_date', 'scheduled_time',
            'total_price', 'status', 'status_display', 'created_at'
        ]

    def get_pets_count(self, obj):
        """获取宠物数量"""
        return obj.pets.count()

    def get_additional_services_count(self, obj):
        """获取附加服务数量"""
        return obj.additional_services.count()