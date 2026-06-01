# -*- coding: utf-8 -*-

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework import status, generics, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from managers.models import Manager
from merchants.models import Merchant, MerchantSubAccount

from utils.authentication import (
    UserAuthentication,
    ManagerAuthentication,
    MerchantOrSubAuthentication,
)
from utils.permission import (
    IsActiveUser,
    IsManager,
    IsActiveMerchant,
)

from .models import Prize, UserPrize, UserPrizeLog
from .serializers import (
    AdminPrizeSerializer,
    MerchantPrizeSerializer,
    PrizeListSerializer,
    UserPrizeSerializer,
    UserPrizeListSerializer,
    AdminIssuePrizeSerializer,
    AdminBatchIssuePrizeSerializer,
    MerchantIssuePrizeSerializer,
    MerchantBatchIssuePrizeSerializer,
    AdminStatusUpdateSerializer,
    MerchantStatusUpdateSerializer,
    UserPrizeClaimSerializer,
)


def get_merchant_from_user(user):
    """
    从 Merchant / MerchantSubAccount 中提取商户主账号对象
    """

    if isinstance(user, Merchant):
        return user

    if isinstance(user, MerchantSubAccount):
        if hasattr(user, '_merchant'):
            return user._merchant
        return user.merchant

    if hasattr(user, '_merchant'):
        return user._merchant

    return None


def get_operator_name(user):
    if not user:
        return '系统'

    return (
        getattr(user, 'username', None)
        or getattr(user, 'name', None)
        or getattr(user, 'company_name', None)
        or getattr(user, 'shop_name', None)
        or str(user)
    )


def create_prize_log(
    user_prize,
    action,
    request_user=None,
    old_status='',
    new_status='',
    note=''
):
    kwargs = {
        'user_prize': user_prize,
        'action': action,
        'old_status': old_status or '',
        'new_status': new_status or '',
        'note': note or '',
    }

    if isinstance(request_user, Manager):
        kwargs.update({
            'operator_type': 'manager',
            'operator_manager': request_user,
            'operator_name': get_operator_name(request_user),
        })
    else:
        merchant = get_merchant_from_user(request_user)
        if merchant:
            kwargs.update({
                'operator_type': 'merchant',
                'operator_merchant': merchant,
                'operator_name': get_operator_name(request_user),
            })
        elif request_user:
            kwargs.update({
                'operator_type': 'user',
                'operator_name': get_operator_name(request_user),
            })
        else:
            kwargs.update({
                'operator_type': 'system',
                'operator_name': '系统',
            })

    return UserPrizeLog.objects.create(**kwargs)


def calc_valid_time(prize, valid_start_time=None, valid_end_time=None):
    final_start = valid_start_time if valid_start_time is not None else prize.start_time
    final_end = valid_end_time

    if final_end is None:
        if prize.end_time:
            final_end = prize.end_time
        elif prize.valid_days:
            final_end = timezone.now() + timezone.timedelta(days=prize.valid_days)

    return final_start, final_end


def set_issue_operator(user_prize, request_user):
    if isinstance(request_user, Manager):
        user_prize.issued_by_manager = request_user
        return

    merchant = get_merchant_from_user(request_user)
    if merchant:
        user_prize.issued_by_merchant = merchant


def set_handle_operator(user_prize, request_user):
    if isinstance(request_user, Manager):
        user_prize.handled_by_manager = request_user
        return

    merchant = get_merchant_from_user(request_user)
    if merchant:
        user_prize.handled_by_merchant = merchant


def change_user_prize_status(
    request,
    user_prize,
    serializer_class,
    new_status,
    allowed_statuses,
    action,
    default_note,
    expired_error_message
):
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)

    user_prize.mark_expired_if_needed()

    if user_prize.status == 'expired':
        return Response(
            {'detail': expired_error_message},
            status=status.HTTP_400_BAD_REQUEST
        )

    if user_prize.status not in allowed_statuses:
        return Response(
            {'detail': '当前状态不能执行该操作'},
            status=status.HTTP_400_BAD_REQUEST
        )

    old_status = user_prize.status
    user_prize.status = new_status
    set_handle_operator(user_prize, request.user)

    if new_status == 'redeemed':
        user_prize.redeemed_at = timezone.now()

    admin_remark = serializer.validated_data.get('admin_remark', '')
    if admin_remark:
        user_prize.admin_remark = admin_remark

    user_prize.save()

    create_prize_log(
        user_prize=user_prize,
        action=action,
        request_user=request.user,
        old_status=old_status,
        new_status=new_status,
        note=serializer.validated_data.get('note') or default_note
    )

    return Response({'message': default_note}, status=status.HTTP_200_OK)


# =========================
# 管理员接口
# =========================

class AdminPrizeListCreateView(generics.ListCreateAPIView):
    """
    管理员：奖品模板列表、创建

    说明：
    - 不传 merchant_id：创建平台奖品
    - 传 merchant_id：创建指定商户的商户奖品
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    queryset = Prize.objects.select_related(
        'merchant',
        'created_by_manager',
        'updated_by_manager',
        'created_by_merchant',
        'updated_by_merchant',
    ).all().order_by('-id')

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['owner_type', 'merchant', 'prize_type', 'status', 'need_address', 'need_appointment']
    search_fields = ['name', 'title', 'content', 'redeem_contact', 'redeem_phone']
    ordering_fields = ['id', 'sort', 'created_at', 'updated_at']
    ordering = ['-id']

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return PrizeListSerializer
        return AdminPrizeSerializer

    def perform_create(self, serializer):
        serializer.save(
            created_by_manager=self.request.user,
            updated_by_manager=self.request.user
        )


class AdminPrizeDetailView(generics.RetrieveUpdateAPIView):
    """
    管理员：奖品模板详情、修改
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    queryset = Prize.objects.select_related(
        'merchant',
        'created_by_manager',
        'updated_by_manager',
        'created_by_merchant',
        'updated_by_merchant',
    ).all()

    serializer_class = AdminPrizeSerializer

    def perform_update(self, serializer):
        serializer.save(updated_by_manager=self.request.user)


class AdminIssuePrizeView(APIView):
    """
    管理员：单个发奖
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

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

        user_prize = UserPrize(
            user=user,
            prize=prize,
            merchant=prize.merchant,
            source=source,
            valid_start_time=final_start,
            valid_end_time=final_end,
            admin_remark=admin_remark,
        )
        set_issue_operator(user_prize, request.user)
        user_prize.save()

        create_prize_log(
            user_prize=user_prize,
            action='issue',
            request_user=request.user,
            old_status='',
            new_status='pending',
            note='管理员手动发放奖品'
        )

        return Response(
            {
                'message': '发放成功',
                'id': user_prize.id,
                'exchange_code': user_prize.exchange_code,
            },
            status=status.HTTP_201_CREATED
        )


class AdminBatchIssuePrizeView(APIView):
    """
    管理员：批量发奖
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

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
            user_prize = UserPrize(
                user=user,
                prize=prize,
                merchant=prize.merchant,
                source=source,
                batch_no=batch_no,
                valid_start_time=final_start,
                valid_end_time=final_end,
                admin_remark=admin_remark,
            )
            set_issue_operator(user_prize, request.user)
            user_prize.save()
            created_ids.append(user_prize.id)

            create_prize_log(
                user_prize=user_prize,
                action='issue',
                request_user=request.user,
                old_status='',
                new_status='pending',
                note=f'管理员批量发放奖品，批次号: {batch_no}'
            )

        return Response(
            {
                'message': '批量发放成功',
                'batch_no': batch_no,
                'count': len(created_ids),
                'ids': created_ids,
            },
            status=status.HTTP_201_CREATED
        )


class AdminUserPrizeListView(generics.ListAPIView):
    """
    管理员：中奖记录列表
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    serializer_class = UserPrizeListSerializer

    queryset = UserPrize.objects.select_related(
        'user',
        'prize',
        'merchant',
        'issued_by_manager',
        'handled_by_manager',
        'issued_by_merchant',
        'handled_by_merchant',
    ).all().order_by('-id')

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'source', 'merchant', 'prize', 'prize_snapshot_type', 'batch_no']
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
                Q(exchange_code__icontains=keyword)
                | Q(prize_snapshot_name__icontains=keyword)
                | Q(title__icontains=keyword)
                | Q(user__username__icontains=keyword)
                | Q(user__phone__icontains=keyword)
                | Q(batch_no__icontains=keyword)
            )

        return queryset


class AdminUserPrizeDetailView(generics.RetrieveAPIView):
    """
    管理员：中奖记录详情
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    queryset = UserPrize.objects.select_related(
        'user',
        'prize',
        'merchant',
        'address',
        'issued_by_manager',
        'handled_by_manager',
        'issued_by_merchant',
        'handled_by_merchant',
    ).prefetch_related('logs')

    serializer_class = UserPrizeSerializer


class AdminUserPrizeProcessView(APIView):
    """
    管理员：标记处理中
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=AdminStatusUpdateSerializer,
            new_status='processing',
            allowed_statuses=['pending', 'claimed', 'rejected'],
            action='process',
            default_note='已标记为处理中',
            expired_error_message='奖品已过期，不能处理'
        )


class AdminUserPrizeRedeemView(APIView):
    """
    管理员：标记已兑奖
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=AdminStatusUpdateSerializer,
            new_status='redeemed',
            allowed_statuses=['pending', 'claimed', 'processing'],
            action='redeem',
            default_note='已标记为已兑奖',
            expired_error_message='奖品已过期，不能兑奖'
        )


class AdminUserPrizeRejectView(APIView):
    """
    管理员：驳回兑奖申请
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=AdminStatusUpdateSerializer,
            new_status='rejected',
            allowed_statuses=['claimed', 'processing'],
            action='reject',
            default_note='已驳回',
            expired_error_message='奖品已过期，不能驳回'
        )


class AdminUserPrizeCancelView(APIView):
    """
    管理员：作废中奖记录
    """

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        if user_prize.status in ['redeemed', 'cancelled', 'expired']:
            return Response({'detail': '当前状态不能作废'}, status=status.HTTP_400_BAD_REQUEST)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=AdminStatusUpdateSerializer,
            new_status='cancelled',
            allowed_statuses=['pending', 'claimed', 'processing', 'rejected'],
            action='cancel',
            default_note='已作废',
            expired_error_message='奖品已过期，不能作废'
        )


# =========================
# 商户端接口
# =========================

class MerchantPrizeListCreateView(generics.ListCreateAPIView):
    """
    商户：奖品模板列表、创建
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['prize_type', 'status', 'need_address', 'need_appointment']
    search_fields = ['name', 'title', 'content', 'redeem_contact', 'redeem_phone']
    ordering_fields = ['id', 'sort', 'created_at', 'updated_at']
    ordering = ['-id']

    def get_queryset(self):
        merchant = get_merchant_from_user(self.request.user)
        return Prize.objects.filter(
            owner_type='merchant',
            merchant=merchant
        ).select_related('merchant').order_by('-id')

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return PrizeListSerializer
        return MerchantPrizeSerializer

    def perform_create(self, serializer):
        merchant = get_merchant_from_user(self.request.user)
        serializer.save(
            owner_type='merchant',
            merchant=merchant,
            created_by_merchant=merchant,
            updated_by_merchant=merchant,
        )


class MerchantPrizeDetailView(generics.RetrieveUpdateAPIView):
    """
    商户：奖品模板详情、修改
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]
    serializer_class = MerchantPrizeSerializer

    def get_queryset(self):
        merchant = get_merchant_from_user(self.request.user)
        return Prize.objects.filter(
            owner_type='merchant',
            merchant=merchant
        ).select_related('merchant')

    def perform_update(self, serializer):
        merchant = get_merchant_from_user(self.request.user)
        serializer.save(
            owner_type='merchant',
            merchant=merchant,
            updated_by_merchant=merchant,
        )


class MerchantIssuePrizeView(APIView):
    """
    商户：单个发奖
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    @transaction.atomic
    def post(self, request):
        merchant = get_merchant_from_user(request.user)

        serializer = MerchantIssuePrizeSerializer(
            data=request.data,
            context={'merchant': merchant}
        )
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        prize = serializer.validated_data['prize']
        source = serializer.validated_data.get('source', 'manual')
        admin_remark = serializer.validated_data.get('admin_remark', '')
        input_valid_start = serializer.validated_data.get('valid_start_time')
        input_valid_end = serializer.validated_data.get('valid_end_time')

        final_start, final_end = calc_valid_time(prize, input_valid_start, input_valid_end)

        user_prize = UserPrize(
            user=user,
            prize=prize,
            merchant=merchant,
            source=source,
            valid_start_time=final_start,
            valid_end_time=final_end,
            admin_remark=admin_remark,
        )
        set_issue_operator(user_prize, request.user)
        user_prize.save()

        create_prize_log(
            user_prize=user_prize,
            action='issue',
            request_user=request.user,
            old_status='',
            new_status='pending',
            note='商户手动发放奖品'
        )

        return Response(
            {
                'message': '发放成功',
                'id': user_prize.id,
                'exchange_code': user_prize.exchange_code,
            },
            status=status.HTTP_201_CREATED
        )


class MerchantBatchIssuePrizeView(APIView):
    """
    商户：批量发奖
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    @transaction.atomic
    def post(self, request):
        merchant = get_merchant_from_user(request.user)

        serializer = MerchantBatchIssuePrizeSerializer(
            data=request.data,
            context={'merchant': merchant}
        )
        serializer.is_valid(raise_exception=True)

        users = serializer.validated_data['users']
        prize = serializer.validated_data['prize']
        source = serializer.validated_data.get('source', 'manual')
        admin_remark = serializer.validated_data.get('admin_remark', '')
        batch_no = serializer.validated_data.get('batch_no') or timezone.now().strftime('MBATCH%Y%m%d%H%M%S')
        input_valid_start = serializer.validated_data.get('valid_start_time')
        input_valid_end = serializer.validated_data.get('valid_end_time')

        final_start, final_end = calc_valid_time(prize, input_valid_start, input_valid_end)

        created_ids = []

        for user in users:
            user_prize = UserPrize(
                user=user,
                prize=prize,
                merchant=merchant,
                source=source,
                batch_no=batch_no,
                valid_start_time=final_start,
                valid_end_time=final_end,
                admin_remark=admin_remark,
            )
            set_issue_operator(user_prize, request.user)
            user_prize.save()
            created_ids.append(user_prize.id)

            create_prize_log(
                user_prize=user_prize,
                action='issue',
                request_user=request.user,
                old_status='',
                new_status='pending',
                note=f'商户批量发放奖品，批次号: {batch_no}'
            )

        return Response(
            {
                'message': '批量发放成功',
                'batch_no': batch_no,
                'count': len(created_ids),
                'ids': created_ids,
            },
            status=status.HTTP_201_CREATED
        )


class MerchantUserPrizeListView(generics.ListAPIView):
    """
    商户：中奖记录列表
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    serializer_class = UserPrizeListSerializer

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'source', 'prize', 'prize_snapshot_type', 'batch_no']
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
        merchant = get_merchant_from_user(self.request.user)

        queryset = UserPrize.objects.filter(
            merchant=merchant
        ).select_related(
            'user',
            'prize',
            'merchant',
            'issued_by_manager',
            'handled_by_manager',
            'issued_by_merchant',
            'handled_by_merchant',
        ).order_by('-id')

        keyword = self.request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(
                Q(exchange_code__icontains=keyword)
                | Q(prize_snapshot_name__icontains=keyword)
                | Q(title__icontains=keyword)
                | Q(user__username__icontains=keyword)
                | Q(user__phone__icontains=keyword)
                | Q(batch_no__icontains=keyword)
            )

        return queryset


class MerchantUserPrizeDetailView(generics.RetrieveAPIView):
    """
    商户：中奖记录详情
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    serializer_class = UserPrizeSerializer

    def get_queryset(self):
        merchant = get_merchant_from_user(self.request.user)

        return UserPrize.objects.filter(
            merchant=merchant
        ).select_related(
            'user',
            'prize',
            'merchant',
            'address',
            'issued_by_manager',
            'handled_by_manager',
            'issued_by_merchant',
            'handled_by_merchant',
        ).prefetch_related('logs')


class MerchantUserPrizeProcessView(APIView):
    """
    商户：标记处理中
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    @transaction.atomic
    def post(self, request, pk):
        merchant = get_merchant_from_user(request.user)

        try:
            user_prize = UserPrize.objects.get(pk=pk, merchant=merchant)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=MerchantStatusUpdateSerializer,
            new_status='processing',
            allowed_statuses=['pending', 'claimed', 'rejected'],
            action='process',
            default_note='已标记为处理中',
            expired_error_message='奖品已过期，不能处理'
        )


class MerchantUserPrizeRedeemView(APIView):
    """
    商户：标记已兑奖
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    @transaction.atomic
    def post(self, request, pk):
        merchant = get_merchant_from_user(request.user)

        try:
            user_prize = UserPrize.objects.get(pk=pk, merchant=merchant)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=MerchantStatusUpdateSerializer,
            new_status='redeemed',
            allowed_statuses=['pending', 'claimed', 'processing'],
            action='redeem',
            default_note='已标记为已兑奖',
            expired_error_message='奖品已过期，不能兑奖'
        )


class MerchantUserPrizeRejectView(APIView):
    """
    商户：驳回兑奖申请
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    @transaction.atomic
    def post(self, request, pk):
        merchant = get_merchant_from_user(request.user)

        try:
            user_prize = UserPrize.objects.get(pk=pk, merchant=merchant)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=MerchantStatusUpdateSerializer,
            new_status='rejected',
            allowed_statuses=['claimed', 'processing'],
            action='reject',
            default_note='已驳回',
            expired_error_message='奖品已过期，不能驳回'
        )


class MerchantUserPrizeCancelView(APIView):
    """
    商户：作废中奖记录
    """

    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsActiveMerchant]

    @transaction.atomic
    def post(self, request, pk):
        merchant = get_merchant_from_user(request.user)

        try:
            user_prize = UserPrize.objects.get(pk=pk, merchant=merchant)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        if user_prize.status in ['redeemed', 'cancelled', 'expired']:
            return Response({'detail': '当前状态不能作废'}, status=status.HTTP_400_BAD_REQUEST)

        return change_user_prize_status(
            request=request,
            user_prize=user_prize,
            serializer_class=MerchantStatusUpdateSerializer,
            new_status='cancelled',
            allowed_statuses=['pending', 'claimed', 'processing', 'rejected'],
            action='cancel',
            default_note='已作废',
            expired_error_message='奖品已过期，不能作废'
        )


# =========================
# 用户接口
# =========================

class UserPrizeListView(generics.ListAPIView):
    """
    用户：我的中奖记录列表
    """

    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]

    serializer_class = UserPrizeListSerializer

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'prize_snapshot_type', 'merchant']
    search_fields = ['exchange_code', 'prize_snapshot_name', 'title']
    ordering_fields = ['id', 'issued_at', 'valid_end_time', 'claimed_at', 'redeemed_at']
    ordering = ['-id']

    def get_queryset(self):
        queryset = UserPrize.objects.filter(
            user=self.request.user
        ).select_related(
            'prize',
            'merchant',
            'address',
        ).order_by('-id')

        for item in queryset[:50]:
            item.mark_expired_if_needed()

        return queryset


class UserPrizeDetailView(generics.RetrieveAPIView):
    """
    用户：中奖记录详情
    """

    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]

    serializer_class = UserPrizeSerializer

    def get_queryset(self):
        return UserPrize.objects.filter(
            user=self.request.user
        ).select_related(
            'prize',
            'merchant',
            'address',
        ).prefetch_related('logs')

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.mark_expired_if_needed()

        if not instance.read_at:
            instance.read_at = timezone.now()
            instance.save(update_fields=['read_at', 'updated_at'])

            create_prize_log(
                user_prize=instance,
                action='read',
                request_user=request.user,
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
    permission_classes = [IsActiveUser]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk, user=request.user)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        user_prize.mark_expired_if_needed()

        if user_prize.status == 'expired':
            return Response({'detail': '该奖品已过期'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = UserPrizeClaimSerializer(
            data=request.data,
            context={
                'request': request,
                'user_prize': user_prize,
            }
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

        create_prize_log(
            user_prize=user_prize,
            action='claim',
            request_user=request.user,
            old_status=old_status,
            new_status='claimed',
            note='用户申请兑奖'
        )

        return Response({'message': '兑奖申请已提交'}, status=status.HTTP_200_OK)


class UserPrizeMarkReadView(APIView):
    """
    用户：手动标记已读
    """

    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]

    @transaction.atomic
    def post(self, request, pk):
        try:
            user_prize = UserPrize.objects.get(pk=pk, user=request.user)
        except UserPrize.DoesNotExist:
            return Response({'detail': '记录不存在'}, status=status.HTTP_404_NOT_FOUND)

        if not user_prize.read_at:
            user_prize.read_at = timezone.now()
            user_prize.save(update_fields=['read_at', 'updated_at'])

            create_prize_log(
                user_prize=user_prize,
                action='read',
                request_user=request.user,
                old_status=user_prize.status,
                new_status=user_prize.status,
                note='用户手动标记已读'
            )

        return Response({'message': '已标记已读'}, status=status.HTTP_200_OK)