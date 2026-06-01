# -*- coding: utf-8 -*-
# @Time    : 2026/4/23 19:58
# @Author  : Delock

from rest_framework import serializers
from .models import HomepagePosition


class HomepagePositionItemSerializer(serializers.Serializer):
    """
    用户端返回结构（商品/服务混排统一格式）
    由 View 层组装，不直接绑定 Model
    """
    id = serializers.IntegerField()                     # 推荐位记录ID
    target_type = serializers.CharField()               # goods / service
    target_id = serializers.IntegerField()              # 商品/服务ID
    name = serializers.CharField()                      # 名称
    cover = serializers.CharField(allow_blank=True)     # 封面图
    price = serializers.CharField()                     # 价格(字符串,避免精度问题)
    sort_order = serializers.IntegerField()


class AdminHomepagePositionSerializer(serializers.ModelSerializer):
    """管理端 CRUD"""
    position_display = serializers.CharField(source='get_position_display', read_only=True)
    target_type_display = serializers.CharField(source='get_target_type_display', read_only=True)
    target_name = serializers.SerializerMethodField()
    target_cover = serializers.SerializerMethodField()
    target_price = serializers.SerializerMethodField()

    class Meta:
        model = HomepagePosition
        fields = [
            'id', 'position', 'position_display',
            'target_type', 'target_type_display', 'target_id',
            'target_name', 'target_cover', 'target_price',
            'sort_order', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def _get_target(self, obj):
        """懒加载目标对象(管理后台单条查询,N条数据性能可接受)"""
        if hasattr(obj, '_target_cache'):
            return obj._target_cache

        target = None
        if obj.target_type == HomepagePosition.TargetType.GOODS:
            from product.models import Goods
            target = Goods.objects.filter(id=obj.target_id).first()
        elif obj.target_type == HomepagePosition.TargetType.SERVICE:
            from services.models import Service  # ← 按实际 app 名改
            target = Service.objects.filter(id=obj.target_id).first()

        obj._target_cache = target
        return target

    def get_target_name(self, obj):
        """
        兼容两种字段名：
        - Service: name
        - Goods:   title
        """
        t = self._get_target(obj)
        if not t:
            return '[已删除]'
        return getattr(t, 'name', None) or getattr(t, 'title', None) or ''

    def get_target_cover(self, obj):
        """
        兼容两种字段名：
        - Service: cover_image
        - Goods:   main_image (或 cover_image,看你 product 模型实际字段)
        """
        t = self._get_target(obj)
        if not t:
            return ''
        return getattr(t, 'cover_image', None) or getattr(t, 'main_image', None) or ''

    def get_target_price(self, obj):
        t = self._get_target(obj)
        if not t:
            return ''
        price = getattr(t, 'price', None)
        return str(price) if price is not None else ''

    def validate(self, attrs):
        """创建/修改时校验目标对象是否存在"""
        target_type = attrs.get('target_type') or getattr(self.instance, 'target_type', None)
        target_id = attrs.get('target_id') or getattr(self.instance, 'target_id', None)

        if target_type == HomepagePosition.TargetType.GOODS:
            from product.models import Goods
            if not Goods.objects.filter(id=target_id).exists():
                raise serializers.ValidationError({'target_id': '商品不存在'})
        elif target_type == HomepagePosition.TargetType.SERVICE:
            from services.models import Service  # ← 按实际 app 名改
            if not Service.objects.filter(id=target_id).exists():
                raise serializers.ValidationError({'target_id': '服务不存在'})

        return attrs