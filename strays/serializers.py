# -*- coding: utf-8 -*-
# @Time    : 2025/11/9 16:20
# @Author  : Delock

from rest_framework import serializers

from user.models import User
from strays.models import (
    StrayAnimal,
    StrayAnimalInteraction,
    StrayAnimalFavorite,
    StrayAnimalReport
)


# ============================================================
# 工具函数
# ============================================================

def is_normal_user(user):
    """
    判断当前认证主体是否为普通用户。

    说明：
    你的项目现在有多种认证主体：
    - User
    - Manager
    - Merchant
    - MerchantSubAccount
    - Staff

    所以不能再简单依赖 request.user.is_authenticated，
    否则 Manager / Staff 等对象可能没有这个属性，或者语义不准确。
    """
    return (
        isinstance(user, User)
        and getattr(user, 'is_active', False)
        and not getattr(user, 'is_banned', False)
    )


# ============================================================
# 用户基础信息
# ============================================================

class UserSimpleSerializer(serializers.ModelSerializer):
    """用户简单信息序列化器"""

    class Meta:
        model = User
        fields = ['id', 'username', 'avatar']


# ============================================================
# 流浪动物相关
# ============================================================

class StrayAnimalListSerializer(serializers.ModelSerializer):
    """流浪动物列表序列化器"""

    reporter = UserSimpleSerializer(read_only=True)
    animal_type_display = serializers.CharField(
        source='get_animal_type_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    distance = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = StrayAnimal
        fields = [
            'id',
            'animal_type',
            'animal_type_display',
            'nickname',
            'main_image_url',
            'province',
            'city',
            'district',
            'status',
            'status_display',
            'health_status',
            'last_seen_date',
            'view_count',
            'interaction_count',
            'favorite_count',
            'reporter',
            'distance',
            'is_favorited',
            'created_at',
        ]

    def get_distance(self, obj):
        """计算距离，如果请求中包含经纬度"""

        request = self.context.get('request')

        if request and hasattr(request, 'query_params'):
            try:
                user_lat = float(request.query_params.get('lat', 0))
                user_lng = float(request.query_params.get('lng', 0))

                if user_lat and user_lng and obj.latitude and obj.longitude:
                    import math

                    earth_radius = 6371000

                    lat1_rad = math.radians(user_lat)
                    lat2_rad = math.radians(float(obj.latitude))
                    delta_lat = math.radians(float(obj.latitude) - user_lat)
                    delta_lng = math.radians(float(obj.longitude) - user_lng)

                    a = (
                        math.sin(delta_lat / 2) ** 2
                        + math.cos(lat1_rad)
                        * math.cos(lat2_rad)
                        * math.sin(delta_lng / 2) ** 2
                    )

                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    distance = earth_radius * c

                    if distance < 1000:
                        return f"{int(distance)}m"

                    return f"{distance / 1000:.1f}km"

            except (TypeError, ValueError):
                pass

        return None

    def get_is_favorited(self, obj):
        """判断当前普通用户是否已收藏"""

        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if request and is_normal_user(user):
            return StrayAnimalFavorite.objects.filter(
                user=user,
                animal=obj
            ).exists()

        return False


class StrayAnimalDetailSerializer(serializers.ModelSerializer):
    """流浪动物详情序列化器"""

    reporter = UserSimpleSerializer(read_only=True)
    animal_type_display = serializers.CharField(
        source='get_animal_type_display',
        read_only=True
    )
    gender_display = serializers.CharField(
        source='get_gender_display',
        read_only=True
    )
    size_display = serializers.CharField(
        source='get_size_display',
        read_only=True
    )
    health_status_display = serializers.CharField(
        source='get_health_status_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    recent_interactions = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = StrayAnimal
        fields = '__all__'
        read_only_fields = [
            'reporter',
            'view_count',
            'interaction_count',
            'favorite_count',
            'created_at',
            'updated_at',
        ]

    def get_recent_interactions(self, obj):
        """获取最近的互动记录"""

        interactions = obj.interactions.select_related('user').all()[:10]

        return StrayAnimalInteractionSerializer(
            interactions,
            many=True,
            context=self.context
        ).data

    def get_is_favorited(self, obj):
        """判断当前普通用户是否已收藏"""

        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if request and is_normal_user(user):
            return StrayAnimalFavorite.objects.filter(
                user=user,
                animal=obj
            ).exists()

        return False


class StrayAnimalCreateSerializer(serializers.ModelSerializer):
    """创建流浪动物序列化器"""

    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        allow_empty=True
    )

    class Meta:
        model = StrayAnimal
        exclude = [
            'reporter',
            'view_count',
            'interaction_count',
            'favorite_count',
        ]
        read_only_fields = [
            'created_at',
            'updated_at',
        ]

    def validate_image_urls(self, value):
        """验证图片 URL 列表"""

        if len(value) > 9:
            raise serializers.ValidationError("最多只能上传9张图片")

        return value

    def create(self, validated_data):
        """创建流浪动物记录"""

        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if not is_normal_user(user):
            raise serializers.ValidationError("请使用普通用户账号发布流浪动物记录")

        validated_data['reporter'] = user

        return super().create(validated_data)


class StrayAnimalUpdateSerializer(serializers.ModelSerializer):
    """更新流浪动物序列化器"""

    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        allow_empty=True
    )

    class Meta:
        model = StrayAnimal
        exclude = [
            'reporter',
            'view_count',
            'interaction_count',
            'favorite_count',
            'created_at',
        ]
        read_only_fields = [
            'reporter',
            'updated_at',
        ]

    def validate_image_urls(self, value):
        """验证图片 URL 列表"""

        if len(value) > 9:
            raise serializers.ValidationError("最多只能上传9张图片")

        return value


# ============================================================
# 互动记录相关
# ============================================================

class StrayAnimalInteractionSerializer(serializers.ModelSerializer):
    """互动记录序列化器"""

    user = UserSimpleSerializer(read_only=True)
    interaction_type_display = serializers.CharField(
        source='get_interaction_type_display',
        read_only=True
    )

    class Meta:
        model = StrayAnimalInteraction
        fields = '__all__'
        read_only_fields = [
            'user',
            'created_at',
        ]


class StrayAnimalInteractionCreateSerializer(serializers.ModelSerializer):
    """创建互动记录序列化器"""

    class Meta:
        model = StrayAnimalInteraction
        fields = [
            'interaction_type',
            'content',
            'latitude',
            'longitude',
            'image_url',
        ]

    def validate(self, attrs):
        """验证互动数据"""

        interaction_type = attrs.get('interaction_type')

        if interaction_type == 'comment' and not attrs.get('content'):
            raise serializers.ValidationError("评论必须包含内容")

        return attrs


# ============================================================
# 附近流浪动物
# ============================================================

class NearbyAnimalSerializer(serializers.ModelSerializer):
    """附近动物序列化器"""

    distance = serializers.FloatField()
    reporter = UserSimpleSerializer(read_only=True)
    animal_type_display = serializers.CharField(
        source='get_animal_type_display',
        read_only=True
    )
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = StrayAnimal
        fields = [
            'id',
            'animal_type',
            'animal_type_display',
            'nickname',
            'main_image_url',
            'latitude',
            'longitude',
            'detail_address',
            'distance',
            'health_status',
            'last_seen_date',
            'reporter',
            'is_favorited',
            'favorite_count',
        ]

    def get_is_favorited(self, obj):
        """判断当前普通用户是否已收藏"""

        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if request and is_normal_user(user):
            return StrayAnimalFavorite.objects.filter(
                user=user,
                animal=obj
            ).exists()

        return False


# ============================================================
# 统计信息
# ============================================================

class StatisticsSerializer(serializers.Serializer):
    """统计信息序列化器"""

    total_animals = serializers.IntegerField()
    active_animals = serializers.IntegerField()
    rescued_animals = serializers.IntegerField()
    adopted_animals = serializers.IntegerField()
    total_interactions = serializers.IntegerField()
    recent_week_reports = serializers.IntegerField()
    by_type = serializers.DictField()
    by_district = serializers.DictField()


# ============================================================
# 收藏相关
# ============================================================

class StrayAnimalFavoriteSerializer(serializers.ModelSerializer):
    """收藏记录序列化器"""

    user = UserSimpleSerializer(read_only=True)
    animal = StrayAnimalListSerializer(read_only=True)

    class Meta:
        model = StrayAnimalFavorite
        fields = '__all__'
        read_only_fields = [
            'user',
            'created_at',
        ]


class FavoriteAnimalSimpleSerializer(serializers.ModelSerializer):
    """收藏列表中的动物简化序列化器"""

    animal_type_display = serializers.CharField(
        source='get_animal_type_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    class Meta:
        model = StrayAnimal
        fields = [
            'id',
            'animal_type',
            'animal_type_display',
            'nickname',
            'main_image_url',
            'city',
            'district',
            'status',
            'status_display',
            'health_status',
            'last_seen_date',
            'favorite_count',
        ]


# ============================================================
# 举报相关
# ============================================================

class StrayAnimalReportCreateSerializer(serializers.ModelSerializer):
    """创建举报记录序列化器"""

    class Meta:
        model = StrayAnimalReport
        fields = [
            'animal',
            'interaction',
            'report_type',
            'reason',
        ]

    def validate(self, attrs):
        """验证举报数据"""

        animal = attrs.get('animal')
        interaction = attrs.get('interaction')

        if not animal and not interaction:
            raise serializers.ValidationError("必须指定举报目标：动物或互动")

        if animal and interaction:
            raise serializers.ValidationError("只能举报一个目标，不能同时举报动物和互动")

        if interaction and not interaction.animal:
            raise serializers.ValidationError("互动记录数据异常")

        return attrs

    def create(self, validated_data):
        """创建举报记录"""

        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if not is_normal_user(user):
            raise serializers.ValidationError("请使用普通用户账号提交举报")

        validated_data['reporter'] = user

        return super().create(validated_data)


class StrayAnimalReportSerializer(serializers.ModelSerializer):
    """举报记录序列化器"""

    reporter = UserSimpleSerializer(read_only=True)
    handler_info = serializers.SerializerMethodField()

    report_type_display = serializers.CharField(
        source='get_report_type_display',
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )

    animal_info = serializers.SerializerMethodField()
    interaction_info = serializers.SerializerMethodField()

    class Meta:
        model = StrayAnimalReport
        fields = '__all__'
        read_only_fields = [
            'reporter',
            'handler',
            'handled_at',
            'created_at',
        ]

    def get_handler_info(self, obj):
        """
        获取处理人信息。

        兼容两种情况：
        1. handler 是 Manager 管理员模型；
        2. handler 仍然是 User 模型。

        如果你已经把 StrayAnimalReport.handler 改成 Manager 外键，
        这里会正常返回管理员信息。
        """

        handler = getattr(obj, 'handler', None)

        if not handler:
            return None

        role = getattr(handler, 'role', None)

        return {
            'id': getattr(handler, 'id', None),
            'username': getattr(handler, 'username', None),
            'name': getattr(handler, 'name', None),
            'role': getattr(role, 'code', None) if role else None,
            'is_superuser': getattr(handler, 'is_superuser', False),
        }

    def get_animal_info(self, obj):
        """获取被举报动物的简要信息"""

        if obj.animal:
            return {
                'id': obj.animal.id,
                'nickname': obj.animal.nickname or '未命名',
                'animal_type': obj.animal.get_animal_type_display(),
                'status': obj.animal.status,
                'status_display': obj.animal.get_status_display(),
                'main_image_url': obj.animal.main_image_url,
            }

        return None

    def get_interaction_info(self, obj):
        """获取被举报互动的简要信息"""

        if obj.interaction:
            return {
                'id': obj.interaction.id,
                'type': obj.interaction.interaction_type,
                'type_display': obj.interaction.get_interaction_type_display(),
                'content': obj.interaction.content[:50] if obj.interaction.content else None,
                'user_id': obj.interaction.user_id,
                'animal_id': obj.interaction.animal_id,
                'created_at': obj.interaction.created_at,
            }

        return None