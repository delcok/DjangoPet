# -*- coding: utf-8 -*-
# @Time    : 2025/7/7 15:39
# @Author  : Delock
from rest_framework import permissions

from user.models import User, SuperAdmin


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    自定义权限：只有订单所有者或管理员可以访问
    """
    def has_object_permission(self, request, view, obj):
        # 普通用户只能访问自己的订单
        if isinstance(request.user, User):
            return obj.user == request.user
        # 超级管理员有所有权限
        if isinstance(request.user, SuperAdmin):
            return True
        return False

class IsUserOwner(permissions.BasePermission):
    """
    只有用户本人可以访问
    """
    def has_object_permission(self, request, view, obj):
        return isinstance(request.user, User) and request.user == obj



