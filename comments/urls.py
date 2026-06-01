# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()

# ── 用户评论 ──────────────────────────────────────
router.register(r'user/product-reviews', views.UserProductReviewViewSet, basename='user-product-review')
router.register(r'user/service-reviews', views.UserServiceReviewViewSet, basename='user-service-review')

# ── 商家评论管理 ───────────────────────────────────
router.register(r'merchant/product-reviews', views.MerchantProductReviewViewSet, basename='merchant-product-review')
router.register(r'merchant/service-reviews', views.MerchantServiceReviewViewSet, basename='merchant-service-review')

# ── 管理员评论管理 ─────────────────────────────────
router.register(r'admin/product-reviews', views.AdminProductReviewViewSet, basename='admin-product-review')
router.register(r'admin/service-reviews', views.AdminServiceReviewViewSet, basename='admin-service-review')

router.register(r'public/product-reviews', views.PublicProductReviewViewSet, basename='public-product-review')
router.register(r'public/service-reviews', views.PublicServiceReviewViewSet, basename='public-service-review')
urlpatterns = [
    path('', include(router.urls)),
]