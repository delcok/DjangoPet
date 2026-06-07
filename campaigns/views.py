# -*- coding: utf-8 -*-
"""促销活动 - 视图"""
import logging
import secrets
import string
import time
from decimal import Decimal

import requests

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, NotFound

from utils.authentication import (
    UserAuthentication, ManagerAuthentication, MerchantOrSubAuthentication,
)
from utils.permission import IsUser, IsManager, IsMerchant
from utils.wechat_client import get_user_mini_client
from utils.oss import upload_bytes, delete_object, extract_object_key

from merchants.models import Merchant, MerchantSubAccount

from .models import Campaign, CouponTemplate, UserCoupon, RedemptionLog
from .pagination import StandardPagination
from .serializers import (
    CouponTemplateSerializer,
    CampaignListSerializer, CampaignDetailSerializer, CampaignPublicSerializer,
    UserCouponSerializer, UserCouponAdminSerializer,
    RedemptionQuerySerializer, RedemptionSerializer, RedemptionLogSerializer,
    # ★ 商户端
    MerchantCouponTemplateSerializer,
    MerchantCampaignListSerializer, MerchantCampaignDetailSerializer,
    MerchantUserCouponSerializer, MerchantRedemptionLogSerializer,
)

logger = logging.getLogger(__name__)


# ============================================================
# 内部辅助
# ============================================================
def _client_ip(request):
    """从请求中获取客户端 IP"""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _generate_wx_scene() -> str:
    """生成 32 位的小程序码 scene 参数"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(32))


def _generate_campaign_qrcode(campaign: Campaign, force: bool = False) -> str:
    """
    生成活动小程序码并上传 OSS

    Args:
        campaign: 活动对象
        force: 强制重新生成(已有则覆盖并删旧文件)

    Returns:
        OSS 可访问 URL

    说明:
        通过 wechatpy 单例 client 拿 access_token(自动 Redis 缓存),
        然后直接 requests.post 调微信接口,避免 wechatpy 旧版本签名问题。
    """
    if campaign.wx_code_image_url and not force:
        return campaign.wx_code_image_url

    client = get_user_mini_client()
    access_token = client.access_token
    if not access_token:
        raise RuntimeError('获取 access_token 失败')

    # 微信"获取不限制小程序码"接口
    url = (
        f'https://api.weixin.qq.com/wxa/getwxacodeunlimit'
        f'?access_token={access_token}'
    )
    payload = {
        'scene': campaign.wx_scene,
        'page': campaign.wx_code_page,         # 例如 'pages/campaigns/campaigns'
        'width': 430,
        'check_path': True,                   # 上线后页面已发布可改 True
        'env_version': 'release',              # release/trial/develop
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
    except Exception as e:
        raise RuntimeError(f'请求微信接口失败:{e}')

    # 成功时返回 image 二进制;失败时返回 JSON 错误
    content_type = resp.headers.get('Content-Type', '')
    if not content_type.startswith('image'):
        try:
            err = resp.json()
        except Exception:
            err = {'errmsg': resp.text[:200]}
        raise RuntimeError(
            f"微信接口返回错误 [{err.get('errcode')}]:{err.get('errmsg', '未知错误')}"
        )

    image_bytes = resp.content

    # 强制重新生成时删除旧文件
    if force and campaign.wx_code_image_url:
        old_key = extract_object_key(campaign.wx_code_image_url)
        if old_key:
            delete_object(old_key)

    timestamp = int(time.time())
    object_key = f'campaigns/qr/{campaign.id}_{campaign.wx_scene}_{timestamp}.jpg'
    oss_url = upload_bytes(image_bytes, object_key, content_type='image/jpeg')

    campaign.wx_code_image_url = oss_url
    campaign.save(update_fields=['wx_code_image_url', 'updated_at'])
    logger.info(f'活动 {campaign.id} 小程序码已生成: {oss_url}')
    return oss_url


def _get_merchant_context(request):
    """
    从商户认证中提取 (merchant_id, operator_type, operator_id, operator_name)

    operator_type ∈ {'merchant', 'merchant_sub'}
    """
    user = request.user
    if isinstance(user, Merchant):
        return (
            user.id, 'merchant', user.id,
            user.name or f'商户#{user.id}',
        )
    if isinstance(user, MerchantSubAccount):
        return (
            user.merchant_id, 'merchant_sub', user.id,
            user.name or f'子账号#{user.id}',
        )
    raise ValidationError('无法识别商户身份')


def _check_coupon_redeemable(coupon: UserCoupon):
    """
    检查券是否可核销,可核销返回 None,否则返回原因字符串
    (商户端 / 管理端 / 客户端共用)
    """
    if coupon.status == 'used':
        return f'该券已于 {coupon.used_at:%Y-%m-%d %H:%M} 核销过'
    if coupon.status == 'cancelled':
        return '该券已作废'
    if coupon.status == 'expired' or coupon.is_expired:
        return '该券已过期'
    now = timezone.now()
    if coupon.valid_from and now < coupon.valid_from:
        return f'该券尚未生效({coupon.valid_from:%Y-%m-%d %H:%M} 起生效)'
    return None


# ============================================================
# 管理端 - 券模板
# ============================================================
class CouponTemplateViewSet(viewsets.ModelViewSet):
    """券模板管理"""

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    queryset = CouponTemplate.objects.all()
    serializer_class = CouponTemplateSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        coupon_type = self.request.query_params.get('coupon_type')
        keyword = self.request.query_params.get('keyword')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('1', 'true', 'yes'))
        if coupon_type:
            qs = qs.filter(coupon_type=coupon_type)
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        return qs

    def perform_create(self, serializer):
        # 管理员创建的是平台公共模板(merchant_id=null)
        serializer.save(created_by=self.request.user)


# ============================================================
# 管理端 - 活动
# ============================================================
class CampaignAdminViewSet(viewsets.ModelViewSet):
    """活动管理(管理端)"""
    pagination_class = StandardPagination
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    queryset = Campaign.objects.select_related('coupon_template', 'created_by').all()

    def get_serializer_class(self):
        if self.action == 'list':
            return CampaignListSerializer
        return CampaignDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action != 'list':
            return qs

        status_param = self.request.query_params.get('status')
        keyword = self.request.query_params.get('keyword')
        scope = self.request.query_params.get('scope')  # platform / merchant / all
        if status_param:
            qs = qs.filter(status=status_param)
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        if scope == 'platform':
            qs = qs.filter(merchant_id__isnull=True)
        elif scope == 'merchant':
            qs = qs.filter(merchant_id__isnull=False)
        return qs

    def perform_create(self, serializer):
        # 生成唯一 wx_scene
        for _ in range(5):
            scene = _generate_wx_scene()
            if not Campaign.objects.filter(wx_scene=scene).exists():
                break
        else:
            raise ValidationError('生成 scene 失败,请重试')

        campaign = serializer.save(created_by=self.request.user, wx_scene=scene)

        # 生成小程序码(失败不阻塞活动创建,后续可手动重试)
        self._qrcode_error = None
        try:
            _generate_campaign_qrcode(campaign)
        except Exception as e:
            logger.error(f'活动 {campaign.id} 小程序码生成失败: {e}', exc_info=True)
            self._qrcode_error = str(e)

    def create(self, request, *args, **kwargs):
        # 重写以便把可能的二维码生成错误带回前端
        self._qrcode_error = None
        response = super().create(request, *args, **kwargs)
        if self._qrcode_error:
            response.data['qrcode_warning'] = (
                f'活动已创建,但小程序码生成失败:{self._qrcode_error}。'
                f'请稍后调用 regenerate-qrcode 重试。'
            )
        return response

    def perform_destroy(self, instance):
        if instance.claimed_count > 0:
            raise ValidationError('该活动已发放过券,不可删除,请改为「已结束」状态')
        # 同步删除 OSS 上的小程序码
        if instance.wx_code_image_url:
            key = extract_object_key(instance.wx_code_image_url)
            if key:
                delete_object(key)
        super().perform_destroy(instance)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """上线活动"""
        campaign = self.get_object()
        if campaign.status == 'ended':
            raise ValidationError('活动已结束,无法重新上线')
        campaign.status = 'active'
        campaign.save(update_fields=['status', 'updated_at'])
        return Response({'detail': '活动已上线', 'status': campaign.status})

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """暂停活动"""
        campaign = self.get_object()
        campaign.status = 'paused'
        campaign.save(update_fields=['status', 'updated_at'])
        return Response({'detail': '活动已暂停', 'status': campaign.status})

    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        """结束活动"""
        campaign = self.get_object()
        campaign.status = 'ended'
        campaign.save(update_fields=['status', 'updated_at'])
        return Response({'detail': '活动已结束', 'status': campaign.status})

    @action(detail=True, methods=['post'], url_path='regenerate-qrcode')
    def regenerate_qrcode(self, request, pk=None):
        """重新生成小程序码(生成失败或要刷新时用)"""
        campaign = self.get_object()
        try:
            url = _generate_campaign_qrcode(campaign, force=True)
            return Response({
                'detail': '小程序码已重新生成',
                'wx_code_image_url': url,
            })
        except Exception as e:
            logger.error(f'活动 {campaign.id} 小程序码重新生成失败: {e}', exc_info=True)
            raise ValidationError(f'生成失败:{e}')

    @action(detail=True, methods=['get'], url_path='coupons')
    def coupons(self, request, pk=None):
        """查看该活动下发出的所有券"""
        campaign = self.get_object()
        qs = UserCoupon.objects.filter(campaign=campaign).select_related(
            'user', 'redeemed_by',
        )
        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                UserCouponAdminSerializer(page, many=True).data
            )
        return Response(UserCouponAdminSerializer(qs, many=True).data)


# ============================================================
# 小程序端 - 活动 & 领券
# ============================================================
class CampaignClientViewSet(viewsets.GenericViewSet):
    """小程序端:扫码进入查看活动 / 领券"""

    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    @action(detail=False, methods=['get'], url_path='by-scene')
    def by_scene(self, request):
        """根据 scene 参数查看活动详情(用户扫码后第一步)"""
        scene = request.query_params.get('scene', '').strip()
        if not scene:
            raise ValidationError('缺少 scene 参数')
        try:
            campaign = Campaign.objects.select_related('coupon_template').get(wx_scene=scene)
        except Campaign.DoesNotExist:
            raise NotFound('活动不存在')

        data = CampaignPublicSerializer(campaign).data
        # 附带当前用户已领取数量
        data['user_claimed_count'] = UserCoupon.objects.filter(
            campaign=campaign, user=request.user
        ).count()
        return Response(data)

    @action(detail=False, methods=['post'], url_path='claim')
    def claim(self, request):
        """
        领取活动券

        请求参数:scene(活动 scene 标识)
        """
        scene = request.data.get('scene', '').strip()
        if not scene:
            raise ValidationError('缺少 scene 参数')

        coupons = self._do_claim(scene, request.user)
        return Response({
            'detail': f'领取成功,共 {len(coupons)} 张',
            'coupons': UserCouponSerializer(coupons, many=True).data,
        }, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def _do_claim(self, scene, user):
        """领券核心逻辑(事务 + 行锁)"""
        try:
            campaign = Campaign.objects.select_for_update().select_related(
                'coupon_template'
            ).get(wx_scene=scene)
        except Campaign.DoesNotExist:
            raise NotFound('活动不存在')

        now = timezone.now()
        # 状态/时间校验
        if campaign.status != 'active':
            raise ValidationError('活动当前不可领取')
        if not (campaign.start_time <= now <= campaign.end_time):
            raise ValidationError('活动不在领取时间内')

        # 总量限制
        if campaign.total_quota is not None:
            if campaign.claimed_count + campaign.quantity_per_claim > campaign.total_quota:
                raise ValidationError('券已被领完')

        # 用户限领
        user_claimed = UserCoupon.objects.filter(campaign=campaign, user=user).count()
        if user_claimed >= campaign.per_user_limit:
            raise ValidationError(f'每人最多领取 {campaign.per_user_limit} 次')

        # 生成券
        template = campaign.coupon_template
        valid_from, valid_to = template.calculate_validity(now)

        coupons = []
        for _ in range(campaign.quantity_per_claim):
            coupon = UserCoupon.objects.create(
                user=user,
                campaign=campaign,
                coupon_template=template,
                merchant_id=campaign.merchant_id,   # ★ 冗余字段,方便核销过滤
                snapshot_name=template.name,
                snapshot_image_url=template.image_url,
                snapshot_face_value=template.face_value,
                snapshot_min_consumption=template.min_consumption,
                snapshot_discount_rate=template.discount_rate,
                valid_from=valid_from,
                valid_to=valid_to,
            )
            coupons.append(coupon)

        # 更新已领数量
        Campaign.objects.filter(pk=campaign.pk).update(
            claimed_count=F('claimed_count') + campaign.quantity_per_claim
        )
        return coupons


# ============================================================
# 小程序端 - 我的券
# ============================================================
class MyCouponViewSet(mixins.ListModelMixin,
                      mixins.RetrieveModelMixin,
                      viewsets.GenericViewSet):
    """
    我的券列表/详情

    状态过期由 Celery 定时任务 campaigns.expire_coupons 异步处理。
    Serializer 层会实时计算展示态,前端看到的永远是准确状态。

    筛选时为了让结果跟展示态一致:
      - status=unused → 排除 valid_to 已过的券(即使 db 还是 unused)
      - status=expired → 包含 valid_to 已过的 unused 券
      - 其它状态正常按 db 字段筛选

    性能优化:
      列表/详情接口会在序列化前一次性批量取出所有 merchant_id 对应的
      商家名,通过 serializer context 传给 UserCouponSerializer.get_merchant_name,
      避免逐张券查 Merchant 表造成 N+1。
    """

    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]
    serializer_class = UserCouponSerializer

    def get_queryset(self):
        qs = UserCoupon.objects.filter(
            user=self.request.user
        ).select_related('campaign', 'coupon_template')

        status_param = self.request.query_params.get('status')
        if not status_param:
            return qs

        now = timezone.now()
        if status_param == 'unused':
            qs = qs.filter(status='unused').filter(
                Q(valid_to__isnull=True) | Q(valid_to__gte=now)
            )
        elif status_param == 'expired':
            qs = qs.filter(
                Q(status='expired') |
                Q(status='unused', valid_to__isnull=False, valid_to__lt=now)
            )
        else:
            qs = qs.filter(status=status_param)
        return qs

    def _build_merchant_map(self, coupons):
        """
        批量取出 coupons 涉及的所有商家名,返回 {merchant_id: name}
        没有 merchant_id 的(平台券)不进 map。
        """
        merchant_ids = {
            c.merchant_id for c in coupons
            if c.merchant_id
        }
        if not merchant_ids:
            return {}
        rows = Merchant.objects.filter(id__in=merchant_ids).only('id', 'name')
        return {m.id: (m.name or '') for m in rows}

    def list(self, request, *args, **kwargs):
        """重写以注入 merchant_map 到 serializer context,消除 N+1"""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = page if page is not None else list(queryset)

        merchant_map = self._build_merchant_map(items)
        ctx = self.get_serializer_context()
        ctx['merchant_map'] = merchant_map

        serializer = self.get_serializer_class()(items, many=True, context=ctx)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """单张券详情,同样注入 context"""
        instance = self.get_object()
        merchant_map = self._build_merchant_map([instance])
        ctx = self.get_serializer_context()
        ctx['merchant_map'] = merchant_map
        serializer = self.get_serializer_class()(instance, context=ctx)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='available')
    def available(self, request):
        """
        下单页查可用券

        GET /api/.../my-coupons/available/?merchant_id=123&amount=99.00
        """
        merchant_id_str = request.query_params.get('merchant_id')
        amount_str = request.query_params.get('amount', '0')
        try:
            amount = Decimal(amount_str)
        except Exception:
            return Response({'error': 'amount 格式错误'}, status=400)

        now = timezone.now()
        qs = UserCoupon.objects.filter(
            user=request.user,
            status='unused',
        ).filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=now),
        ).filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=now),
        ).select_related('coupon_template')

        if merchant_id_str:
            try:
                mid = int(merchant_id_str)
            except (TypeError, ValueError):
                return Response({'error': 'merchant_id 格式错误'}, status=400)
            # 平台券(merchant_id=null) + 该商家的券
            qs = qs.filter(
                Q(merchant_id__isnull=True) | Q(merchant_id=mid)
            )

        result = []
        for c in qs:
            tpl = c.coupon_template
            # 只有代金券和折扣券走线上抵扣
            if tpl.coupon_type not in ('cash', 'discount'):
                continue
            if c.snapshot_min_consumption and amount < c.snapshot_min_consumption:
                continue
            result.append(c)

        # 按抵扣金额降序
        def _calc(c):
            if c.coupon_template.coupon_type == 'cash':
                return min(c.snapshot_face_value or Decimal('0'), amount)
            elif c.coupon_template.coupon_type == 'discount':
                rate = c.snapshot_discount_rate or Decimal('1')
                return amount * (Decimal('1') - rate)
            return Decimal('0')

        result.sort(key=_calc, reverse=True)

        merchant_map = self._build_merchant_map(result)
        ctx = self.get_serializer_context()
        ctx['merchant_map'] = merchant_map
        serializer = UserCouponSerializer(result, many=True, context=ctx)
        return Response(serializer.data)


# ============================================================
# 管理端 - 核销
# ============================================================
class RedemptionViewSet(viewsets.GenericViewSet):
    """管理员核销券码"""
    pagination_class = StandardPagination

    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    @action(detail=False, methods=['post'], url_path='query')
    def query(self, request):
        """核销前查询:管理员输入券码,先返回券信息让其确认"""
        serializer = RedemptionQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data['code']

        try:
            coupon = UserCoupon.objects.select_related(
                'user', 'campaign', 'coupon_template'
            ).get(code=code)
        except UserCoupon.DoesNotExist:
            raise NotFound('券码不存在,请检查输入')

        data = UserCouponAdminSerializer(coupon).data
        reason = _check_coupon_redeemable(coupon)
        data['can_redeem'] = reason is None
        data['cannot_redeem_reason'] = reason
        return Response(data)

    @action(detail=False, methods=['post'], url_path='redeem')
    def redeem(self, request):
        """执行核销"""
        serializer = RedemptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        coupon = self._do_redeem(
            code=serializer.validated_data['code'],
            operator=request.user,
            amount=serializer.validated_data.get('amount'),
            remark=serializer.validated_data.get('remark', ''),
            ip=_client_ip(request),
        )
        return Response({
            'detail': '核销成功',
            'coupon': UserCouponAdminSerializer(coupon).data,
        })

    @action(detail=False, methods=['get'], url_path='logs')
    def logs(self, request):
        """核销日志查询"""
        qs = RedemptionLog.objects.select_related('user_coupon', 'operator').all()

        operator_id = request.query_params.get('operator_id')
        action_param = request.query_params.get('action')
        start = request.query_params.get('start_time')
        end = request.query_params.get('end_time')
        if operator_id:
            qs = qs.filter(operator_id=operator_id)
        if action_param:
            qs = qs.filter(action=action_param)
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)

        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                RedemptionLogSerializer(page, many=True).data
            )
        return Response(RedemptionLogSerializer(qs, many=True).data)

    # -------- helpers --------
    @transaction.atomic
    def _do_redeem(self, code, operator, amount, remark, ip):
        """核销核心逻辑(事务 + 行锁)"""
        try:
            coupon = UserCoupon.objects.select_for_update().get(code=code)
        except UserCoupon.DoesNotExist:
            raise NotFound('券码不存在')

        reason = _check_coupon_redeemable(coupon)
        if reason:
            raise ValidationError(reason)

        now = timezone.now()
        operator_name = (
            getattr(operator, 'name', None)
            or getattr(operator, 'username', '')
            or f'管理员#{operator.id}'
        )

        coupon.status = 'used'
        coupon.used_at = now
        coupon.redeemed_by = operator  # 兼容旧字段
        coupon.redeemer_type = 'manager'
        coupon.redeemer_id = operator.id
        coupon.redeemer_name = operator_name
        coupon.redemption_amount = amount
        if remark:
            coupon.remark = remark
        coupon.save(update_fields=[
            'status', 'used_at', 'redeemed_by',
            'redeemer_type', 'redeemer_id', 'redeemer_name',
            'redemption_amount', 'remark',
        ])

        RedemptionLog.objects.create(
            user_coupon=coupon,
            operator=operator,  # 兼容旧字段
            action='redeem',
            amount=amount,
            remark=remark,
            ip_address=ip,
            actor_type='manager',
            actor_id=operator.id,
            actor_name=operator_name,
        )
        return coupon


# ============================================================
# 商户端 - 券模板
# ============================================================
class MerchantCouponTemplateViewSet(viewsets.ModelViewSet):
    """
    商户端券模板

    GET    list / retrieve   本商家私有模板 + 所有平台公共模板
    POST   create            创建本商家私有模板
    PUT    update / DELETE   仅可操作自己的私有模板

    Query 参数:
      scope=mine    只看自己的
      scope=public  只看平台公共
      is_active=1/0
      coupon_type=cash/discount/...
      keyword=...
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    serializer_class = MerchantCouponTemplateSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        merchant_id, *_ = _get_merchant_context(self.request)

        # 列表/详情:自己的 + 公共;编辑/删除:只自己的
        if self.action in ('list', 'retrieve'):
            qs = CouponTemplate.objects.filter(
                Q(merchant_id=merchant_id) | Q(merchant_id__isnull=True)
            )
        else:
            qs = CouponTemplate.objects.filter(merchant_id=merchant_id)

        is_active = self.request.query_params.get('is_active')
        coupon_type = self.request.query_params.get('coupon_type')
        keyword = self.request.query_params.get('keyword')
        scope = self.request.query_params.get('scope')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('1', 'true', 'yes'))
        if coupon_type:
            qs = qs.filter(coupon_type=coupon_type)
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        if scope == 'mine':
            qs = qs.filter(merchant_id=merchant_id)
        elif scope == 'public':
            qs = qs.filter(merchant_id__isnull=True)
        return qs.order_by('-created_at')

    def perform_create(self, serializer):
        merchant_id, op_type, op_id, _name = _get_merchant_context(self.request)
        serializer.save(
            merchant_id=merchant_id,
            created_by_merchant_type=op_type,
            created_by_merchant_id=op_id,
        )

    def perform_update(self, serializer):
        merchant_id, *_ = _get_merchant_context(self.request)
        instance = self.get_object()
        if instance.merchant_id != merchant_id:
            raise ValidationError('无法编辑非本店模板')
        serializer.save()

    def perform_destroy(self, instance):
        merchant_id, *_ = _get_merchant_context(self.request)
        if instance.merchant_id != merchant_id:
            raise ValidationError('无法删除非本店模板')
        if instance.campaigns.exists():
            raise ValidationError('该模板已被活动引用,无法删除,请改为停用')
        super().perform_destroy(instance)


# ============================================================
# 商户端 - 活动
# ============================================================
class MerchantCampaignViewSet(viewsets.ModelViewSet):
    """
    商户端活动管理(只看/管自己 merchant_id 下的活动)

    GET    list / retrieve
    POST   create / update / DELETE
    POST   {id}/activate
    POST   {id}/pause
    POST   {id}/end
    POST   {id}/regenerate-qrcode
    GET    {id}/coupons      查看本活动发出的所有券
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    pagination_class = StandardPagination

    def get_queryset(self):
        merchant_id, *_ = _get_merchant_context(self.request)
        qs = Campaign.objects.filter(merchant_id=merchant_id).select_related(
            'coupon_template'
        )
        if self.action != 'list':
            return qs

        status_param = self.request.query_params.get('status')
        keyword = self.request.query_params.get('keyword')
        if status_param:
            qs = qs.filter(status=status_param)
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return MerchantCampaignListSerializer
        return MerchantCampaignDetailSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        try:
            merchant_id, *_ = _get_merchant_context(self.request)
            ctx['merchant_id'] = merchant_id
        except Exception:
            pass
        return ctx

    def perform_create(self, serializer):
        merchant_id, op_type, op_id, _name = _get_merchant_context(self.request)

        # 生成唯一 wx_scene
        for _ in range(5):
            scene = _generate_wx_scene()
            if not Campaign.objects.filter(wx_scene=scene).exists():
                break
        else:
            raise ValidationError('生成 scene 失败,请重试')

        campaign = serializer.save(
            merchant_id=merchant_id,
            created_by_merchant_type=op_type,
            created_by_merchant_id=op_id,
            wx_scene=scene,
        )

        # 生成小程序码(失败不阻塞)
        self._qrcode_error = None
        try:
            _generate_campaign_qrcode(campaign)
        except Exception as e:
            logger.error(f'活动 {campaign.id} 小程序码生成失败: {e}', exc_info=True)
            self._qrcode_error = str(e)

    def create(self, request, *args, **kwargs):
        self._qrcode_error = None
        response = super().create(request, *args, **kwargs)
        if self._qrcode_error:
            response.data['qrcode_warning'] = (
                f'活动已创建,但小程序码生成失败:{self._qrcode_error}。'
                f'请稍后调用 regenerate-qrcode 重试。'
            )
        return response

    def perform_destroy(self, instance):
        if instance.claimed_count > 0:
            raise ValidationError('该活动已发放过券,不可删除,请改为「已结束」状态')
        if instance.wx_code_image_url:
            key = extract_object_key(instance.wx_code_image_url)
            if key:
                delete_object(key)
        super().perform_destroy(instance)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        campaign = self.get_object()
        if campaign.status == 'ended':
            raise ValidationError('活动已结束,无法重新上线')
        campaign.status = 'active'
        campaign.save(update_fields=['status', 'updated_at'])
        return Response({'detail': '活动已上线', 'status': campaign.status})

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = 'paused'
        campaign.save(update_fields=['status', 'updated_at'])
        return Response({'detail': '活动已暂停', 'status': campaign.status})

    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = 'ended'
        campaign.save(update_fields=['status', 'updated_at'])
        return Response({'detail': '活动已结束', 'status': campaign.status})

    @action(detail=True, methods=['post'], url_path='regenerate-qrcode')
    def regenerate_qrcode(self, request, pk=None):
        campaign = self.get_object()
        try:
            url = _generate_campaign_qrcode(campaign, force=True)
            return Response({
                'detail': '小程序码已重新生成',
                'wx_code_image_url': url,
            })
        except Exception as e:
            logger.error(f'活动 {campaign.id} 小程序码重新生成失败: {e}', exc_info=True)
            raise ValidationError(f'生成失败:{e}')

    @action(detail=True, methods=['get'], url_path='coupons')
    def coupons(self, request, pk=None):
        campaign = self.get_object()
        qs = UserCoupon.objects.filter(campaign=campaign).select_related('user')
        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                MerchantUserCouponSerializer(page, many=True).data
            )
        return Response(MerchantUserCouponSerializer(qs, many=True).data)


# ============================================================
# 商户端 - 核销
# ============================================================
class MerchantRedemptionViewSet(viewsets.GenericViewSet):
    """
    商户端核销

    POST   /query/    核销前查询券码,返回券信息
    POST   /redeem/   执行核销
    GET    /logs/     本店核销日志

    关键约束:商家只能核销 user_coupon.merchant_id == 自己 merchant_id 的券
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    pagination_class = StandardPagination

    @action(detail=False, methods=['post'], url_path='query')
    def query(self, request):
        """核销前查询券信息"""
        merchant_id, *_ = _get_merchant_context(request)

        serializer = RedemptionQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data['code']

        try:
            coupon = UserCoupon.objects.select_related(
                'user', 'campaign', 'coupon_template',
            ).get(code=code)
        except UserCoupon.DoesNotExist:
            raise NotFound('券码不存在,请检查输入')

        # 商家归属校验
        if coupon.merchant_id != merchant_id:
            raise NotFound('该券码不属于本店,无法核销')

        data = MerchantUserCouponSerializer(coupon).data
        reason = _check_coupon_redeemable(coupon)
        data['can_redeem'] = reason is None
        data['cannot_redeem_reason'] = reason
        return Response(data)

    @action(detail=False, methods=['post'], url_path='redeem')
    def redeem(self, request):
        """执行核销"""
        merchant_id, op_type, op_id, op_name = _get_merchant_context(request)

        serializer = RedemptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        coupon = self._do_redeem(
            code=serializer.validated_data['code'],
            merchant_id=merchant_id,
            operator_type=op_type,
            operator_id=op_id,
            operator_name=op_name,
            amount=serializer.validated_data.get('amount'),
            remark=serializer.validated_data.get('remark', ''),
            ip=_client_ip(request),
        )
        return Response({
            'detail': '核销成功',
            'coupon': MerchantUserCouponSerializer(coupon).data,
        })

    @action(detail=False, methods=['get'], url_path='logs')
    def logs(self, request):
        """本店核销日志"""
        merchant_id, *_ = _get_merchant_context(request)
        qs = RedemptionLog.objects.filter(
            user_coupon__merchant_id=merchant_id,
        ).select_related('user_coupon', 'user_coupon__user')

        action_param = request.query_params.get('action')
        start = request.query_params.get('start_time')
        end = request.query_params.get('end_time')
        operator_id_param = request.query_params.get('operator_id')
        operator_type_param = request.query_params.get('operator_type')
        if action_param:
            qs = qs.filter(action=action_param)
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)
        if operator_id_param:
            qs = qs.filter(actor_id=operator_id_param)
        if operator_type_param:
            qs = qs.filter(actor_type=operator_type_param)

        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                MerchantRedemptionLogSerializer(page, many=True).data
            )
        return Response(MerchantRedemptionLogSerializer(qs, many=True).data)

    @transaction.atomic
    def _do_redeem(self, code, merchant_id, operator_type, operator_id,
                   operator_name, amount, remark, ip):
        """商户端核销核心逻辑"""
        try:
            coupon = UserCoupon.objects.select_for_update().get(code=code)
        except UserCoupon.DoesNotExist:
            raise NotFound('券码不存在')

        # 商家归属校验
        if coupon.merchant_id != merchant_id:
            raise ValidationError('该券码不属于本店,无法核销')

        reason = _check_coupon_redeemable(coupon)
        if reason:
            raise ValidationError(reason)

        coupon.status = 'used'
        coupon.used_at = timezone.now()
        coupon.redeemer_type = operator_type
        coupon.redeemer_id = operator_id
        coupon.redeemer_name = operator_name
        coupon.redemption_amount = amount
        if remark:
            coupon.remark = remark
        coupon.save(update_fields=[
            'status', 'used_at',
            'redeemer_type', 'redeemer_id', 'redeemer_name',
            'redemption_amount', 'remark',
        ])

        RedemptionLog.objects.create(
            user_coupon=coupon,
            action='redeem',
            amount=amount,
            remark=remark,
            ip_address=ip,
            actor_type=operator_type,
            actor_id=operator_id,
            actor_name=operator_name,
        )
        return coupon