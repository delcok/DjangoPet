# -*- coding: utf-8 -*-
# @Time    : 2025/10/20 18:51
# @Author  : Delock

from rest_framework import serializers
from .models import PetCategory, Pet, PetDiary, PetServiceRecord


class PetCategorySerializer(serializers.ModelSerializer):
    """宠物分类序列化器"""

    class Meta:
        model = PetCategory
        fields = [
            'id', 'name', 'icon', 'sort_order',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class PetListSerializer(serializers.ModelSerializer):
    """宠物列表序列化器（简化版）"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    age_display = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)

    class Meta:
        model = Pet
        fields = [
            'id', 'name', 'category', 'category_name', 'breed',
            'avatar', 'gender', 'gender_display', 'age_display',
            'created_at'
        ]

    def get_age_display(self, obj):
        """返回年龄显示"""
        total = obj.age_months
        if total is None:
            # 返回 None（前端可自行显示“未知”），或者改成返回 '未知年龄'
            return None
        years = obj.age_years
        months = obj.age_months % 12
        if years > 0:
            return f"{years}岁{months}个月" if months > 0 else f"{years}岁"
        return f"{months}个月"


class PetDetailSerializer(serializers.ModelSerializer):
    """宠物详情序列化器"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    owner_name = serializers.CharField(source='owner.username', read_only=True)
    age_years = serializers.IntegerField(read_only=True)
    age_months = serializers.IntegerField(read_only=True)
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)

    class Meta:
        model = Pet
        fields = [
            'id', 'owner', 'owner_name', 'category', 'category_name',
            'name', 'breed', 'birth_date', 'gender', 'gender_display',
            'weight', 'color', 'avatar', 'personality', 'health_status',
            'vaccination_record', 'special_notes', 'age_years', 'age_months',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['owner', 'created_at', 'updated_at']

    def create(self, validated_data):
        # 自动设置当前用户为宠物主人
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)


class PetDiaryListSerializer(serializers.ModelSerializer):
    """宠物日记列表序列化器"""
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True)
    diary_type_display = serializers.CharField(source='get_diary_type_display', read_only=True)
    image_count = serializers.SerializerMethodField()

    class Meta:
        model = PetDiary
        fields = [
            'id', 'pet', 'pet_name', 'author', 'author_name',
            'diary_type', 'diary_type_display', 'title',
            'diary_date', 'image_count', 'created_at'
        ]

    def get_image_count(self, obj):
        return len(obj.images) if obj.images else 0


class PetDiaryDetailSerializer(serializers.ModelSerializer):
    """宠物日记详情序列化器"""
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True)
    diary_type_display = serializers.CharField(source='get_diary_type_display', read_only=True)

    class Meta:
        model = PetDiary
        fields = [
            'id', 'pet', 'pet_name', 'author', 'author_name',
            'diary_type', 'diary_type_display', 'title', 'content',
            'images', 'videos', 'diary_date', 'created_at', 'updated_at'
        ]
        read_only_fields = ['author', 'created_at', 'updated_at']

    def create(self, validated_data):
        # 自动设置当前用户为记录人
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)

    def validate_pet(self, value):
        """验证宠物是否属于当前用户"""
        user = self.context['request'].user
        if value.owner != user and not user.type == 'admin':
            raise serializers.ValidationError("您没有权限为该宠物创建日记")
        return value


class PetServiceRecordListSerializer(serializers.ModelSerializer):
    """宠物服务记录列表序列化器"""
    pet_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    provider_name = serializers.SerializerMethodField()
    order_number = serializers.CharField(source='related_order.order_number', read_only=True)

    class Meta:
        model = PetServiceRecord
        fields = [
            'id', 'related_order', 'order_number', 'pet_name',
            'service_name', 'provider_name', 'actual_start_time',
            'actual_end_time', 'rating', 'created_at'
        ]

    def get_pet_name(self, obj):
        pet = obj.pet
        return pet.name if pet else None

    def get_service_name(self, obj):
        service = obj.related_order.service
        return service.name if service else None

    def get_provider_name(self, obj):
        provider = obj.service_provider
        return provider.username if provider else None


class PetServiceRecordDetailSerializer(serializers.ModelSerializer):
    """宠物服务记录详情序列化器"""
    pet_info = serializers.SerializerMethodField()
    service_info = serializers.SerializerMethodField()
    provider_info = serializers.SerializerMethodField()
    order_info = serializers.SerializerMethodField()

    class Meta:
        model = PetServiceRecord
        fields = [
            'id', 'related_order', 'related_diary', 'order_info',
            'pet_info', 'service_info', 'provider_info',
            'actual_start_time', 'actual_end_time', 'actual_duration',
            'pet_condition_before', 'pet_condition_after', 'pet_behavior_notes',
            'service_summary', 'professional_recommendations', 'next_service_suggestion',
            'before_images', 'after_images', 'process_videos',
            'special_notes', 'customer_feedback', 'rating',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'actual_duration']

    def get_pet_info(self, obj):
        pet = obj.pet
        if pet:
            return {
                'id': pet.id,
                'name': pet.name,
                'breed': pet.breed,
                'avatar': pet.avatar
            }
        return None

    def get_service_info(self, obj):
        service = obj.related_order.service
        if service:
            return {
                'id': service.id,
                'name': service.name
            }
        return None

    def get_provider_info(self, obj):
        provider = obj.service_provider
        if provider:
            return {
                'id': provider.id,
                'username': provider.username
            }
        return None

    def get_order_info(self, obj):
        order = obj.related_order
        return {
            'id': order.id,
            'order_number': order.order_number,
            'status': order.status
        }

    def validate(self, data):
        """验证时间逻辑"""
        if 'actual_start_time' in data and 'actual_end_time' in data:
            if data['actual_end_time'] <= data['actual_start_time']:
                raise serializers.ValidationError("结束时间必须晚于开始时间")
        return data


class PetServiceRecordCreateSerializer(serializers.ModelSerializer):
    """宠物服务记录创建序列化器（服务商使用）"""

    class Meta:
        model = PetServiceRecord
        fields = [
            'related_order', 'actual_start_time', 'actual_end_time',
            'pet_condition_before', 'pet_condition_after', 'pet_behavior_notes',
            'service_summary', 'professional_recommendations', 'next_service_suggestion',
            'before_images', 'after_images', 'process_videos', 'special_notes'
        ]

    def validate_related_order(self, value):
        """验证订单状态和权限"""
        user = self.context['request'].user

        # 检查是否已存在服务记录
        if hasattr(value, 'service_record'):
            raise serializers.ValidationError("该订单已有服务记录")

        # 检查是否是服务提供者
        if value.staff != user:
            raise serializers.ValidationError("您没有权限为该订单创建服务记录")

        # 检查订单状态
        if value.status != 'completed':
            raise serializers.ValidationError("只能为已完成的订单创建服务记录")

        return value

