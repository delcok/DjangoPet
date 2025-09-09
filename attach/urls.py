# -*- coding: utf-8 -*-
# @Time    : 2025/8/22 19:16
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from attach import views

# 创建路由器
router = DefaultRouter()
router.register(r'', views.BannerViewSet, basename='banner')

# URL配置
urlpatterns = [
    # ViewSet自动生成的路由
    path('banners/', include(router.urls)),

]

