# care/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

# ── 用户端 ──
user_router = DefaultRouter()
user_router.register('ingredients', views.UserIngredientViewSet, basename='user-care-ingredient')
user_router.register('functional-tags', views.UserFunctionalTagViewSet, basename='user-care-tag')
user_router.register('recipes', views.UserRecipeViewSet, basename='user-care-recipe')
user_router.register('care-activities', views.UserCareActivityViewSet, basename='user-care-activity')
user_router.register('care-profiles', views.UserPetCareProfileViewSet, basename='user-care-profile')
user_router.register('care-plans', views.UserCarePlanViewSet, basename='user-care-plan')
user_router.register('care-tasks', views.UserCareTaskViewSet, basename='user-care-task')

# ── 管理端 ──
admin_router = DefaultRouter()
admin_router.register('ingredients', views.AdminIngredientViewSet, basename='admin-care-ingredient')
admin_router.register('functional-tags', views.AdminFunctionalTagViewSet, basename='admin-care-tag')
admin_router.register('feeding-rules', views.AdminFeedingRuleViewSet, basename='admin-care-feeding-rule')
admin_router.register('recipes', views.AdminRecipeViewSet, basename='admin-care-recipe')
admin_router.register('recipe-ingredients', views.AdminRecipeIngredientViewSet, basename='admin-care-recipe-ingredient')
admin_router.register('care-activities', views.AdminCareActivityViewSet, basename='admin-care-activity')
admin_router.register('care-rules', views.AdminCareRuleViewSet, basename='admin-care-rule')
admin_router.register('care-plans', views.AdminCarePlanViewSet, basename='admin-care-plan')
admin_router.register('care-tasks', views.AdminCareTaskViewSet, basename='admin-care-task')

urlpatterns = [
    path('care/', include([
        path('user/', include(user_router.urls)),
        path('admin/', include(admin_router.urls)),
    ])),
]