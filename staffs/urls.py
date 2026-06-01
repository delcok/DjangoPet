from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register(r'merchant/staffs', views.MerchantStaffViewSet, basename='merchant-staff')

staff_router = DefaultRouter()
staff_router.register(
    r'dispatches',
    views.StaffDispatchViewSet,
    basename='staff-dispatch',
)

# 排班路由需要嵌套 staff_id
schedule_router = DefaultRouter()
schedule_router.register(r'schedules', views.MerchantStaffScheduleViewSet, basename='staff-schedule')


urlpatterns = [
    # ── 员工认证 ──────────────────────────────────────
    path('staff/auth/send-sms/',        views.StaffSendSMSCodeView.as_view(),    name='staff-send-sms'),
    path('staff/auth/login/password/',  views.StaffPasswordLoginView.as_view(),  name='staff-login-password'),
    path('staff/auth/login/sms/',       views.StaffSMSLoginView.as_view(),       name='staff-login-sms'),
    path('staff/auth/reset-password/',  views.StaffResetPasswordView.as_view(),  name='staff-reset-password'),

    # ── 员工自身管理 ───────────────────────────────────
    path('staff/profile/',               views.StaffProfileView.as_view(),             name='staff-profile'),
    path('staff/profile/verification/',  views.StaffSubmitVerificationView.as_view(),  name='staff-submit-verification'),
    path('staff/change-password/',       views.StaffChangePasswordView.as_view(),      name='staff-change-password'),
    path('staff/schedules/',             views.StaffMyScheduleView.as_view(),          name='staff-my-schedules'),
    path('staff/time-slots/',            views.StaffMyTimeSlotsView.as_view(),         name='staff-my-timeslots'),

    path('staff/', include(staff_router.urls)),

    # ── 商家管理员工 ───────────────────────────────────
    # 自动生成的审核接口:
    #   GET  /api/merchant/staffs/{id}/verification/
    #   POST /api/merchant/staffs/{id}/review_verification/
    path('', include(router.urls)),
    path('merchant/staffs/<int:staff_id>/', include(schedule_router.urls)),
]