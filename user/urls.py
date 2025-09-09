# -*- coding: utf-8 -*-
# @Time    : 2025/8/20 17:26
# @Author  : Delock
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from user import views

router = DefaultRouter()


urlpatterns = [
    # 用户微信登录
    path('user/wechat-login/', views.wechat_login, name='wechat-login'),
    # 用户信息修改
    path('user/update/', views.update_avator_or_username, name='update-avator-or-username'),

    path('admin/login/', views.admin_login, name='admin-login'),

    ]

