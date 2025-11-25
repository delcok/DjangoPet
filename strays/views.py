from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
import math

from utils.authentication import UserAuthentication
from utils.permission import AnyUser
from .models import (
    StrayAnimal,
    StrayAnimalInteraction,
    StrayAnimalFavorite,
    StrayAnimalReport
)
from .serializers import (
    StrayAnimalListSerializer,
    StrayAnimalDetailSerializer,
    StrayAnimalCreateSerializer,
    StrayAnimalUpdateSerializer,
    StrayAnimalInteractionSerializer,
    StrayAnimalInteractionCreateSerializer,
    NearbyAnimalSerializer,
    StatisticsSerializer,
    StrayAnimalFavoriteSerializer,
    FavoriteAnimalSimpleSerializer,
    StrayAnimalReportCreateSerializer,
    StrayAnimalReportSerializer,
)


class StrayAnimalViewSet(viewsets.ModelViewSet):
    """流浪动物视图集"""
    queryset = StrayAnimal.objects.filter(is_active=True)
    authentication_classes = [UserAuthentication]
    permission_classes = [AnyUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nickname', 'breed', 'distinctive_features', 'detail_address']
    ordering_fields = ['created_at', 'last_seen_date', 'view_count', 'interaction_count', 'favorite_count']
    ordering = ['-last_seen_date']

    def get_serializer_class(self):
        """根据操作返回对应的序列化器"""
        if self.action == 'list':
            return StrayAnimalListSerializer
        elif self.action == 'create':
            return StrayAnimalCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return StrayAnimalUpdateSerializer
        elif self.action == 'nearby':
            return NearbyAnimalSerializer
        return StrayAnimalDetailSerializer

    def get_queryset(self):
        """获取查询集，支持过滤"""
        queryset = super().get_queryset()
        params = self.request.query_params

        # 按动物类型过滤
        animal_type = params.get('animal_type')
        if animal_type:
            queryset = queryset.filter(animal_type=animal_type)

        # 按状态过滤
        status_filter = params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # 按健康状态过滤
        health_status = params.get('health_status')
        if health_status:
            queryset = queryset.filter(health_status=health_status)

        # 按地区过滤
        province = params.get('province')
        city = params.get('city')
        district = params.get('district')

        if province:
            queryset = queryset.filter(province=province)
        if city:
            queryset = queryset.filter(city=city)
        if district:
            queryset = queryset.filter(district=district)

        # 按时间范围过滤
        days = params.get('days')
        if days:
            try:
                days = int(days)
                date_from = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(last_seen_date__gte=date_from.date())
            except ValueError:
                pass

        # 只看我发布的
        my_only = params.get('my_only')
        if my_only and self.request.user.is_authenticated:
            queryset = queryset.filter(reporter=self.request.user)

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """获取详情时增加浏览次数"""
        instance = self.get_object()
        instance.increase_view_count()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """创建时设置报告人"""
        serializer.save(reporter=self.request.user)

    def perform_update(self, serializer):
        """更新时记录最后见到日期"""
        if 'last_seen_date' not in serializer.validated_data:
            serializer.validated_data['last_seen_date'] = timezone.now().date()
        serializer.save()

    @action(detail=False, methods=['get'])
    def nearby(self, request):
        """获取附近的流浪动物"""
        try:
            lat = float(request.query_params.get('lat'))
            lng = float(request.query_params.get('lng'))
            radius = float(request.query_params.get('radius', 5000))  # 默认5公里
        except (TypeError, ValueError):
            return Response(
                {'error': '请提供有效的经纬度参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 计算经纬度范围（粗略过滤）
        lat_range = radius / 111000  # 1纬度约111公里
        lng_range = radius / (111000 * math.cos(math.radians(lat)))

        # 查询在范围内的动物
        queryset = self.get_queryset().filter(
            latitude__range=(lat - lat_range, lat + lat_range),
            longitude__range=(lng - lng_range, lng + lng_range)
        )

        # 计算精确距离并排序
        animals_with_distance = []
        for animal in queryset:
            if animal.latitude and animal.longitude:
                # 使用 Haversine 公式计算距离
                R = 6371000  # 地球半径（米）
                lat1_rad = math.radians(lat)
                lat2_rad = math.radians(float(animal.latitude))
                delta_lat = math.radians(float(animal.latitude) - lat)
                delta_lng = math.radians(float(animal.longitude) - lng)

                a = math.sin(delta_lat / 2) ** 2 + \
                    math.cos(lat1_rad) * math.cos(lat2_rad) * \
                    math.sin(delta_lng / 2) ** 2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                distance = R * c

                if distance <= radius:
                    animal.distance = distance
                    animals_with_distance.append(animal)

        # 按距离排序
        animals_with_distance.sort(key=lambda x: x.distance)

        # 分页
        page = self.paginate_queryset(animals_with_distance)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(animals_with_distance, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[AnyUser])
    def interact(self, request, pk=None):
        """添加互动记录"""
        animal = self.get_object()
        serializer = StrayAnimalInteractionCreateSerializer(data=request.data)

        if serializer.is_valid():
            # 创建互动记录
            interaction = StrayAnimalInteraction.objects.create(
                animal=animal,
                user=request.user,
                **serializer.validated_data
            )

            # 如果是目击，更新最后见到日期
            if interaction.interaction_type == 'sighting':
                animal.last_seen_date = timezone.now().date()
                if interaction.latitude and interaction.longitude:
                    # 可以选择更新动物位置
                    animal.latitude = interaction.latitude
                    animal.longitude = interaction.longitude
                animal.save()

            return Response(
                StrayAnimalInteractionSerializer(interaction).data,
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def interactions(self, request, pk=None):
        """获取动物的互动记录"""
        animal = self.get_object()
        interactions = animal.interactions.all()

        # 支持按类型过滤
        interaction_type = request.query_params.get('type')
        if interaction_type:
            interactions = interactions.filter(interaction_type=interaction_type)

        # 分页
        page = self.paginate_queryset(interactions)
        if page is not None:
            serializer = StrayAnimalInteractionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StrayAnimalInteractionSerializer(interactions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取统计信息"""
        queryset = self.get_queryset()

        # 支持地区过滤
        province = request.query_params.get('province')
        city = request.query_params.get('city')
        district = request.query_params.get('district')

        if province:
            queryset = queryset.filter(province=province)
        if city:
            queryset = queryset.filter(city=city)
        if district:
            queryset = queryset.filter(district=district)

        # 基础统计
        total_animals = queryset.count()
        active_animals = queryset.filter(status='active').count()
        rescued_animals = queryset.filter(status='rescued').count()
        adopted_animals = queryset.filter(status='adopted').count()

        # 互动统计
        total_interactions = StrayAnimalInteraction.objects.filter(
            animal__in=queryset
        ).count()

        # 最近一周新增
        week_ago = timezone.now() - timedelta(days=7)
        recent_week_reports = queryset.filter(created_at__gte=week_ago).count()

        # 按类型统计
        by_type = dict(queryset.values_list('animal_type').annotate(count=Count('id')))

        # 按地区统计（如果没有指定地区）
        by_district = {}
        if not district:
            district_stats = queryset.values('district').annotate(count=Count('id')).order_by('-count')[:10]
            by_district = {item['district'] or '未知': item['count'] for item in district_stats}

        data = {
            'total_animals': total_animals,
            'active_animals': active_animals,
            'rescued_animals': rescued_animals,
            'adopted_animals': adopted_animals,
            'total_interactions': total_interactions,
            'recent_week_reports': recent_week_reports,
            'by_type': by_type,
            'by_district': by_district
        }

        serializer = StatisticsSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def hot(self, request):
        """获取热门流浪动物（互动最多的）"""
        days = int(request.query_params.get('days', 7))
        limit = int(request.query_params.get('limit', 10))

        # 获取指定天数内互动最多的动物
        date_from = timezone.now() - timedelta(days=days)

        queryset = self.get_queryset().filter(
            interactions__created_at__gte=date_from
        ).annotate(
            recent_interaction_count=Count('interactions')
        ).order_by('-recent_interaction_count')[:limit]

        serializer = StrayAnimalListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[AnyUser])
    def report_update(self, request, pk=None):
        """报告动物状态更新（如已被领养、已去世等）"""
        animal = self.get_object()
        new_status = request.data.get('status')
        notes = request.data.get('notes', '')

        if new_status not in dict(StrayAnimal.STATUS_CHOICES):
            return Response(
                {'error': '无效的状态'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 更新状态
        animal.status = new_status
        if notes:
            animal.additional_notes = f"{animal.additional_notes}\n{timezone.now()}: {notes}" if animal.additional_notes else f"{timezone.now()}: {notes}"
        animal.save()

        # 创建一条互动记录
        StrayAnimalInteraction.objects.create(
            animal=animal,
            user=request.user,
            interaction_type='comment',
            content=f"报告状态更新为: {animal.get_status_display()}. {notes}"
        )

        return Response({'message': '状态已更新'})

    # ========== 收藏功能 ==========

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def favorite(self, request, pk=None):
        """收藏动物"""
        animal = self.get_object()

        # 检查是否已收藏
        favorite, created = StrayAnimalFavorite.objects.get_or_create(
            user=request.user,
            animal=animal
        )

        if created:
            return Response(
                {'message': '收藏成功', 'is_favorited': True},
                status=status.HTTP_201_CREATED
            )
        else:
            return Response(
                {'message': '已经收藏过了', 'is_favorited': True},
                status=status.HTTP_200_OK
            )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def unfavorite(self, request, pk=None):
        """取消收藏动物"""
        animal = self.get_object()

        deleted_count = StrayAnimalFavorite.objects.filter(
            user=request.user,
            animal=animal
        ).delete()[0]

        if deleted_count > 0:
            return Response(
                {'message': '取消收藏成功', 'is_favorited': False},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {'message': '未收藏该动物', 'is_favorited': False},
                status=status.HTTP_200_OK
            )

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_favorites(self, request):
        """获取我的收藏列表"""
        favorites = StrayAnimalFavorite.objects.filter(
            user=request.user
        ).select_related('animal')

        # 提取动物列表
        animals = [f.animal for f in favorites if f.animal.is_active]

        # 分页
        page = self.paginate_queryset(animals)
        if page is not None:
            serializer = StrayAnimalListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = StrayAnimalListSerializer(animals, many=True, context={'request': request})
        return Response(serializer.data)


class StrayAnimalInteractionViewSet(viewsets.ReadOnlyModelViewSet):
    """互动记录视图集（只读）"""
    queryset = StrayAnimalInteraction.objects.all()
    serializer_class = StrayAnimalInteractionSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [AnyUser]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_queryset(self):
        """支持按用户和动物过滤"""
        queryset = super().get_queryset()

        # 按用户过滤
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # 按动物过滤
        animal_id = self.request.query_params.get('animal_id')
        if animal_id:
            queryset = queryset.filter(animal_id=animal_id)

        # 按互动类型过滤
        interaction_type = self.request.query_params.get('type')
        if interaction_type:
            queryset = queryset.filter(interaction_type=interaction_type)

        return queryset

    @action(detail=False, methods=['get'])
    def my_interactions(self, request):
        """获取当前用户的所有互动记录"""
        if not request.user.is_authenticated:
            return Response(
                {'error': '请先登录'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        interactions = self.get_queryset().filter(user=request.user)

        page = self.paginate_queryset(interactions)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(interactions, many=True)
        return Response(serializer.data)


class StrayAnimalFavoriteViewSet(viewsets.ReadOnlyModelViewSet):
    """收藏记录视图集（只读，主要用于管理）"""
    queryset = StrayAnimalFavorite.objects.all()
    serializer_class = StrayAnimalFavoriteSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_queryset(self):
        """只返回当前用户的收藏"""
        return super().get_queryset().filter(user=self.request.user)


class StrayAnimalReportViewSet(viewsets.ModelViewSet):
    """举报记录视图集"""
    queryset = StrayAnimalReport.objects.all()
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_serializer_class(self):
        """根据操作返回对应的序列化器"""
        if self.action == 'create':
            return StrayAnimalReportCreateSerializer
        return StrayAnimalReportSerializer

    def get_queryset(self):
        """普通用户只能看到自己的举报，管理员可以看到所有"""
        queryset = super().get_queryset()

        # 如果是管理员，可以看到所有举报
        if self.request.user.is_staff:
            # 支持按状态过滤
            report_status = self.request.query_params.get('status')
            if report_status:
                queryset = queryset.filter(status=report_status)
            return queryset

        # 普通用户只能看到自己提交的举报
        return queryset.filter(reporter=self.request.user)

    def perform_create(self, serializer):
        """创建举报时设置举报人"""
        serializer.save(reporter=self.request.user)

    @action(detail=False, methods=['get'])
    def my_reports(self, request):
        """获取我的举报记录"""
        reports = self.get_queryset().filter(reporter=request.user)

        page = self.paginate_queryset(reports)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(reports, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def handle(self, request, pk=None):
        """处理举报（仅管理员）"""
        if not request.user.is_staff:
            return Response(
                {'error': '只有管理员可以处理举报'},
                status=status.HTTP_403_FORBIDDEN
            )

        report = self.get_object()
        new_status = request.data.get('status')
        handler_note = request.data.get('handler_note', '')

        if new_status not in ['processing', 'resolved', 'rejected']:
            return Response(
                {'error': '无效的处理状态'},
                status=status.HTTP_400_BAD_REQUEST
            )

        report.status = new_status
        report.handler = request.user
        report.handler_note = handler_note
        report.handled_at = timezone.now()
        report.save()

        return Response(
            StrayAnimalReportSerializer(report).data,
            status=status.HTTP_200_OK
        )