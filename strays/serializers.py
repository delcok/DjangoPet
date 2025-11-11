# -*- coding: utf-8 -*-
# @Time    : 2025/11/9 16:20
# @Author  : Delock

from rest_framework import serializers

from user.models import User
from strays.models import StrayAnimal, StrayAnimalInteraction


class UserSimpleSerializer(serializers.ModelSerializer):
    """用户简单信息序列化器"""

    class Meta:
        model = User
        fields = ['id', 'username', 'avatar']


class StrayAnimalListSerializer(serializers.ModelSerializer):
    """流浪动物列表序列化器"""
    reporter = UserSimpleSerializer(read_only=True)
    animal_type_display = serializers.CharField(source='get_animal_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    distance = serializers.SerializerMethodField()

    class Meta:
        model = StrayAnimal
        fields = [
            'id', 'animal_type', 'animal_type_display', 'nickname',
            'main_image_url', 'province', 'city', 'district',
            'status', 'status_display', 'health_status',
            'last_seen_date', 'view_count', 'interaction_count',
            'reporter', 'distance', 'created_at'
        ]

    def get_distance(self, obj):
        """计算距离（如果请求中包含经纬度）"""
        request = self.context.get('request')
        if request and hasattr(request, 'query_params'):
            try:
                user_lat = float(request.query_params.get('lat', 0))
                user_lng = float(request.query_params.get('lng', 0))
                if user_lat and user_lng and obj.latitude and obj.longitude:
                    # 简单的距离计算（米）
                    import math
                    R = 6371000  # 地球半径（米）
                    lat1_rad = math.radians(user_lat)
                    lat2_rad = math.radians(float(obj.latitude))
                    delta_lat = math.radians(float(obj.latitude) - user_lat)
                    delta_lng = math.radians(float(obj.longitude) - user_lng)

                    a = math.sin(delta_lat / 2) ** 2 + \
                        math.cos(lat1_rad) * math.cos(lat2_rad) * \
                        math.sin(delta_lng / 2) ** 2
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    distance = R * c

                    # 格式化距离显示
                    if distance < 1000:
                        return f"{int(distance)}m"
                    else:
                        return f"{distance / 1000:.1f}km"
            except (TypeError, ValueError):
                pass
        return None


class StrayAnimalDetailSerializer(serializers.ModelSerializer):
    """流浪动物详情序列化器"""
    reporter = UserSimpleSerializer(read_only=True)
    animal_type_display = serializers.CharField(source='get_animal_type_display', read_only=True)
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    size_display = serializers.CharField(source='get_size_display', read_only=True)
    health_status_display = serializers.CharField(source='get_health_status_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    recent_interactions = serializers.SerializerMethodField()

    class Meta:
        model = StrayAnimal
        fields = '__all__'
        read_only_fields = ['reporter', 'view_count', 'interaction_count', 'created_at', 'updated_at']

    def get_recent_interactions(self, obj):
        """获取最近的互动记录"""
        interactions = obj.interactions.all()[:10]
        return StrayAnimalInteractionSerializer(interactions, many=True).data


class StrayAnimalCreateSerializer(serializers.ModelSerializer):
    """创建流浪动物序列化器"""
    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        allow_empty=True
    )

    class Meta:
        model = StrayAnimal
        exclude = ['reporter', 'view_count', 'interaction_count']

    def validate_image_urls(self, value):
        """验证图片URL列表"""
        if len(value) > 9:
            raise serializers.ValidationError("最多只能上传9张图片")
        return value

    def create(self, validated_data):
        """创建流浪动物记录"""
        validated_data['reporter'] = self.context['request'].user
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
        exclude = ['reporter', 'view_count', 'interaction_count', 'created_at']
        read_only_fields = ['reporter']

    def validate_image_urls(self, value):
        """验证图片URL列表"""
        if len(value) > 9:
            raise serializers.ValidationError("最多只能上传9张图片")
        return value


class StrayAnimalInteractionSerializer(serializers.ModelSerializer):
    """互动记录序列化器"""
    user = UserSimpleSerializer(read_only=True)
    interaction_type_display = serializers.CharField(source='get_interaction_type_display', read_only=True)

    class Meta:
        model = StrayAnimalInteraction
        fields = '__all__'
        read_only_fields = ['user', 'created_at']


class StrayAnimalInteractionCreateSerializer(serializers.ModelSerializer):
    """创建互动记录序列化器"""

    class Meta:
        model = StrayAnimalInteraction
        fields = ['interaction_type', 'content', 'latitude', 'longitude', 'image_url']

    def validate(self, attrs):
        """验证互动数据"""
        interaction_type = attrs.get('interaction_type')

        # 评论必须有内容
        if interaction_type == 'comment' and not attrs.get('content'):
            raise serializers.ValidationError("评论必须包含内容")

        # 目击和投喂建议包含位置
        if interaction_type in ['sighting', 'feed'] and not attrs.get('latitude'):
            # 这里可以是警告而不是强制
            pass

        return attrs


class NearbyAnimalSerializer(serializers.ModelSerializer):
    """附近动物序列化器"""
    distance = serializers.FloatField()
    reporter = UserSimpleSerializer(read_only=True)
    animal_type_display = serializers.CharField(source='get_animal_type_display', read_only=True)

    class Meta:
        model = StrayAnimal
        fields = [
            'id', 'animal_type', 'animal_type_display', 'nickname',
            'main_image_url', 'latitude', 'longitude', 'detail_address',
            'distance', 'health_status', 'last_seen_date', 'reporter'
        ]


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