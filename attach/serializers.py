# -*- coding: utf-8 -*-
# @Time    : 2025/8/22 19:19
# @Author  : Delock

from rest_framework import serializers

from attach.models import Banner


class BannerSerializer(serializers.ModelSerializer):
    """轮播图序列化器"""
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Banner
        fields = [
            'id', 'type', 'type_display', 'url', 'link', 'title',
            'description', 'sort_order', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_sort_order(self, value):
        """验证排序字段"""
        if value < 0:
            raise serializers.ValidationError("排序值不能为负数")
        return value

    def validate_url(self, value):
        """验证图片链接"""
        if not value:
            raise serializers.ValidationError("图片链接不能为空")
        return value


class BannerListSerializer(serializers.ModelSerializer):
    """轮播图列表序列化器（简化版，用于列表展示）"""

    class Meta:
        model = Banner
        fields = ['id', 'type', 'url', 'link', 'title', 'sort_order']


class BannerCreateSerializer(serializers.ModelSerializer):
    """轮播图创建序列化器"""

    class Meta:
        model = Banner
        fields = ['type', 'url', 'link', 'title', 'description', 'sort_order']

    def validate(self, attrs):
        """自定义验证"""
        # 检查同类型轮播图数量限制（可选）
        banner_type = attrs.get('type', 'home')
        existing_count = Banner.objects.filter(type=banner_type, is_active=True).count()
        if existing_count >= 10:  # 限制每种类型最多10张轮播图
            raise serializers.ValidationError(f"{banner_type}类型轮播图数量已达上限（10张）")

        return attrs
