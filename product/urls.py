# goods/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

cart_router = DefaultRouter()
cart_router.register(r'cart', views.CartViewSet, basename='goods-cart')

# ── 商家端路由 ──────────────────────────────────────────
merchant_router = DefaultRouter()
merchant_router.register(r'goods', views.MerchantGoodsViewSet, basename='merchant-goods')
merchant_router.register(r'goods-groups', views.MerchantGoodsGroupViewSet, basename='merchant-goods-group')
merchant_router.register(r'goods-tags', views.MerchantGoodsTagViewSet, basename='merchant-goods-tag')
merchant_router.register(r'goods-brands', views.MerchantBrandViewSet, basename='merchant-goods-brand')  # ★ 新增


# 嵌套路由：商品下的规格和 SKU
spec_router = DefaultRouter()
spec_router.register(r'specs', views.MerchantGoodsSpecViewSet, basename='merchant-goods-spec')

sku_router = DefaultRouter()
sku_router.register(r'skus', views.MerchantGoodsSkuViewSet, basename='merchant-goods-sku')

spec_value_router = DefaultRouter()
spec_value_router.register(r'values', views.MerchantGoodsSpecValueViewSet, basename='merchant-goods-spec-value')

# ── 管理端路由 ──────────────────────────────────────────
admin_router = DefaultRouter()
admin_router.register(r'categories', views.AdminGoodsCategoryViewSet, basename='admin-goods-category')
admin_router.register(r'brands', views.AdminBrandViewSet, basename='admin-goods-brand')
admin_router.register(r'tags', views.AdminGoodsTagViewSet, basename='admin-goods-tag')
admin_router.register(r'goods', views.AdminGoodsViewSet, basename='admin-goods')

urlpatterns = [
    # ══════ 用户端（公开，无需认证） ══════
    path('goods/', views.GoodsListView.as_view(), name='goods-list'),
    path('goods/<int:pk>/', views.GoodsDetailView.as_view(), name='goods-detail'),
    path('goods/categories/', views.GoodsCategoryListView.as_view(), name='goods-category-list'),

    path('goods/categories/tree/', views.GoodsCategoryTreeView.as_view(), name='goods-category-tree'),  # ← 新增

    path('goods/brands/', views.BrandListView.as_view(), name='goods-brand-list'),
    path('goods/tags/', views.GoodsTagListView.as_view(), name='goods-tag-list'),

    # ══════ 用户端（需登录） ══════
    path('goods/favorite/', views.GoodsFavoriteView.as_view(), name='goods-favorite'),
    path('goods/favorite/<int:goods_id>/', views.GoodsFavoriteView.as_view(), name='goods-unfavorite'),
    path('goods/favorites/', views.GoodsFavoriteListView.as_view(), name='goods-favorite-list'),
    path('goods/freight-preview/', views.FreightPreviewView.as_view(), name='goods-freight-preview'),

    path('goods/', include(cart_router.urls)),

    # ══════ 商家端 ══════
    path('merchant/', include(merchant_router.urls)),
    # 嵌套：/api/merchant/goods/{goods_id}/specs/
    path('merchant/goods/<int:goods_id>/', include(spec_router.urls)),
    # 嵌套：/api/merchant/goods/{goods_id}/skus/
    path('merchant/goods/<int:goods_id>/', include(sku_router.urls)),
    # 嵌套：/api/merchant/goods/{goods_id}/specs/{spec_id}/values/
    path('merchant/goods/<int:goods_id>/specs/<int:spec_id>/', include(spec_value_router.urls)),

    # ══════ 管理端 ══════
    path('admin/goods/', include(admin_router.urls)),
]