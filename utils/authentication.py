# -*- coding: utf-8 -*-
# @Time    : 2025/7/7 16:02
# @Author  : Delock
import logging

from rest_framework_simplejwt.authentication import JWTAuthentication, AuthUser
from rest_framework_simplejwt.exceptions import InvalidToken
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.tokens import RefreshToken, Token
from user.models import User, SuperAdmin


# 自定义生成token
def generate_jwt_tokens(user, user_type='user'):
    """生成JWT token"""
    refresh = RefreshToken.for_user(user)
    refresh['type'] = user_type
    refresh['user_id'] = user.id

    access = refresh.access_token
    access['type'] = user_type
    access['user_id'] = user.id

    return str(refresh), str(access)

class UserAuthentication(JWTAuthentication):
    def get_user(self, validated_token: Token):
        try:
            user_id = validated_token['user_id']
        except KeyError:
            raise InvalidToken(_('Token contained no recognizable user identification'))
        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            raise InvalidToken(_('User not found'))
        return user


class AdminAuthentication(JWTAuthentication):
    def get_user(self, validated_token: Token):
        try:
            user_id = validated_token['user_id']
        except KeyError:
            raise InvalidToken(_('Token contained no recognizable user identification'))
        try:
            user = SuperAdmin.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            raise InvalidToken(_('User not found'))
        return user

