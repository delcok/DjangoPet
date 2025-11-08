# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Modified for better order flow

from rest_framework import serializers
from decimal import Decimal
from django.utils import timezone
from bill.models import Bill, ServiceOrder
from pet.models import Pet
from staff.models import Staff
from user.models import User
from service.models import ServiceModel, AdditionalService, PetType


class ServiceOrderPetSerializer(serializers.ModelSerializer):
    """服务订单中的宠物信息序列化器"""
    # 修改：直接使用 category.name，因为 Pet 模型中是 category 字段
    pet_type_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Pet
        fields = ['id', 'name', 'pet_type_name', 'breed', 'weight']


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


class ServiceOrderListSerializer(serializers.ModelSerializer):
    """服务订单列表序列化器（简化版）"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    base_service_name = serializers.CharField(source='base_service.name', read_only=True)
    pets_count = serializers.SerializerMethodField()
    additional_services_count = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    latest_bill_status = serializers.SerializerMethodField()

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'user_name', 'base_service_name', 'pets_count',
            'additional_services_count', 'scheduled_date', 'scheduled_time',
            'total_price', 'final_price', 'status', 'status_display',
            'latest_bill_status', 'created_at'
        ]

    def get_pets_count(self, obj):
        return obj.pets.count()

    def get_additional_services_count(self, obj):
        return obj.additional_services.count()

    def get_latest_bill_status(self, obj):
        """获取最新的支付账单状态"""
        latest_bill = obj.bills.filter(transaction_type='payment').order_by('-created_at').first()
        if latest_bill:
            return {
                'status': latest_bill.payment_status,
                'status_display': latest_bill.get_payment_status_display()
            }
        return None


class ServiceOrderDetailSerializer(serializers.ModelSerializer):
    """服务订单详情序列化器"""
    user_info = serializers.SerializerMethodField()
    staff_info = serializers.SerializerMethodField()
    pets_info = ServiceOrderPetSerializer(source='pets', many=True, read_only=True)
    base_service_info = BaseServiceSerializer(source='base_service', read_only=True)
    additional_services_info = AdditionalServiceSerializer(
        source='additional_services', many=True, read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    bills = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_refund = serializers.SerializerMethodField()

    class Meta:
        model = ServiceOrder
        fields = [
            'id', 'user', 'user_info', 'staff', 'staff_info',
            'pets', 'pets_info', 'base_service', 'base_service_info',
            'additional_services', 'additional_services_info',
            'scheduled_date', 'scheduled_time', 'duration_minutes',
            'province', 'city', 'district',
            'service_address', 'contact_phone', 'contact_name',
            'base_price', 'additional_price', 'total_price',
            'discount_amount', 'final_price',
            'status', 'status_display', 'can_cancel', 'can_refund',
            'customer_notes', 'staff_notes', 'cancel_reason',
            'bills', 'created_at', 'updated_at', 'paid_at', 'completed_at'
        ]

    def get_user_info(self, obj):
        if obj.user:
            return {
                'id': obj.user.id,
                'username': obj.user.username,
                'phone': getattr(obj.user, 'phone', ''),
            }
        return None

    def get_staff_info(self, obj):
        if obj.staff:
            return {
                'id': obj.staff.id,
                'name': obj.staff.name,
                'phone': getattr(obj.staff, 'phone', ''),
            }
        return None

    def get_bills(self, obj):
        """获取相关的账单信息"""
        bills = obj.bills.all().order_by('-created_at')
        return [{
            'id': bill.id,
            'out_trade_no': bill.out_trade_no,
            'transaction_type': bill.transaction_type,
            'transaction_type_display': bill.get_transaction_type_display(),
            'amount': bill.amount,
            'payment_method': bill.payment_method,
            'payment_status': bill.payment_status,
            'payment_status_display': bill.get_payment_status_display(),
            'created_at': bill.created_at,
            'paid_at': bill.paid_at
        } for bill in bills]

    def get_can_cancel(self, obj):
        return obj.can_cancel()

    def get_can_refund(self, obj):
        return obj.can_refund()


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
            'base_service', 'additional_services', 'pets',
            'scheduled_date', 'scheduled_time', 'duration_minutes',
            'province', 'city', 'district',
            'service_address', 'contact_phone', 'contact_name',
            'customer_notes', 'discount_amount'
        ]

    def validate_pets(self, value):
        """验证宠物是否属于当前用户"""
        user = self.context['request'].user
        for pet in value:
            if pet.owner != user:
                raise serializers.ValidationError(f"宠物 {pet.name} 不属于当前用户")
            if pet.is_deleted:
                raise serializers.ValidationError(f"宠物 {pet.name} 已被删除")
        if not value:
            raise serializers.ValidationError("请至少选择一只宠物")
        return value

    def validate_base_service(self, value):
        """验证基础服务"""
        if not value.is_active:
            raise serializers.ValidationError("该基础服务已停用")
        return value

    def validate_additional_services(self, value):
        """验证附加服务"""
        for service in value:
            if not service.is_active:
                raise serializers.ValidationError(f"附加服务 {service.name} 已停用")
        return value

    def create(self, validated_data):
        """
        创建服务订单
        关键修复：先 pop 多对多字段，手动计算价格，创建对象时传入所有价格，
        最后再设置多对多关系
        """
        # 1. 提取多对多字段（必须在创建对象前提取）
        additional_services = validated_data.pop('additional_services', [])
        pets = validated_data.pop('pets', [])

        # 2. 获取当前用户
        user = self.context['request'].user

        # 3. 手动计算价格（不依赖模型的 calculate_prices 方法）
        base_service = validated_data['base_service']
        base_price = base_service.base_price

        # 计算附加服务总价
        additional_price = sum(service.price for service in additional_services)

        # 计算总价和最终价格
        total_price = base_price + additional_price
        discount_amount = validated_data.get('discount_amount', Decimal('0'))
        final_price = max(Decimal('0'), total_price - discount_amount)

        # 4. 创建订单对象，传入所有计算好的价格
        # 这样模型的 save() 方法就不需要调用 calculate_prices() 了
        service_order = ServiceOrder.objects.create(
            user=user,
            base_price=base_price,
            additional_price=additional_price,
            total_price=total_price,
            final_price=final_price,
            **validated_data
        )

        # 5. 现在对象已经有 id 了，可以安全地设置多对多关系
        service_order.pets.set(pets)
        if additional_services:
            service_order.additional_services.set(additional_services)

        return service_order


class ServiceOrderUpdateSerializer(serializers.ModelSerializer):
    """更新服务订单序列化器（仅允许更新部分字段）"""

    class Meta:
        model = ServiceOrder
        fields = [
            'scheduled_date', 'scheduled_time', 'duration_minutes',
            'province', 'city', 'district',
            'service_address', 'contact_phone', 'contact_name',
            'customer_notes'
        ]

    def validate(self, attrs):
        """验证更新条件"""
        if self.instance.status not in ['draft', 'paid']:
            raise serializers.ValidationError("只能修改待支付或已支付的订单")
        return attrs


class ServiceOrderCancelSerializer(serializers.ModelSerializer):
    """取消服务订单序列化器"""
    cancel_reason = serializers.CharField(required=True, help_text="取消原因")

    class Meta:
        model = ServiceOrder
        fields = ['cancel_reason']

    def validate(self, attrs):
        """验证是否可以取消"""
        if not self.instance.can_cancel():
            raise serializers.ValidationError(
                f"订单状态为 {self.instance.get_status_display()}，无法取消"
            )
        return attrs

    def update(self, instance, validated_data):
        """取消订单"""
        instance.status = 'cancelled'
        instance.cancel_reason = validated_data.get('cancel_reason', '')
        instance.save()
        return instance


class BillListSerializer(serializers.ModelSerializer):
    """账单列表序列化器"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display', read_only=True
    )
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', read_only=True
    )
    payment_status_display = serializers.CharField(
        source='get_payment_status_display', read_only=True
    )
    service_order_id = serializers.IntegerField(
        source='service_order.id', read_only=True
    )

    class Meta:
        model = Bill
        fields = [
            'id', 'out_trade_no', 'user_name', 'service_order_id',
            'transaction_type', 'transaction_type_display',
            'amount', 'payment_method', 'payment_method_display',
            'payment_status', 'payment_status_display',
            'created_at', 'paid_at'
        ]


class BillDetailSerializer(serializers.ModelSerializer):
    """账单详情序列化器"""
    user_info = serializers.SerializerMethodField()
    service_order_info = serializers.SerializerMethodField()
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display', read_only=True
    )
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', read_only=True
    )
    payment_status_display = serializers.CharField(
        source='get_payment_status_display', read_only=True
    )

    class Meta:
        model = Bill
        fields = [
            'id', 'out_trade_no', 'third_party_no',
            'user', 'user_info', 'service_order', 'service_order_info',
            'transaction_type', 'transaction_type_display',
            'amount', 'payment_method', 'payment_method_display',
            'payment_status', 'payment_status_display',
            'description', 'failure_reason',
            'refund_amount', 'refund_reason', 'original_bill',
            'created_at', 'updated_at', 'paid_at', 'expired_at'
        ]

    def get_user_info(self, obj):
        if obj.user:
            return {
                'id': obj.user.id,
                'username': obj.user.username,
                'phone': getattr(obj.user, 'phone', ''),
            }
        return None

    def get_service_order_info(self, obj):
        if obj.service_order:
            return {
                'id': obj.service_order.id,
                'base_service': obj.service_order.base_service.name,
                'scheduled_date': obj.service_order.scheduled_date,
                'scheduled_time': obj.service_order.scheduled_time,
                'total_price': obj.service_order.final_price,
                'status': obj.service_order.status,
                'status_display': obj.service_order.get_status_display()
            }
        return None


class CreatePaymentBillSerializer(serializers.Serializer):
    """创建支付账单序列化器"""
    service_order_id = serializers.IntegerField(help_text="服务订单ID")
    payment_method = serializers.ChoiceField(
        choices=Bill.PAYMENT_CHOICES,
        help_text="支付方式"
    )

    def validate_service_order_id(self, value):
        """验证服务订单"""
        try:
            service_order = ServiceOrder.objects.get(id=value)
        except ServiceOrder.DoesNotExist:
            raise serializers.ValidationError("服务订单不存在")

        # 验证订单是否属于当前用户
        user = self.context['request'].user
        if service_order.user != user:
            raise serializers.ValidationError("无权操作此订单")

        # 验证订单状态
        if service_order.status != 'draft':
            raise serializers.ValidationError(
                f"订单状态为 {service_order.get_status_display()}，无法创建支付订单"
            )

        # 检查是否已有待支付的账单
        existing_bill = Bill.objects.filter(
            service_order=service_order,
            transaction_type='payment',
            payment_status='pending'
        ).first()
        if existing_bill:
            raise serializers.ValidationError(
                f"该订单已有待支付账单：{existing_bill.out_trade_no}"
            )

        self.service_order = service_order
        return value

    def create(self, validated_data):
        """创建支付账单"""
        service_order = self.service_order
        user = self.context['request'].user

        # 创建支付账单
        bill = Bill.objects.create(
            user=user,
            service_order=service_order,
            transaction_type='payment',
            amount=service_order.final_price,
            payment_method=validated_data['payment_method'],
            payment_status='pending',
            description=f"服务订单#{service_order.id}支付"
        )

        return bill


class RefundBillSerializer(serializers.Serializer):
    """创建退款账单序列化器"""
    service_order_id = serializers.IntegerField(help_text="服务订单ID")
    refund_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="退款金额（不填则全额退款）"
    )
    refund_reason = serializers.CharField(help_text="退款原因")

    def validate_service_order_id(self, value):
        """验证服务订单"""
        try:
            service_order = ServiceOrder.objects.get(id=value)
        except ServiceOrder.DoesNotExist:
            raise serializers.ValidationError("服务订单不存在")

        # 验证权限
        user = self.context['request'].user
        if service_order.user != user and not user.is_staff:
            raise serializers.ValidationError("无权操作此订单")

        # 验证订单是否可退款
        if not service_order.can_refund():
            raise serializers.ValidationError(
                f"订单状态为 {service_order.get_status_display()}，无法退款"
            )

        # 获取原支付账单
        original_bill = Bill.objects.filter(
            service_order=service_order,
            transaction_type='payment',
            payment_status='success'
        ).first()
        if not original_bill:
            raise serializers.ValidationError("未找到原支付记录")

        self.service_order = service_order
        self.original_bill = original_bill
        return value

    def validate_refund_amount(self, value):
        """验证退款金额"""
        if hasattr(self, 'original_bill'):
            if value > self.original_bill.amount:
                raise serializers.ValidationError("退款金额不能大于原支付金额")
        return value

    def create(self, validated_data):
        """创建退款账单"""
        service_order = self.service_order
        original_bill = self.original_bill
        refund_amount = validated_data.get('refund_amount', original_bill.amount)

        # 创建退款账单
        refund_bill = Bill.objects.create(
            user=service_order.user,
            service_order=service_order,
            transaction_type='refund',
            amount=refund_amount,
            payment_method=original_bill.payment_method,
            payment_status='pending',
            refund_amount=refund_amount,
            refund_reason=validated_data['refund_reason'],
            original_bill=original_bill,
            description=f"服务订单#{service_order.id}退款"
        )

        return refund_bill