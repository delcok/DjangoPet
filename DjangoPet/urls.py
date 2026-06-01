"""
URL configuration for DjangoPet project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),

    # 已检查
    path('api/v1/', include('attach.urls')),
    path('api/v1/', include('bill.urls')),
    path('api/v1/', include('feedback.urls')),
    path('api/v1/', include('community.urls')),
    path('api/v1/', include('user.urls')),
    path('api/v1/', include('points.urls')),
    path('api/v1/', include('pet.urls')),
    path('api/v1/', include('prize.urls')),
    path('api/v1/', include('strays.urls')),


    # 新加的
    path('api/v1', include('address.urls')),
    path('api/v1', include('attract.urls')),
    path('api/v1', include('wallet.urls')),
    path('api/v1', include('campaigns.urls')),
    path('api/v1', include('comments.urls')),
    path('api/v1', include('managers.urls')),
    path('api/v1', include('merchants.urls')),
    path('api/v1', include('pay.urls')),
    path('api/v1', include('product.urls')),
    path('api/v1', include('promotions.urls')),
    path('api/v1', include('services.urls')),
    path('api/v1', include('staffs.urls')),
    path('api/v1', include('wallet.urls')),
    path('api/v1', include('prize.urls'))
]
