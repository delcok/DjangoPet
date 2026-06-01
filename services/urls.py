# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()

# 公开接口（无需 token）
router.register(r'services', views.PublicServiceViewSet, basename='public-service')
router.register(r'categories', views.PublicCategoryViewSet, basename='public-category')


# 用户端（需要 token）
router.register(r'user/favorites', views.ServiceFavoriteViewSet, basename='user-favorite')
# 商家端
router.register(r'merchant/services', views.MerchantServiceViewSet, basename='merchant-services')
# 管理员端
router.register(r'admin/services/admin/services', views.AdminServiceViewSet, basename='admin-services')
router.register(r'admin/services/admin/categories', views.AdminCategoryViewSet, basename='admin-categories')

urlpatterns = [
    path('', include(router.urls)),

]