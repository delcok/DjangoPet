# merchants/urls.py
"""
商家模块 URL 配置
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ══════════════════════════════════════════════════════════════
# 管理端路由
# ══════════════════════════════════════════════════════════════

admin_router = DefaultRouter()
admin_router.register('merchants', views.MerchantAdminViewSet, basename='admin-merchant')
admin_router.register('categories', views.MerchantCategoryAdminViewSet, basename='admin-category')
admin_router.register('districts', views.BusinessDistrictAdminViewSet, basename='admin-district')

# ══════════════════════════════════════════════════════════════
# URL 配置
# ══════════════════════════════════════════════════════════════

urlpatterns = [
    # ══════ 公共接口 ══════
    path('sms/send/', views.SendSMSCodeView.as_view(), name='send-sms'),

    # ══════ 商家登录 ══════
    path('merchant/login/password/', views.MerchantPasswordLoginView.as_view(), name='merchant-login-password'),
    path('merchant/login/sms/', views.MerchantSMSLoginView.as_view(), name='merchant-login-sms'),
    path('merchant/reset-password/', views.MerchantResetPasswordView.as_view(), name='merchant-reset-password'),

    # ══════ 商家端（需认证）══════
    path('merchant/profile/', views.MerchantProfileView.as_view(), name='merchant-profile'),
    path('merchant/onboarding/', views.MerchantOnboardingView.as_view(), name='merchant-onboarding'),  # ← 新增：入驻资料 读/暂存/提交
    path('merchant/change-password/', views.MerchantChangePasswordView.as_view(), name='merchant-change-password'),
    path('merchant/delivery-config/', views.MerchantDeliveryConfigView.as_view(), name='merchant-delivery-config'),
    path('merchant/bank-account/', views.MerchantBankAccountView.as_view(), name='merchant-bank-account'),

    # ══════ 用户端（公开）══════
    path('merchants/', views.MerchantListView.as_view(), name='merchant-list'),
    path('merchants/nearby/', views.NearbyMerchantView.as_view(), name='merchant-nearby'),
    path('merchants/recommended/', views.RecommendedMerchantView.as_view(), name='merchant-recommended'),
    path('merchants/search/', views.MerchantSearchView.as_view(), name='merchant-search'),
    path('merchants/categories/', views.MerchantCategoryListView.as_view(), name='category-list'),
    path('merchants/districts/', views.BusinessDistrictListView.as_view(), name='district-list'),
    path('merchants/<int:pk>/', views.MerchantDetailView.as_view(), name='merchant-detail'),

    # ══════ 管理后台 ══════
    path('admin/merchants/', include(admin_router.urls)),
]