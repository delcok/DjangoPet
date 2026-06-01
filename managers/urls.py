# -*- coding: utf-8 -*-
# @Time    : 2026/4/7 18:52
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views


router = DefaultRouter()
router.register('roles', views.ManagerRoleViewSet, basename='role')
router.register('managers', views.ManagerViewSet, basename='manager')
router.register('logs', views.ManagerOperationLogViewSet, basename='log')
router.register('configs', views.SystemConfigViewSet, basename='config')

# ══════════════════════════════════════════════════════════════
# URL 配置
# ══════════════════════════════════════════════════════════════

urlpatterns = [
    # ══════ 认证相关 ══════
    path('admin/login/', views.ManagerLoginView.as_view(), name='manager-login'),
    path('admin/logout/', views.ManagerLogoutView.as_view(), name='manager-logout'),
    path('admin/change-password/', views.ManagerChangePasswordView.as_view(), name='manager-change-password'),

    # ══════ 个人信息 ══════
    path('admin/profile/', views.ManagerProfileView.as_view(), name='manager-profile'),

    # ══════ 仪表盘 ══════
    path('admin/dashboard/', views.DashboardView.as_view(), name='manager-dashboard'),

    # ══════ ViewSet 路由 ══════
    path('admin/', include(router.urls)),
]
