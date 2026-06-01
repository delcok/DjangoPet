# -*- coding: utf-8 -*-
# @Time    : 2026/4/16 17:07
# @Author  : Delock


import re
from rest_framework import serializers
from .models import UserAddress


class UserAddressSerializer(serializers.ModelSerializer):
    """
    用户地址序列化器（完整版）
    - 读取时返回所有字段 + 计算属性
    - 写入时根据 address_type 校验必填项
    """
    full_address = serializers.CharField(read_only=True)
    short_address = serializers.CharField(read_only=True)
    service_address = serializers.CharField(read_only=True)

    class Meta:
        model = UserAddress
        fields = [
            'id',
            # 收货人
            'receiver_name', 'receiver_phone',
            # 地址类型
            'address_type',
            # 省市区（当前可选，全国化后必填）
            'province', 'city', 'district',
            # 社区模式
            'community', 'building', 'unit', 'room',
            # 街道模式
            'street', 'house_number',
            # 兼容 & 展示
            'detail_address', 'full_address', 'short_address', 'service_address',
            # 坐标
            'longitude', 'latitude',
            # 其他
            'access_instructions', 'is_default', 'tag',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'detail_address',  # detail_address 由 model.save() 自动拼接
            'created_at', 'updated_at',
        ]

    def validate_receiver_phone(self, value):
        if not re.match(r'^1[3-9]\d{9}$', value):
            raise serializers.ValidationError('请输入正确的手机号')
        return value

    def validate(self, attrs):
        address_type = attrs.get(
            'address_type',
            self.instance.address_type if self.instance else UserAddress.AddressType.COMMUNITY
        )

        if address_type == UserAddress.AddressType.COMMUNITY:
            community = attrs.get('community', getattr(self.instance, 'community', ''))
            building = attrs.get('building', getattr(self.instance, 'building', ''))
            room = attrs.get('room', getattr(self.instance, 'room', ''))

            errors = {}
            if not community:
                errors['community'] = '请填写小区/社区名称'
            if not building:
                errors['building'] = '请填写楼栋'
            if not room:
                errors['room'] = '请填写门牌号'
            if errors:
                raise serializers.ValidationError(errors)

        elif address_type == UserAddress.AddressType.STREET:
            street = attrs.get('street', getattr(self.instance, 'street', ''))
            if not street:
                raise serializers.ValidationError({'street': '请填写街道地址'})

        return attrs

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        address = super().create(validated_data)

        # 设为默认时取消其他默认
        if address.is_default:
            UserAddress.objects.filter(
                user=address.user, is_default=True
            ).exclude(pk=address.pk).update(is_default=False)

        return address

    def update(self, instance, validated_data):
        address = super().update(instance, validated_data)

        if address.is_default:
            UserAddress.objects.filter(
                user=address.user, is_default=True
            ).exclude(pk=address.pk).update(is_default=False)

        return address


class UserAddressSimpleSerializer(serializers.ModelSerializer):
    """地址简要信息（列表 & 下单选择用）"""
    short_address = serializers.CharField(read_only=True)
    service_address = serializers.CharField(read_only=True)

    class Meta:
        model = UserAddress
        fields = [
            'id', 'receiver_name', 'receiver_phone',
            'address_type', 'short_address', 'service_address',
            'community', 'building', 'room',
            'street', 'house_number',
            'tag', 'is_default', 'longitude', 'latitude',
        ]


class UserAddressAdminSerializer(serializers.ModelSerializer):
    """管理后台 — 地址详情（只读，带用户信息）"""
    full_address = serializers.CharField(read_only=True)
    short_address = serializers.CharField(read_only=True)
    service_address = serializers.CharField(read_only=True)
    user_nickname = serializers.CharField(source='user.nickname', read_only=True, default='')
    user_phone = serializers.CharField(source='user.phone', read_only=True, default='')

    class Meta:
        model = UserAddress
        fields = [
            'id',
            # 用户信息
            'user', 'user_nickname', 'user_phone',
            # 收货人
            'receiver_name', 'receiver_phone',
            # 地址
            'address_type',
            'province', 'city', 'district',
            'community', 'building', 'unit', 'room',
            'street', 'house_number',
            'detail_address', 'full_address', 'short_address', 'service_address',
            # 坐标
            'longitude', 'latitude',
            # 其他
            'access_instructions', 'is_default', 'tag',
            'created_at', 'updated_at',
        ]