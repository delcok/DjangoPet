# -*- coding: utf-8 -*-
# @Time    : 2026/4/6 16:11
# @Author  : Delock
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    # ═══════════════════ 用户端 ═══════════════════
    # 微信登录
    path('user/wechat-login/', views.wechat_login, name='wechat-login'),
    # 用户信息
    path('user/info/', views.get_user_info, name='user-info'),
    path('user/update/', views.update_user_info, name='user-update'),
    # Token 刷新
    path('user/auth/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
# ═══════════════════ App 端 - 短信验证码登录 ═══════════════════
    path('user/sms/send/', views.send_sms_code_api, name='user-sms-send'),
    path('user/sms-login/', views.sms_login, name='user-sms-login'),

    # ═══════════════════ 管理员端 - 用户管理 ═══════════════════
    # 列表 / 详情 / 编辑
    path('admin/users/', views.admin_user_list, name='admin-user-list'),
    path('admin/users/stats/', views.admin_user_stats, name='admin-user-stats'),
    path('admin/users/<int:user_id>/', views.admin_user_detail, name='admin-user-detail'),
    path('admin/users/<int:user_id>/update/', views.admin_update_user, name='admin-user-update'),

# 资料审核（头像/昵称）
    path('admin/profile-audits/', views.admin_profile_audit_list, name='admin-profile-audit-list'),
    path('admin/profile-audits/<int:audit_id>/review/', views.admin_review_profile_audit, name='admin-profile-audit-review'),

    # 状态管理
    path('admin/users/<int:user_id>/ban/', views.admin_ban_user, name='admin-user-ban'),
    path('admin/users/<int:user_id>/toggle-active/', views.admin_toggle_active, name='admin-user-toggle-active'),
    # VIP 管理
    path('admin/users/<int:user_id>/vip/', views.admin_set_vip, name='admin-user-set-vip'),
    path('admin/users/<int:user_id>/vip/cancel/', views.admin_cancel_vip, name='admin-user-cancel-vip'),
    # 实名认证
    path('admin/users/<int:user_id>/verify/', views.admin_verify_user, name='admin-user-verify'),
    # 等级 / 经验
    path('admin/users/<int:user_id>/level/', views.admin_change_level, name='admin-user-change-level'),
    # 重置密码
    path('admin/users/<int:user_id>/reset-password/', views.admin_reset_password, name='admin-user-reset-password'),
    # 登录日志
    path('admin/users/<int:user_id>/login-logs/', views.admin_user_login_logs, name='admin-user-login-logs'),
    path('admin/login-logs/', views.admin_login_logs, name='admin-login-logs'),

    # ═══════════════════ 邀请好友 ═══════════════════
    path('user/invite/summary/', views.get_invite_summary_api, name='user-invite-summary'),
    path('user/invite/records/', views.get_invite_records, name='user-invite-records'),

    # ═══════════════════ 转赠金币 ═══════════════════
    path('user/transfer/lookup/', views.transfer_lookup, name='user-transfer-lookup'),
    path('user/transfer/', views.transfer_gold, name='user-transfer'),
]