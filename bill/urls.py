# -*- coding: utf-8 -*-
# @Time    : 2025/8/25 16:09
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from bill.views import (
    wechat_callback, CreatePaymentView,
    BillViewSet, ServiceOrderViewSet
)

# 创建路由器
router = DefaultRouter()
router.register(r'bills', BillViewSet, basename='bill')
router.register(r'service-orders', ServiceOrderViewSet, basename='serviceorder')

urlpatterns = [
    # API路由
    path('api/', include(router.urls)),

    # 支付相关
    path('wechat_callback/<str:callback_type>/', wechat_callback, name='wechat_pay_notify'),
    path('wechatpay/create_payment/', CreatePaymentView.as_view(), name='create_payment'),
]