# -*- coding: utf-8 -*-
from rest_framework.routers import DefaultRouter
from .views import (
    CouponTemplateViewSet,
    CampaignAdminViewSet,
    CampaignClientViewSet,
    MyCouponViewSet,
    RedemptionViewSet,
    # ★ 新增
    MerchantCouponTemplateViewSet,
    MerchantCampaignViewSet,
    MerchantRedemptionViewSet,
)

router = DefaultRouter()

# 管理端
router.register(r'admin/coupon-templates', CouponTemplateViewSet, basename='admin-coupon-template')
router.register(r'admin/campaigns', CampaignAdminViewSet, basename='admin-campaign')
router.register(r'admin/redemption', RedemptionViewSet, basename='admin-redemption')

# 商户端(★ 新增)
router.register(r'merchant/coupon-templates', MerchantCouponTemplateViewSet,
                basename='merchant-coupon-template')
router.register(r'merchant/campaigns', MerchantCampaignViewSet,
                basename='merchant-campaign')
router.register(r'merchant/redemption', MerchantRedemptionViewSet,
                basename='merchant-redemption')

# 小程序端
router.register(r'client/campaigns', CampaignClientViewSet, basename='client-campaign')
router.register(r'client/my-coupons', MyCouponViewSet, basename='client-my-coupon')

urlpatterns = router.urls