# -*- coding: utf-8 -*-
# @Time    : 2026/1/3 18:56
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'products', views.IntegralProductViewSet, basename='integral-product')
router.register(r'orders', views.IntegralOrderViewSet, basename='integral-order')
router.register(r'records', views.IntegralRecordViewSet, basename='integral-record')
router.register(r'virtual-products', views.UserIntegralProductViewSet, basename='virtual-product')

urlpatterns = [
    path('integral/', include(router.urls)),
]