from django.urls import path

from . import views

urlpatterns = [
    path('init/', views.InitiateUploadView.as_view(), name='media_init'),
    path('<uuid:media_id>/complete/', views.CompleteUploadView.as_view(), name='media_complete'),
    path('<uuid:media_id>/status/', views.MediaStatusView.as_view(), name='media_status'),
    path('<uuid:media_id>/cancel/', views.CancelUploadView.as_view(), name='media_cancel'),
    path('<uuid:media_id>/preview/', views.MediaPreviewView.as_view(), name='media_preview'),
    path('<uuid:media_id>/download/', views.MediaDownloadView.as_view(), name='media_download'),
    path('<uuid:media_id>/', views.DeleteOrphanMediaView.as_view(), name='media_delete_orphan'),
    # Local-dev fallback proxy (only active when no S3-compatible bucket is
    # configured) — see storage.LocalMediaBackend / views.LocalUpload/DownloadProxyView.
    path('local-proxy/upload/', views.LocalUploadProxyView.as_view(), name='media_local_upload'),
    path('local-proxy/download/', views.LocalDownloadProxyView.as_view(), name='media_local_download'),
]
