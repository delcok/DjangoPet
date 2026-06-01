from rest_framework import viewsets, status, filters, mixins, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta
import math

from user.models import User
from utils.authentication import UserAuthentication, ManagerAuthentication
from utils.permission import AllowAny, IsActiveUser, IsManager

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
    StrayAnimalReportCreateSerializer,
    StrayAnimalReportSerializer,
)


def is_normal_user(user):
    return isinstance(user, User) and getattr(user, 'is_active', False) and not getattr(user, 'is_banned', False)


class IsStrayAnimalReporter(permissions.BasePermission):
    """只有发布者本人可以修改或删除流浪动物记录"""

    message = '只有发布者可以修改或删除该流浪动物记录'

    def has_object_permission(self, request, view, obj):
        return is_normal_user(request.user) and obj.reporter_id == request.user.id


class StrayAnimalViewSet(viewsets.ModelViewSet):
    """用户端：流浪动物记录"""

    queryset = StrayAnimal.objects.filter(is_active=True).select_related('reporter')
    authentication_classes = [UserAuthentication]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nickname', 'breed', 'distinctive_features', 'detail_address']
    ordering_fields = ['created_at', 'last_seen_date', 'view_count', 'interaction_count', 'favorite_count']
    ordering = ['-last_seen_date']

    user_required_actions = {
        'create',
        'interact',
        'report_update',
        'favorite',
        'unfavorite',
        'my_favorites',
    }

    owner_required_actions = {
        'update',
        'partial_update',
        'destroy',
    }

    def get_permissions(self):
        if self.action in self.owner_required_actions:
            return [IsActiveUser(), IsStrayAnimalReporter()]

        if self.action in self.user_required_actions:
            return [IsActiveUser()]

        return [AllowAny()]

    def get_serializer_class(self):
        if self.action == 'list':
            return StrayAnimalListSerializer
        if self.action == 'create':
            return StrayAnimalCreateSerializer
        if self.action in ['update', 'partial_update']:
            return StrayAnimalUpdateSerializer
        if self.action == 'nearby':
            return NearbyAnimalSerializer
        return StrayAnimalDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        animal_type = params.get('animal_type')
        if animal_type:
            queryset = queryset.filter(animal_type=animal_type)

        status_filter = params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        health_status = params.get('health_status')
        if health_status:
            queryset = queryset.filter(health_status=health_status)

        province = params.get('province')
        city = params.get('city')
        district = params.get('district')

        if province:
            queryset = queryset.filter(province=province)
        if city:
            queryset = queryset.filter(city=city)
        if district:
            queryset = queryset.filter(district=district)

        days = params.get('days')
        if days:
            try:
                days = int(days)
                date_from = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(last_seen_date__gte=date_from.date())
            except ValueError:
                pass

        my_only = params.get('my_only')
        if my_only in ['1', 'true', 'True']:
            if is_normal_user(self.request.user):
                queryset = queryset.filter(reporter=self.request.user)
            else:
                queryset = queryset.none()

        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.increase_view_count()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)

    def perform_update(self, serializer):
        if 'last_seen_date' not in serializer.validated_data:
            serializer.validated_data['last_seen_date'] = timezone.now().date()
        serializer.save()

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()

    @action(detail=False, methods=['get'])
    def nearby(self, request):
        try:
            lat = float(request.query_params.get('lat'))
            lng = float(request.query_params.get('lng'))
            radius = float(request.query_params.get('radius', 5000))
        except (TypeError, ValueError):
            return Response(
                {'error': '请提供有效的经纬度参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        lat_range = radius / 111000
        lng_range = radius / (111000 * math.cos(math.radians(lat)))

        queryset = self.get_queryset().filter(
            latitude__range=(lat - lat_range, lat + lat_range),
            longitude__range=(lng - lng_range, lng + lng_range)
        )

        animals_with_distance = []

        for animal in queryset:
            if animal.latitude and animal.longitude:
                R = 6371000
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

        animals_with_distance.sort(key=lambda x: x.distance)

        page = self.paginate_queryset(animals_with_distance)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(animals_with_distance, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def interact(self, request, pk=None):
        animal = self.get_object()
        serializer = StrayAnimalInteractionCreateSerializer(data=request.data)

        if serializer.is_valid():
            interaction = StrayAnimalInteraction.objects.create(
                animal=animal,
                user=request.user,
                **serializer.validated_data
            )

            if interaction.interaction_type == 'sighting':
                animal.last_seen_date = timezone.now().date()

                if interaction.latitude and interaction.longitude:
                    animal.latitude = interaction.latitude
                    animal.longitude = interaction.longitude

                animal.save()

            return Response(
                StrayAnimalInteractionSerializer(interaction, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def interactions(self, request, pk=None):
        animal = self.get_object()
        interactions = animal.interactions.select_related('user').all()

        interaction_type = request.query_params.get('type')
        if interaction_type:
            interactions = interactions.filter(interaction_type=interaction_type)

        page = self.paginate_queryset(interactions)
        if page is not None:
            serializer = StrayAnimalInteractionSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = StrayAnimalInteractionSerializer(interactions, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        queryset = self.get_queryset()

        province = request.query_params.get('province')
        city = request.query_params.get('city')
        district = request.query_params.get('district')

        if province:
            queryset = queryset.filter(province=province)
        if city:
            queryset = queryset.filter(city=city)
        if district:
            queryset = queryset.filter(district=district)

        total_animals = queryset.count()
        active_animals = queryset.filter(status='active').count()
        rescued_animals = queryset.filter(status='rescued').count()
        adopted_animals = queryset.filter(status='adopted').count()

        total_interactions = StrayAnimalInteraction.objects.filter(
            animal__in=queryset
        ).count()

        week_ago = timezone.now() - timedelta(days=7)
        recent_week_reports = queryset.filter(created_at__gte=week_ago).count()

        by_type = dict(queryset.values_list('animal_type').annotate(count=Count('id')))

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
        try:
            days = int(request.query_params.get('days', 7))
            limit = int(request.query_params.get('limit', 10))
        except ValueError:
            return Response({'error': 'days 和 limit 必须是数字'}, status=status.HTTP_400_BAD_REQUEST)

        date_from = timezone.now() - timedelta(days=days)

        queryset = self.get_queryset().filter(
            interactions__created_at__gte=date_from
        ).annotate(
            recent_interaction_count=Count('interactions')
        ).order_by('-recent_interaction_count')[:limit]

        serializer = StrayAnimalListSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def report_update(self, request, pk=None):
        animal = self.get_object()
        new_status = request.data.get('status')
        notes = request.data.get('notes', '')

        if new_status not in dict(StrayAnimal.STATUS_CHOICES):
            return Response({'error': '无效的状态'}, status=status.HTTP_400_BAD_REQUEST)

        animal.status = new_status

        if notes:
            animal.additional_notes = (
                f"{animal.additional_notes}\n{timezone.now()}: {notes}"
                if animal.additional_notes
                else f"{timezone.now()}: {notes}"
            )

        animal.save()

        StrayAnimalInteraction.objects.create(
            animal=animal,
            user=request.user,
            interaction_type='comment',
            content=f"报告状态更新为: {animal.get_status_display()}. {notes}"
        )

        return Response({'message': '状态已更新'})

    @action(detail=True, methods=['post'])
    def favorite(self, request, pk=None):
        animal = self.get_object()

        favorite, created = StrayAnimalFavorite.objects.get_or_create(
            user=request.user,
            animal=animal
        )

        if created:
            return Response(
                {'message': '收藏成功', 'is_favorited': True},
                status=status.HTTP_201_CREATED
            )

        return Response(
            {'message': '已经收藏过了', 'is_favorited': True},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def unfavorite(self, request, pk=None):
        animal = self.get_object()

        deleted_count = StrayAnimalFavorite.objects.filter(
            user=request.user,
            animal=animal
        ).delete()[0]

        if deleted_count > 0:
            return Response({'message': '取消收藏成功', 'is_favorited': False})

        return Response({'message': '未收藏该动物', 'is_favorited': False})

    @action(detail=False, methods=['get'])
    def my_favorites(self, request):
        favorites = StrayAnimalFavorite.objects.filter(
            user=request.user,
            animal__is_active=True
        ).select_related('animal', 'animal__reporter')

        animals = [favorite.animal for favorite in favorites]

        page = self.paginate_queryset(animals)
        if page is not None:
            serializer = StrayAnimalListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = StrayAnimalListSerializer(animals, many=True, context={'request': request})
        return Response(serializer.data)


class StrayAnimalInteractionViewSet(viewsets.ReadOnlyModelViewSet):
    """用户端：互动记录只读"""

    queryset = StrayAnimalInteraction.objects.select_related('user', 'animal').all()
    serializer_class = StrayAnimalInteractionSerializer
    authentication_classes = [UserAuthentication]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_permissions(self):
        if self.action == 'my_interactions':
            return [IsActiveUser()]
        return [AllowAny()]

    def get_queryset(self):
        queryset = super().get_queryset()

        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        animal_id = self.request.query_params.get('animal_id')
        if animal_id:
            queryset = queryset.filter(animal_id=animal_id)

        interaction_type = self.request.query_params.get('type')
        if interaction_type:
            queryset = queryset.filter(interaction_type=interaction_type)

        return queryset

    @action(detail=False, methods=['get'])
    def my_interactions(self, request):
        interactions = self.get_queryset().filter(user=request.user)

        page = self.paginate_queryset(interactions)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(interactions, many=True)
        return Response(serializer.data)


class StrayAnimalFavoriteViewSet(viewsets.ReadOnlyModelViewSet):
    """用户端：我的收藏记录"""

    serializer_class = StrayAnimalFavoriteSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_queryset(self):
        return StrayAnimalFavorite.objects.filter(
            user=self.request.user
        ).select_related('animal', 'animal__reporter')


class StrayAnimalReportViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    """用户端：举报记录"""

    queryset = StrayAnimalReport.objects.all()
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return StrayAnimalReportCreateSerializer
        return StrayAnimalReportSerializer

    def get_queryset(self):
        queryset = StrayAnimalReport.objects.filter(
            reporter=self.request.user
        ).select_related('reporter', 'animal', 'interaction')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)

    @action(detail=False, methods=['get'])
    def my_reports(self, request):
        reports = self.get_queryset()

        page = self.paginate_queryset(reports)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(reports, many=True)
        return Response(serializer.data)


class StrayAnimalAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet
):
    """管理员端：流浪动物管理"""

    queryset = StrayAnimal.objects.all().select_related('reporter')
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nickname', 'breed', 'distinctive_features', 'detail_address']
    ordering_fields = ['created_at', 'updated_at', 'last_seen_date', 'view_count', 'interaction_count', 'favorite_count']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return StrayAnimalUpdateSerializer
        if self.action == 'list':
            return StrayAnimalListSerializer
        return StrayAnimalDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        is_active = params.get('is_active')
        if is_active in ['1', 'true', 'True']:
            queryset = queryset.filter(is_active=True)
        elif is_active in ['0', 'false', 'False']:
            queryset = queryset.filter(is_active=False)

        animal_type = params.get('animal_type')
        if animal_type:
            queryset = queryset.filter(animal_type=animal_type)

        status_filter = params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        reporter_id = params.get('reporter_id')
        if reporter_id:
            queryset = queryset.filter(reporter_id=reporter_id)

        province = params.get('province')
        city = params.get('city')
        district = params.get('district')

        if province:
            queryset = queryset.filter(province=province)
        if city:
            queryset = queryset.filter(city=city)
        if district:
            queryset = queryset.filter(district=district)

        return queryset

    def destroy(self, request, *args, **kwargs):
        animal = self.get_object()
        animal.is_active = False
        animal.save()
        return Response({'message': '已下架该流浪动物记录'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        animal = self.get_object()
        animal.is_active = True
        animal.save()
        return Response({'message': '已恢复该流浪动物记录'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def set_status(self, request, pk=None):
        animal = self.get_object()
        new_status = request.data.get('status')
        notes = request.data.get('notes', '')

        if new_status not in dict(StrayAnimal.STATUS_CHOICES):
            return Response({'error': '无效的状态'}, status=status.HTTP_400_BAD_REQUEST)

        animal.status = new_status

        if notes:
            animal.additional_notes = (
                f"{animal.additional_notes}\n管理员 {request.user.id} 于 {timezone.now()} 备注：{notes}"
                if animal.additional_notes
                else f"管理员 {request.user.id} 于 {timezone.now()} 备注：{notes}"
            )

        animal.save()

        return Response(
            {
                'message': '状态已更新',
                'status': animal.status,
                'status_display': animal.get_status_display()
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        queryset = self.get_queryset()

        data = {
            'total_animals': queryset.count(),
            'active_records': queryset.filter(is_active=True).count(),
            'inactive_records': queryset.filter(is_active=False).count(),
            'active_animals': queryset.filter(status='active').count(),
            'rescued_animals': queryset.filter(status='rescued').count(),
            'adopted_animals': queryset.filter(status='adopted').count(),
            'total_interactions': StrayAnimalInteraction.objects.filter(animal__in=queryset).count(),
            'total_favorites': StrayAnimalFavorite.objects.filter(animal__in=queryset).count(),
            'pending_reports': StrayAnimalReport.objects.filter(status='pending').count(),
            'by_type': dict(queryset.values_list('animal_type').annotate(count=Count('id'))),
        }

        return Response(data)


class StrayAnimalReportAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    """管理员端：举报管理"""

    queryset = StrayAnimalReport.objects.all()
    serializer_class = StrayAnimalReportSerializer
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = StrayAnimalReport.objects.all().select_related(
            'reporter',
            'animal',
            'interaction',
            'handler',
        )

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        report_type = self.request.query_params.get('report_type')
        if report_type:
            queryset = queryset.filter(report_type=report_type)

        animal_id = self.request.query_params.get('animal_id')
        if animal_id:
            queryset = queryset.filter(animal_id=animal_id)

        reporter_id = self.request.query_params.get('reporter_id')
        if reporter_id:
            queryset = queryset.filter(reporter_id=reporter_id)

        return queryset

    @action(detail=True, methods=['post'])
    def handle(self, request, pk=None):
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
            StrayAnimalReportSerializer(report, context={'request': request}).data,
            status=status.HTTP_200_OK
        )