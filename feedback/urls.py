from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import FeedbackViewSet, FeedbackAdminViewSet

router = DefaultRouter()
router.register(r'feedbacks', FeedbackViewSet, basename='feedback')
router.register(r'admin/feedbacks', FeedbackAdminViewSet, basename='admin-feedback')

urlpatterns = [
    path('', include(router.urls)),
]