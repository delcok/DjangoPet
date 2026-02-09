# -*- coding: utf-8 -*-
# @Time    : 2026/1/18 16:35
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    ProductViewSet,
    SKUViewSet,
    SpecificationViewSet,
    CartViewSet,
    OrderViewSet,
    FavoriteViewSet, mall_wechat_callback
)

# 创建路由器
router = DefaultRouter()

# 注册视图集
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'skus', SKUViewSet, basename='sku')
router.register(r'specifications', SpecificationViewSet, basename='specification')
router.register(r'cart', CartViewSet, basename='cart')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'favorites', FavoriteViewSet, basename='favorite')

# URL配置
urlpatterns = [
    path('mall/', include(router.urls)),

    path('mall/wechat_callback/payment/', mall_wechat_callback, name='mall-wechat-callback'),

]