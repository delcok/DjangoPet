from rest_framework import viewsets, mixins, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count

from utils.authentication import UserAuthentication, ManagerAuthentication
from utils.permission import IsUser, IsResourceOwner, IsManager
from .models import Feedback
from .serializers import FeedbackSerializer, FeedbackAdminSerializer
from .filters import FeedbackFilter
from .pagination import FeedbackPagination


# ============================================================
# 用户端：提交 / 查看 / 维护自己的反馈
# ============================================================
class FeedbackViewSet(viewsets.ModelViewSet):
    """反馈视图集（用户端）"""
    queryset = Feedback.objects.all()
    # ✅ 用户端统一用普通序列化器：其中 status / reply 是 read_only，用户改不了
    serializer_class = FeedbackSerializer
    authentication_classes = [UserAuthentication]
    # IsUserOwner -> IsUser（必须登录用户）+ IsResourceOwner（只能操作自己的反馈，按 user 字段判定）
    permission_classes = [IsUser, IsResourceOwner]
    pagination_class = FeedbackPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = FeedbackFilter
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_queryset(self):
        """普通用户只能看到自己的反馈"""
        if self.request.user.is_authenticated:
            return Feedback.objects.filter(user=self.request.user)
        # 未登录兜底：返回空集（权限层已拦截匿名，这里防止返回 None 触发异常）
        return Feedback.objects.none()

    def create(self, request, *args, **kwargs):
        """创建反馈（IsUser 已挡匿名，这里保留自定义成功响应）"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({
            'code': 201,
            'message': '提交成功，我们会尽快处理您的反馈',
            'data': serializer.data
        }, status=201)

    @action(detail=False, methods=['get'], permission_classes=[IsUser])
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


# ============================================================
# 管理端：平台管理员处理反馈（查看全部 / 改状态 / 回复 / 删除 / 统计）
# ============================================================
class FeedbackAdminViewSet(mixins.ListModelMixin,
                           mixins.RetrieveModelMixin,
                           mixins.UpdateModelMixin,
                           mixins.DestroyModelMixin,
                           viewsets.GenericViewSet):
    """
    反馈管理视图集（需要平台管理员 Manager 登录）

    - GET    admin/feedbacks/             列表（feedback_type / status / keyword / has_reply / 时间区间 筛选）
    - GET    admin/feedbacks/{id}/        详情
    - PATCH  admin/feedbacks/{id}/        处理：可改 status / reply（走 FeedbackAdminSerializer）
    - DELETE admin/feedbacks/{id}/        删除
    - POST   admin/feedbacks/{id}/reply/  快捷回复（可同时改状态）
    - GET    admin/feedbacks/statistics/  统计（按状态 / 类型分组）

    不提供 create：反馈由用户提交，后台不凭空创建。
    """
    queryset = Feedback.objects.select_related('user').all()
    serializer_class = FeedbackAdminSerializer  # status / reply 可写
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    pagination_class = FeedbackPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = FeedbackFilter
    ordering_fields = ['created_at', 'updated_at', 'status']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        """快捷回复反馈（可同时更新状态）"""
        feedback = self.get_object()

        reply_text = (request.data.get('reply') or '').strip()
        if not reply_text:
            return Response({'code': 400, 'message': '回复内容不能为空'}, status=400)

        data = {'reply': reply_text}
        if request.data.get('status'):
            data['status'] = request.data['status']

        # 走序列化器，借助 ChoiceField 校验 status 合法性
        serializer = self.get_serializer(feedback, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            'code': 200,
            'message': '回复成功',
            'data': serializer.data
        })

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """反馈统计（按状态、类型分组）"""
        qs = Feedback.objects.all()
        return Response({
            'code': 200,
            'message': '获取成功',
            'data': {
                'total': qs.count(),
                'by_status': list(qs.values('status').annotate(count=Count('id')).order_by('status')),
                'by_type': list(qs.values('feedback_type').annotate(count=Count('id')).order_by('feedback_type')),
            }
        })