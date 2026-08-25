from django.urls import path

from . import views

urlpatterns = [
    path('create/', views.create_post, name='create_post'),
    path('<uuid:post_id>/image/', views.post_image, name='post_image'),
    path('<uuid:post_id>/edit/', views.edit_post, name='edit_post'),
    path('<uuid:post_id>/delete/', views.delete_post, name='delete_post'),
    path('<uuid:post_id>/hide/', views.hide_post, name='hide_post'),
]
