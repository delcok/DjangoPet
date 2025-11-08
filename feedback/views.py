from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from utils.authentication import UserAuthentication
from utils.permission import IsUserOwner
from .models import Feedback
from .serializers import FeedbackSerializer, FeedbackAdminSerializer


class FeedbackViewSet(viewsets.ModelViewSet):
    """反馈视图集"""
    queryset = Feedback.objects.all()
    serializer_class = FeedbackSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUserOwner]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['feedback_type', 'status']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        """管理员使用不同的序列化器"""
        if self.action in ['update', 'partial_update']:
            return FeedbackAdminSerializer
        return FeedbackSerializer

    def get_queryset(self):
        """普通用户只能看到自己的反馈"""
        if self.request.user.is_authenticated:
            return Feedback.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """创建反馈（禁止匿名用户）"""
        if not request.user.is_authenticated:
            raise PermissionDenied('匿名用户不能创建反馈')

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({
            'message': '提交成功，我们会尽快处理您的反馈',
            'data': serializer.data
        }, status=201)

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def my_feedbacks(self, request):
        """获取我的反馈列表"""
        queryset = self.filter_queryset(
            Feedback.objects.filter(user=request.user)
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)