# -*- coding: utf-8 -*-
# @Time    : 2025/9/10 20:30
# @Author  : Delock

from rest_framework import serializers
from .models import ServiceModel, PetType, AdditionalService


class ServiceModelSerializer(serializers.ModelSerializer):
    """基础服务序列化器"""

    class Meta:
        model = ServiceModel
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class PetTypeSerializer(serializers.ModelSerializer):
    """宠物类型序列化器"""

    class Meta:
        model = PetType
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class PetTypeSimpleSerializer(serializers.ModelSerializer):
    """简化的宠物类型序列化器，用于关联显示"""

    class Meta:
        model = PetType
        fields = ('id', 'name', 'base_price')


class AdditionalServiceSerializer(serializers.ModelSerializer):
    """附加服务序列化器"""
    applicable_pets_detail = PetTypeSimpleSerializer(source='applicable_pets', many=True, read_only=True)
    applicable_pets_count = serializers.SerializerMethodField()
    applicable_pets_names = serializers.SerializerMethodField()

    class Meta:
        model = AdditionalService
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def get_applicable_pets_count(self, obj):
        """获取适用宠物类型数量"""
        return obj.applicable_pets.count()

    def get_applicable_pets_names(self, obj):
        """获取适用宠物类型名称列表"""
        return [pet.name for pet in obj.applicable_pets.all()]


class AdditionalServiceSimpleSerializer(serializers.ModelSerializer):
    """简化的附加服务序列化器"""
    applicable_pets_names = serializers.SerializerMethodField()

    class Meta:
        model = AdditionalService
        fields = ('id', 'name', 'price', 'applicable_pets_names', 'is_active', 'icon')

    def get_applicable_pets_names(self, obj):
        """获取适用宠物类型名称列表"""
        return [pet.name for pet in obj.applicable_pets.all()]