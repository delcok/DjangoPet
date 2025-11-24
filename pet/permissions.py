# -*- coding: utf-8 -*-
# @Time    : 2025/10/20 18:56
# @Author  : Delock
from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    对象级权限：只允许对象的所有者编辑
    """

    def has_object_permission(self, request, view, obj):
        # 读取权限允许任何请求
        if request.method in permissions.SAFE_METHODS:
            return True

        # 写入权限只允许所有者
        return obj.author == request.user or request.user.type == 'admin'


class IsPetOwner(permissions.BasePermission):
    """
    宠物主人权限：只有宠物主人可以访问宠物信息
    """

    def has_object_permission(self, request, view, obj):

        # 宠物主人可以访问自己的宠物
        return obj.owner == request.user


class IsPetDiaryAuthor(permissions.BasePermission):
    """
    宠物日记作者权限：只有作者和宠物主人可以访问和编辑日记
    """

    def has_object_permission(self, request, view, obj):
        # 管理员可以访问所有内容

        # 宠物主人可以查看自己宠物的所有日记
        if obj.pet.author == request.user:
            return True

        # 日记作者可以编辑自己的日记
        if request.method in ['PUT', 'PATCH', 'DELETE']:
            return obj.author == request.user

        return False


class IsServiceProvider(permissions.BasePermission):
    """
    服务提供者权限：用于服务记录的创建和编辑
    """

    def has_permission(self, request, view):
        # 已认证用户可以访问
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):

        # 宠物主人可以查看服务记录
        pet = obj.pet
        if pet and pet.owner == request.user:
            # 主人只能查看和添加反馈，不能修改服务记录
            if request.method in permissions.SAFE_METHODS or view.action == 'add_feedback':
                return True
            return False

        # 服务提供者可以编辑自己创建的服务记录
        if obj.service_provider == request.user:
            return True

        return False


class IsOwnerOrServiceProvider(permissions.BasePermission):
    """
    综合权限：宠物主人或服务提供者
    用于宠物服务记录的访问控制
    """

    def has_object_permission(self, request, view, obj):

        # 宠物主人可以查看记录
        if hasattr(obj, 'related_order'):
            # 通过订单判断是否是宠物主人
            if obj.related_order.customer == request.user:
                return True

            # 服务提供者可以查看和编辑
            if obj.related_order.staff == request.user:
                return True

        return False
