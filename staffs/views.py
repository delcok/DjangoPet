# staffs/views.py

from datetime import datetime

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.authentication import (
    MerchantOrSubAuthentication,
    StaffAuthentication,
    generate_staff_tokens,
)
from utils.cache import LoginSecurityManager
from utils.permission import IsMerchant, IsStaff
from utils.send_sms import send_sms_code, verify_sms_code

from .models import Staff, StaffSchedule, StaffTimeSlot
from .serializers import (
    StaffAdminUpdateSerializer,
    StaffChangePasswordSerializer,
    StaffCreateSerializer,
    StaffDetailSerializer,
    StaffListSerializer,
    StaffPasswordLoginSerializer,
    StaffProfileSerializer,
    StaffResetPasswordByMerchantSerializer,
    StaffResetPasswordSerializer,
    StaffScheduleSerializer,
    StaffSendSMSSerializer,
    StaffSMSLoginSerializer,
    StaffSubmitVerificationSerializer,
    StaffTimeSlotSerializer,
    StaffUpdateSelfSerializer,
    StaffVerificationReviewSerializer,
)


# ══════════════════════════════════════════════════════════════
# 认证相关
# ══════════════════════════════════════════════════════════════

class StaffSendSMSCodeView(APIView):
    """POST /api/staff/auth/send-sms/  body: { phone, scene }"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StaffSendSMSSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        scene = serializer.validated_data['scene']

        if not Staff.objects.filter(phone=phone, status=Staff.Status.ACTIVE).exists():
            return Response(
                {'error': '该手机号未注册或账号已停用'},
                status=status.HTTP_404_NOT_FOUND
            )

        success, message, code = send_sms_code(phone, scene)
        response_data = {'message': message}
        if code:
            response_data['code'] = code

        if success:
            return Response(response_data)
        return Response(response_data, status=status.HTTP_400_BAD_REQUEST)


class StaffPasswordLoginView(APIView):
    """POST /api/staff/auth/login/password/"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StaffPasswordLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone    = serializer.validated_data['phone']
        password = serializer.validated_data['password']

        security = LoginSecurityManager()

        is_locked, remaining = security.is_locked(phone, 'staff')
        if is_locked:
            minutes = remaining // 60 + 1
            return Response(
                {'error': f'账户已锁定,请 {minutes} 分钟后重试'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            staff = Staff.objects.select_related('merchant').get(
                phone=phone, status=Staff.Status.ACTIVE
            )
        except Staff.DoesNotExist:
            return Response(
                {'error': '手机号或密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Staff.MultipleObjectsReturned:
            staff = Staff.objects.select_related('merchant').filter(
                phone=phone, status=Staff.Status.ACTIVE
            ).order_by('id').first()

        if not staff.check_password(password):
            fail_count, locked = security.record_fail(phone, 'staff')
            if locked:
                return Response(
                    {'error': '密码错误次数过多,账户已锁定 30 分钟'},
                    status=status.HTTP_403_FORBIDDEN
                )
            remaining = security.get_remaining_attempts(phone, 'staff')
            return Response(
                {'error': f'密码错误,还剩 {remaining} 次机会'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        return self._login_success(staff, security, phone)

    @staticmethod
    def _login_success(staff, security, phone):
        security.clear_fail_count(phone, 'staff')
        staff.last_login = datetime.now()
        staff.save(update_fields=['last_login'])
        tokens = generate_staff_tokens(staff)
        return Response({
            **tokens,
            'staff': StaffProfileSerializer(staff).data,
        })


class StaffSMSLoginView(APIView):
    """POST /api/staff/auth/login/sms/"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StaffSMSLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        code  = serializer.validated_data['code']

        valid, error = verify_sms_code(phone, code, 'login')
        if not valid:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            staff = Staff.objects.select_related('merchant').get(
                phone=phone, status=Staff.Status.ACTIVE
            )
        except Staff.DoesNotExist:
            return Response(
                {'error': '该手机号未注册或账号已停用'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Staff.MultipleObjectsReturned:
            staff = Staff.objects.select_related('merchant').filter(
                phone=phone, status=Staff.Status.ACTIVE
            ).order_by('id').first()

        security = LoginSecurityManager()
        return StaffPasswordLoginView._login_success(staff, security, phone)


class StaffResetPasswordView(APIView):
    """POST /api/staff/auth/reset-password/"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = StaffResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone        = serializer.validated_data['phone']
        code         = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']

        valid, error = verify_sms_code(phone, code, 'reset_password')
        if not valid:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            staff = Staff.objects.get(phone=phone, status=Staff.Status.ACTIVE)
        except Staff.DoesNotExist:
            return Response({'error': '该手机号未注册'}, status=status.HTTP_404_NOT_FOUND)

        staff.set_password(new_password)
        staff.token_version += 1
        staff.save(update_fields=['password', 'token_version'])

        return Response({'message': '密码重置成功'})


# ══════════════════════════════════════════════════════════════
# 员工端 - 自身信息管理
# ══════════════════════════════════════════════════════════════

class StaffProfileView(APIView):
    """
    GET  /api/staff/profile/
    PUT  /api/staff/profile/   仅修改非敏感字段
    """
    authentication_classes = [StaffAuthentication]
    permission_classes     = [IsStaff]

    def get(self, request):
        return Response(StaffProfileSerializer(request.user).data)

    def put(self, request):
        serializer = StaffUpdateSelfSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(StaffProfileSerializer(request.user).data)


class StaffSubmitVerificationView(APIView):
    """
    员工端 - 提交实名/住址/个人信息审核

    POST /api/staff/profile/verification/
    body: 含任意 EMPLOYEE_SUBMITTABLE_FIELDS 字段
    提交后 verification_status 变为 pending,审核期间不参与自动派单
    """
    authentication_classes = [StaffAuthentication]
    permission_classes     = [IsStaff]

    def post(self, request):
        serializer = StaffSubmitVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        staff = request.user
        try:
            staff.submit_verification(serializer.validated_data)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': '已提交审核,商家审核通过后生效',
            'verification_status': staff.verification_status,
            'pending_changes': staff.pending_changes,
            'verification_submitted_at': staff.verification_submitted_at,
        })


class StaffChangePasswordView(APIView):
    """POST /api/staff/change-password/"""
    authentication_classes = [StaffAuthentication]
    permission_classes     = [IsStaff]

    def post(self, request):
        serializer = StaffChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        staff = request.user
        if not staff.check_password(serializer.validated_data['old_password']):
            return Response({'error': '原密码错误'}, status=status.HTTP_400_BAD_REQUEST)

        staff.set_password(serializer.validated_data['new_password'])
        staff.token_version += 1
        staff.save(update_fields=['password', 'token_version'])

        return Response({'message': '密码修改成功'})


class StaffMyScheduleView(generics.ListAPIView):
    """GET /api/staff/schedules/"""
    authentication_classes = [StaffAuthentication]
    permission_classes     = [IsStaff]
    serializer_class       = StaffScheduleSerializer

    def get_queryset(self):
        qs        = StaffSchedule.objects.filter(staff=self.request.user)
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs.order_by('date')


class StaffMyTimeSlotsView(generics.ListAPIView):
    """GET /api/staff/time-slots/"""
    authentication_classes = [StaffAuthentication]
    permission_classes     = [IsStaff]
    serializer_class       = StaffTimeSlotSerializer

    def get_queryset(self):
        qs = StaffTimeSlot.objects.filter(
            staff=self.request.user,
            status__in=[StaffTimeSlot.Status.BOOKED, StaffTimeSlot.Status.LOCKED]
        )
        date = self.request.query_params.get('date')
        if date:
            qs = qs.filter(date=date)
        return qs.order_by('date', 'start_time')


# ══════════════════════════════════════════════════════════════
# 商家端 - 员工管理
# ══════════════════════════════════════════════════════════════

class MerchantStaffViewSet(viewsets.ModelViewSet):
    """
    商家端 - 员工 CRUD

    GET    /api/merchant/staffs/                    列表(支持 ?verification_status=pending 等过滤)
    POST   /api/merchant/staffs/                    创建
    GET    /api/merchant/staffs/{id}/               详情
    PUT    /api/merchant/staffs/{id}/               更新
    DELETE /api/merchant/staffs/{id}/               软删除(改为离职)
    POST   /api/merchant/staffs/{id}/reset_password/      重置密码
    POST   /api/merchant/staffs/{id}/toggle_status/       启用/暂停
    GET    /api/merchant/staffs/{id}/verification/        查看待审核详情(含对比)
    POST   /api/merchant/staffs/{id}/review_verification/ 审核 approve/reject
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes     = [IsMerchant]
    filter_backends        = [DjangoFilterBackend]

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        qs = Staff.objects.filter(
            merchant_id=merchant_id
        ).prefetch_related('service_categories')

        # ?verification_status=pending|unverified|approved|rejected
        verification_status = self.request.query_params.get('verification_status')
        if verification_status:
            qs = qs.filter(verification_status=verification_status)

        # ?status=active|inactive|suspended
        staff_status = self.request.query_params.get('status')
        if staff_status:
            qs = qs.filter(status=staff_status)

        # ?keyword=张三  (按 name / real_name / phone / employee_no 模糊搜索)
        keyword = self.request.query_params.get('keyword')
        if keyword:
            from django.db.models import Q
            qs = qs.filter(
                Q(name__icontains=keyword) |
                Q(real_name__icontains=keyword) |
                Q(phone__icontains=keyword) |
                Q(employee_no__icontains=keyword)
            )

        return qs.order_by('-is_recommended', '-sort_order', '-rating', 'id')

    def get_serializer_class(self):
        if self.action == 'list':
            return StaffListSerializer
        if self.action == 'create':
            return StaffCreateSerializer
        if self.action in ['update', 'partial_update']:
            return StaffAdminUpdateSerializer
        return StaffDetailSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['merchant'] = self._get_merchant()
        ctx['reviewer'] = self._get_reviewer_label()
        return ctx

    def perform_destroy(self, instance):
        # 软删除:标记为离职,不物理删除
        instance.status = Staff.Status.INACTIVE
        instance.leave_date = timezone.now().date()
        instance.work_status = Staff.WorkStatus.OFFLINE
        instance.save(update_fields=['status', 'leave_date', 'work_status', 'updated_at'])

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """商家重置员工密码"""
        staff      = self.get_object()
        serializer = StaffResetPasswordByMerchantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        staff.set_password(serializer.validated_data['password'])
        staff.token_version += 1
        staff.save(update_fields=['password', 'token_version'])

        return Response({'message': '密码已重置'})

    @action(detail=True, methods=['post'])
    def toggle_status(self, request, pk=None):
        """启用 / 暂停员工接单"""
        staff = self.get_object()

        if staff.status == Staff.Status.ACTIVE:
            staff.status = Staff.Status.SUSPENDED
            message = '已暂停接单'
        elif staff.status == Staff.Status.SUSPENDED:
            staff.status = Staff.Status.ACTIVE
            message = '已恢复接单'
        else:
            return Response(
                {'error': '离职员工不支持此操作，请使用恢复功能'},
                status=status.HTTP_400_BAD_REQUEST
            )

        staff.save(update_fields=['status'])
        return Response({'message': message, 'status': staff.status})

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """恢复离职员工为在职状态"""
        staff = self.get_object()

        if staff.status != Staff.Status.INACTIVE:
            return Response(
                {'error': '只有离职员工可以恢复'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 校验同商家下同手机号是否有其他在职员工（防止重复）
        if Staff.objects.filter(
            merchant_id=staff.merchant_id,
            phone=staff.phone,
            status=Staff.Status.ACTIVE
        ).exclude(id=staff.id).exists():
            return Response(
                {'error': '该手机号已有其他在职员工使用，无法恢复'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 恢复为在职状态
        staff.status = Staff.Status.ACTIVE
        staff.leave_date = None
        staff.work_status = Staff.WorkStatus.OFFLINE
        staff.token_version += 1  # 失效旧登录token，需要重新登录
        staff.save(update_fields=['status', 'leave_date', 'work_status', 'token_version', 'updated_at'])

        return Response({
            'message': '员工已恢复为在职状态',
            'status': staff.status,
            'need_relogin': True
        })

    @action(detail=True, methods=['get'])
    def verification(self, request, pk=None):
        """
        商家查看某员工的待审核详情
        返回当前已审核生效的字段值 + 待审核的字段值,前端可做对比展示
        """
        staff = self.get_object()
        current = {
            field: getattr(staff, field)
            for field in Staff.EMPLOYEE_SUBMITTABLE_FIELDS
        }
        # Decimal/date 转成字符串方便前端展示对比
        for k, v in current.items():
            if v is None:
                continue
            if hasattr(v, 'isoformat'):  # date
                current[k] = v.isoformat()
            elif not isinstance(v, (str, int, float, bool, list, dict)):
                current[k] = str(v)

        return Response({
            'verification_status': staff.verification_status,
            'pending_changes': staff.pending_changes,
            'current_values': current,
            'verification_remark': staff.verification_remark,
            'verification_submitted_at': staff.verification_submitted_at,
            'verified_at': staff.verified_at,
            'verified_by': staff.verified_by,
        })

    @action(detail=True, methods=['post'])
    def review_verification(self, request, pk=None):
        """
        商家审核 approve / reject
        body: { action: 'approve' | 'reject', remark?: str }
        """
        staff = self.get_object()
        serializer = StaffVerificationReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_type = serializer.validated_data['action']
        reviewer = self._get_reviewer_label()

        try:
            if action_type == 'approve':
                staff.approve_verification(reviewer=reviewer)
                message = '审核已通过,字段已生效'
            else:
                staff.reject_verification(
                    reason=serializer.validated_data.get('remark', ''),
                    reviewer=reviewer,
                )
                message = '审核已拒绝'
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': message,
            'verification_status': staff.verification_status,
            'verified_at': staff.verified_at,
            'verified_by': staff.verified_by,
        })

    # ── 商家身份解析(主账号 / 子账号兼容)────────────────
    def _get_merchant_id(self):
        auth = self.request.auth
        if not auth:
            return None
        if auth.get('merchant_id'):
            return auth['merchant_id']
        if auth.get('type') == 'merchant':
            return auth.get('user_id')
        return None

    def _get_merchant(self):
        from merchants.models import Merchant
        mid = self._get_merchant_id()
        if not mid:
            raise serializers.ValidationError('无法识别商家身份')
        return Merchant.objects.get(id=mid)

    def _get_reviewer_label(self):
        """审核人标识,写入 verified_by"""
        auth = self.request.auth or {}
        if auth.get('merchant_id'):
            # 子账号
            return f"子账号#{auth.get('user_id', '')}"
        if auth.get('type') == 'merchant':
            return f"商家#{auth.get('user_id', '')}"
        return '未知'

# ══════════════════════════════════════════════════════════════
# 员工端 - 派单 / 接单 / 转单
# ══════════════════════════════════════════════════════════════

class StaffDispatchViewSet(viewsets.GenericViewSet):
    """
    员工端 - 派单/转单相关接口

    GET    /api/staff/dispatches/                我的待接单/待确认转单列表
    POST   /api/staff/dispatches/{id}/accept/    接受派单
    POST   /api/staff/dispatches/{id}/reject/    拒绝派单
    POST   /api/staff/dispatches/{id}/request_transfer/  主动申请转出(基于已接单订单)
    """
    authentication_classes = [StaffAuthentication]
    permission_classes     = [IsStaff]

    def get_queryset(self):
        # 仅当前员工的 PENDING 派单(含初次派单和待确认转单)
        from bill.models import OrderTransfer
        return OrderTransfer.objects.filter(
            to_staff=self.request.user,
            status=OrderTransfer.Status.PENDING,
        ).select_related('order', 'from_staff').order_by('-created_at')

    def list(self, request):
        """我的待接单列表 — 按 confirm_deadline 倒数排序"""
        from bill.serializers import StaffPendingTransferSerializer
        qs = self.get_queryset()
        # 已经超时的不展示(避免员工点了空单)
        from django.utils import timezone
        qs = qs.filter(confirm_deadline__gt=timezone.now())
        ser = StaffPendingTransferSerializer(qs, many=True)
        return Response(ser.data)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """接受派单/转单"""
        from bill.services.dispatch import staff_accept
        try:
            order, record = staff_accept(int(pk), request.user.id)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'message': '接单成功',
            'order_id': order.id,
            'order_no': order.order_no,
            'order_status': order.status,
        })

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """拒绝派单 → 系统自动派给下一个候选员工"""
        from bill.services.dispatch import staff_reject
        reason = (request.data.get('reason') or '').strip()
        try:
            staff_reject(int(pk), request.user.id, reason=reason)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': '已拒绝,系统将派给其他员工'})

    @action(detail=False, methods=['post'], url_path=r'orders/(?P<order_id>\d+)/request_transfer')
    def request_transfer(self, request, order_id=None):
        """
        员工对自己已接单(ASSIGNED 状态)的订单申请转出。
        创建 PENDING 状态的 OrderTransfer,等系统/商家匹配下一员工。

        body: {
            to_staff_id?: int,       # 留空 = 系统自动匹配
            reason?: str,
            confirm_timeout_minutes?: int  # 默认 15
        }
        """
        from bill.models import ServiceOrder, OrderTransfer
        from bill.serializers import TransferRequestSerializer

        try:
            order = ServiceOrder.objects.get(id=order_id)
        except ServiceOrder.DoesNotExist:
            return Response({'error': '订单不存在'}, status=status.HTTP_404_NOT_FOUND)

        # 必须是当前员工自己的订单
        if order.assigned_staff_id != request.user.id:
            return Response(
                {'error': '只能转出自己负责的订单'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if order.status != ServiceOrder.Status.ASSIGNED:
            return Response(
                {'error': f'当前状态({order.get_status_display()})无法转出'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not order.can_transfer:
            return Response(
                {'error': f'已达最大转单次数 {order.max_transfer_count}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = TransferRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # 校验目标员工(如果指定了)
        to_staff = None
        to_staff_id = ser.validated_data.get('to_staff_id')
        if to_staff_id:
            try:
                to_staff = Staff.objects.get(
                    id=to_staff_id,
                    merchant_id=order.merchant_id,
                    status=Staff.Status.ACTIVE,
                )
            except Staff.DoesNotExist:
                return Response(
                    {'error': '目标员工不存在或不可接单'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if to_staff.id == request.user.id:
                return Response(
                    {'error': '不能转给自己'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 检查是否已有待确认转单(防止重复申请)
        if OrderTransfer.objects.filter(
            order=order, status=OrderTransfer.Status.PENDING,
        ).exists():
            return Response(
                {'error': '该订单已有待确认转单,请先取消'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from datetime import timedelta
        from django.utils import timezone
        from django.db import transaction

        timeout_min = ser.validated_data['confirm_timeout_minutes']
        deadline = timezone.now() + timedelta(minutes=timeout_min)

        with transaction.atomic():
            sequence = OrderTransfer.objects.filter(order=order).count() + 1
            record = OrderTransfer.objects.create(
                order=order,
                from_staff=request.user,
                to_staff=to_staff,                 # 可空 → 后续由商家或系统匹配
                initiated_by=OrderTransfer.InitiatedBy.STAFF,
                transfer_type=OrderTransfer.TransferType.VOLUNTARY,
                reason=ser.validated_data['reason'],
                status=OrderTransfer.Status.PENDING,
                sequence=sequence,
                confirm_deadline=deadline,
            )

        # 写日志
        try:
            from bill.serializers import create_order_log
            create_order_log(
                order.order_no, 'service', 'transfer',
                operator_type='staff',
                operator_id=request.user.id,
                description=f'员工 {request.user.name} 申请转单 → {to_staff.name if to_staff else "待匹配"}',
            )
        except Exception:
            pass

        # 如果指定了目标员工,立即给对方发短信通知
        if to_staff:
            try:
                from bill.tasks import task_send_sms
                transaction.on_commit(lambda: task_send_sms.delay(
                    phone=to_staff.phone,
                    template_code='order_transfer',
                    template_param={'name': to_staff.name},
                ))
            except Exception:
                pass

        return Response({
            'message': '转单已发起,等待确认',
            'transfer_id': record.id,
            'confirm_deadline': record.confirm_deadline,
        })


class MerchantStaffScheduleViewSet(viewsets.ModelViewSet):
    """商家端 - 员工排班管理"""
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes     = [IsMerchant]
    serializer_class       = StaffScheduleSerializer

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        staff_id    = self.kwargs.get('staff_id')
        return StaffSchedule.objects.filter(
            staff_id=staff_id,
            staff__merchant_id=merchant_id
        ).order_by('date')

    def perform_create(self, serializer):
        merchant_id = self._get_merchant_id()
        staff_id    = self.kwargs.get('staff_id')
        staff = Staff.objects.get(id=staff_id, merchant_id=merchant_id)
        serializer.save(staff=staff)

    def _get_merchant_id(self):
        auth = self.request.auth
        if not auth:
            return None
        if auth.get('merchant_id'):
            return auth['merchant_id']
        if auth.get('type') == 'merchant':
            return auth.get('user_id')
        return None