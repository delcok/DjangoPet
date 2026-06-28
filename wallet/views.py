# -*- coding: utf-8 -*-
"""
钱包模块视图
分三个域:用户端 / 商户端 / 管理端

⚠️ 币种约束:
  - 用户钱包:只能操作 积分(points) / 金币(gold)
  - 商户钱包:只能操作 现金(cash) / 金币(gold)
  serializer 层已限定 choices,view 层根据 currency 分发到不同模型方法。
"""
import logging
import uuid
from decimal import Decimal
from datetime import timedelta

from django.db import transaction, IntegrityError
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

# 认证 & 权限(用你现有的)
from utils.authentication import (
    UserAuthentication, MerchantOrSubAuthentication, ManagerAuthentication,
)
from utils.permission import (
    IsAuthenticated, IsActiveUser, IsMerchant, IsManager, HasModuleAccess,
)

from .models import (
    UserWallet, WalletTransaction, WalletStatusLog,
    MerchantWallet, MerchantWalletTransaction,
    WithdrawalRequest, MerchantSettlementConfig,
    Currency,
)
from . import serializers as sz

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
#                        公共工具
# ════════════════════════════════════════════════════════════════

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _get_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _get_merchant_id_from_user(user):
    """从商户端 request.user 提取 merchant_id(主账号/子账号通用)"""
    from merchants.models import Merchant, MerchantSubAccount
    if isinstance(user, Merchant):
        return user.id
    if isinstance(user, MerchantSubAccount):
        return user.merchant_id
    return None


def _gen_withdraw_no():
    """提现单号:WD + 14位时间 + 6位随机"""
    return f"WD{timezone.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


def _gen_idempotent_key(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def _error(msg, code=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': str(msg)}, status=code)


# ════════════════════════════════════════════════════════════════
#                        用户端视图
# ════════════════════════════════════════════════════════════════

class UserWalletView(APIView):
    """GET /api/wallet/me/ 当前用户钱包"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        wallet, _ = UserWallet.objects.get_or_create(user=request.user)
        return Response(sz.UserWalletSerializer(wallet).data)


class UserWalletTransactionView(APIView):
    """GET /api/wallet/me/transactions/ 当前用户流水列表"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated, IsActiveUser]
    pagination_class = StandardPagination

    def get(self, request):
        qs = WalletTransaction.objects.filter(user_id=request.user.id)

        # 币种过滤(只允许 points/gold,挡掉 ?currency=cash 这种越权请求)
        currency = request.query_params.get('currency')
        if currency in (Currency.POINTS, Currency.GOLD):
            qs = qs.filter(currency=currency)

        action_type = request.query_params.get('action')
        if action_type:
            qs = qs.filter(action=action_type)

        start = request.query_params.get('start_date')
        end   = request.query_params.get('end_date')
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)

        qs = qs.order_by('-created_at')

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = sz.UserWalletTransactionSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)


class UserExpiringPointsView(APIView):
    """GET /api/wallet/me/expiring-points/?days=30 即将过期积分"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated, IsActiveUser]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 30))
        except ValueError:
            return _error('days 参数无效')
        days = max(1, min(days, 365))

        now = timezone.now()
        deadline = now + timedelta(days=days)

        rows = (
            WalletTransaction.objects
            .filter(
                user_id=request.user.id,
                currency=Currency.POINTS,
                status=WalletTransaction.Status.NORMAL,
                remaining_amount__gt=0,
                expire_at__isnull=False,
                expire_at__gte=now,
                expire_at__lte=deadline,
            )
            .values('expire_at')
            .annotate(amount=Sum('remaining_amount'))
            .order_by('expire_at')
        )
        return Response({'results': list(rows), 'total': sum(r['amount'] for r in rows)})


# ════════════════════════════════════════════════════════════════
#                        商户端视图
# ════════════════════════════════════════════════════════════════

class MerchantWalletView(APIView):
    """GET /api/merchant/wallet/ 当前商户钱包(含现金 + 金币)"""
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsAuthenticated, IsMerchant]

    def get(self, request):
        merchant_id = _get_merchant_id_from_user(request.user)
        if not merchant_id:
            return _error('无法识别商户身份', status.HTTP_403_FORBIDDEN)
        wallet = get_object_or_404(MerchantWallet, merchant_id=merchant_id)
        return Response(sz.MerchantWalletSerializer(wallet).data)


class MerchantWalletTransactionView(APIView):
    """GET /api/merchant/wallet/transactions/ 商户流水(支持 ?currency=cash|gold)"""
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsAuthenticated, IsMerchant]

    def get(self, request):
        merchant_id = _get_merchant_id_from_user(request.user)
        if not merchant_id:
            return _error('无法识别商户身份', status.HTTP_403_FORBIDDEN)

        qs = MerchantWalletTransaction.objects.filter(merchant_id=merchant_id)

        # 币种过滤(商户只能看现金/金币,挡掉 ?currency=points 这种越权请求)
        currency = request.query_params.get('currency')
        if currency in (Currency.CASH, Currency.GOLD):
            qs = qs.filter(currency=currency)

        action_type = request.query_params.get('action')
        if action_type:
            qs = qs.filter(action=action_type)
        order_no = request.query_params.get('order_no')
        if order_no:
            qs = qs.filter(related_order_no=order_no)
        start = request.query_params.get('start_date')
        end   = request.query_params.get('end_date')
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)

        qs = qs.order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = sz.MerchantWalletTransactionSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)


class MerchantSettlementConfigView(APIView):
    """GET /api/merchant/wallet/settlement-config/ 查看结算配置(只读)"""
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsAuthenticated, IsMerchant]

    def get(self, request):
        merchant_id = _get_merchant_id_from_user(request.user)
        config = get_object_or_404(MerchantSettlementConfig, merchant_id=merchant_id)
        return Response(sz.MerchantSettlementConfigSerializer(config).data)


class AdminMerchantSettlementConfigView(APIView):
    """管理端获取/修改商家结算配置
    GET /api/admin/wallet/merchants/<merchant_id>/settlement-config/
    PUT /api/admin/wallet/merchants/<merchant_id>/settlement-config/
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsAuthenticated, IsManager]

    def get(self, request, merchant_id):
        # 自动为没有配置的商家创建默认配置
        config, _ = MerchantSettlementConfig.objects.get_or_create(merchant_id=merchant_id)
        return Response(sz.AdminMerchantSettlementConfigSerializer(config).data)

    def put(self, request, merchant_id):
        config, _ = MerchantSettlementConfig.objects.get_or_create(merchant_id=merchant_id)
        serializer = sz.AdminMerchantSettlementConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # 返回时带上显示名称
        return Response(sz.MerchantSettlementConfigSerializer(config).data)


class MerchantWithdrawalViewSet(viewsets.ViewSet):
    """
    商户提现(只支持现金提现,金币不参与)
      POST   /api/merchant/withdrawals/          创建
      GET    /api/merchant/withdrawals/          列表
      GET    /api/merchant/withdrawals/{id}/     详情
      POST   /api/merchant/withdrawals/{id}/cancel/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsAuthenticated, IsMerchant]
    pagination_class = StandardPagination

    def _get_merchant_id(self, request):
        mid = _get_merchant_id_from_user(request.user)
        if not mid:
            raise PermissionError('无法识别商户身份')
        return mid

    def list(self, request):
        try:
            merchant_id = self._get_merchant_id(request)
        except PermissionError as e:
            return _error(e, status.HTTP_403_FORBIDDEN)

        qs = WithdrawalRequest.objects.filter(merchant_id=merchant_id)
        st = request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)

        qs = qs.order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = sz.WithdrawalRequestSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    def retrieve(self, request, pk=None):
        try:
            merchant_id = self._get_merchant_id(request)
        except PermissionError as e:
            return _error(e, status.HTTP_403_FORBIDDEN)
        obj = get_object_or_404(WithdrawalRequest, pk=pk, merchant_id=merchant_id)
        return Response(sz.WithdrawalRequestSerializer(obj).data)

    def create(self, request):
        try:
            merchant_id = self._get_merchant_id(request)
        except PermissionError as e:
            return _error(e, status.HTTP_403_FORBIDDEN)

        ser = sz.WithdrawalCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            wd = self._create_withdrawal(request, merchant_id, data)
        except ValueError as e:
            return _error(e)
        return Response(sz.WithdrawalRequestSerializer(wd).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        try:
            merchant_id = self._get_merchant_id(request)
        except PermissionError as e:
            return _error(e, status.HTTP_403_FORBIDDEN)

        obj = get_object_or_404(WithdrawalRequest, pk=pk, merchant_id=merchant_id)
        ser = sz.WithdrawalCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            obj.cancel(operator_id=getattr(request.user, 'id', None),
                       reason=ser.validated_data['reason'])
        except ValueError as e:
            return _error(e)
        return Response(sz.WithdrawalRequestSerializer(obj).data)

    # ───── 核心创建逻辑 ─────
    def _create_withdrawal(self, request, merchant_id, data):
        """
        校验 + 生成提现单(只针对现金账户)
        - 读结算配置(min / daily cap / times cap)
        - 校验可用现金余额
        - 计算手续费
        - 快照申请时余额
        注:此处只创建 PENDING 单,审核通过时才冻结余额(见 approve)
        """
        amount = Decimal(str(data['amount']))
        now = timezone.now()

        with transaction.atomic():
            wallet = MerchantWallet.objects.select_for_update().filter(merchant_id=merchant_id).first()
            if not wallet:
                raise ValueError('商户钱包不存在')

            if wallet.status == MerchantWallet.Status.FROZEN:
                raise ValueError('钱包已冻结,无法提现')
            if wallet.status == MerchantWallet.Status.SUSPENDED:
                raise ValueError('钱包已暂停提现')

            # 结算配置
            cfg = MerchantSettlementConfig.objects.filter(merchant_id=merchant_id).first()
            if cfg:
                if amount < cfg.min_withdraw_amount:
                    raise ValueError(f'提现金额不能低于 {cfg.min_withdraw_amount}')
                # 当日已提现次数/金额
                today = now.date()
                today_qs = WithdrawalRequest.objects.filter(
                    merchant_id=merchant_id,
                    created_at__date=today,
                ).exclude(status__in=[
                    WithdrawalRequest.Status.CANCELLED,
                    WithdrawalRequest.Status.REJECTED,
                ])
                if today_qs.count() >= cfg.max_withdraw_times_per_day:
                    raise ValueError(f'每日提现次数上限:{cfg.max_withdraw_times_per_day}')
                today_sum = today_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
                if today_sum + amount > cfg.max_withdraw_per_day:
                    raise ValueError(
                        f'超出每日提现金额上限 {cfg.max_withdraw_per_day},已申请 {today_sum}'
                    )
                fee = cfg.calc_withdraw_fee(amount)
            else:
                fee = Decimal('0.00')

            # wallet/views.py  —— MerchantWithdrawalViewSet._create_withdrawal 内
            # 在 "可用余额校验" 之前,加这段:

            if data['payment_channel'] == WithdrawalRequest.PaymentChannel.BANK:
                if not data.get('bank_account_no'):
                    # 前端没传卡号(已绑定卡场景),从商户档案补全
                    from merchants.models import Merchant
                    m = Merchant.objects.filter(id=merchant_id).only(
                        'bank_name', 'bank_account_name', 'bank_account_no'
                    ).first()
                    if not m or not m.bank_account_no:
                        raise ValueError('未绑定提现银行卡,请先在"提现银行卡"页面绑定')
                    data['bank_name'] = m.bank_name
                    data['bank_account_name'] = m.bank_account_name
                    data['bank_account_no'] = m.bank_account_no

            # 可用现金余额校验
            if wallet.available_balance < amount:
                raise ValueError(f'可用余额不足:{wallet.available_balance}')

            # 若设置了提现密码则校验
            if wallet.pay_password:
                pwd = (data.get('pay_password') or '').strip()
                if not pwd:
                    raise ValueError('请输入提现密码')
                from django.contrib.auth.hashers import check_password
                if not check_password(pwd, wallet.pay_password):
                    raise ValueError('提现密码错误')

            actual = amount - fee
            if actual <= 0:
                raise ValueError('扣除手续费后实际到账金额必须大于 0')

            wd = WithdrawalRequest.objects.create(
                wallet=wallet,
                merchant_id=merchant_id,
                applicant_id=getattr(request.user, 'id', None),
                applicant_name=getattr(request.user, 'name', '') or getattr(request.user, 'nickname', ''),
                withdraw_no=_gen_withdraw_no(),
                amount=amount,
                fee=fee,
                actual_amount=actual,
                balance_snapshot=wallet.balance,
                available_snapshot=wallet.available_balance,
                bank_name=data.get('bank_name', ''),
                bank_account_name=data.get('bank_account_name', ''),
                bank_account_no=data.get('bank_account_no', ''),
                alipay_account=data.get('alipay_account', ''),
                wechat_openid=data.get('wechat_openid', ''),
                payment_channel=data['payment_channel'],
                remark=data.get('remark', ''),
                ip_address=_get_client_ip(request),
                status=WithdrawalRequest.Status.PENDING,
            )
            return wd


# ════════════════════════════════════════════════════════════════
#                        管理端 - 用户钱包
# ════════════════════════════════════════════════════════════════

class AdminUserWalletViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """管理员管理用户钱包(只允许操作积分/金币)"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsAuthenticated, IsManager, HasModuleAccess]
    required_module = 'wallet'

    queryset = UserWallet.objects.select_related('user').all()
    serializer_class = sz.AdminUserWalletSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = super().get_queryset()
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        user_id = self.request.query_params.get('user_id')
        if user_id:
            qs = qs.filter(user_id=user_id)
        mobile = self.request.query_params.get('mobile')
        if mobile:
            qs = qs.filter(user__mobile__icontains=mobile)
        return qs.order_by('-updated_at')

    # ───── 调整积分/金币 ─────
    @action(detail=True, methods=['post'], url_path='adjust')
    def adjust(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminWalletAdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        currency = d['currency']
        amount   = d['amount']
        A = WalletTransaction.Action

        # 根据币种 + 正负号决定 action
        if currency == Currency.POINTS:
            action_type = A.ADMIN_GRANT if amount > 0 else A.ADMIN_DEDUCT
        else:  # GOLD
            action_type = A.GOLD_GRANT if amount > 0 else A.GOLD_DEDUCT

        ikey = _gen_idempotent_key(f'admin_adj_{request.user.id}')

        try:
            with transaction.atomic():
                tx = self._apply_user_wallet_change(
                    wallet=wallet,
                    currency=currency,
                    amount=amount,
                    action_type=action_type,
                    remark=d['remark'],
                    operator_id=request.user.id,
                    operator_ip=_get_client_ip(request),
                    idempotent_key=ikey,
                    expire_at=d.get('expire_at') if currency == Currency.POINTS else None,
                    batch_no=d.get('batch_no', ''),
                )
        except ValueError as e:
            return _error(e)

        wallet.refresh_from_db()
        return Response({
            'wallet': sz.AdminUserWalletSerializer(wallet).data,
            'transaction': sz.AdminUserWalletTransactionSerializer(tx).data,
        })

    # ───── 冻结 ─────
    @action(detail=True, methods=['post'], url_path='freeze')
    def freeze(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminWalletFreezeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        ikey = _gen_idempotent_key(f'admin_freeze_{request.user.id}')
        try:
            tx = wallet.freeze_amount(
                currency=d['currency'],
                amount=d['amount'],
                reason=d['reason'],
                operator_id=request.user.id,
                operator_role='admin',
                idempotent_key=ikey,
            )
        except ValueError as e:
            return _error(e)
        except IntegrityError:
            tx = WalletTransaction.objects.get(idempotent_key=ikey)

        wallet.refresh_from_db()
        return Response({
            'wallet': sz.AdminUserWalletSerializer(wallet).data,
            'transaction': sz.AdminUserWalletTransactionSerializer(tx).data,
        })

    # ───── 解冻 ─────
    @action(detail=True, methods=['post'], url_path='unfreeze')
    def unfreeze(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminWalletFreezeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        ikey = _gen_idempotent_key(f'admin_unfreeze_{request.user.id}')
        try:
            tx = wallet.unfreeze_amount(
                currency=d['currency'],
                amount=d['amount'],
                reason=d['reason'],
                operator_id=request.user.id,
                operator_role='admin',
                idempotent_key=ikey,
            )
        except ValueError as e:
            return _error(e)

        wallet.refresh_from_db()
        return Response({
            'wallet': sz.AdminUserWalletSerializer(wallet).data,
            'transaction': sz.AdminUserWalletTransactionSerializer(tx).data,
        })

    # ───── 修改钱包状态 ─────
    @action(detail=True, methods=['post'], url_path='change-status')
    def change_status(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminWalletStatusChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        if wallet.status == d['status']:
            return _error('状态未变化')

        with transaction.atomic():
            old = wallet.status
            wallet.status = d['status']
            wallet.status_reason = d['reason']
            wallet.save(update_fields=['status', 'status_reason', 'updated_at'])
            WalletStatusLog.objects.create(
                wallet=wallet,
                old_status=old,
                new_status=d['status'],
                reason=d['reason'],
                operator_id=request.user.id,
                operator_role='admin',
                operator_ip=_get_client_ip(request),
            )
        return Response(sz.AdminUserWalletSerializer(wallet).data)

    # ───── 查看该钱包的流水 ─────
    @action(detail=True, methods=['get'], url_path='transactions')
    def transactions(self, request, pk=None):
        wallet = self.get_object()
        qs = WalletTransaction.objects.filter(wallet=wallet)

        currency = request.query_params.get('currency')
        if currency in (Currency.POINTS, Currency.GOLD):
            qs = qs.filter(currency=currency)
        action_type = request.query_params.get('action')
        if action_type:
            qs = qs.filter(action=action_type)
        st = request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        start = request.query_params.get('start_date')
        end   = request.query_params.get('end_date')
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)

        qs = qs.order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = sz.AdminUserWalletTransactionSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    # ───── 查看状态变更日志 ─────
    @action(detail=True, methods=['get'], url_path='status-logs')
    def status_logs(self, request, pk=None):
        wallet = self.get_object()
        qs = wallet.status_logs.order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = sz.WalletStatusLogSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    # ───── 辅助:统一走状态校验 + 方向校验(Service 层该做的事)─────
    @staticmethod
    def _apply_user_wallet_change(wallet, currency, amount, action_type,
                                  remark, operator_id, operator_ip,
                                  idempotent_key, expire_at=None, batch_no=''):
        """
        复用模型上的 change_points/change_gold 方法。
        模型方法会做状态/方向/余额校验。
        """
        kwargs = dict(
            action=action_type,
            operator_id=operator_id,
            operator_role='admin',
            operator_ip=operator_ip,
            idempotent_key=idempotent_key,
            remark=remark,
            batch_no=batch_no,
        )
        # 幂等键预检
        existing = WalletTransaction.objects.filter(idempotent_key=idempotent_key).first()
        if existing:
            return existing

        if currency == Currency.POINTS:
            return wallet.change_points(amount=amount, expire_at=expire_at, **kwargs)
        else:
            return wallet.change_gold(amount=amount, **kwargs)


class AdminUserWalletTransactionReverseView(APIView):
    """POST /api/admin/wallet/user-wallet-transactions/<id>/reverse/ 撤销一笔用户流水"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsAuthenticated, IsManager, HasModuleAccess]
    required_module = 'wallet'

    def post(self, request, pk):
        tx = get_object_or_404(WalletTransaction, pk=pk)
        ser = sz.AdminTransactionReverseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        wallet = tx.wallet
        try:
            reverse_tx = wallet.reverse_transaction(
                tx,
                reason=ser.validated_data['reason'],
                operator_id=request.user.id,
                operator_role='admin',
            )
        except ValueError as e:
            return _error(e)
        return Response(sz.AdminUserWalletTransactionSerializer(reverse_tx).data,
                        status=status.HTTP_201_CREATED)


# ════════════════════════════════════════════════════════════════
#                        管理端 - 商户钱包(支持现金 + 金币)
# ════════════════════════════════════════════════════════════════

class AdminMerchantWalletViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """管理员管理商户钱包(支持现金 + 金币两种币种)"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsAuthenticated, IsManager, HasModuleAccess]
    required_module = 'wallet'

    queryset = MerchantWallet.objects.select_related('merchant').all()
    serializer_class = sz.AdminMerchantWalletSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = super().get_queryset()
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        mid = self.request.query_params.get('merchant_id')
        if mid:
            qs = qs.filter(merchant_id=mid)
        name = self.request.query_params.get('merchant_name')
        if name:
            qs = qs.filter(merchant__name__icontains=name)
        return qs.order_by('-updated_at')

    # ───── 调整(现金 / 金币)─────
    @action(detail=True, methods=['post'], url_path='adjust')
    def adjust(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminMerchantAdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        A = MerchantWalletTransaction.Action
        ikey = _gen_idempotent_key(f'adm_mw_adj_{request.user.id}')

        existing = MerchantWalletTransaction.objects.filter(idempotent_key=ikey).first()
        if existing:
            tx = existing
        else:
            try:
                if d['currency'] == Currency.CASH:
                    # 现金:正数=ADJUSTMENT_ADD,负数=ADJUSTMENT_SUB
                    action_type = A.ADJUSTMENT_ADD if d['amount'] > 0 else A.ADJUSTMENT_SUB
                    tx = wallet.change_balance(
                        amount=d['amount'],
                        action=action_type,
                        operator_id=request.user.id,
                        operator_role='admin',
                        operator_ip=_get_client_ip(request),
                        remark=d['remark'],
                        idempotent_key=ikey,
                        batch_no=d.get('batch_no', ''),
                    )
                else:
                    # 金币:正数=GOLD_ADJUST_ADD,负数=GOLD_ADJUST_SUB
                    action_type = A.GOLD_ADJUST_ADD if d['amount'] > 0 else A.GOLD_ADJUST_SUB
                    tx = wallet.change_gold(
                        amount=int(d['amount']),
                        action=action_type,
                        operator_id=request.user.id,
                        operator_role='admin',
                        operator_ip=_get_client_ip(request),
                        remark=d['remark'],
                        idempotent_key=ikey,
                        batch_no=d.get('batch_no', ''),
                    )
            except ValueError as e:
                return _error(e)

        wallet.refresh_from_db()
        return Response({
            'wallet': sz.AdminMerchantWalletSerializer(wallet).data,
            'transaction': sz.AdminMerchantWalletTransactionSerializer(tx).data,
        })

    # ───── 冻结(现金 / 金币)─────
    @action(detail=True, methods=['post'], url_path='freeze')
    def freeze(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminMerchantFreezeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        ikey = _gen_idempotent_key(f'adm_mw_freeze_{request.user.id}')
        try:
            if d['currency'] == Currency.CASH:
                tx = wallet.freeze(
                    amount=d['amount'], reason=d['reason'],
                    operator_id=request.user.id, operator_role='admin',
                    idempotent_key=ikey,
                )
            else:
                tx = wallet.freeze_gold(
                    amount=int(d['amount']), reason=d['reason'],
                    operator_id=request.user.id, operator_role='admin',
                    idempotent_key=ikey,
                )
        except ValueError as e:
            return _error(e)

        wallet.refresh_from_db()
        return Response({
            'wallet': sz.AdminMerchantWalletSerializer(wallet).data,
            'transaction': sz.AdminMerchantWalletTransactionSerializer(tx).data,
        })

    # ───── 解冻(现金 / 金币)─────
    @action(detail=True, methods=['post'], url_path='unfreeze')
    def unfreeze(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminMerchantFreezeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        ikey = _gen_idempotent_key(f'adm_mw_unfreeze_{request.user.id}')
        try:
            if d['currency'] == Currency.CASH:
                tx = wallet.unfreeze(
                    amount=d['amount'], reason=d['reason'],
                    operator_id=request.user.id, operator_role='admin',
                    idempotent_key=ikey,
                )
            else:
                tx = wallet.unfreeze_gold(
                    amount=int(d['amount']), reason=d['reason'],
                    operator_id=request.user.id, operator_role='admin',
                    idempotent_key=ikey,
                )
        except ValueError as e:
            return _error(e)

        wallet.refresh_from_db()
        return Response({
            'wallet': sz.AdminMerchantWalletSerializer(wallet).data,
            'transaction': sz.AdminMerchantWalletTransactionSerializer(tx).data,
        })

    # ───── 修改钱包状态 ─────
    @action(detail=True, methods=['post'], url_path='change-status')
    def change_status(self, request, pk=None):
        wallet = self.get_object()
        ser = sz.AdminMerchantStatusChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        if wallet.status == d['status']:
            return _error('状态未变化')

        wallet.status = d['status']
        wallet.status_reason = d['reason']
        wallet.save(update_fields=['status', 'status_reason', 'updated_at'])
        return Response(sz.AdminMerchantWalletSerializer(wallet).data)

    # ───── 查看该钱包的流水(支持 ?currency=cash|gold)─────
    @action(detail=True, methods=['get'], url_path='transactions')
    def transactions(self, request, pk=None):
        wallet = self.get_object()
        qs = MerchantWalletTransaction.objects.filter(wallet=wallet)

        currency = request.query_params.get('currency')
        if currency in (Currency.CASH, Currency.GOLD):
            qs = qs.filter(currency=currency)

        action_type = request.query_params.get('action')
        if action_type:
            qs = qs.filter(action=action_type)
        st = request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        order_no = request.query_params.get('order_no')
        if order_no:
            qs = qs.filter(related_order_no=order_no)

        qs = qs.order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = sz.AdminMerchantWalletTransactionSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)


# ════════════════════════════════════════════════════════════════
#                        管理端 - 提现审核
# ════════════════════════════════════════════════════════════════

class AdminWithdrawalViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsAuthenticated, IsManager, HasModuleAccess]
    required_module = 'wallet'

    queryset = WithdrawalRequest.objects.select_related('merchant', 'wallet').all()
    serializer_class = sz.AdminWithdrawalSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = super().get_queryset()
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        mid = self.request.query_params.get('merchant_id')
        if mid:
            qs = qs.filter(merchant_id=mid)
        risk = self.request.query_params.get('risk_level')
        if risk:
            qs = qs.filter(risk_level=risk)
        wd_no = self.request.query_params.get('withdraw_no')
        if wd_no:
            qs = qs.filter(withdraw_no=wd_no)
        start = self.request.query_params.get('start_date')
        end   = self.request.query_params.get('end_date')
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)
        return qs.order_by('-created_at')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        wd = self.get_object()
        ser = sz.AdminWithdrawalApproveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            wd.approve(
                reviewer_id=request.user.id,
                reviewer_name=getattr(request.user, 'name', '') or getattr(request.user, 'username', ''),
                admin_remark=ser.validated_data.get('admin_remark', ''),
            )
        except ValueError as e:
            return _error(e)
        return Response(sz.AdminWithdrawalSerializer(wd).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        wd = self.get_object()
        ser = sz.AdminWithdrawalRejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            wd.reject(
                reviewer_id=request.user.id,
                reason=d['reason'],
                reviewer_name=getattr(request.user, 'name', '') or getattr(request.user, 'username', ''),
                admin_remark=d.get('admin_remark', ''),
            )
        except ValueError as e:
            return _error(e)
        return Response(sz.AdminWithdrawalSerializer(wd).data)

    @action(detail=True, methods=['post'], url_path='mark-processing')
    def mark_processing(self, request, pk=None):
        wd = self.get_object()
        ser = sz.AdminWithdrawalProcessingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            wd.mark_processing(payment_channel=ser.validated_data.get('payment_channel', ''))
        except ValueError as e:
            return _error(e)
        return Response(sz.AdminWithdrawalSerializer(wd).data)

    @action(detail=True, methods=['post'], url_path='mark-success')
    def mark_success(self, request, pk=None):
        wd = self.get_object()
        ser = sz.AdminWithdrawalSuccessSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            wd.mark_success(
                transfer_no=d['transfer_no'],
                channel_response=d.get('channel_response'),
            )
        except ValueError as e:
            return _error(e)
        return Response(sz.AdminWithdrawalSerializer(wd).data)

    @action(detail=True, methods=['post'], url_path='mark-failed')
    def mark_failed(self, request, pk=None):
        wd = self.get_object()
        ser = sz.AdminWithdrawalFailedSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            wd.mark_failed(
                reason=d['reason'],
                channel_response=d.get('channel_response'),
            )
        except ValueError as e:
            return _error(e)
        return Response(sz.AdminWithdrawalSerializer(wd).data)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        wd = self.get_object()
        try:
            wd.retry(operator_id=request.user.id)
        except ValueError as e:
            return _error(e)
        return Response(sz.AdminWithdrawalSerializer(wd).data)