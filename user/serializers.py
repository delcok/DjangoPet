# -*- coding: utf-8 -*-
# @Time    : 2025/7/7 19:53
# @Author  : Delock


from rest_framework import serializers
from django.utils import timezone

from user.models import User, UserAddress, SuperAdmin
from rest_framework import serializers
from django.utils import timezone
from .models import User


class UserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()
    vip_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'avatar', 'phone', 'gender',
            'birth_date', 'email', 'openid', 'unionid', 'is_vip', 'vip_level',
            'vip_expired_at', 'integral', 'gold', 'is_active', 'last_login',
            'created_at', 'updated_at', 'avatar_url', 'vip_status',
            'followers_count', 'following_count', 'posts_count', 'likes_received',
            'is_verified', 'verification_type', 'verified_at', 'level', 'exp',
            'is_public', 'allow_message', 'last_active_at', 'bio'
        ]
        read_only_fields = [
            'openid', 'unionid', 'created_at', 'updated_at', 'last_login',
            'followers_count', 'following_count', 'posts_count', 'likes_received',
            'is_verified', 'verification_type', 'verified_at', 'level', 'exp',
            'last_active_at', 'avatar_url', 'vip_status'
        ]

    def get_avatar_url(self, obj):
        # 如果avatar字段存储的是完整URL
        if obj.avatar and obj.avatar.startswith('http'):
            return obj.avatar
        # 如果avatar字段存储的是文件路径，需要加上CDN前缀
        elif obj.avatar:
            if obj.avatar.startswith('/'):
                return f"https://cdn.khjade.com{obj.avatar}"
            else:
                return f"https://cdn.khjade.com/{obj.avatar}"
        # 默认头像
        return "https://cdn.yimengzhiyuan.com/avatar/av1.jpg"

    def get_vip_status(self, obj):
        """获取VIP状态"""
        if not obj.is_vip:
            return '普通用户'

        if obj.vip_expired_at and obj.vip_expired_at < timezone.now():
            return 'VIP已过期'

        return f'VIP{obj.vip_level}级用户'


class UserAddressSerializer(serializers.ModelSerializer):
    """用户地址序列化器"""
    full_address = serializers.SerializerMethodField()

    class Meta:
        model = UserAddress
        fields = [
            'id', 'receiver_name', 'receiver_phone', 'province', 'city',
            'district', 'detail_address', 'is_default', 'tag',
            'created_at', 'updated_at', 'full_address'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_full_address(self, obj):
        """获取完整地址"""
        parts = []
        if obj.province:
            parts.append(obj.province)
        if obj.city:
            parts.append(obj.city)
        if obj.district:
            parts.append(obj.district)
        if obj.detail_address:
            parts.append(obj.detail_address)
        return ''.join(parts)

    def validate(self, attrs):
        """验证数据"""
        # 检查手机号格式
        receiver_phone = attrs.get('receiver_phone')
        if receiver_phone:
            phone_regex = r'^\+?1?\d{9,15}$'
            import re
            if not re.match(phone_regex, receiver_phone):
                raise serializers.ValidationError("收货人手机号格式不正确")

        # 检查收货人姓名
        receiver_name = attrs.get('receiver_name')
        if receiver_name and len(receiver_name.strip()) < 2:
            raise serializers.ValidationError("收货人姓名至少需要2个字符")

        return attrs

    def create(self, validated_data):
        """创建地址"""
        user = self.context['request'].user
        validated_data['user'] = user

        # 如果设置为默认地址，先取消其他默认地址
        if validated_data.get('is_default', False):
            UserAddress.objects.filter(user=user, is_default=True).update(is_default=False)

        return super().create(validated_data)

    def update(self, instance, validated_data):
        """更新地址"""
        # 如果设置为默认地址，先取消其他默认地址
        if validated_data.get('is_default', False):
            UserAddress.objects.filter(
                user=instance.user,
                is_default=True
            ).exclude(id=instance.id).update(is_default=False)

        return super().update(instance, validated_data)


class UserAddressCreateSerializer(serializers.ModelSerializer):
    """创建地址专用序列化器"""

    class Meta:
        model = UserAddress
        fields = [
            'receiver_name', 'receiver_phone', 'province', 'city',
            'district', 'detail_address', 'is_default', 'tag'
        ]

    def validate(self, attrs):
        """验证数据"""
        # 检查必填字段
        required_fields = ['receiver_name', 'receiver_phone', 'detail_address']
        for field in required_fields:
            if not attrs.get(field):
                field_name = {
                    'receiver_name': '收货人姓名',
                    'receiver_phone': '收货人手机号',
                    'detail_address': '详细地址'
                }.get(field, field)
                raise serializers.ValidationError(f"{field_name}不能为空")

        return super().validate(attrs)


class SetDefaultAddressSerializer(serializers.Serializer):
    """设置默认地址序列化器"""
    address_id = serializers.IntegerField(help_text="地址ID")

class SuperAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuperAdmin
        fields = [
            'id', 'username', 'phone', 'is_active', 'last_login',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'last_login']