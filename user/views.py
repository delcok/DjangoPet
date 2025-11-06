from rest_framework.decorators import api_view, authentication_classes, action
from rest_framework.response import Response
from rest_framework import status, viewsets, permissions
from django.conf import settings
from rest_framework import filters
from django.utils import timezone
from wechatpy import WeChatClient
from wechatpy.crypto import WeChatWxaCrypto

from user.models import User, SuperAdmin, UserAddress
from user.serializers import UserSerializer, SuperAdminSerializer, UserAddressSerializer, UserAddressCreateSerializer
from utils.authentication import generate_jwt_tokens, UserAuthentication
from utils.fetch_number import fetch_phone_number
from django.db import transaction, models

from utils.permission import IsUserOwner


@api_view(['POST'])
def wechat_login(request):
    """
    微信小程序登录
    :param request:
    :return:
    """
    app_id = settings.MINI_PROGRAM_SETTINGS['USER']['APPID']
    app_secret = settings.MINI_PROGRAM_SETTINGS['USER']['APPSECRET']

    code = request.data.get('code')
    phone_code = request.data.get('phone_code')  # 获取微信小程序手机码，设置为可选
    iv = request.data.get('iv')  # 前端传来的iv
    encrypted_data = request.data.get('encryptedData')  # 前端传来的加密数据
    openid = request.data.get('openid')

    if openid:
        try:
            user = User.objects.get(openid=openid)
            if user.is_active:
                user.last_login = timezone.now()
                user.save()
                refresh, access = generate_jwt_tokens(user, 'user')
                return Response({
                    'refresh': refresh,
                    'access': access,
                    'user_info': UserSerializer(user).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({'error': '您已被禁用，请联系客服!'}, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            pass

    if not code:
        return Response({'error': 'Missing code'}, status=status.HTTP_400_BAD_REQUEST)

    wechat_client = WeChatClient(app_id, app_secret)
    try:
        # 通过 code 获取 session 信息
        result = wechat_client.wxa.code_to_session(code)
        session_key = result.get('session_key')
        openid = result.get('openid')
        unionid = result.get('unionid', '')

        if not openid:
            return Response({'error': 'Failed to get openid from WeChat'}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return Response({'error': f'Failed to get session from WeChat: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST)

    # 尝试通过 openid 查找用户
    try:
        user = User.objects.get(openid=openid)
        if user.is_active:
            user.last_login = timezone.now()
            user.save()
            refresh, access = generate_jwt_tokens(user, 'user')
            return Response({
                'refresh': refresh,
                'access': access,
                'user_info': UserSerializer(user).data,
                'openid': openid
            }, status=status.HTTP_200_OK)
        else:
            return Response({'error': '您已被禁用，请联系客服!'}, status=status.HTTP_400_BAD_REQUEST)
    except User.DoesNotExist:
        # 用户不存在，需要创建新用户
        if not phone_code:
            return Response({'error': 'User does not exist and phone_code is required to register'},
                            status=status.HTTP_400_BAD_REQUEST)

        # 获取 access_token
        try:
            token_data = wechat_client.fetch_access_token()
            access_token = token_data.get('access_token')
            if not access_token:
                return Response({'error': 'Failed to fetch access_token from WeChat'},
                                status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Failed to fetch access_token: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST)

        # 获取用户的手机号
        phone_number = fetch_phone_number(access_token, phone_code)
        if not phone_number:
            return Response({'error': 'Failed to fetch phone number'}, status=status.HTTP_400_BAD_REQUEST)

        # 解密用户信息
        try:
            crypto = WeChatWxaCrypto(session_key, iv, app_id)
            user_info = crypto.decrypt_message(encrypted_data)
        except Exception as e:
            return Response({'error': f'Failed to decrypt user information: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST)

        # 创建新用户
        username = f"铲屎官-{phone_number[-4:]}"
        try:
            user = User.objects.create(
                openid=openid,
                phone=phone_number,
                unionid=unionid,
                username=username,
                # 设置头像URL，根据用户信息中的头像
                avatar=user_info.get('avatarUrl', ''),
                gender='M' if user_info.get('gender') == 1 else 'F'
            )
            user.last_login = timezone.now()
            user.save()
        except Exception as e:
            return Response({'error': f'Failed to create user: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

        # 生成 JWT token
        refresh, access = generate_jwt_tokens(user, 'user')
        return Response({
            'refresh': refresh,
            'access': access,
            'user_info': UserSerializer(user).data,
            'openid': openid
        }, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@authentication_classes([UserAuthentication])
def update_avator_or_username(request):
    """更新用户头像和用户名"""
    try:
        user = request.user

        # 验证用户是否已认证
        if not user.is_authenticated:
            return Response(
                {'error': '用户未认证'},
                status=status.HTTP_401_UNAUTHORIZED
            )


        # 更新用户信息
        username = request.data.get('username')
        avatar_url = request.data.get('avatar_url')
        bio = request.data.get('bio')  # 添加个人简介更新

        updated_fields = []

        if username:
            user.username = username.strip()
            updated_fields.append('username')

        if avatar_url:
            # 根据User模型，字段名是avatar
            user.avatar = avatar_url
            updated_fields.append('avatar')

        if bio is not None:  # 允许设置为空字符串
            user.bio = bio.strip()
            updated_fields.append('bio')

        if not updated_fields:
            return Response(
                {'error': '没有提供需要更新的字段'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 保存更新
        user.save(update_fields=updated_fields + ['updated_at'])


        # 序列化用户数据返回
        serializer = UserSerializer(user)
        return Response({
            'message': '更新成功',
            'user': serializer.data,
            'updated_fields': updated_fields
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"更新用户信息失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response(
            {'error': f'更新失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def admin_login(request):
    """管理员/超级管理员登录"""
    username = request.data.get('username')
    password = request.data.get('password')

    if not username:
        return Response({'error': '请提供用户名'}, status=status.HTTP_400_BAD_REQUEST)

    UserModel = SuperAdmin
    token_type = 'super_admin'
    serializer_class = SuperAdminSerializer

    # 查找用户
    user = None
    if username:
        try:
            user = UserModel.objects.get(username=username, is_active=True)
        except UserModel.DoesNotExist:
            pass

    if not user:
        return Response({'error': '用户不存在或已被禁用'}, status=status.HTTP_400_BAD_REQUEST)

    # 密码登录
    if password:
        if user.check_password(password):
            user.last_login = timezone.now()
            user.save()
            refresh, access = generate_jwt_tokens(user, token_type)
            return Response({
                'refresh': refresh,
                'access': access,
                'user_info': serializer_class(user).data,
                'user_type': token_type
            }, status=status.HTTP_200_OK)
        else:
            return Response({'error': '密码错误'}, status=status.HTTP_400_BAD_REQUEST)


    return Response({'error': '请提供密码'}, status=status.HTTP_400_BAD_REQUEST)



@api_view(['POST'])
@authentication_classes([UserAuthentication])
def add_integral(request):
    """增加积分"""
    user = request.user
    amount = request.data.get('amount')

    if not amount or int(amount) <= 0:
        return Response({'error': '积分数量必须大于0'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            user.integral = models.F('integral') + int(amount)
            user.save(update_fields=['integral', 'updated_at'])
            user.refresh_from_db()

        return Response({
            'message': '积分增加成功',
            'integral': user.integral
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([UserAuthentication])
def deduct_integral(request):
    """扣除积分"""
    user = request.user
    amount = request.data.get('amount')

    if not amount or int(amount) <= 0:
        return Response({'error': '积分数量必须大于0'}, status=status.HTTP_400_BAD_REQUEST)

    if user.integral < int(amount):
        return Response({'error': '积分不足'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            user.integral = models.F('integral') - int(amount)
            user.save(update_fields=['integral', 'updated_at'])
            user.refresh_from_db()

        return Response({
            'message': '积分扣除成功',
            'integral': user.integral
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([UserAuthentication])
def get_integral(request):
    """查询积分"""
    return Response({
        'integral': request.user.integral
    }, status=status.HTTP_200_OK)


class UserAddressViewSet(viewsets.ModelViewSet):
    """用户地址管理ViewSet"""
    serializer_class = UserAddressSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsUserOwner]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'is_default']
    ordering = ['-is_default', '-created_at']

    def get_queryset(self):
        """只返回当前用户的地址"""
        return UserAddress.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        """根据action选择序列化器"""
        if self.action == 'create':
            return UserAddressCreateSerializer
        return UserAddressSerializer

    def perform_create(self, serializer):
        """创建地址时关联当前用户"""
        user = self.request.user

        # 如果用户没有地址，自动设为默认地址
        if not UserAddress.objects.filter(user=user).exists():
            serializer.validated_data['is_default'] = True

        # 如果设置为默认地址，取消其他默认地址
        if serializer.validated_data.get('is_default', False):
            UserAddress.objects.filter(user=user, is_default=True).update(is_default=False)

        serializer.save(user=user)

    def perform_update(self, serializer):
        """更新地址"""
        # 如果设置为默认地址，取消其他默认地址
        if serializer.validated_data.get('is_default', False):
            UserAddress.objects.filter(
                user=self.request.user,
                is_default=True
            ).exclude(id=serializer.instance.id).update(is_default=False)

        serializer.save()

    def perform_destroy(self, instance):
        """删除地址时的处理"""
        user = self.request.user
        is_default = instance.is_default

        # 删除地址
        instance.delete()

        # 如果删除的是默认地址，设置第一个地址为默认地址
        if is_default:
            first_address = UserAddress.objects.filter(user=user).first()
            if first_address:
                first_address.is_default = True
                first_address.save()

    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """设置为默认地址"""
        try:
            address = self.get_object()

            # 取消当前用户的所有默认地址
            UserAddress.objects.filter(
                user=request.user,
                is_default=True
            ).update(is_default=False)

            # 设置当前地址为默认
            address.is_default = True
            address.save()

            return Response({
                'message': '已设置为默认地址',
                'address': UserAddressSerializer(address).data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                'error': f'设置默认地址失败: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def default(self, request):
        """获取默认地址"""
        try:
            default_address = UserAddress.objects.filter(
                user=request.user,
                is_default=True
            ).first()

            if default_address:
                return Response({
                    'address': UserAddressSerializer(default_address).data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'message': '暂无默认地址'
                }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                'error': f'获取默认地址失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """地址统计信息"""
        user = request.user
        queryset = self.get_queryset()

        total = queryset.count()
        has_default = queryset.filter(is_default=True).exists()

        # 按省份统计
        province_stats = {}
        for address in queryset:
            province = address.province or '未知'
            province_stats[province] = province_stats.get(province, 0) + 1

        return Response({
            'total': total,
            'has_default': has_default,
            'province_stats': province_stats
        }, status=status.HTTP_200_OK)

    def list(self, request, *args, **kwargs):
        """重写列表方法，添加额外信息"""
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        return Response({
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)


# 如果需要单独的地址相关功能视图，可以添加以下函数式视图

@api_view(['POST'])
@authentication_classes([UserAuthentication])
def quick_create_address(request):
    """快速创建地址（用于下单时）"""
    try:
        user = request.user

        if not user.is_authenticated:
            return Response(
                {'error': '用户未认证'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = UserAddressCreateSerializer(
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            # 如果用户没有地址，自动设为默认地址
            if not UserAddress.objects.filter(user=user).exists():
                serializer.validated_data['is_default'] = True

            # 如果设置为默认地址，取消其他默认地址
            if serializer.validated_data.get('is_default', False):
                UserAddress.objects.filter(user=user, is_default=True).update(is_default=False)

            address = serializer.save(user=user)

            return Response({
                'message': '地址创建成功',
                'address': UserAddressSerializer(address).data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return Response({
            'error': f'创建地址失败: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([UserAuthentication])
def get_address_suggestions(request):
    """获取地址建议（基于用户历史地址）"""
    try:
        user = request.user

        if not user.is_authenticated:
            return Response(
                {'error': '用户未认证'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 获取用户最近使用的省市区
        recent_addresses = UserAddress.objects.filter(user=user).order_by('-updated_at')[:10]

        suggestions = {
            'provinces': [],
            'cities': [],
            'districts': [],
            'recent_receivers': []
        }

        provinces_set = set()
        cities_set = set()
        districts_set = set()
        receivers_set = set()

        for addr in recent_addresses:
            if addr.province:
                provinces_set.add(addr.province)
            if addr.city:
                cities_set.add(addr.city)
            if addr.district:
                districts_set.add(addr.district)
            if addr.receiver_name:
                receivers_set.add(addr.receiver_name)

        suggestions['provinces'] = list(provinces_set)
        suggestions['cities'] = list(cities_set)
        suggestions['districts'] = list(districts_set)
        suggestions['recent_receivers'] = list(receivers_set)

        return Response(suggestions, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'error': f'获取地址建议失败: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)