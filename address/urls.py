# -*- coding: utf-8 -*-
# @Time    : 2026/4/16 17:08
# @Author  : Delock


from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ══════ 用户端路由 ══════
user_router = DefaultRouter()
user_router.register('', views.UserAddressViewSet, basename='user-address')


urlpatterns = [
    # 用户端
    path('user/addresses/', include(user_router.urls)),
]