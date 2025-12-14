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
        if obj.age_months is None:
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
        read_only_fields = ['owner', 'created_at', 'updated_at', 'age_years', 'age_months']

    def create(self, validated_data):
        # 自动设置当前用户为宠物主人
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)

    def validate_weight(self, value):
        """验证体重"""
        if value is not None and value <= 0:
            raise serializers.ValidationError("体重必须大于0")
        return value


class PetDiaryListSerializer(serializers.ModelSerializer):
    """宠物日记列表序列化器"""
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True, allow_null=True)
    diary_type_display = serializers.CharField(source='get_diary_type_display', read_only=True)
    image_count = serializers.SerializerMethodField()
    video_count = serializers.SerializerMethodField()

    class Meta:
        model = PetDiary
        fields = [
            'id', 'pet', 'pet_name', 'author', 'author_name',
            'diary_type', 'diary_type_display', 'title', 'cover_image',
            'diary_date', 'image_count', 'video_count', 'created_at'
        ]

    def get_image_count(self, obj):
        return len(obj.images) if obj.images else 0

    def get_video_count(self, obj):
        return len(obj.videos) if obj.videos else 0


class PetDiaryDetailSerializer(serializers.ModelSerializer):
    """宠物日记详情序列化器"""
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True, allow_null=True)
    diary_type_display = serializers.CharField(source='get_diary_type_display', read_only=True)

    class Meta:
        model = PetDiary
        fields = [
            'id', 'pet', 'pet_name', 'author', 'author_name',
            'diary_type', 'diary_type_display', 'title', 'content',
            'images', 'videos', 'cover_image', 'diary_date',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['author', 'created_at', 'updated_at']

    def create(self, validated_data):
        # 自动设置当前用户为记录人
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)

    def validate_pet(self, value):
        """验证宠物是否属于当前用户"""
        user = self.context['request'].user
        # 检查是否是宠物主人或管理员
        if value.owner != user and user.type != 'admin':
            raise serializers.ValidationError("您没有权限为该宠物创建日记")
        return value

    def validate(self, data):
        """验证数据完整性"""
        # 如果设置了封面图，确保它在图片列表中
        images = data.get('images')
        cover_image = data.get('cover_image')
        if cover_image and images and len(images) > 0:
            if cover_image not in images:
                raise serializers.ValidationError("封面图片必须在图片列表中")

        return data

class PetServiceRecordListSerializer(serializers.ModelSerializer):
    """宠物服务记录列表序列化器"""
    pet_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    provider_name = serializers.SerializerMethodField()
    order_number = serializers.SerializerMethodField()
    order_status = serializers.CharField(source='related_order.status', read_only=True)

    class Meta:
        model = PetServiceRecord
        fields = [
            'id', 'related_order', 'order_number', 'order_status',
            'pet_name', 'service_name', 'provider_name',
            'actual_start_time', 'actual_end_time', 'actual_duration',
            'rating', 'created_at'
        ]

    def get_pet_name(self, obj):
        """获取宠物名称"""
        pet = obj.pet
        return pet.name if pet else None

    def get_service_name(self, obj):
        """获取服务名称 - 修复：使用 base_service 而不是 service"""
        try:
            if obj.related_order and obj.related_order.base_service:
                return obj.related_order.base_service.name
        except Exception:
            pass
        return None

    def get_provider_name(self, obj):
        """获取服务提供者名称"""
        provider = obj.service_provider
        return provider.username if provider else None

    def get_order_number(self, obj):
        """获取订单ID作为订单号"""
        return f"#{obj.related_order.id}" if obj.related_order else None


class PetServiceRecordDetailSerializer(serializers.ModelSerializer):
    """宠物服务记录详情序列化器"""
    pet_info = serializers.SerializerMethodField()
    service_info = serializers.SerializerMethodField()
    provider_info = serializers.SerializerMethodField()
    order_info = serializers.SerializerMethodField()
    diary_info = serializers.SerializerMethodField()

    class Meta:
        model = PetServiceRecord
        fields = [
            'id', 'related_order', 'related_diary', 'order_info',
            'pet_info', 'service_info', 'provider_info', 'diary_info',
            'actual_start_time', 'actual_end_time', 'actual_duration',
            'pet_condition_before', 'pet_condition_after', 'pet_behavior_notes',
            'service_summary', 'professional_recommendations', 'next_service_suggestion',
            'before_images', 'after_images', 'process_videos',
            'special_notes', 'customer_feedback', 'rating',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'actual_duration']

    def get_pet_info(self, obj):
        """获取宠物信息"""
        pet = obj.pet
        if pet:
            return {
                'id': pet.id,
                'name': pet.name,
                'breed': pet.breed,
                'avatar': pet.avatar,
                'gender': pet.gender,
                'gender_display': pet.get_gender_display()
            }
        return None

    def get_service_info(self, obj):
        """获取服务信息 - 修复：使用 base_service 而不是 service"""
        try:
            if obj.related_order and obj.related_order.base_service:
                service = obj.related_order.base_service
                return {
                    'id': service.id,
                    'name': service.name,
                }
        except Exception:
            pass
        return None

    def get_provider_info(self, obj):
        """获取服务提供者信息"""
        provider = obj.service_provider
        if provider:
            return {
                'id': provider.id,
                'username': provider.username,
            }
        return None

    def get_order_info(self, obj):
        """获取订单信息"""
        order = obj.related_order
        return {
            'id': order.id,
            'order_number': f"#{order.id}",
            'status': order.status,
            'status_display': order.get_status_display(),
        }

    def get_diary_info(self, obj):
        """获取关联日记信息"""
        if obj.related_diary:
            diary = obj.related_diary
            return {
                'id': diary.id,
                'title': diary.title,
                'diary_date': diary.diary_date,
            }
        return None

    def validate(self, data):
        """验证时间逻辑"""
        start_time = data.get('actual_start_time')
        end_time = data.get('actual_end_time')

        if start_time and end_time:
            if end_time <= start_time:
                raise serializers.ValidationError("结束时间必须晚于开始时间")

        # 验证评分范围
        rating = data.get('rating')
        if rating is not None and (rating < 1 or rating > 5):
            raise serializers.ValidationError("评分必须在1-5之间")

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

    def validate(self, data):
        """验证时间逻辑"""
        start_time = data.get('actual_start_time')
        end_time = data.get('actual_end_time')

        if start_time and end_time:
            if end_time <= start_time:
                raise serializers.ValidationError("结束时间必须晚于开始时间")

        return data


class PetServiceRecordUpdateSerializer(serializers.ModelSerializer):
    """宠物服务记录更新序列化器（用于客户反馈）"""

    class Meta:
        model = PetServiceRecord
        fields = ['customer_feedback', 'rating']

    def validate_rating(self, value):
        """验证评分"""
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("评分必须在1-5之间")
        return value