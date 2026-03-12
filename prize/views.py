# -*- coding: utf-8 -*-
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework import status, generics, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from utils.authentication import AdminAuthentication, UserAuthentication

from .models import Prize, UserPrize, UserPrizeLog
from .serializers import (
    PrizeSerializer,
    PrizeListSerializer,
    UserPrizeSerializer,
    UserPrizeListSerializer,
    AdminIssuePrizeSerializer,
    AdminBatchIssuePrizeSerializer,
    AdminStatusUpdateSerializer,
    UserPrizeClaimSerializer,
)
from utils.permission import IsStaffAdmin, IsUserClient
from .filters import PrizeFilter, UserPrizeFilter


def calc_valid_time(prize, valid_start_time=None, valid_end_time=None):
    final_start = valid_start_time if valid_start_time is not None else prize.start_time
    final_end = valid_end_time

    if final_end is None:
        if prize.end_time:
            final_end = prize.end_time
        elif prize.valid_days:
            final_end = timezone.now() + timezone.timedelta(days=prize.valid_days)

    return final_start, final_end


# =========================
# 管理员接口
# =========================

class AdminPrizeListCreateView(generics.ListCreateAPIView):
    """
    管理员：奖品模板列表、创建
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]
    queryset = Prize.objects.all().order_by('-id')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PrizeFilter
    search_fields = ['name', 'title', 'content', 'redeem_contact', 'redeem_phone']
    ordering_fields = ['id', 'sort', 'created_at', 'updated_at']
    ordering = ['-id']

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return PrizeListSerializer
        return PrizeSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)


class AdminPrizeDetailView(generics.RetrieveUpdateAPIView):
    """
    管理员：奖品模板详情、修改
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]
    queryset = Prize.objects.all()
    serializer_class = PrizeSerializer

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class AdminIssuePrizeView(APIView):
    """
    管理员：单个发奖
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]

    @transaction.atomic
    def post(self, request):
        serializer = AdminIssuePrizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        prize = serializer.validated_data['prize']
        source = serializer.validated_data.get('source', 'manual')
        admin_remark = serializer.validated_data.get('admin_remark', '')
        input_valid_start = serializer.validated_data.get('valid_start_time')
        input_valid_end = serializer.validated_data.get('valid_end_time')

        final_start, final_end = calc_valid_time(prize, input_valid_start, input_valid_end)

        user_prize = UserPrize.objects.create(
            user=user,
            prize=prize,
            source=source,
            valid_start_time=final_start,
            valid_end_time=final_end,
            admin_remark=admin_remark,
            issued_by=request.user,
        )

        UserPrizeLog.objects.create(
            user_prize=user_prize,
            action='issue',
            operator_staff=request.user,
            old_status='',
            new_status='pending',
            note='管理员手动发放奖品'
        )

        return Response({
            'message': '发放成功',
            'id': user_prize.id,
            'exchange_code': user_prize.exchange_code
        }, status=status.HTTP_201_CREATED)


class AdminBatchIssuePrizeView(APIView):
    """
    管理员：批量发奖
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]

    @transaction.atomic
    def post(self, request):
        serializer = AdminBatchIssuePrizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        users = serializer.validated_data['users']
        prize = serializer.validated_data['prize']
        source = serializer.validated_data.get('source', 'manual')
        admin_remark = serializer.validated_data.get('admin_remark', '')
        batch_no = serializer.validated_data.get('batch_no') or timezone.now().strftime('BATCH%Y%m%d%H%M%S')
        input_valid_start = serializer.validated_data.get('valid_start_time')
        input_valid_end = serializer.validated_data.get('valid_end_time')

        final_start, final_end = calc_valid_time(prize, input_valid_start, input_valid_end)

        created_ids = []

        for user in users:
            user_prize = UserPrize.objects.create(
                user=user,
                prize=prize,
                source=source,
                batch_no=batch_no,
                valid_start_time=final_start,
                valid_end_time=final_end,
                admin_remark=admin_remark,
                issued_by=request.user,
            )
            created_ids.append(user_prize.id)

            UserPrizeLog.objects.create(
                user_prize=user_prize,
                action='issue',
                operator_staff=request.user,
                old_status='',
                new_status='pending',
                note=f'管理员批量发放奖品，批次号: {batch_no}'
            )

        return Response({
            'message': '批量发放成功',
            'batch_no': batch_no,
            'count': len(created_ids),
            'ids': created_ids
        }, status=status.HTTP_201_CREATED)


class AdminUserPrizeListView(generics.ListAPIView):
    """
    管理员：中奖记录列表
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]
    serializer_class = UserPrizeListSerializer
    queryset = UserPrize.objects.select_related('user', 'prize', 'issued_by', 'handled_by').all().order_by('-id')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = UserPrizeFilter
    search_fields = [
        'exchange_code',
        'prize_snapshot_name',
        'title',
        'user__username',
        'user__phone',
        'batch_no',
    ]
    ordering_fields = ['id', 'issued_at', 'valid_end_time', 'claimed_at', 'redeemed_at', 'created_at']
    ordering = ['-id']

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(
                Q(exchange_code__icontains=keyword) |
                Q(prize_snapshot_name__icontains=keyword) |
                Q(title__icontains=keyword) |
                Q(user__username__icontains=keyword) |
                Q(user__phone__icontains=keyword) |
                Q(batch_no__icontains=keyword)
            )
        return queryset


class AdminUserPrizeDetailView(generics.RetrieveAPIView):
    """
    管理员：中奖记录详情
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]
    queryset = UserPrize.objects.select_related(
        'user', 'prize', 'issued_by', 'handled_by', 'address'
    ).prefetch_related('logs')
    serializer_class = UserPrizeSerializer


class AdminUserPrizeProcessView(APIView):
    """
    管理员：标记处理中
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=404)

        serializer = AdminStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_prize.mark_expired_if_needed()
        if user_prize.status == 'expired':
            return Response({'detail': '奖品已过期，不能处理'}, status=400)

        if user_prize.status not in ['pending', 'claimed', 'rejected']:
            return Response({'detail': '当前状态不能标记为处理中'}, status=400)

        old_status = user_prize.status
        user_prize.status = 'processing'
        user_prize.handled_by = request.user
        user_prize.admin_remark = serializer.validated_data.get('admin_remark', user_prize.admin_remark)
        user_prize.save(update_fields=['status', 'handled_by', 'admin_remark', 'updated_at'])

        UserPrizeLog.objects.create(
            user_prize=user_prize,
            action='process',
            operator_staff=request.user,
            old_status=old_status,
            new_status='processing',
            note=serializer.validated_data.get('note', '管理员标记处理中')
        )

        return Response({'message': '已标记为处理中'})


class AdminUserPrizeRedeemView(APIView):
    """
    管理员：标记已兑奖
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=404)

        serializer = AdminStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_prize.mark_expired_if_needed()
        if user_prize.status == 'expired':
            return Response({'detail': '奖品已过期，不能兑奖'}, status=400)

        if user_prize.status not in ['pending', 'claimed', 'processing']:
            return Response({'detail': '当前状态不能标记为已兑奖'}, status=400)

        old_status = user_prize.status
        user_prize.status = 'redeemed'
        user_prize.handled_by = request.user
        user_prize.redeemed_at = timezone.now()
        user_prize.admin_remark = serializer.validated_data.get('admin_remark', user_prize.admin_remark)
        user_prize.save(update_fields=['status', 'handled_by', 'redeemed_at', 'admin_remark', 'updated_at'])

        UserPrizeLog.objects.create(
            user_prize=user_prize,
            action='redeem',
            operator_staff=request.user,
            old_status=old_status,
            new_status='redeemed',
            note=serializer.validated_data.get('note', '管理员标记已兑奖')
        )

        return Response({'message': '已标记为已兑奖'})


class AdminUserPrizeRejectView(APIView):
    """
    管理员：驳回兑奖申请
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=404)

        serializer = AdminStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_prize.mark_expired_if_needed()
        if user_prize.status == 'expired':
            return Response({'detail': '奖品已过期，不能驳回'}, status=400)

        if user_prize.status not in ['claimed', 'processing']:
            return Response({'detail': '当前状态不能驳回'}, status=400)

        old_status = user_prize.status
        user_prize.status = 'rejected'
        user_prize.handled_by = request.user
        user_prize.admin_remark = serializer.validated_data.get('admin_remark', user_prize.admin_remark)
        user_prize.save(update_fields=['status', 'handled_by', 'admin_remark', 'updated_at'])

        UserPrizeLog.objects.create(
            user_prize=user_prize,
            action='reject',
            operator_staff=request.user,
            old_status=old_status,
            new_status='rejected',
            note=serializer.validated_data.get('note', '管理员驳回兑奖申请')
        )

        return Response({'message': '已驳回'})


class AdminUserPrizeCancelView(APIView):
    """
    管理员：作废中奖记录
    """
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsStaffAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=404)

        serializer = AdminStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if user_prize.status in ['redeemed', 'cancelled', 'expired']:
            return Response({'detail': '当前状态不能作废'}, status=400)

        old_status = user_prize.status
        user_prize.status = 'cancelled'
        user_prize.handled_by = request.user
        user_prize.admin_remark = serializer.validated_data.get('admin_remark', user_prize.admin_remark)
        user_prize.save(update_fields=['status', 'handled_by', 'admin_remark', 'updated_at'])

        UserPrizeLog.objects.create(
            user_prize=user_prize,
            action='cancel',
            operator_staff=request.user,
            old_status=old_status,
            new_status='cancelled',
            note=serializer.validated_data.get('note', '管理员作废中奖记录')
        )

        return Response({'message': '已作废'})


# =========================
# 用户接口
# =========================

class UserPrizeListView(generics.ListAPIView):
    """
    用户：我的中奖记录列表
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUserClient]
    serializer_class = UserPrizeListSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'prize_snapshot_type']
    search_fields = ['exchange_code', 'prize_snapshot_name', 'title']
    ordering_fields = ['id', 'issued_at', 'valid_end_time', 'claimed_at', 'redeemed_at']
    ordering = ['-id']

    def get_queryset(self):
        queryset = UserPrize.objects.filter(user=self.request.user).order_by('-id')
        for item in queryset[:50]:
            item.mark_expired_if_needed()
        return queryset


class UserPrizeDetailView(generics.RetrieveAPIView):
    """
    用户：中奖记录详情
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUserClient]
    serializer_class = UserPrizeSerializer

    def get_queryset(self):
        return UserPrize.objects.filter(user=self.request.user).select_related(
            'prize', 'address'
        ).prefetch_related('logs')

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.mark_expired_if_needed()

        if not instance.read_at:
            instance.read_at = timezone.now()
            instance.save(update_fields=['read_at', 'updated_at'])
            UserPrizeLog.objects.create(
                user_prize=instance,
                action='read',
                old_status=instance.status,
                new_status=instance.status,
                note='用户查看中奖详情'
            )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class UserPrizeClaimView(APIView):
    """
    用户：申请兑奖
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUserClient]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk, user=request.user)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=404)

        user_prize.mark_expired_if_needed()
        if user_prize.status == 'expired':
            return Response({'detail': '该奖品已过期'}, status=400)

        serializer = UserPrizeClaimSerializer(
            data=request.data,
            context={'request': request, 'user_prize': user_prize}
        )
        serializer.is_valid(raise_exception=True)

        old_status = user_prize.status
        user_prize.contact_name = serializer.validated_data.get('contact_name', '')
        user_prize.contact_phone = serializer.validated_data.get('contact_phone', '')
        user_prize.user_remark = serializer.validated_data.get('user_remark', '')
        user_prize.claimed_at = timezone.now()
        user_prize.status = 'claimed'

        address = serializer.validated_data.get('address')
        if address:
            user_prize.address = address
            user_prize.set_address_snapshot(address)

        user_prize.save()

        UserPrizeLog.objects.create(
            user_prize=user_prize,
            action='claim',
            old_status=old_status,
            new_status='claimed',
            note='用户申请兑奖'
        )

        return Response({'message': '兑奖申请已提交'})


class UserPrizeMarkReadView(APIView):
    """
    用户：手动标记已读
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUserClient]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk, user=request.user)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=404)

        if not user_prize.read_at:
            user_prize.read_at = timezone.now()
            user_prize.save(update_fields=['read_at', 'updated_at'])
            UserPrizeLog.objects.create(
                user_prize=user_prize,
                action='read',
                old_status=user_prize.status,
                new_status=user_prize.status,
                note='用户手动标记已读'
            )

        return Response({'message': '已标记已读'})

