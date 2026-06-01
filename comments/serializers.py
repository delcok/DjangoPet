# -*- coding: utf-8 -*-
# @Time    : 2026/4/19 20:49
# @Author  : Delock

from django.utils import timezone
from rest_framework import serializers

from .models import (
    ProductReview, ProductReviewItem, ProductReviewImage,
    ServiceReview, ServiceReviewImage, ReviewStatusMixin
)


# =========================
# 通用
# =========================

class ReviewReplySerializer(serializers.Serializer):
    replied_content = serializers.CharField(max_length=1000)


class ReviewAuditSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ReviewStatusMixin.Status.choices)


# =========================
# 用户身份 helper
# 适配 user.User 模型:username / avatar / display_name / is_active / is_banned
# =========================

def _user_nickname(user, is_anonymous):
    """
    评价中展示的用户昵称。
    - 匿名:固定 '匿名用户'
    - 注销/封禁:'已注销用户'(避免展示已下线用户)
    - 否则:用 User.display_name(空 username 自动兜底 '用户XXXX')
    """
    if is_anonymous or not user:
        return '匿名用户'

    # 注销 / 封禁用户脱敏
    if not getattr(user, 'is_active', True) or getattr(user, 'is_banned', False):
        return '已注销用户'

    # User 模型上的 display_name property 已经处理好了 username 为空的情况
    name = getattr(user, 'display_name', None)
    if name:
        return name

    # 极端兜底
    return (
        getattr(user, 'username', '')
        or f'用户{str(getattr(user, "id", "0000"))[-4:].rjust(4, "0")}'
    )


def _user_avatar(user, is_anonymous):
    """
    评价中展示的头像 URL。
    - 匿名 / 注销 / 封禁:返回空(前端走默认头像)
    """
    if is_anonymous or not user:
        return ''
    if not getattr(user, 'is_active', True) or getattr(user, 'is_banned', False):
        return ''
    return getattr(user, 'avatar', '') or ''


# =========================
# 商品评价图片
# =========================

class ProductReviewImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductReviewImage
        fields = ['id', 'image', 'sort_order', 'created_at']
        read_only_fields = ['id', 'created_at']


# =========================
# 商品评价明细
# =========================

class ProductReviewItemSerializer(serializers.ModelSerializer):
    images = ProductReviewImageSerializer(many=True, read_only=True)

    class Meta:
        model = ProductReviewItem
        fields = [
            'id',
            'order_item',
            'goods',
            'sku',
            'goods_id_snapshot',
            'sku_id_snapshot',
            'goods_title',
            'goods_image',
            'sku_text',
            'score',
            'quality_score',
            'match_score',
            'content',
            'has_images',
            'like_count',
            'images',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'has_images', 'like_count', 'created_at', 'updated_at'
        ]


class ProductReviewItemCreateSerializer(serializers.Serializer):
    order_item = serializers.IntegerField()
    goods = serializers.IntegerField(required=False, allow_null=True)
    sku = serializers.IntegerField(required=False, allow_null=True)
    goods_id_snapshot = serializers.IntegerField(required=False, allow_null=True)
    sku_id_snapshot = serializers.IntegerField(required=False, allow_null=True)
    goods_title = serializers.CharField(max_length=200)
    goods_image = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    sku_text = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    score = serializers.IntegerField(min_value=1, max_value=5, default=5)
    quality_score = serializers.IntegerField(min_value=1, max_value=5, default=5)
    match_score = serializers.IntegerField(min_value=1, max_value=5, default=5)
    content = serializers.CharField(required=False, allow_blank=True, default='')
    images = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        default=list
    )


# =========================
# 商品评价
# =========================

class ProductReviewListSerializer(serializers.ModelSerializer):
    avg_item_score = serializers.FloatField(read_only=True)
    images = ProductReviewImageSerializer(many=True, read_only=True)
    items = ProductReviewItemSerializer(many=True, read_only=True)

    # ★ 用户昵称 / 头像(匿名 / 注销 / 封禁时自动隐藏)
    user_nickname = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()

    class Meta:
        model = ProductReview
        fields = [
            'id', 'order',
            'user', 'user_nickname', 'user_avatar',
            'merchant_id', 'merchant_name',
            'logistics_score', 'service_score', 'content',
            'is_anonymous', 'has_images', 'status',
            'replied_content', 'replied_at',
            'created_at', 'updated_at', 'avg_item_score',
            'images', 'items',
        ]

    def get_user_nickname(self, obj):
        return _user_nickname(obj.user, obj.is_anonymous)

    def get_user_avatar(self, obj):
        return _user_avatar(obj.user, obj.is_anonymous)


class ProductReviewDetailSerializer(serializers.ModelSerializer):
    images = ProductReviewImageSerializer(many=True, read_only=True)
    items = ProductReviewItemSerializer(many=True, read_only=True)
    avg_item_score = serializers.FloatField(read_only=True)

    # ★ 用户昵称 / 头像
    user_nickname = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()

    class Meta:
        model = ProductReview
        fields = [
            'id', 'order',
            'user', 'user_nickname', 'user_avatar',
            'merchant_id', 'merchant_name',
            'logistics_score', 'service_score', 'content',
            'is_anonymous', 'has_images', 'status',
            'replied_content', 'replied_at',
            'images', 'items',
            'created_at', 'updated_at', 'avg_item_score',
        ]

    def get_user_nickname(self, obj):
        return _user_nickname(obj.user, obj.is_anonymous)

    def get_user_avatar(self, obj):
        return _user_avatar(obj.user, obj.is_anonymous)


class ProductReviewCreateSerializer(serializers.ModelSerializer):
    images = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        default=list,
        write_only=True
    )
    items = ProductReviewItemCreateSerializer(many=True, required=False, default=list, write_only=True)

    class Meta:
        model = ProductReview
        fields = [
            'id',
            'order',
            'merchant_id',
            'merchant_name',
            'logistics_score',
            'service_score',
            'content',
            'is_anonymous',
            'images',
            'items',
        ]
        read_only_fields = ['id']

    def validate_order(self, value):
        request = self.context['request']
        if getattr(value, 'user_id', None) != request.user.id:
            raise serializers.ValidationError('只能评价自己的商品订单')
        return value

    def create(self, validated_data):
        images = validated_data.pop('images', [])
        items_data = validated_data.pop('items', [])

        review = ProductReview.objects.create(**validated_data)

        for idx, image in enumerate(images):
            ProductReviewImage.objects.create(
                review=review,
                image=image,
                sort_order=idx
            )

        for item_data in items_data:
            item_images = item_data.pop('images', [])
            review_item = ProductReviewItem.objects.create(
                review=review,
                order_item_id=item_data.pop('order_item'),
                goods_id=item_data.pop('goods', None),
                sku_id=item_data.pop('sku', None),
                **item_data
            )
            for idx, image in enumerate(item_images):
                ProductReviewImage.objects.create(
                    review_item=review_item,
                    image=image,
                    sort_order=idx
                )
            review_item.sync_has_images()

        review.sync_has_images()

        # ★ 回写订单"已评价"状态
        order = review.order
        if not order.is_reviewed:
            order.is_reviewed = True
            order.reviewed_at = timezone.now()
            order.save(update_fields=['is_reviewed', 'reviewed_at', 'updated_at'])

        return review

    def update(self, instance, validated_data):
        validated_data.pop('images', None)
        validated_data.pop('items', None)
        return super().update(instance, validated_data)


# =========================
# 服务评价图片
# =========================

class ServiceReviewImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceReviewImage
        fields = ['id', 'image', 'sort_order', 'created_at']
        read_only_fields = ['id', 'created_at']


# =========================
# 服务评价
# =========================

class ServiceReviewListSerializer(serializers.ModelSerializer):
    images = ServiceReviewImageSerializer(many=True, read_only=True)

    # ★ 用户昵称 / 头像
    user_nickname = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()

    class Meta:
        model = ServiceReview
        fields = [
            'id', 'order', 'order_item',
            'user', 'user_nickname', 'user_avatar',
            'merchant_id', 'merchant_name',
            'service', 'service_id_snapshot', 'service_name',
            'service_image', 'spec_name',
            'score', 'attitude_score', 'professional_score', 'punctuality_score',
            'content', 'is_anonymous', 'has_images',
            'staff_id', 'staff_name',
            'service_start_at', 'service_end_at',
            'status', 'replied_content', 'replied_at',
            'created_at', 'updated_at',
            'images',
        ]

    def get_user_nickname(self, obj):
        return _user_nickname(obj.user, obj.is_anonymous)

    def get_user_avatar(self, obj):
        return _user_avatar(obj.user, obj.is_anonymous)


class ServiceReviewDetailSerializer(serializers.ModelSerializer):
    images = ServiceReviewImageSerializer(many=True, read_only=True)

    # ★ 用户昵称 / 头像
    user_nickname = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()

    class Meta:
        model = ServiceReview
        fields = [
            'id', 'order', 'order_item',
            'user', 'user_nickname', 'user_avatar',
            'merchant_id', 'merchant_name',
            'service', 'service_id_snapshot', 'service_name',
            'service_image', 'spec_name',
            'score', 'attitude_score', 'professional_score', 'punctuality_score',
            'content', 'is_anonymous', 'has_images',
            'staff_id', 'staff_name',
            'service_start_at', 'service_end_at',
            'status', 'replied_content', 'replied_at',
            'images',
            'created_at', 'updated_at',
        ]

    def get_user_nickname(self, obj):
        return _user_nickname(obj.user, obj.is_anonymous)

    def get_user_avatar(self, obj):
        return _user_avatar(obj.user, obj.is_anonymous)


class ServiceReviewCreateSerializer(serializers.ModelSerializer):
    images = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        default=list,
        write_only=True
    )

    class Meta:
        model = ServiceReview
        fields = [
            'id',
            'order',
            'order_item',
            'merchant_id',
            'merchant_name',
            'service',
            'service_id_snapshot',
            'service_name',
            'service_image',
            'spec_name',
            'score',
            'attitude_score',
            'professional_score',
            'punctuality_score',
            'content',
            'is_anonymous',
            'staff_id',
            'staff_name',
            'service_start_at',
            'service_end_at',
            'images',
        ]
        read_only_fields = ['id']

    def validate_order(self, value):
        request = self.context['request']
        if getattr(value, 'user_id', None) != request.user.id:
            raise serializers.ValidationError('只能评价自己的服务订单')
        return value

    def create(self, validated_data):
        images = validated_data.pop('images', [])

        review = ServiceReview.objects.create(**validated_data)

        for idx, image in enumerate(images):
            ServiceReviewImage.objects.create(
                review=review,
                image=image,
                sort_order=idx
            )

        review.sync_has_images()

        # ★ 回写订单"已评价"状态
        order = review.order
        if not order.is_reviewed:
            order.is_reviewed = True
            order.reviewed_at = timezone.now()
            order.save(update_fields=['is_reviewed', 'reviewed_at', 'updated_at'])

        return review