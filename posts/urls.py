from django.urls import path

from . import views

urlpatterns = [
    path('create/', views.create_post, name='create_post'),
    path('<uuid:post_id>/image/', views.post_image, name='post_image'),
]
