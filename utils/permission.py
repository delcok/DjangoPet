# -*- coding: utf-8 -*-
# @Time    : 2025/7/7 15:39
# @Author  : Delock
from rest_framework import permissions

from staff.models import Staff
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
        return isinstance(request.user, User)

class AnyUser(permissions.BasePermission):
    """
    任何用户都可以访问
    """
    def has_permission(self, request, view):
        return True


class IsStaffAdmin(permissions.BasePermission):
    """
    仅 Staff 管理员可访问
    """
    def has_permission(self, request, view):
        return isinstance(request.user, Staff) and request.user.is_active


class IsUserClient(permissions.BasePermission):
    """
    仅普通用户可访问
    """
    def has_permission(self, request, view):
        return isinstance(request.user, User) and request.user.is_active