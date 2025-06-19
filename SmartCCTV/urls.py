"""
URL configuration for SmartCCTV project.

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
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

from dashboard_api.views import serve_analytics_image

urlpatterns = [
       path('admin/', admin.site.urls),
       path('api/v1/cameras/', include('cameras.urls')),             # cameras 앱 URL 매핑
       path('api/v1/analytics/', include('analytics.urls')),         # analytics 앱 URL 매핑 (필요시)
       path('api/v1/', include('dashboard_api.urls')), # dashboard_api.urls 포함
       path('analytics/<path:filepath>', serve_analytics_image, name='serve_analytics_image'),
]
