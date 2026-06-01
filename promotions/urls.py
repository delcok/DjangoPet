# -*- coding: utf-8 -*-
# @Time    : 2026/5/9 16:56
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AdminPaymentActivityViewSet,
    MerchantActivityViewSet,
    CreateRechargeView,
    RechargePreviewView,
    MyRechargeListView, UserRechargeActivitiesView, AdminPromotionsDashboardView,
)

admin_router = DefaultRouter()
admin_router.register(
    r'activities', AdminPaymentActivityViewSet, basename='admin-activity',
)

merchant_router = DefaultRouter()
merchant_router.register(
    r'activities', MerchantActivityViewSet, basename='merchant-activity',
)

urlpatterns = [
    path('admin/promotions/',    include(admin_router.urls)),
    path('merchant/promotions/', include(merchant_router.urls)),
    path('wallet/recharge/activities/', UserRechargeActivitiesView.as_view()),

    path('admin/promotions/dashboard/', AdminPromotionsDashboardView.as_view()),

    path('wallet/recharge/',         CreateRechargeView.as_view()),
    path('wallet/recharge/preview/', RechargePreviewView.as_view()),
    path('wallet/recharges/',        MyRechargeListView.as_view()),
]