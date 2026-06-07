# -*- coding: utf-8 -*-
# @Time    : 2026/4/23 20:01
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

# ── 管理端路由 ──
admin_router = DefaultRouter()
admin_router.register(
    r'positions',
    views.AdminHomepagePositionViewSet,
    basename='admin-homepage-position',
)

admin_router.register(
    r'sections',
    views.AdminHomepageSectionViewSet,
    basename='admin-homepage-section',
)


urlpatterns = [
    # ══════ 用户端（公开，无需认证） ══════
    path('homepage/positions/', views.HomepagePositionListView.as_view(), name='homepage-position-list'),
    path('homepage/sections/', views.HomepageSectionListView.as_view(), name='homepage-section-list'),  # 新增

    # ══════ 管理端 ══════
    path('admin/homepage/', include(admin_router.urls)),
]