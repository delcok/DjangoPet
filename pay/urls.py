# -*- coding: utf-8 -*-
# pay/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    # 用户端
    PaymentOrderViewSet, UserRefundViewSet,
    CreatePaymentView, WechatAppPayCreateView, AlipayPayCreateView,
    QueryPaymentView,
    # 商家端
    MerchantRefundViewSet,
    # 管理端
    AdminRefundViewSet,
    # 回调
    wechat_callback, alipay_callback, ClosePaymentView,
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
    # GET  /payments/                     支付单列表
    # GET  /payments/{id}/                支付单详情
    # GET  /refunds/                      我的退款单列表
    # GET  /refunds/{id}/                 退款单详情
    path('', include(user_router.urls)),

    # POST /wechatpay/create_payment/     微信小程序创建支付（原有稳定接口）
    # POST /wechatpay/query/              查询支付
    path('wechatpay/create_payment/', CreatePaymentView.as_view(), name='create_payment'),
    # APP端专用支付接口
    path('wechatpay/app/create/', WechatAppPayCreateView.as_view(), name='wechat_app_create_payment'),
    path('alipay/create/', AlipayPayCreateView.as_view(), name='alipay_create_payment'),
    path('wechatpay/query/',          QueryPaymentView.as_view(),  name='query_payment'),

    # ─── 商家端 ───
    # GET  /merchant/refunds/             退款列表
    # GET  /merchant/refunds/{id}/        退款详情
    # POST /merchant/refunds/approve/     同意退款
    # POST /merchant/refunds/reject/      拒绝退款
    path('merchant/', include(merchant_router.urls)),

    # ─── 管理端 ───
    # GET  /admin/refunds/                退款列表(全部)
    # GET  /admin/refunds/{id}/           退款详情
    # POST /admin/refunds/approve/        同意退款(可强制)
    # POST /admin/refunds/reject/         拒绝退款
    path('admin/', include(admin_router.urls)),

    # ─── 微信异步回调 ───
    # callback_type: payment / refund
    path('wechat_callback/<str:callback_type>/', wechat_callback, name='wechat_callback'),

    # ─── 支付宝异步回调 ───
    path('alipay_callback/', alipay_callback, name='alipay_callback'),

    path('wechatpay/close/', ClosePaymentView.as_view()),
]