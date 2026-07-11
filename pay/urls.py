# -*- coding: utf-8 -*-
# pay/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    # 用户端
    PaymentOrderViewSet, UserRefundViewSet,
    CreatePaymentView, WechatAppPayCreateView, AlipayPayCreateView,
    QueryPaymentView,
    # 虚拟支付（金币充值）
    CreateVirtualPaymentView,
    VirtualPaymentOrderListView, QueryVirtualPaymentView,
    virtual_pay_callback,
    # 商家端
    MerchantRefundViewSet,
    # 管理端
    AdminRefundViewSet,
    # 回调
    wechat_callback, alipay_callback, ClosePaymentView, ConfirmVirtualPaymentView, wx_message_push,
)

# 用户端
user_router = DefaultRouter()
user_router.register(r'payments', PaymentOrderViewSet, basename='payment')
user_router.register(r'refunds',  UserRefundViewSet,   basename='user-refund')

# 商家端
merchant_router = DefaultRouter()
merchant_router.register(r'refunds', MerchantRefundViewSet, basename='merchant-refund')

# 管理端
admin_router = DefaultRouter()
admin_router.register(r'refunds', AdminRefundViewSet, basename='admin-refund')


urlpatterns = [
    # ─── 用户端 ───
    path('', include(user_router.urls)),

    path('wechatpay/create_payment/', CreatePaymentView.as_view(), name='create_payment'),
    path('wechatpay/app/create/', WechatAppPayCreateView.as_view(), name='wechat_app_create_payment'),
    path('alipay/create/', AlipayPayCreateView.as_view(), name='alipay_create_payment'),
    path('wechatpay/query/', QueryPaymentView.as_view(), name='query_payment'),

    # ─── 商家端 ───
    path('merchant/', include(merchant_router.urls)),

    # ─── 管理端 ───
    path('admin/', include(admin_router.urls)),

    # ─── 微信异步回调 ───
    path('wechat_callback/<str:callback_type>/', wechat_callback, name='wechat_callback'),

    # ─── 支付宝异步回调 ───
    path('alipay_callback/', alipay_callback, name='alipay_callback'),

    path('wechatpay/close/', ClosePaymentView.as_view()),

    # ─── 微信小程序虚拟支付（金币充值） ───
    # POST /virtual/create/    创建虚拟支付订单（金额制，复用充值活动）
    # GET  /virtual/orders/    我的虚拟充值记录
    # GET  /virtual/query/     查询订单状态（主动补单）
    path('virtual/create/', CreateVirtualPaymentView.as_view(), name='create_virtual_payment'),
    path('virtual/orders/', VirtualPaymentOrderListView.as_view(), name='virtual_orders'),
    path('virtual/query/', QueryVirtualPaymentView.as_view(), name='query_virtual_payment'),
    path('virtual_pay/callback/', virtual_pay_callback, name='virtual_pay_callback'),

    path('virtual/confirm/', ConfirmVirtualPaymentView.as_view(), name='confirm_virtual_payment'),

    path('wx/message/push/', wx_message_push, name='wx_message_push'),
]