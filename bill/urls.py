# bill/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ── 用户端 ──
user_router = DefaultRouter()
user_router.register('product-orders', views.UserProductOrderViewSet, basename='user-product-order')
user_router.register('service-orders', views.UserServiceOrderViewSet, basename='user-service-order')

# ── 商家端 ──
merchant_router = DefaultRouter()
merchant_router.register('product-orders', views.MerchantProductOrderViewSet, basename='merchant-product-order')
merchant_router.register('service-orders', views.MerchantServiceOrderViewSet, basename='merchant-service-order')

# ── 员工端 ──
staff_router = DefaultRouter()
staff_router.register('service-orders', views.StaffServiceOrderViewSet, basename='staff-service-order')

# ── 管理端 ──
admin_router = DefaultRouter()
admin_router.register('product-orders', views.AdminProductOrderViewSet, basename='admin-product-order')
admin_router.register('service-orders', views.AdminServiceOrderViewSet, basename='admin-service-order')
admin_router.register('order-logs', views.AdminOrderLogViewSet, basename='admin-order-log')

urlpatterns = [
    # ── 用户端 ──
    path('user/order-counts/', views.UserOrderCountsView.as_view(), name='user-order-counts'),
    path('user/', include(user_router.urls)),

    # ── 商家端 ──
    # ★ 商家首页统计(放在 merchant_router 前面,避免被 router 拦截)
    path('merchant/dashboard-stats/',
         views.MerchantDashboardStatsView.as_view(),
         name='merchant-dashboard-stats'),

    # ★ 商家订单统计接口
    path('merchant/orders/stats/',
         views.MerchantOrderStatsView.as_view(),
         name='merchant-order-stats'),
    path('merchant/dashboard/',
         views.MerchantDashboardView.as_view(),
         name='merchant-dashboard'),

    # ★ 统一核销接口(同样放在 router 前)
    path('merchant/orders/verify-by-code/',
         views.MerchantUnifiedVerifyView.as_view(),
         name='merchant-unified-verify'),

    path('merchant/', include(merchant_router.urls)),

    # ── 员工端 ──
    path('staff/', include(staff_router.urls)),

    # ── 管理端 ──
    path('admin/', include(admin_router.urls)),
]