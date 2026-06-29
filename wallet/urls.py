# -*- coding: utf-8 -*-
"""
钱包模块路由

约定前缀(建议在项目总路由中挂载):
  /api/wallet/          -> 用户端
  /api/merchant/        -> 商户端
  /api/admin/wallet/    -> 管理端

注意:URL 本身不区分现金/金币,统一用 ?currency=cash|gold 或请求体中的
currency 字段来切换。这样的好处是新增币种不用动路由。
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'wallet'


# ════════════════════════════════════════════════════════════════
#                    用户端(C 端)
# ════════════════════════════════════════════════════════════════
user_urlpatterns = [
    path('me/',
         views.UserWalletView.as_view(),
         name='user-wallet-me'),
    # ─── 签到(更具体的 calendar / makeup 放在 sign-in/ 之前)───
    path('me/sign-in/calendar/',
         views.UserSignInCalendarView.as_view(),
         name='user-sign-in-calendar'),
    path('me/sign-in/makeup/',
         views.UserSignInMakeupView.as_view(),
         name='user-sign-in-makeup'),
    path('me/sign-in/',
         views.UserSignInView.as_view(),
         name='user-sign-in'),
    path('me/transactions/',
         views.UserWalletTransactionView.as_view(),
         name='user-wallet-transactions'),
    path('me/expiring-points/',
         views.UserExpiringPointsView.as_view(),
         name='user-expiring-points'),
]


# ════════════════════════════════════════════════════════════════
#                    商户端(B 端)
# ════════════════════════════════════════════════════════════════
merchant_router = DefaultRouter()
merchant_router.register(
    r'withdrawals',
    views.MerchantWithdrawalViewSet,
    basename='merchant-withdrawal',
)

merchant_urlpatterns = [
    # 非 ViewSet 路由
    path('wallet/',
         views.MerchantWalletView.as_view(),
         name='merchant-wallet'),
    path('wallet/transactions/',
         views.MerchantWalletTransactionView.as_view(),
         name='merchant-wallet-transactions'),
    path('wallet/settlement-config/',
         views.MerchantSettlementConfigView.as_view(),
         name='merchant-settlement-config'),
    # ViewSet 路由(提现)
    path('', include(merchant_router.urls)),
]


# ════════════════════════════════════════════════════════════════
#                    管理端
# ════════════════════════════════════════════════════════════════
admin_router = DefaultRouter()
admin_router.register(
    r'user-wallets',
    views.AdminUserWalletViewSet,
    basename='admin-user-wallet',
)
admin_router.register(
    r'merchant-wallets',
    views.AdminMerchantWalletViewSet,
    basename='admin-merchant-wallet',
)
admin_router.register(
    r'withdrawals',
    views.AdminWithdrawalViewSet,
    basename='admin-withdrawal',
)
# 🆕 签到记录管理(list / retrieve / stats)
admin_router.register(
    r'sign-ins',
    views.AdminUserSignInViewSet,
    basename='admin-sign-in',
)

admin_urlpatterns = [
    path('', include(admin_router.urls)),
    path(
        'user-wallet-transactions/<int:pk>/reverse/',
        views.AdminUserWalletTransactionReverseView.as_view(),
        name='admin-user-wallet-tx-reverse',
    ),
    # 🆕 签到奖励配置(GET 读 / PUT 改)
    path(
        'sign-in-config/',
        views.AdminSignInConfigView.as_view(),
        name='admin-sign-in-config',
    ),
]


# ════════════════════════════════════════════════════════════════
#                    汇总
# ════════════════════════════════════════════════════════════════
urlpatterns = [
    path('wallet/',       include((user_urlpatterns,     'user'))),
    path('merchant/',     include((merchant_urlpatterns, 'merchants'))),
    path('admin/wallet/', include((admin_urlpatterns,    'managers'))),
]