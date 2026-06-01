# -*- coding: utf-8 -*-
# promotions/views.py

import logging
from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.authentication import (
    UserAuthentication, MerchantOrSubAuthentication, ManagerAuthentication,
)
from utils.permission import IsUser, IsMerchant, IsManager

from .models import (
    PaymentActivity, MerchantActivityEnrollment,
    ActivityUserGrant, ActivityMerchantEarn,
)
from .serializers import (
    PaymentActivitySerializer,
    MerchantActivityEnrollmentSerializer,
    EnrollmentAuditSerializer,
    ActivityUserGrantSerializer,
    ActivityMerchantEarnSerializer,
    CreateRechargeSerializer,
    WalletRechargeSerializer,
)

logger = logging.getLogger(__name__)


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _merchant_id_of(user):
    """从 request.user 提取商家ID(主账号 + 子账号通用)"""
    return getattr(user, 'merchant_id', None) or getattr(user, 'id', None)


# ══════════════════════════════════════════════════════════════
# 管理端 - 活动管理
# ══════════════════════════════════════════════════════════════

class AdminPaymentActivityViewSet(viewsets.ModelViewSet):
    """
    /admin/promotions/activities/
    平台管理员管理活动 + 审批商家报名
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes     = [IsManager]
    queryset               = PaymentActivity.objects.all()
    serializer_class       = PaymentActivitySerializer
    pagination_class       = StandardPagination

    def get_queryset(self):
        qs = super().get_queryset()
        for k in ('activity_type', 'status', 'enrollment_mode'):
            v = self.request.query_params.get(k)
            if v:
                qs = qs.filter(**{k: v})
        kw = self.request.query_params.get('keyword')
        if kw:
            qs = qs.filter(name__icontains=kw)
        return qs.order_by('-created_at')

    # 报名记录管理
    @action(detail=True, methods=['get'], url_path='enrollments')
    def list_enrollments(self, request, pk=None):
        qs = MerchantActivityEnrollment.objects.filter(
            activity_id=pk,
        ).select_related('merchant').order_by('-created_at')

        st = request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = MerchantActivityEnrollmentSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    @action(detail=True, methods=['post'], url_path=r'enrollments/(?P<eid>\d+)/audit')
    def audit_enrollment(self, request, pk=None, eid=None):
        ser = EnrollmentAuditSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            enr = MerchantActivityEnrollment.objects.get(pk=eid, activity_id=pk)
        except MerchantActivityEnrollment.DoesNotExist:
            return Response({'error': '报名不存在'}, status=404)
        if enr.status != MerchantActivityEnrollment.Status.PENDING:
            return Response({'error': f'当前状态({enr.get_status_display()})不可审批'}, status=400)

        enr.status = (
            MerchantActivityEnrollment.Status.ACTIVE
            if ser.validated_data['action'] == 'approve'
            else MerchantActivityEnrollment.Status.REJECTED
        )
        enr.audit_remark = ser.validated_data.get('remark', '')
        enr.audited_by_id = request.user.id
        enr.audited_at = timezone.now()
        enr.save(update_fields=['status', 'audit_remark', 'audited_by_id', 'audited_at', 'updated_at'])
        return Response(MerchantActivityEnrollmentSerializer(enr).data)

    @action(detail=True, methods=['get'], url_path='user-grants')
    def list_user_grants(self, request, pk=None):
        qs = ActivityUserGrant.objects.filter(activity_id=pk).order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = ActivityUserGrantSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    @action(detail=True, methods=['get'], url_path='merchant-earns')
    def list_merchant_earns(self, request, pk=None):
        qs = ActivityMerchantEarn.objects.filter(
            activity_id=pk,
        ).select_related('merchant').order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = ActivityMerchantEarnSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)


# ══════════════════════════════════════════════════════════════
# 商家端 - 活动广场 + 报名
# ══════════════════════════════════════════════════════════════

class MerchantActivityViewSet(viewsets.GenericViewSet):
    """
    /merchant/promotions/activities/
      GET   available     可参加的活动
      GET   enrolled      我已报名的活动
      POST  {id}/enroll   报名
      POST  {id}/quit     退出
      GET   {id}/earns    我在此活动的入金记录
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes     = [IsMerchant]
    pagination_class       = StandardPagination

    @action(detail=False, methods=['get'])
    def available(self, request):
        qs = PaymentActivity.objects.filter(
            activity_type=PaymentActivity.ActivityType.ORDER_SPEND,
            status__in=[PaymentActivity.Status.ACTIVE, PaymentActivity.Status.PAUSED],
        ).order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = PaymentActivitySerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    @action(detail=False, methods=['get'])
    def enrolled(self, request):
        merchant_id = _merchant_id_of(request.user)
        qs = MerchantActivityEnrollment.objects.filter(
            merchant_id=merchant_id,
        ).select_related('activity').order_by('-created_at')
        st = request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = MerchantActivityEnrollmentSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        try:
            act = PaymentActivity.objects.get(pk=pk)
        except PaymentActivity.DoesNotExist:
            return Response({'error': '活动不存在'}, status=404)

        if act.activity_type != PaymentActivity.ActivityType.ORDER_SPEND:
            return Response({'error': '此活动类型不支持商家报名'}, status=400)
        if act.enrollment_mode == PaymentActivity.EnrollmentMode.ALL:
            return Response({'error': '本活动所有商家自动参加,无需报名'}, status=400)
        if act.enrollment_mode == PaymentActivity.EnrollmentMode.INVITE:
            return Response({'error': '本活动仅限平台邀请'}, status=403)
        if act.status not in (PaymentActivity.Status.ACTIVE, PaymentActivity.Status.PAUSED):
            return Response({'error': f'活动状态({act.get_status_display()})不可报名'}, status=400)

        merchant_id = _merchant_id_of(request.user)
        target_status = (
            MerchantActivityEnrollment.Status.PENDING
            if act.enrollment_audit
            else MerchantActivityEnrollment.Status.ACTIVE
        )

        with transaction.atomic():
            enr, created = MerchantActivityEnrollment.objects.get_or_create(
                activity=act, merchant_id=merchant_id,
                defaults={
                    'status': target_status,
                    'apply_remark': request.data.get('remark', ''),
                },
            )
            if not created:
                if enr.status in (MerchantActivityEnrollment.Status.ACTIVE, MerchantActivityEnrollment.Status.PENDING):
                    return Response({'error': '已在报名流程中'}, status=400)
                # REJECTED / QUIT → 重置
                enr.status = target_status
                enr.apply_remark = request.data.get('remark', '')
                enr.audit_remark = ''
                enr.audited_by_id = None
                enr.audited_at = None
                if not act.enrollment_audit:
                    enr.audited_at = timezone.now()
                enr.save(update_fields=['status', 'apply_remark', 'audit_remark', 'audited_by_id', 'audited_at', 'updated_at'])
            elif not act.enrollment_audit:
                enr.audited_at = timezone.now()
                enr.audit_remark = '免审批,自动通过'
                enr.save(update_fields=['audited_at', 'audit_remark', 'updated_at'])

        msg = '报名成功,已加入' if target_status == MerchantActivityEnrollment.Status.ACTIVE else '报名已提交,等待审批'
        return Response({
            'message': msg,
            'enrollment': MerchantActivityEnrollmentSerializer(enr).data,
        })

    @action(detail=True, methods=['post'])
    def quit(self, request, pk=None):
        merchant_id = _merchant_id_of(request.user)
        try:
            enr = MerchantActivityEnrollment.objects.get(activity_id=pk, merchant_id=merchant_id)
        except MerchantActivityEnrollment.DoesNotExist:
            return Response({'error': '未报名此活动'}, status=404)
        if enr.status not in (MerchantActivityEnrollment.Status.ACTIVE, MerchantActivityEnrollment.Status.PENDING):
            return Response({'error': '当前状态不可退出'}, status=400)
        enr.status = MerchantActivityEnrollment.Status.QUIT
        enr.save(update_fields=['status', 'updated_at'])
        return Response({'message': '已退出'})

    @action(detail=True, methods=['get'])
    def earns(self, request, pk=None):
        merchant_id = _merchant_id_of(request.user)
        qs = ActivityMerchantEarn.objects.filter(
            activity_id=pk, merchant_id=merchant_id,
        ).order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = ActivityMerchantEarnSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)


# ══════════════════════════════════════════════════════════════
# 用户端 - 充值
# ══════════════════════════════════════════════════════════════

class CreateRechargeView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def post(self, request):
        ser = CreateRechargeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        amount = ser.validated_data['amount']
        channel = ser.validated_data['channel']
        openid = ser.validated_data.get('openid', '') or getattr(request.user, 'openid', '')

        if not openid and channel == 'wechat_mini':
            return Response({'error': '当前用户未绑定微信,无法发起 JSAPI 支付'}, status=400)

        from wallet.models import WalletRecharge
        from pay.models import PaymentOrder, generate_payment_no
        from pay.views import pick_best_recharge_activity  # ★ 新增
        from utils.wechat_pay import WeChatPayHelper

        # ★ 下单时就锁定最佳活动 + 加送金币
        best_act, bonus = pick_best_recharge_activity(request.user.id, amount)

        with transaction.atomic():
            recharge = WalletRecharge.objects.create(
                user=request.user,
                amount=amount,
                face_coins=int(amount),
                bonus_coins=bonus,                       # ★ 锁定
                activity_id=best_act.id if best_act else None,  # ★ 锁定
            )
            payment_no = generate_payment_no()
            payment = PaymentOrder.objects.create(
                payment_no=payment_no,
                out_trade_no=payment_no,
                order_no=recharge.recharge_no,
                order_type='recharge',
                user_id=request.user.id,
                channel=channel,
                amount=amount,
                status='pending',
                expire_at=timezone.now() + timedelta(minutes=15),
            )

        if payment.amount_in_cents <= 0:
            return Response({'error': '充值金额不能为 0'}, status=400)

        helper = WeChatPayHelper()
        try:
            pay_params = helper.create_payment_order(
                openid=openid,
                total_fee=payment.amount_in_cents,
                body=f'充值 ¥{amount}',
                out_trade_no=payment.out_trade_no,
            )
        except Exception as e:
            logger.exception('充值调起微信失败 recharge_no=%s', recharge.recharge_no)
            payment.status = 'failed'
            payment.callback_raw = f'create error: {e}'
            payment.save(update_fields=['status', 'callback_raw', 'updated_at'])
            return Response({'error': f'调起微信支付失败: {e}'}, status=400)

        payment.pay_params = pay_params
        payment.save(update_fields=['pay_params', 'updated_at'])

        return Response({
            'recharge_no': recharge.recharge_no,
            'payment_no': payment.payment_no,
            'out_trade_no': payment.out_trade_no,
            'pay_params': pay_params,
            'bonus_preview': {                # ★ 让前端能展示
                'activity_name': best_act.name if best_act else '',
                'bonus_coins': bonus,
            },
        })

class RechargePreviewView(APIView):
    """
    GET /wallet/recharge/preview/?amount=200
    返回最优活动 + 加送金币（支持 percent 比例奖励）
    """
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]

    def get(self, request):
        try:
            amount = Decimal(str(request.query_params.get('amount', '0')))
        except Exception:
            return Response({'error': 'amount 无效'}, status=400)
        if amount <= 0:
            return Response({'error': 'amount 必须大于 0'}, status=400)

        face_coins = int(amount)
        bonus, act_name = 0, ''

        activities = PaymentActivity.objects.filter(
            activity_type=PaymentActivity.ActivityType.RECHARGE,
            status=PaymentActivity.Status.ACTIVE,
            user_reward_enabled=True,
        )
        for act in activities:
            if not act.is_runnable():
                continue
            if act.per_user_limit > 0:
                taken = ActivityUserGrant.objects.filter(
                    activity=act, user_id=request.user.id, is_revoked=False,
                ).count()
                if taken >= act.per_user_limit:
                    continue

            r = act.calc_user_reward(amount)   # 支持 FIXED / PERCENT / TIERED
            if r > bonus:
                bonus, act_name = r, act.name

        return Response({
            'amount': str(amount),
            'face_coins': face_coins,
            'bonus_coins': bonus,
            'total_coins': face_coins + bonus,
            'activity_name': act_name,
        })


class MyRechargeListView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]

    def get(self, request):
        from wallet.models import WalletRecharge
        qs = WalletRecharge.objects.filter(user=request.user).order_by('-created_at')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = WalletRechargeSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)


class UserRechargeActivitiesView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]

    def get(self, request):
        qs = PaymentActivity.objects.filter(
            activity_type=PaymentActivity.ActivityType.RECHARGE,
            status=PaymentActivity.Status.ACTIVE,
            user_reward_enabled=True,
        ).order_by('-created_at')

        runnable = [a for a in qs if a.is_runnable()]
        ser = PaymentActivitySerializer(runnable, many=True)
        return Response({'results': ser.data, 'count': len(runnable)})

# ══════════════════════════════════════════════════════════════
# 管理员 - 活动监控大盘
# ══════════════════════════════════════════════════════════════

class AdminPromotionsDashboardView(APIView):
    """
    GET /admin/promotions/dashboard/
    返回平台所有活动的运营总览数据
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes     = [IsManager]

    def get(self, request):
        from django.db.models import Sum, Count, Q
        from datetime import timedelta

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        # ─── 1. 活动整体概况 ───
        all_activities = PaymentActivity.objects.all()
        activity_overview = {
            'total':          all_activities.count(),
            'active':         all_activities.filter(status='active').count(),
            'paused':         all_activities.filter(status='paused').count(),
            'draft':          all_activities.filter(status='draft').count(),
            'ended':          all_activities.filter(status='ended').count(),
            'order_spend':    all_activities.filter(activity_type='order_spend').count(),
            'recharge':       all_activities.filter(activity_type='recharge').count(),
        }

        # ─── 2. 金币发放统计 ───
        user_grant_stats = ActivityUserGrant.objects.aggregate(
            total_count=Count('id'),
            total_coins=Sum('reward_coins'),
            today_count=Count('id', filter=Q(created_at__gte=today_start)),
            today_coins=Sum('reward_coins', filter=Q(created_at__gte=today_start)),
            week_count=Count('id', filter=Q(created_at__gte=week_start)),
            week_coins=Sum('reward_coins', filter=Q(created_at__gte=week_start)),
            revoked_count=Count('id', filter=Q(is_revoked=True)),
            revoked_coins=Sum('reward_coins', filter=Q(is_revoked=True)),
        )

        merchant_earn_stats = ActivityMerchantEarn.objects.aggregate(
            total_count=Count('id'),
            total_coins=Sum('earned_coins'),
            today_count=Count('id', filter=Q(created_at__gte=today_start)),
            today_coins=Sum('earned_coins', filter=Q(created_at__gte=today_start)),
            week_count=Count('id', filter=Q(created_at__gte=week_start)),
            week_coins=Sum('earned_coins', filter=Q(created_at__gte=week_start)),
            frozen_count=Count('id', filter=Q(frozen_status='frozen')),
            frozen_coins=Sum('earned_coins', filter=Q(frozen_status='frozen')),
            unfrozen_count=Count('id', filter=Q(frozen_status='unfrozen')),
            unfrozen_coins=Sum('earned_coins', filter=Q(frozen_status='unfrozen')),
            revoked_count=Count('id', filter=Q(frozen_status='revoked')),
            revoked_coins=Sum('earned_coins', filter=Q(frozen_status='revoked')),
        )

        # ─── 3. 商家报名统计 ───
        enrollment_stats = MerchantActivityEnrollment.objects.aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status='pending')),
            active=Count('id', filter=Q(status='active')),
            rejected=Count('id', filter=Q(status='rejected')),
            quit=Count('id', filter=Q(status='quit')),
        )

        # ─── 4. 进行中活动详细列表(带运营数据) ───
        running_activities = []
        for act in all_activities.filter(status='active').order_by('-created_at'):
            in_period = act.is_in_period()
            budget_used = (act.user_granted_coins or 0) + (act.merchant_earned_coins or 0)
            budget_pct = 0
            if act.total_budget_coins > 0:
                budget_pct = min(100, round(budget_used * 100 / act.total_budget_coins, 1))

            # 该活动的报名数
            enroll_count = MerchantActivityEnrollment.objects.filter(
                activity=act, status='active',
            ).count()
            pending_count = MerchantActivityEnrollment.objects.filter(
                activity=act, status='pending',
            ).count()

            running_activities.append({
                'id':                     act.id,
                'name':                   act.name,
                'activity_type':          act.activity_type,
                'activity_type_display':  act.get_activity_type_display(),
                'in_period':              in_period,
                'is_runnable':            act.is_runnable(),
                'start_time':             act.start_time,
                'end_time':               act.end_time,
                'enrollment_mode':        act.enrollment_mode,
                'enrollment_mode_display':act.get_enrollment_mode_display(),
                'enroll_count':           enroll_count,
                'pending_count':          pending_count,
                'user_granted_count':     act.user_granted_count or 0,
                'user_granted_coins':     act.user_granted_coins or 0,
                'merchant_earned_count':  act.merchant_earned_count or 0,
                'merchant_earned_coins':  act.merchant_earned_coins or 0,
                'total_budget_coins':     act.total_budget_coins or 0,
                'budget_used':            budget_used,
                'budget_pct':             budget_pct,
            })

        # ─── 5. 待处理报名(管理员需关注) ───
        pending_enrollments = (
            MerchantActivityEnrollment.objects
            .filter(status='pending')
            .select_related('merchant', 'activity')
            .order_by('-created_at')[:10]
        )
        pending_list = [{
            'id':            e.id,
            'activity_id':   e.activity_id,
            'activity_name': e.activity.name if e.activity else '',
            'merchant_id':   e.merchant_id,
            'merchant_name': e.merchant.name if e.merchant else '',
            'apply_remark':  e.apply_remark,
            'created_at':    e.created_at,
        } for e in pending_enrollments]

        # ─── 6. 排行:发金币最多的活动(top 5) ───
        top_user_activities = list(
            all_activities.exclude(user_granted_coins=0)
            .order_by('-user_granted_coins')[:5]
            .values('id', 'name', 'activity_type',
                    'user_granted_coins', 'user_granted_count')
        )
        top_merchant_activities = list(
            all_activities.exclude(merchant_earned_coins=0)
            .order_by('-merchant_earned_coins')[:5]
            .values('id', 'name', 'activity_type',
                    'merchant_earned_coins', 'merchant_earned_count')
        )

        # ─── 7. 最近 7 天每日发放趋势 ───
        from django.db.models.functions import TruncDate

        daily_user = (
            ActivityUserGrant.objects
            .filter(created_at__gte=week_start)
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(count=Count('id'), coins=Sum('reward_coins'))
            .order_by('date')
        )
        daily_merchant = (
            ActivityMerchantEarn.objects
            .filter(created_at__gte=week_start)
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(count=Count('id'), coins=Sum('earned_coins'))
            .order_by('date')
        )

        # 补齐 7 天日期(没数据的填 0)
        date_map_user = {d['date']: d for d in daily_user}
        date_map_merchant = {d['date']: d for d in daily_merchant}
        trend = []
        for i in range(7):
            d = (today_start - timedelta(days=6 - i)).date()
            u = date_map_user.get(d, {'count': 0, 'coins': 0})
            m = date_map_merchant.get(d, {'count': 0, 'coins': 0})
            trend.append({
                'date':           d.strftime('%m-%d'),
                'user_count':     u.get('count') or 0,
                'user_coins':     u.get('coins') or 0,
                'merchant_count': m.get('count') or 0,
                'merchant_coins': m.get('coins') or 0,
            })

        return Response({
            'activity_overview':     activity_overview,
            'user_grant_stats':      user_grant_stats,
            'merchant_earn_stats':   merchant_earn_stats,
            'enrollment_stats':      enrollment_stats,
            'running_activities':    running_activities,
            'pending_enrollments':   pending_list,
            'top_user_activities':   top_user_activities,
            'top_merchant_activities': top_merchant_activities,
            'trend_7d':              trend,
            'updated_at':            now,
        })