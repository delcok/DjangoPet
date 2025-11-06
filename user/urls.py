# -*- coding: utf-8 -*-
# @Time    : 2025/8/20 17:26
# @Author  : Delock
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from user import views

router = DefaultRouter()

router.register(r'addresses', views.UserAddressViewSet, basename='address')


urlpatterns = [
    path('', include(router.urls)),
    # 用户微信登录
    path('user/wechat-login/', views.wechat_login, name='wechat-login'),
    # 用户信息修改
    path('user/update/', views.update_avator_or_username, name='update-avator-or-username'),

    path('admin/login/', views.admin_login, name='admin-login'),

    path('user/integral/add/', views.add_integral, name='add-integral'),
    path('user/integral/deduct/', views.deduct_integral, name='deduct-integral'),
    path('user/integral/', views.get_integral, name='get-integral'),

    ]

