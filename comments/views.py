# -*- coding: utf-8 -*-
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from utils.authentication import (
    UserAuthentication,
    MerchantOrSubAuthentication,
    StaffOrMerchantAuthentication,
    ManagerAuthentication, OptionalUserAuthentication,
)
from utils.permission import (
    IsActiveUser,
    IsMerchantOrStaff,
    IsManager,
    get_merchant_id_from_request, AllowAny,
)

from .filters import ProductReviewFilter, ServiceReviewFilter
from .models import ProductReview, ServiceReview, ReviewStatusMixin
from .pagination import ReviewPageNumberPagination
from .serializers import (
    ProductReviewListSerializer,
    ProductReviewDetailSerializer,
    ProductReviewCreateSerializer,
    ServiceReviewListSerializer,
    ServiceReviewDetailSerializer,
    ServiceReviewCreateSerializer,
    ReviewReplySerializer,
    ReviewAuditSerializer,
)


# ============================================
# 通用基类
# ============================================

class ReviewBaseMixin:
    pagination_class = ReviewPageNumberPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    ordering_fields = ['created_at', 'updated_at', 'score']
    ordering = ['-created_at']
    search_fields = ['content', 'merchant_name', 'replied_content']


# ============================================
# 用户端 - 商品评价
# ============================================

class UserProductReviewViewSet(
    ReviewBaseMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet
):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    filterset_class = ProductReviewFilter

    def get_queryset(self):
        return ProductReview.objects.prefetch_related(
            'images', 'items', 'items__images'
        ).filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'create':
            return ProductReviewCreateSerializer
        elif self.action == 'retrieve':
            return ProductReviewDetailSerializer
        return ProductReviewListSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != ReviewStatusMixin.Status.PENDING:
            return Response({'detail': '只有待审核评论允许用户修改'}, status=status.HTTP_400_BAD_REQUEST)
        return super().partial_update(request, *args, **kwargs)


# ============================================
# 用户端 - 服务评价
# ============================================

class UserServiceReviewViewSet(
    ReviewBaseMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet
):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    filterset_class = ServiceReviewFilter

    def get_queryset(self):
        return ServiceReview.objects.prefetch_related('images').filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'create':
            return ServiceReviewCreateSerializer
        elif self.action == 'retrieve':
            return ServiceReviewDetailSerializer
        return ServiceReviewListSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != ReviewStatusMixin.Status.PENDING:
            return Response({'detail': '只有待审核评论允许用户修改'}, status=status.HTTP_400_BAD_REQUEST)
        return super().partial_update(request, *args, **kwargs)


# ============================================
# 商家端 - 商品评价管理 / 回复
# ============================================

class MerchantProductReviewViewSet(
    ReviewBaseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchantOrStaff]
    filterset_class = ProductReviewFilter

    def get_queryset(self):
        merchant_id = get_merchant_id_from_request(self.request)
        return ProductReview.objects.prefetch_related(
            'images', 'items', 'items__images'
        ).filter(merchant_id=merchant_id)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProductReviewDetailSerializer
        return ProductReviewListSerializer

    @action(methods=['post'], detail=True, url_path='reply')
    def reply(self, request, pk=None):
        review = self.get_object()
        serializer = ReviewReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.replied_content = serializer.validated_data['replied_content']
        review.replied_at = timezone.now()
        review.save(update_fields=['replied_content', 'replied_at', 'updated_at'])

        return Response({'detail': '回复成功'})


# ============================================
# 商家端 - 服务评价管理 / 回复
# ============================================

class MerchantServiceReviewViewSet(
    ReviewBaseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    authentication_classes = [StaffOrMerchantAuthentication]
    permission_classes = [IsMerchantOrStaff]
    filterset_class = ServiceReviewFilter

    def get_queryset(self):
        merchant_id = get_merchant_id_from_request(self.request)
        return ServiceReview.objects.prefetch_related('images').filter(merchant_id=merchant_id)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ServiceReviewDetailSerializer
        return ServiceReviewListSerializer

    @action(methods=['post'], detail=True, url_path='reply')
    def reply(self, request, pk=None):
        review = self.get_object()
        serializer = ReviewReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.replied_content = serializer.validated_data['replied_content']
        review.replied_at = timezone.now()
        review.save(update_fields=['replied_content', 'replied_at', 'updated_at'])

        return Response({'detail': '回复成功'})


# ============================================
# 管理端 - 商品评价超管操作
# ============================================

class AdminProductReviewViewSet(
    ReviewBaseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet
):
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filterset_class = ProductReviewFilter

    def get_queryset(self):
        return ProductReview.objects.prefetch_related(
            'images', 'items', 'items__images'
        ).all()

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProductReviewDetailSerializer
        return ProductReviewListSerializer

    @action(methods=['post'], detail=True, url_path='audit')
    def audit(self, request, pk=None):
        review = self.get_object()
        serializer = ReviewAuditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.status = serializer.validated_data['status']
        review.save(update_fields=['status', 'updated_at'])

        return Response({
            'detail': '审核成功',
            'id': review.id,
            'status': review.status
        })

    @action(methods=['post'], detail=True, url_path='reply')
    def reply(self, request, pk=None):
        review = self.get_object()
        serializer = ReviewReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.replied_content = serializer.validated_data['replied_content']
        review.replied_at = timezone.now()
        review.save(update_fields=['replied_content', 'replied_at', 'updated_at'])

        return Response({'detail': '回复成功'})

    @action(methods=['post'], detail=False, url_path='batch_audit')
    def batch_audit(self, request):
        ids = request.data.get('ids') or []
        new_status = request.data.get('status')
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'ids 不能为空'}, status=status.HTTP_400_BAD_REQUEST)
        valid_statuses = [s.value for s in ReviewStatusMixin.Status]
        if new_status not in valid_statuses:
            return Response({'detail': '无效状态'}, status=status.HTTP_400_BAD_REQUEST)
        updated = self.get_queryset().filter(id__in=ids).update(
            status=new_status, updated_at=timezone.now()
        )
        return Response({
            'detail': f'批量审核成功，共更新 {updated} 条',
            'updated': updated,
            'status': new_status,
        })


# ============================================
# 管理端 - 服务评价超管操作
# ============================================

class AdminServiceReviewViewSet(
    ReviewBaseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet
):
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filterset_class = ServiceReviewFilter

    def get_queryset(self):
        return ServiceReview.objects.prefetch_related('images').all()

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ServiceReviewDetailSerializer
        return ServiceReviewListSerializer

    @action(methods=['post'], detail=True, url_path='audit')
    def audit(self, request, pk=None):
        review = self.get_object()
        serializer = ReviewAuditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.status = serializer.validated_data['status']
        review.save(update_fields=['status', 'updated_at'])

        return Response({
            'detail': '审核成功',
            'id': review.id,
            'status': review.status
        })

    @action(methods=['post'], detail=True, url_path='reply')
    def reply(self, request, pk=None):
        review = self.get_object()
        serializer = ReviewReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.replied_content = serializer.validated_data['replied_content']
        review.replied_at = timezone.now()
        review.save(update_fields=['replied_content', 'replied_at', 'updated_at'])

        return Response({'detail': '回复成功'})

    @action(methods=['post'], detail=False, url_path='batch_audit')
    def batch_audit(self, request):
        ids = request.data.get('ids') or []
        new_status = request.data.get('status')
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'ids 不能为空'}, status=status.HTTP_400_BAD_REQUEST)
        valid_statuses = [s.value for s in ReviewStatusMixin.Status]
        if new_status not in valid_statuses:
            return Response({'detail': '无效状态'}, status=status.HTTP_400_BAD_REQUEST)
        updated = self.get_queryset().filter(id__in=ids).update(
            status=new_status, updated_at=timezone.now()
        )
        return Response({
            'detail': f'批量审核成功，共更新 {updated} 条',
            'updated': updated,
            'status': new_status,
        })


class PublicProductReviewViewSet(
    ReviewBaseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    """公开商品评价 - 无需登录，登录则识别用户身份"""
    authentication_classes = [OptionalUserAuthentication]
    permission_classes = [AllowAny]
    filterset_class = ProductReviewFilter

    def get_queryset(self):
        return ProductReview.objects.prefetch_related(
            'images', 'items', 'items__images'
        ).filter(status=ReviewStatusMixin.Status.APPROVED)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProductReviewDetailSerializer
        return ProductReviewListSerializer


class PublicServiceReviewViewSet(
    ReviewBaseMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    """公开服务评价 - 无需登录，登录则识别用户身份"""
    authentication_classes = [OptionalUserAuthentication]
    permission_classes = [AllowAny]
    filterset_class = ServiceReviewFilter

    def get_queryset(self):
        return ServiceReview.objects.prefetch_related('images').filter(
            status=ReviewStatusMixin.Status.APPROVED
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ServiceReviewDetailSerializer
        return ServiceReviewListSerializer