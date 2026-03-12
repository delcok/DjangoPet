# -*- coding: utf-8 -*-
# @Time    : 2026/3/12 15:58
# @Author  : Delock

from django.urls import path
from .views import (
    # 管理员接口
    AdminPrizeListCreateView,
    AdminPrizeDetailView,
    AdminIssuePrizeView,
    AdminBatchIssuePrizeView,
    AdminUserPrizeListView,
    AdminUserPrizeDetailView,
    AdminUserPrizeProcessView,
    AdminUserPrizeRedeemView,
    AdminUserPrizeRejectView,
    AdminUserPrizeCancelView,

    # 用户接口
    UserPrizeListView,
    UserPrizeDetailView,
    UserPrizeClaimView,
    UserPrizeMarkReadView,
)

urlpatterns = [
    # =========================
    # 管理员接口
    # =========================
    path('admin/prizes/', AdminPrizeListCreateView.as_view(), name='admin-prize-list-create'),
    path('admin/prizes/<int:pk>/', AdminPrizeDetailView.as_view(), name='admin-prize-detail'),

    path('admin/user-prizes/issue/', AdminIssuePrizeView.as_view(), name='admin-user-prize-issue'),
    path('admin/user-prizes/batch-issue/', AdminBatchIssuePrizeView.as_view(), name='admin-user-prize-batch-issue'),

    path('admin/user-prizes/', AdminUserPrizeListView.as_view(), name='admin-user-prize-list'),
    path('admin/user-prizes/<int:pk>/', AdminUserPrizeDetailView.as_view(), name='admin-user-prize-detail'),

    path('admin/user-prizes/<int:pk>/process/', AdminUserPrizeProcessView.as_view(), name='admin-user-prize-process'),
    path('admin/user-prizes/<int:pk>/redeem/', AdminUserPrizeRedeemView.as_view(), name='admin-user-prize-redeem'),
    path('admin/user-prizes/<int:pk>/reject/', AdminUserPrizeRejectView.as_view(), name='admin-user-prize-reject'),
    path('admin/user-prizes/<int:pk>/cancel/', AdminUserPrizeCancelView.as_view(), name='admin-user-prize-cancel'),

    # =========================
    # 用户接口
    # =========================
    path('user/prizes/', UserPrizeListView.as_view(), name='user-prize-list'),
    path('user/prizes/<int:pk>/', UserPrizeDetailView.as_view(), name='user-prize-detail'),
    path('user/prizes/<int:pk>/claim/', UserPrizeClaimView.as_view(), name='user-prize-claim'),
    path('user/prizes/<int:pk>/read/', UserPrizeMarkReadView.as_view(), name='user-prize-read'),
]
