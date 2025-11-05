# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Delock (Modified by ChatGPT)

from rest_framework import serializers
from .models import ServiceModel, PetType, AdditionalService


class PetTypeSerializer(serializers.ModelSerializer):
    """宠物类型序列化器"""
    services_count = serializers.SerializerMethodField()
    additional_services_count = serializers.SerializerMethodField()

    class Meta:
        model = PetType
        fields = [
            'id', 'name', 'base_price', 'description', 'is_active',
            'sort_order', 'services_count', 'additional_services_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_services_count(self, obj):
        return obj.get_services_count()

    def get_additional_services_count(self, obj):
        return obj.get_additional_services_count()


class PetTypeSimpleSerializer(serializers.ModelSerializer):
    """简化的宠物类型序列化器，用于关联显示"""
    class Meta:
        model = PetType
        fields = ['id', 'name', 'base_price']


# ===================== 基础服务序列化 ======================

class ServiceModelSerializer(serializers.ModelSerializer):
    """基础服务序列化器"""
    applicable_pets_detail = PetTypeSimpleSerializer(source='applicable_pets', many=True, read_only=True)
    applicable_pets_count = serializers.SerializerMethodField()
    applicable_pets_names = serializers.SerializerMethodField()
    applicable_pets_display = serializers.SerializerMethodField()

    class Meta:
        model = ServiceModel
        fields = [
            'id', 'name', 'base_price', 'icon', 'description', 'is_active',
            'sort_order', 'applicable_pets', 'applicable_pets_detail',
            'applicable_pets_count', 'applicable_pets_names',
            'applicable_pets_display', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_applicable_pets_count(self, obj):
        return obj.applicable_pets.count()

    def get_applicable_pets_names(self, obj):
        pets = obj.applicable_pets.all()
        return [pet.name for pet in pets] if pets.exists() else []

    def get_applicable_pets_display(self, obj):
        return obj.get_applicable_pets_display()


class ServiceModelSimpleSerializer(serializers.ModelSerializer):
    """简化的基础服务序列化器（含描述字段）"""
    applicable_pets_names = serializers.SerializerMethodField()
    applicable_pets_display = serializers.SerializerMethodField()

    class Meta:
        model = ServiceModel
        fields = [
            'id', 'name', 'base_price', 'icon', 'description',
            'applicable_pets_names', 'applicable_pets_display', 'is_active'
        ]

    def get_applicable_pets_names(self, obj):
        pets = obj.applicable_pets.all()
        return [pet.name for pet in pets] if pets.exists() else []

    def get_applicable_pets_display(self, obj):
        return obj.get_applicable_pets_display()


# ===================== 附加服务序列化 ======================

class AdditionalServiceSerializer(serializers.ModelSerializer):
    """附加服务序列化器"""
    applicable_pets_detail = PetTypeSimpleSerializer(source='applicable_pets', many=True, read_only=True)
    applicable_pets_count = serializers.SerializerMethodField()
    applicable_pets_names = serializers.SerializerMethodField()
    applicable_pets_display = serializers.SerializerMethodField()

    class Meta:
        model = AdditionalService
        fields = [
            'id', 'name', 'price', 'icon', 'description', 'is_active',
            'sort_order', 'applicable_pets', 'applicable_pets_detail',
            'applicable_pets_count', 'applicable_pets_names',
            'applicable_pets_display', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_applicable_pets_count(self, obj):
        return obj.applicable_pets.count()

    def get_applicable_pets_names(self, obj):
        pets = obj.applicable_pets.all()
        return [pet.name for pet in pets] if pets.exists() else []

    def get_applicable_pets_display(self, obj):
        return obj.get_applicable_pets_display()


class AdditionalServiceSimpleSerializer(serializers.ModelSerializer):
    """简化的附加服务序列化器（含描述字段）"""
    applicable_pets_names = serializers.SerializerMethodField()
    applicable_pets_display = serializers.SerializerMethodField()

    class Meta:
        model = AdditionalService
        fields = [
            'id', 'name', 'price', 'icon', 'description',
            'applicable_pets_names', 'applicable_pets_display', 'is_active'
        ]

    def get_applicable_pets_names(self, obj):
        pets = obj.applicable_pets.all()
        return [pet.name for pet in pets] if pets.exists() else []

    def get_applicable_pets_display(self, obj):
        return obj.get_applicable_pets_display()
