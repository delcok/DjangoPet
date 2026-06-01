# merchants/views.py
"""
商家视图
"""

import logging

from django.db.models import Count, Q, F
from django.forms.models import model_to_dict
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, generics, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.account_factory import onboard_merchant
from utils.authentication import (
    generate_merchant_tokens,
    ManagerAuthentication,
    MerchantOrSubAuthentication, MerchantAuthentication,
)
from utils.cache import LoginSecurityManager, BusinessCache
from utils.db import escape_like
from utils.permission import IsMerchant, IsManager, get_merchant_id_from_request
from utils.send_sms import send_sms_code, verify_sms_code

from .filters import (
    MerchantUserFilter, NearbyMerchantFilter, MerchantAdminFilter,
    MerchantCategoryFilter, BusinessDistrictFilter,
)
from .models import Merchant, MerchantCategory, BusinessDistrict, MerchantSubAccount
from .paginations import MerchantListPagination, AdminPagination, NoPagination
from .serializers import (
    SendSMSCodeSerializer, PasswordLoginSerializer, SMSLoginSerializer,
    ResetPasswordSerializer, ChangePasswordSerializer,
    MerchantCategorySerializer, BusinessDistrictSerializer,
    BusinessDistrictAdminSerializer, BusinessDistrictDetailSerializer,
    MerchantListSerializer, MerchantDetailSerializer,
    MerchantProfileSerializer, MerchantUpdateSerializer,
    MerchantAdminListSerializer, MerchantAdminDetailSerializer,
    MerchantAdminUpdateSerializer,
    MerchantAuditSerializer,
    MerchantCategoryAdminSerializer, MerchantBankAccountUpdateSerializer,
    MerchantDeliveryConfigSerializer,
)


logger = logging.getLogger(__name__)

_SENSITIVE_FIELDS = {'password', 'bank_account_no', 'id_card_front', 'id_card_back'}


# ══════════════════════════════════════════════════════════════
# 操作日志辅助
# ══════════════════════════════════════════════════════════════

def _get_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _snapshot(instance):
    if instance is None:
        return None
    try:
        data = model_to_dict(instance)
        for k in list(data.keys()):
            if k in _SENSITIVE_FIELDS:
                data.pop(k, None)
        return data
    except Exception as e:
        logger.warning(f'快照模型失败: {e}')
        return None


def _safe_log(request, **kwargs):
    try:
        from managers.models import ManagerOperationLog, Manager

        manager = getattr(request, 'user', None)
        if not isinstance(manager, Manager):
            return

        ManagerOperationLog.objects.create(
            manager=manager,
            manager_name=manager.name or '',
            manager_username=manager.username or '',
            ip_address=_get_client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT', '') or '')[:500],
            **kwargs,
        )
    except Exception as e:
        logger.exception(f'记录管理员操作日志失败: {e}')


class AdminLogMixin:
    log_module = ''
    log_target_type = ''
    log_object_label = '对象'
    log_name_field = 'name'

    def _obj_name(self, instance):
        return getattr(instance, self.log_name_field, None) or str(instance)

    def perform_create(self, serializer):
        serializer.save()
        instance = getattr(serializer, 'instance', None)
        if instance is None:
            return
        _safe_log(
            self.request,
            action='create',
            module=self.log_module,
            description=f'创建{self.log_object_label}: {self._obj_name(instance)}',
            target_type=self.log_target_type,
            target_id=str(instance.pk),
            new_data=_snapshot(instance),
        )

    def perform_update(self, serializer):
        old_data = _snapshot(serializer.instance)
        serializer.save()
        instance = serializer.instance
        _safe_log(
            self.request,
            action='update',
            module=self.log_module,
            description=f'更新{self.log_object_label}: {self._obj_name(instance)}',
            target_type=self.log_target_type,
            target_id=str(instance.pk),
            old_data=old_data,
            new_data=_snapshot(instance),
        )

    def perform_destroy(self, instance):
        old_data = _snapshot(instance)
        name = self._obj_name(instance)
        pk = instance.pk
        instance.delete()
        _safe_log(
            self.request,
            action='delete',
            module=self.log_module,
            description=f'删除{self.log_object_label}: {name}',
            target_type=self.log_target_type,
            target_id=str(pk),
            old_data=old_data,
        )


# ══════════════════════════════════════════════════════════════
# 认证视图
# ══════════════════════════════════════════════════════════════

class SendSMSCodeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SendSMSCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        scene = serializer.validated_data['scene']

        success, message, code = send_sms_code(phone, scene)

        response_data = {'message': message}
        if code:
            response_data['code'] = code

        if success:
            return Response(response_data)
        else:
            return Response(response_data, status=status.HTTP_400_BAD_REQUEST)


class MerchantPasswordLoginView(APIView):
    """
    商家密码登录

    ✅ 修复 #2:
    - 失败计数无论账号是否存在都记录,防枚举/防绕过锁定
    - 账号 status 检查放在密码验证之后,避免攻击者用 status 异常账号绕过锁定
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        password = serializer.validated_data['password']

        security = LoginSecurityManager()

        # 1) 锁定检查 — 始终第一步,不区分账号是否存在
        is_locked, remaining = security.is_locked(phone, 'merchant')
        if is_locked:
            minutes = remaining // 60 + 1
            return Response(
                {'error': f'账户已锁定,请{minutes}分钟后重试'},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2) 查商家(用 filter().first() 替代 try/except)
        merchant = Merchant.objects.filter(phone=phone).first()

        # 3) 密码错误或账号不存在 — 统一计入失败,防枚举
        if merchant is None or not merchant.check_password(password):
            fail_count, locked = security.record_fail(phone, 'merchant')
            if locked:
                return Response(
                    {'error': '密码错误次数过多,账户已锁定30分钟'},
                    status=status.HTTP_403_FORBIDDEN
                )
            remaining_attempts = security.get_remaining_attempts(phone, 'merchant')
            return Response(
                {'error': f'手机号或密码错误,还剩{remaining_attempts}次机会'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 4) 密码正确才检查 status — 不算失败,直接告知
        if merchant.status != Merchant.Status.ACTIVE:
            status_msg = {
                'pending': '账户待审核',
                'suspended': '账户已被暂停',
                'rejected': '账户审核被拒绝',
                'closed': '账户已关闭',
            }
            return Response(
                {'error': status_msg.get(merchant.status, '账户状态异常')},
                status=status.HTTP_403_FORBIDDEN
            )

        # 5) 登录成功
        security.clear_fail_count(phone, 'merchant')
        merchant.last_login = timezone.now()  # ✅ 修复 #7: timezone-aware
        merchant.save(update_fields=['last_login'])

        tokens = generate_merchant_tokens(merchant)
        return Response({
            **tokens,
            'merchant': MerchantProfileSerializer(merchant).data
        })


class MerchantSMSLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SMSLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']

        valid, error = verify_sms_code(phone, code, 'login')
        if not valid:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        merchant = Merchant.objects.filter(phone=phone).first()
        if merchant is None:
            return Response(
                {'error': '该手机号未注册'},
                status=status.HTTP_404_NOT_FOUND
            )

        if merchant.status != Merchant.Status.ACTIVE:
            status_msg = {
                'pending': '账户待审核',
                'suspended': '账户已被暂停',
                'rejected': '账户审核被拒绝',
                'closed': '账户已关闭',
            }
            return Response(
                {'error': status_msg.get(merchant.status, '账户状态异常')},
                status=status.HTTP_403_FORBIDDEN
            )

        LoginSecurityManager().clear_fail_count(phone, 'merchant')
        merchant.last_login = timezone.now()  # ✅ 修复 #7
        merchant.save(update_fields=['last_login'])

        tokens = generate_merchant_tokens(merchant)

        return Response({
            **tokens,
            'merchant': MerchantProfileSerializer(merchant).data
        })


class MerchantResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']

        valid, error = verify_sms_code(phone, code, 'reset_password')
        if not valid:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        merchant = Merchant.objects.filter(phone=phone).first()
        if merchant is None:
            return Response(
                {'error': '该手机号未注册'},
                status=status.HTTP_404_NOT_FOUND
            )

        merchant.set_password(new_password)
        merchant.token_version += 1
        merchant.save(update_fields=['password', 'token_version'])

        return Response({'message': '密码重置成功'})


# ══════════════════════════════════════════════════════════════
# 用户端 - 商家列表/详情
# ══════════════════════════════════════════════════════════════

class MerchantListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MerchantListSerializer
    pagination_class = MerchantListPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = MerchantUserFilter

    def get_queryset(self):
        return Merchant.objects.filter(
            status=Merchant.Status.ACTIVE
        ).select_related('category', 'business_district')


class NearbyMerchantView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MerchantListSerializer
    pagination_class = MerchantListPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = NearbyMerchantFilter

    def get_queryset(self):
        return Merchant.objects.filter(
            status=Merchant.Status.ACTIVE,
            longitude__isnull=False,
            latitude__isnull=False
        ).select_related('category', 'business_district')


class MerchantDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = MerchantDetailSerializer

    def get_queryset(self):
        return Merchant.objects.filter(
            status=Merchant.Status.ACTIVE
        ).select_related('category', 'business_district')


class RecommendedMerchantView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MerchantListSerializer
    pagination_class = MerchantListPagination

    def get_queryset(self):
        return Merchant.objects.filter(
            status=Merchant.Status.ACTIVE,
            is_recommended=True
        ).select_related(
            'category', 'business_district'
        ).order_by('-recommend_sort', '-rating', '-monthly_sales')


# ══════════════════════════════════════════════════════════════
# 用户端 - 分类/商圈
# ══════════════════════════════════════════════════════════════

class MerchantCategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MerchantCategorySerializer
    pagination_class = NoPagination

    def get_queryset(self):
        return MerchantCategory.objects.filter(
            is_active=True
        ).annotate(
            merchant_count=Count(
                'merchants',
                filter=Q(merchants__status=Merchant.Status.ACTIVE)
            )
        ).order_by('sort_order', 'id')


class BusinessDistrictListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = BusinessDistrictSerializer
    pagination_class = NoPagination

    def get_queryset(self):
        qs = BusinessDistrict.objects.filter(is_active=True)

        province = self.request.query_params.get('province', '')
        city = self.request.query_params.get('city', '')
        district = self.request.query_params.get('district', '')

        if province:
            qs = qs.filter(province__icontains=escape_like(province))
        if city:
            qs = qs.filter(city__icontains=escape_like(city))
        if district:
            qs = qs.filter(district__icontains=escape_like(district))

        return qs.annotate(
            merchant_count=Count(
                'merchants',
                filter=Q(merchants__status=Merchant.Status.ACTIVE)
            )
        ).order_by('sort_order', '-heat_score', 'id')


# ══════════════════════════════════════════════════════════════
# 商家端 - 自身信息
# ══════════════════════════════════════════════════════════════

class MerchantProfileView(APIView):
    """
    ✅ 修复 #5: 用 get_merchant_id_from_request 解析真正的 merchant_id,
    避免子账号登录时把 sub_account.id 当成 merchant.id 误查到错商家。
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def get(self, request):
        merchant = self._get_merchant(request)
        if not merchant:
            return Response({'error': '未找到商家信息'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(MerchantProfileSerializer(merchant).data)

    def put(self, request):
        merchant = self._get_merchant(request)
        if not merchant:
            return Response({'error': '未找到商家信息'},
                            status=status.HTTP_404_NOT_FOUND)

        serializer = MerchantUpdateSerializer(
            merchant, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        BusinessCache().delete_merchant(merchant.id)
        return Response(MerchantProfileSerializer(merchant).data)

    def _get_merchant(self, request):
        merchant_id = get_merchant_id_from_request(request)
        if not merchant_id:
            return None
        return Merchant.objects.filter(id=merchant_id).first()


class MerchantChangePasswordView(APIView):
    """
    ✅ 修复 #5: 子账号场景下改子账号自己的密码,
    旧代码 `merchant = request.user` 会把子账号当作 Merchant,
    `merchant.token_version += 1` 等操作走到子账号自己身上但语义混乱。
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        if isinstance(user, (Merchant, MerchantSubAccount)):
            target = user
        else:
            return Response({'error': '无效的账号类型'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not target.check_password(serializer.validated_data['old_password']):
            return Response({'error': '原密码错误'},
                            status=status.HTTP_400_BAD_REQUEST)

        target.set_password(serializer.validated_data['new_password'])
        target.token_version += 1
        target.save(update_fields=['password', 'token_version'])

        return Response({'message': '密码修改成功'})


# ══════════════════════════════════════════════════════════════
# 管理端 - 商家管理
# ══════════════════════════════════════════════════════════════

class MerchantAdminViewSet(AdminLogMixin, viewsets.ModelViewSet):
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    pagination_class = AdminPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = MerchantAdminFilter

    log_module = 'merchant'
    log_target_type = 'merchant'
    log_object_label = '商家'
    log_name_field = 'name'

    def get_queryset(self):
        return Merchant.objects.select_related(
            'category', 'business_district'
        ).order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return MerchantAdminListSerializer
        elif self.action in ['update', 'partial_update']:
            return MerchantAdminUpdateSerializer
        else:
            return MerchantAdminDetailSerializer

    def perform_create(self, serializer):
        merchant = onboard_merchant(**serializer.validated_data)

        if merchant is None:
            phone = serializer.validated_data.get('phone')
            if phone:
                merchant = Merchant.objects.filter(phone=phone).first()

        if merchant is not None:
            _safe_log(
                self.request,
                action='create',
                module=self.log_module,
                description=f'创建{self.log_object_label}: {merchant.name}',
                target_type=self.log_target_type,
                target_id=str(merchant.id),
                new_data=_snapshot(merchant),
            )

    def perform_update(self, serializer):
        """
        覆写 update:
        - 普通字段:走父类 AdminLogMixin.perform_update(自动写审计日志,
          old_data/new_data 快照里已包含 phone 变更,可追溯)
        - 登录手机号变更:额外让该商家所有 token 立即失效,并清商户缓存
        """
        # save() 之前记下旧手机号
        old_phone = serializer.instance.phone

        # 父类完成 save() + 审计日志
        super().perform_update(serializer)

        new_phone = serializer.instance.phone
        if old_phone != new_phone:
            # 原子自增 token_version,作废所有已签发 token
            Merchant.objects.filter(pk=serializer.instance.pk).update(
                token_version=F('token_version') + 1
            )
            # 清商户缓存,避免脏数据
            BusinessCache().delete_merchant(serializer.instance.pk)

            # 额外补一条更醒目的日志(可选;不加也能从 update 日志的快照里 diff 出来)
            _safe_log(
                self.request,
                action='update',
                module=self.log_module,
                description=f'修改{self.log_object_label}登录手机号: '
                            f'{serializer.instance.name} ({old_phone} → {new_phone})',
                target_type=self.log_target_type,
                target_id=str(serializer.instance.pk),
                old_data={'phone': old_phone},
                new_data={'phone': new_phone},
            )

    @action(detail=True, methods=['post'])
    def audit(self, request, pk=None):
        merchant = self.get_object()

        if merchant.status != Merchant.Status.PENDING:
            return Response(
                {'error': '只能审核待审核状态的商家'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = MerchantAuditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        audit_action = serializer.validated_data['action']
        old_status = merchant.status

        if audit_action == 'approve':
            merchant.status = Merchant.Status.ACTIVE
            merchant.reject_reason = ''
            action_text = '审核通过'
        else:
            merchant.status = Merchant.Status.REJECTED
            merchant.reject_reason = serializer.validated_data.get('reject_reason', '')
            action_text = f'审核拒绝: {merchant.reject_reason or "未填写原因"}'

        merchant.save(update_fields=['status', 'reject_reason'])

        _safe_log(
            request,
            action='audit',
            module=self.log_module,
            description=f'{action_text} — {merchant.name}',
            target_type=self.log_target_type,
            target_id=str(merchant.id),
            old_data={'status': old_status},
            new_data={'status': merchant.status, 'reject_reason': merchant.reject_reason},
        )

        return Response({
            'message': '审核通过' if audit_action == 'approve' else '已拒绝',
            'status': merchant.status
        })

    @action(detail=True, methods=['post'])
    def toggle_status(self, request, pk=None):
        merchant = self.get_object()
        old_status = merchant.status

        if merchant.status == Merchant.Status.ACTIVE:
            merchant.status = Merchant.Status.SUSPENDED
            message = '已暂停'
        elif merchant.status == Merchant.Status.SUSPENDED:
            merchant.status = Merchant.Status.ACTIVE
            message = '已启用'
        else:
            return Response(
                {'error': '当前状态不支持此操作'},
                status=status.HTTP_400_BAD_REQUEST
            )

        merchant.save(update_fields=['status'])
        BusinessCache().delete_merchant(merchant.id)

        _safe_log(
            request,
            action='update',
            module=self.log_module,
            description=f'{message}{self.log_object_label}: {merchant.name}',
            target_type=self.log_target_type,
            target_id=str(merchant.id),
            old_data={'status': old_status},
            new_data={'status': merchant.status},
        )

        return Response({'message': message, 'status': merchant.status})

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        merchant = self.get_object()

        new_password = request.data.get('password', '123456')
        merchant.set_password(new_password)
        merchant.token_version += 1
        merchant.save(update_fields=['password', 'token_version'])

        _safe_log(
            request,
            action='update',
            module=self.log_module,
            description=f'重置{self.log_object_label}密码: {merchant.name}',
            target_type=self.log_target_type,
            target_id=str(merchant.id),
        )

        return Response({'message': '密码已重置', 'password': new_password})

# ══════════════════════════════════════════════════════════════
# 管理端 - 分类/商圈
# ══════════════════════════════════════════════════════════════

class MerchantCategoryAdminViewSet(AdminLogMixin, viewsets.ModelViewSet):
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    queryset = MerchantCategory.objects.all().order_by('sort_order', 'id')
    pagination_class = AdminPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = MerchantCategoryFilter

    log_module = 'merchant_category'
    log_target_type = 'merchant_category'
    log_object_label = '商家分类'
    log_name_field = 'name'

    def get_serializer_class(self):
        if self.action == 'list':
            return MerchantCategorySerializer
        return MerchantCategoryAdminSerializer


class BusinessDistrictAdminViewSet(AdminLogMixin, viewsets.ModelViewSet):
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    pagination_class = AdminPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = BusinessDistrictFilter

    log_module = 'business_district'
    log_target_type = 'business_district'
    log_object_label = '商圈'
    log_name_field = 'name'

    def get_queryset(self):
        return BusinessDistrict.objects.annotate(
            merchant_count=Count(
                'merchants',
                filter=Q(merchants__status=Merchant.Status.ACTIVE)
            )
        ).order_by('sort_order', '-heat_score', 'id')

    def get_serializer_class(self):
        if self.action == 'list':
            return BusinessDistrictAdminSerializer
        elif self.action == 'retrieve':
            return BusinessDistrictDetailSerializer
        else:
            return BusinessDistrictAdminSerializer


class MerchantBankAccountView(APIView):
    """商家端 - 修改提现银行卡(仅主账号 + 短信验证)"""
    authentication_classes = [MerchantAuthentication]
    permission_classes = [IsMerchant]

    def get(self, request):
        m = request.user
        no = m.bank_account_no or ''
        masked = (no[:4] + '*' * max(0, len(no) - 8) + no[-4:]) if len(no) >= 8 else no
        return Response({
            'bank_name': m.bank_name,
            'bank_account_name': m.bank_account_name,
            'bank_account_no_masked': masked,
            'has_bank_account': bool(no),
        })

    def put(self, request):
        m = request.user
        serializer = MerchantBankAccountUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ok, msg = verify_sms_code(m.phone, data['code'], scene='change_bank')
        if not ok:
            return Response({'error': msg or '验证码错误或已过期'},
                            status=status.HTTP_400_BAD_REQUEST)

        m.bank_name = data['bank_name']
        m.bank_account_name = data['bank_account_name']
        m.bank_account_no = data['bank_account_no']
        m.save(update_fields=['bank_name', 'bank_account_name', 'bank_account_no'])

        BusinessCache().delete_merchant(m.id)

        return Response({'message': '银行卡信息已更新'})


# ══════════════════════════════════════════════════════════════
# 用户端 - 综合搜索
# ══════════════════════════════════════════════════════════════

class MerchantSearchView(generics.ListAPIView):
    """C端用户 - 综合搜索"""
    permission_classes = [AllowAny]
    serializer_class = MerchantListSerializer
    pagination_class = MerchantListPagination

    MAX_KEYWORD_LEN = 50
    MAX_MERCHANTS = 500  # ✅ 修复:命中集合上限,防内存爆炸

    def list(self, request, *args, **kwargs):
        keyword = (request.query_params.get('keyword') or '').strip()
        if not keyword:
            page = self.paginate_queryset([])
            if page is not None:
                return self.get_paginated_response([])
            return Response({'count': 0, 'results': []})

        if len(keyword) > self.MAX_KEYWORD_LEN:
            keyword = keyword[:self.MAX_KEYWORD_LEN]

        # ✅ 修复 #4: LIKE 通配符转义
        safe_kw = escape_like(keyword)

        merchant_ids = set()

        # (1) 商家命中
        ids = Merchant.objects.filter(
            Q(name__icontains=safe_kw) | Q(description__icontains=safe_kw),
            status=Merchant.Status.ACTIVE,
        ).values_list('id', flat=True)[:self.MAX_MERCHANTS]
        merchant_ids.update(ids)

        # (2) 商品命中
        try:
            from product.models import Goods
            ids = Goods.objects.filter(
                Q(title__icontains=safe_kw) |
                Q(subtitle__icontains=safe_kw) |
                Q(keywords__icontains=safe_kw),
                status='on_sale',
            ).values_list('merchant_id', flat=True).distinct()[:self.MAX_MERCHANTS]
            merchant_ids.update(ids)
        except Exception as e:
            logger.warning(f'搜索商品时出错(忽略): {e}')

        # (3) 服务命中
        try:
            from services.models import Service
            ids = Service.objects.filter(
                Q(name__icontains=safe_kw) |
                Q(subtitle__icontains=safe_kw) |
                Q(description__icontains=safe_kw),
                status=Service.Status.ACTIVE,
            ).values_list('merchant_id', flat=True).distinct()[:self.MAX_MERCHANTS]
            merchant_ids.update(ids)
        except Exception as e:
            logger.warning(f'搜索服务时出错(忽略): {e}')

        if not merchant_ids:
            page = self.paginate_queryset([])
            if page is not None:
                return self.get_paginated_response([])
            return Response({'count': 0, 'results': []})

        # 总命中上限
        if len(merchant_ids) > self.MAX_MERCHANTS:
            merchant_ids = set(list(merchant_ids)[:self.MAX_MERCHANTS])

        qs = Merchant.objects.filter(
            id__in=merchant_ids,
            status=Merchant.Status.ACTIVE,
        ).select_related('category', 'business_district')

        if request.query_params.get('category_id'):
            qs = qs.filter(category_id=request.query_params['category_id'])

        if request.query_params.get('district_id'):
            qs = qs.filter(business_district_id=request.query_params['district_id'])

        if str(request.query_params.get('is_open', '')).lower() in ('1', 'true'):
            qs = qs.filter(is_open=True)

        if str(request.query_params.get('is_recommended', '')).lower() in ('1', 'true'):
            qs = qs.filter(is_recommended=True)

        merchants = list(qs)

        user_lng = request.query_params.get('longitude')
        user_lat = request.query_params.get('latitude')
        try:
            user_lng_f = float(user_lng) if user_lng else None
            user_lat_f = float(user_lat) if user_lat else None
        except (TypeError, ValueError):
            user_lng_f = user_lat_f = None

        has_location = user_lng_f is not None and user_lat_f is not None
        for m in merchants:
            m._distance = (
                self._haversine(user_lng_f, user_lat_f, m.longitude, m.latitude)
                if has_location else None
            )

        sort = (request.query_params.get('sort') or 'default').lower()

        if sort in ('default', 'distance') and has_location:
            merchants.sort(key=lambda m: (
                m._distance if m._distance is not None else float('inf'),
                -float(m.rating or 0),
            ))
        elif sort == 'sales':
            merchants.sort(key=lambda m: -(m.monthly_sales or 0))
        elif sort == 'rating':
            merchants.sort(key=lambda m: -float(m.rating or 0))
        else:
            merchants.sort(key=lambda m: (
                0 if m.is_recommended else 1,
                -float(m.rating or 0),
                -(m.monthly_sales or 0),
            ))

        page = self.paginate_queryset(merchants)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(merchants, many=True)
        return Response(serializer.data)

    @staticmethod
    def _haversine(lng1, lat1, lng2, lat2):
        if lng2 is None or lat2 is None:
            return None
        try:
            from math import radians, sin, cos, sqrt, atan2
            lng2_f, lat2_f = float(lng2), float(lat2)
            R = 6371000
            lat1_r = radians(lat1)
            lat2_r = radians(lat2_f)
            dlat = radians(lat2_f - lat1)
            dlng = radians(lng2_f - lng1)
            a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlng / 2) ** 2
            return R * 2 * atan2(sqrt(a), sqrt(1 - a))
        except (TypeError, ValueError):
            return None


class MerchantDeliveryConfigView(APIView):
    """商家端 - 配送配置(读 / 改)"""
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def _get_merchant(self, request):
        mid = get_merchant_id_from_request(request)
        if not mid:
            return None
        return Merchant.objects.filter(id=mid).first()

    def get(self, request):
        merchant = self._get_merchant(request)
        if not merchant:
            return Response({'error': '未找到商家信息'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(MerchantDeliveryConfigSerializer(merchant).data)

    def put(self, request):
        merchant = self._get_merchant(request)
        if not merchant:
            return Response({'error': '未找到商家信息'},
                            status=status.HTTP_404_NOT_FOUND)

        serializer = MerchantDeliveryConfigSerializer(
            merchant, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        BusinessCache().delete_merchant(merchant.id)

        return Response({
            'message': '配送配置已更新',
            **serializer.data,
        })