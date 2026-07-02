"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('schools/', views.schools, name='schools'),
    path('schools/<int:school_id>/select/', views.select_school, name='select_school'),
    path('connections/', views.connections, name='connections'),
    path('cohort/', views.cohort, name='cohort'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/alumni/', include('alumni.urls')),
    path('api/connections/', include('connections.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
