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
from django.urls import path, re_path, include
from django.conf import settings
from django.shortcuts import redirect
from django.contrib.auth import views as auth_views
from django.views.static import serve as serve_static
from . import views

urlpatterns = [
    path('', views.home, name='home'),
path('register/', views.register, name='register'),
    path('terms/', views.terms, name='terms'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('reset-password/<uidb64>/<token>/', views.reset_password_confirm, name='reset_password_confirm'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('opportunities/', views.opportunities_page, name='opportunities'),
    path('opportunities/<uuid:opportunity_id>/interest/', views.toggle_opportunity_interest, name='toggle_opportunity_interest'),
    path('schools/', lambda request: redirect('opportunities')),
    path('schools/search/', views.school_search, name='school_search'),
    path('schools/<int:school_id>/select/', views.select_school, name='select_school'),
    path('feedback/submit/', views.submit_feedback, name='submit_feedback'),
    path('connections/', views.connections, name='connections'),
    path('connections/connect/<uuid:user_id>/', views.send_connection_web, name='send_connection_web'),
    path('connections/respond/<uuid:connection_id>/', views.respond_connection_web, name='respond_connection_web'),
    path('cohort/', lambda request: redirect('/connections/?tab=discover'), name='cohort'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('messages/', views.messages_inbox, name='messages_inbox'),
    path('messages/start/<uuid:user_id>/', views.messages_start, name='messages_start'),
    path('messages/<uuid:conversation_id>/', views.messages_thread, name='messages_thread'),
    path('messages/<uuid:conversation_id>/poll/', views.messages_poll, name='messages_poll'),
    path('messages/<uuid:conversation_id>/earlier/', views.messages_earlier, name='messages_earlier'),
    path('messages/<uuid:conversation_id>/send/', views.messages_send, name='messages_send'),
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/alumni/', include('alumni.urls')),
    path('api/connections/', include('connections.urls')),
    path('api/opportunities/', include('opportunities.urls')),
    path('api/messaging/', include('messaging.urls')),
    # Serve user-uploaded media (avatars, etc.) unconditionally — Django's
    # static() helper only wires this up when DEBUG=True, which left avatars
    # 404ing in production and falling back to the initials placeholder.
    re_path(r'^media/(?P<path>.*)$', serve_static, {'document_root': settings.MEDIA_ROOT}),
]
