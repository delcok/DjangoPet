from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from utils.authentication import UserAuthentication
from .models import PetCategory, Pet, PetDiary, PetServiceRecord
from .serializers import (
    PetCategorySerializer, PetListSerializer, PetDetailSerializer,
    PetDiaryListSerializer, PetDiaryDetailSerializer,
    PetServiceRecordListSerializer, PetServiceRecordDetailSerializer,
    PetServiceRecordCreateSerializer
)
from .filters import PetFilter, PetDiaryFilter, PetServiceRecordFilter
from pet.permissions import IsOwnerOrReadOnly, IsPetOwner, IsServiceProvider


class PetCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    宠物分类视图集（只读）
    list: 获取分类列表
    retrieve: 获取分类详情
    """
    queryset = PetCategory.objects.filter(is_active=True)
    serializer_class = PetCategorySerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['sort_order', 'created_at']
    ordering = ['sort_order']


class PetViewSet(viewsets.ModelViewSet):
    """
    宠物信息视图集
    list: 获取当前用户的宠物列表
    retrieve: 获取宠物详情
    create: 创建宠物
    update/partial_update: 更新宠物信息
    destroy: 删除宠物（软删除）
    """
    permission_classes = [IsAuthenticated, IsPetOwner]
    authentication_classes = [UserAuthentication]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PetFilter
    search_fields = ['name', 'breed']
    ordering_fields = ['created_at', 'name', 'birth_date']
    ordering = ['-created_at']

    def get_queryset(self):
        """只返回当前用户的宠物"""
        user = self.request.user
        return Pet.objects.filter(owner=user, is_deleted=False)

    def get_serializer_class(self):
        """根据不同操作返回不同的序列化器"""
        if self.action == 'list':
            return PetListSerializer
        return PetDetailSerializer

    def perform_destroy(self, instance):
        """软删除"""
        instance.is_deleted = True
        instance.save()

    @action(detail=True, methods=['get'])
    def diaries(self, request, pk=None):
        """获取指定宠物的日记列表"""
        pet = self.get_object()
        diaries = PetDiary.objects.filter(pet=pet)

        # 支持日记类型过滤
        diary_type = request.query_params.get('diary_type')
        if diary_type:
            diaries = diaries.filter(diary_type=diary_type)

        page = self.paginate_queryset(diaries)
        if page is not None:
            serializer = PetDiaryListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetDiaryListSerializer(diaries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def service_records(self, request, pk=None):
        """获取指定宠物的服务记录"""
        pet = self.get_object()
        # 通过订单关联查询服务记录
        records = PetServiceRecord.objects.filter(
            related_order__pets=pet
        ).select_related('related_order', 'related_diary')

        page = self.paginate_queryset(records)
        if page is not None:
            serializer = PetServiceRecordListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetServiceRecordListSerializer(records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取宠物统计信息"""
        user = request.user
        pets = Pet.objects.filter(owner=user, is_deleted=False)

        stats = {
            'total_pets': pets.count(),
            'category_distribution': {},
            'gender_distribution': {
                'M': pets.filter(gender='M').count(),
                'F': pets.filter(gender='F').count(),
                'U': pets.filter(gender='U').count(),
            }
        }

        # 按分类统计
        for pet in pets:
            category_name = pet.category.name
            stats['category_distribution'][category_name] = \
                stats['category_distribution'].get(category_name, 0) + 1

        return Response(stats)


class PetDiaryViewSet(viewsets.ModelViewSet):
    """
    宠物日记视图集
    list: 获取日记列表
    retrieve: 获取日记详情
    create: 创建日记
    update/partial_update: 更新日记
    destroy: 删除日记
    """
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    authentication_classes = [UserAuthentication]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PetDiaryFilter
    search_fields = ['title', 'content']
    ordering_fields = ['diary_date', 'created_at']
    ordering = ['-diary_date', '-created_at']

    def get_queryset(self):
        """只返回用户自己宠物的日记"""
        user = self.request.user
        # 用户只能看到自己宠物的日记
        return PetDiary.objects.filter(pet__owner=user)

    def get_serializer_class(self):
        if self.action == 'list':
            return PetDiaryListSerializer
        return PetDiaryDetailSerializer

    def perform_create(self, serializer):
        """创建日记时验证权限"""
        pet = serializer.validated_data['pet']
        user = self.request.user

        # 确保只能为自己的宠物创建日记
        if pet.owner != user:
            return Response(
                {'error': '您没有权限为该宠物创建日记'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer.save(author=user)

    def perform_update(self, serializer):
        """只有作者可以更新日记"""
        if serializer.instance.author != self.request.user:
            return Response(
                {'error': '您没有权限修改该日记'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer.save()

    def perform_destroy(self, instance):
        """只有作者可以删除日记"""
        if instance.author != self.request.user:
            return Response(
                {'error': '您没有权限删除该日记'},
                status=status.HTTP_403_FORBIDDEN
            )
        instance.delete()

    @action(detail=False, methods=['get'])
    def my_diaries(self, request):
        """获取当前用户创建的所有日记"""
        diaries = PetDiary.objects.filter(author=request.user)

        page = self.paginate_queryset(diaries)
        if page is not None:
            serializer = PetDiaryListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetDiaryListSerializer(diaries, many=True)
        return Response(serializer.data)


class PetServiceRecordViewSet(viewsets.ModelViewSet):
    """
    宠物服务记录视图集
    list: 获取服务记录列表
    retrieve: 获取服务记录详情
    create: 创建服务记录（仅服务提供者）
    update/partial_update: 更新服务记录
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = PetServiceRecordFilter
    ordering_fields = ['actual_start_time', 'created_at', 'rating']
    ordering = ['-actual_start_time']

    def get_queryset(self):
        """
        宠物主人：查看自己宠物的服务记录
        服务提供者：查看自己创建的服务记录
        管理员：查看所有记录
        """
        user = self.request.user


        # 宠物主人看自己宠物的记录 或 服务提供者看自己创建的记录
        return PetServiceRecord.objects.filter(
            Q(related_order__pets__owner=user) |
            Q(related_order__staff=user)
        ).distinct()

    def get_serializer_class(self):
        if self.action == 'create':
            return PetServiceRecordCreateSerializer
        elif self.action == 'list':
            return PetServiceRecordListSerializer
        return PetServiceRecordDetailSerializer

    def perform_create(self, serializer):
        """创建服务记录"""
        serializer.save()

    @action(detail=True, methods=['post'])
    def add_feedback(self, request, pk=None):
        """客户添加反馈和评分"""
        record = self.get_object()

        # 验证是否是宠物主人
        if record.related_order.customer != request.user:
            return Response(
                {'error': '只有客户可以添加反馈'},
                status=status.HTTP_403_FORBIDDEN
            )

        feedback = request.data.get('customer_feedback')
        rating = request.data.get('rating')

        if rating and (rating < 1 or rating > 5):
            return Response(
                {'error': '评分必须在1-5之间'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if feedback:
            record.customer_feedback = feedback
        if rating:
            record.rating = rating

        record.save()

        serializer = self.get_serializer(record)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def my_records(self, request):
        """获取当前用户作为服务提供者创建的服务记录"""
        records = PetServiceRecord.objects.filter(
            related_order__staff=request.user
        )

        page = self.paginate_queryset(records)
        if page is not None:
            serializer = PetServiceRecordListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PetServiceRecordListSerializer(records, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取服务记录统计（服务提供者）"""
        user = request.user
        records = PetServiceRecord.objects.filter(related_order__staff=user)

        stats = {
            'total_records': records.count(),
            'average_rating': 0,
            'rating_distribution': {
                '5': records.filter(rating=5).count(),
                '4': records.filter(rating=4).count(),
                '3': records.filter(rating=3).count(),
                '2': records.filter(rating=2).count(),
                '1': records.filter(rating=1).count(),
            }
        }

        # 计算平均评分
        rated_records = records.exclude(rating__isnull=True)
        if rated_records.exists():
            total_rating = sum([r.rating for r in rated_records])
            stats['average_rating'] = round(total_rating / rated_records.count(), 2)

        return Response(stats)
