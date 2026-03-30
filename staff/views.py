from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response

from staff.models import Staff
from staff.serializers import StaffLoginSerializer, StaffInfoSerializer
from utils.authentication import generate_jwt_tokens, AdminAuthentication
from utils.permission import IsStaffAdmin


@api_view(['POST'])
@authentication_classes([])      # 登录接口无需认证
@permission_classes([])           # 登录接口无需权限
def staff_login(request):
    """
    管理员登录
    POST /staff/login/
    Body: { "phone": "...", "password": "..." }
    """
    ser = StaffLoginSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    phone = ser.validated_data['phone']
    password = ser.validated_data['password']

    # 1. 查找用户
    try:
        staff = Staff.objects.get(phone=phone)
    except Staff.DoesNotExist:
        return Response(
            {'code': 400, 'message': '账号或密码错误'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 2. 校验密码
    if not staff.check_password(password):
        return Response(
            {'code': 400, 'message': '账号或密码错误'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 3. 校验状态
    if not staff.is_active:
        return Response(
            {'code': 403, 'message': '该账号已被禁用'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # 4. 更新最后登录时间
    staff.last_login = timezone.now()
    # 用 update 避免触发 save() 里的密码重新加密
    Staff.objects.filter(pk=staff.pk).update(last_login=staff.last_login)

    # 5. 生成 JWT
    refresh_token, access_token = generate_jwt_tokens(staff, user_type='admin')

    return Response({
        'code': 200,
        'message': '登录成功',
        'data': {
            'access': access_token,
            'refresh': refresh_token,
            'staff': StaffInfoSerializer(staff).data,
        }
    })


@api_view(['GET'])
@authentication_classes([AdminAuthentication])
@permission_classes([IsStaffAdmin])
def staff_profile(request):
    """
    获取当前管理员信息
    GET /staff/profile/
    Header: Authorization: Bearer <access_token>
    """
    return Response({
        'code': 200,
        'data': StaffInfoSerializer(request.user).data,
    })