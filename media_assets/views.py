from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, Http404
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .exceptions import MediaValidationError
from .models import MediaAsset
from .permissions import IsMediaOwner
from .serializers import InitiateUploadSerializer, MediaAssetSerializer
from .storage import LocalMediaBackend, get_media_backend


class InitiateUploadView(APIView):
    """POST /api/media/init/ — step 1-4 of the upload flow: verifies the
    authenticated user, feature flag and declared type/size, creates a
    pending MediaAsset, and returns a short-lived upload URL for a
    quarantine storage key."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = InitiateUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            asset, upload_url = services.initiate_upload(
                user=request.user,
                category=data['category'],
                filename=data['filename'],
                declared_mime_type=data.get('declared_mime_type', ''),
                declared_size_bytes=data['declared_size_bytes'],
            )
        except services.MediaFeatureDisabled as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except MediaValidationError as e:
            return Response({'error': e.reason}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'media': MediaAssetSerializer(asset).data,
            'upload_url': upload_url,
            'upload_method': 'PUT',
            'upload_url_expires_at': asset.upload_url_expires_at,
        }, status=status.HTTP_201_CREATED)


class _OwnedMediaMixin:
    permission_classes = [permissions.IsAuthenticated, IsMediaOwner]

    def get_asset(self, request, media_id):
        asset = get_object_or_404(MediaAsset, pk=media_id)
        self.check_object_permissions(request, asset)
        return asset


class CompleteUploadView(_OwnedMediaMixin, APIView):
    """POST /api/media/<id>/complete/ — steps 6-10: verifies the object
    landed in storage, validates real content/size/signature, scans and
    processes it, and only then flips it to READY. Idempotent — calling
    this again on an already-processed (or in-flight) asset just returns
    its current state rather than reprocessing."""

    def post(self, request, media_id):
        asset = self.get_asset(request, media_id)
        asset = services.complete_upload(asset.id)
        return Response(MediaAssetSerializer(asset).data)


class MediaStatusView(_OwnedMediaMixin, APIView):
    def get(self, request, media_id):
        asset = self.get_asset(request, media_id)
        return Response(MediaAssetSerializer(asset).data)


class CancelUploadView(_OwnedMediaMixin, APIView):
    def post(self, request, media_id):
        asset = self.get_asset(request, media_id)
        try:
            asset = services.cancel_upload(asset)
        except MediaValidationError as e:
            return Response({'error': e.reason}, status=status.HTTP_409_CONFLICT)
        return Response(MediaAssetSerializer(asset).data)


class DeleteOrphanMediaView(_OwnedMediaMixin, APIView):
    """DELETE /api/media/<id>/ — only ever for media not yet attached to a
    message or post; attached media's lifecycle belongs to whatever it's
    attached to, added in a later phase."""

    def delete(self, request, media_id):
        asset = self.get_asset(request, media_id)
        try:
            asset = services.delete_orphan(asset)
        except MediaValidationError as e:
            return Response({'error': e.reason}, status=status.HTTP_409_CONFLICT)
        return Response(MediaAssetSerializer(asset).data)


class MediaPreviewView(_OwnedMediaMixin, APIView):
    """GET /api/media/<id>/preview/ — redirects to a short-lived signed URL
    for the thumbnail (falls back to the full asset if there is none).
    Never returns a permanent URL, and only after ownership is checked
    above and MediaAsset.is_downloadable passes (READY, not on hold, and
    CLEAN if it's a document)."""

    def get(self, request, media_id):
        asset = self.get_asset(request, media_id)
        url = services.get_preview_url(asset)
        if not url:
            return Response({'error': 'media is not currently available'}, status=status.HTTP_404_NOT_FOUND)
        return HttpResponseRedirect(url)


class MediaDownloadView(_OwnedMediaMixin, APIView):
    """GET /api/media/<id>/download/ — same authorization/availability gate
    as preview, redirecting to a signed URL for the full processed file."""

    def get(self, request, media_id):
        asset = self.get_asset(request, media_id)
        url = services.get_download_url(asset)
        if not url:
            return Response({'error': 'media is not currently available'}, status=status.HTTP_404_NOT_FOUND)
        return HttpResponseRedirect(url)


# ---------------------------------------------------------------------------
# Local-dev-only proxy views. Only reachable when MEDIA_ASSETS_S3_ENABLED is
# False (no bucket credentials configured) — LocalMediaBackend hands out
# URLs to these instead of real presigned S3 URLs. Not JWT/session
# authenticated, by design: the signed, expiring token in the query string
# IS the authorization, exactly like a real presigned URL's signature — the
# authenticated init/complete/status/preview/download endpoints above are
# what decide who ever receives one of these URLs in the first place.
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name='dispatch')
class LocalUploadProxyView(View):
    def put(self, request, *args, **kwargs):
        return self._handle(request)

    def post(self, request, *args, **kwargs):
        return self._handle(request)

    def _handle(self, request):
        backend = get_media_backend()
        if not isinstance(backend, LocalMediaBackend):
            return HttpResponse('local upload proxy is not active', status=404)

        token = request.GET.get('token', '')
        if not token:
            return HttpResponseBadRequest('missing token')
        try:
            payload = LocalMediaBackend.unsign_upload_token(
                token, max_age=settings.MEDIA_ASSETS_UPLOAD_URL_TTL_SECONDS,
            )
        except Exception:
            return HttpResponse('upload URL is invalid or has expired', status=403)

        max_bytes = max(
            settings.MEDIA_ASSETS_IMAGE_MAX_BYTES,
            settings.MEDIA_ASSETS_VIDEO_MAX_BYTES,
            settings.MEDIA_ASSETS_DOCUMENT_MAX_BYTES,
        )
        body = request.body
        if len(body) > max_bytes:
            return HttpResponse('payload too large', status=413)

        backend.write_bytes(payload['key'], body)
        return HttpResponse(status=200)


@method_decorator(csrf_exempt, name='dispatch')
class LocalDownloadProxyView(View):
    def get(self, request, *args, **kwargs):
        backend = get_media_backend()
        if not isinstance(backend, LocalMediaBackend):
            return HttpResponse('local download proxy is not active', status=404)

        token = request.GET.get('token', '')
        try:
            payload = LocalMediaBackend.unsign_download_token(
                token, max_age=settings.MEDIA_ASSETS_SIGNED_URL_TTL_SECONDS,
            )
        except Exception:
            return HttpResponse('download URL is invalid or has expired', status=403)

        path = backend.local_path_for(payload['key'])
        import os
        if not os.path.isfile(path):
            raise Http404('object not found')

        with open(path, 'rb') as f:
            data = f.read()
        response = HttpResponse(data, content_type=payload.get('content_type') or 'application/octet-stream')
        if payload.get('filename'):
            response['Content-Disposition'] = f'attachment; filename="{payload["filename"]}"'
        return response
