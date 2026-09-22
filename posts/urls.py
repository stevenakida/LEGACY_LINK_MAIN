from django.urls import path

from . import views

urlpatterns = [
    path('create/', views.create_post, name='create_post'),
    path('<uuid:post_id>/image/', views.post_image, name='post_image'),
    path('<uuid:post_id>/edit/', views.edit_post, name='edit_post'),
    path('<uuid:post_id>/delete/', views.delete_post, name='delete_post'),
    path('<uuid:post_id>/hide/', views.hide_post, name='hide_post'),
    path('<uuid:post_id>/report/', views.report_post, name='report_post'),
    path('<uuid:post_id>/report-media/', views.report_post_media, name='report_post_media'),
    path('<uuid:post_id>/like/', views.toggle_like, name='toggle_post_like'),
    path('<uuid:post_id>/comments/', views.list_comments, name='list_post_comments'),
    path('<uuid:post_id>/comments/add/', views.add_comment, name='add_post_comment'),
    path('comments/<uuid:comment_id>/delete/', views.delete_comment, name='delete_post_comment'),
]
