"""The local-dev upload proxy accepts realistic photo sizes (Django's 2.5 MB
in-memory body limit must not apply) but still enforces the media limits."""
from django.test import override_settings
from django.urls import reverse

from media_assets.models import MediaAsset

from .base import MediaAssetTestCase, make_user


class LocalProxyUploadSizeTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def init_upload(self, declared):
        response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE, 'filename': 'photo.jpg',
            'declared_mime_type': 'image/jpeg', 'declared_size_bytes': declared,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['upload_url']

    def test_a_multi_megabyte_photo_uploads_past_djangos_2_5_mb_body_limit(self):
        payload = b'\xff' * (6 * 1024 * 1024)                 # a typical 12 MP phone photo is 3-8 MB
        response = self.client.generic('PUT', self.init_upload(len(payload)), data=payload, content_type='image/jpeg')
        self.assertEqual(response.status_code, 200)

    def test_the_exact_bytes_are_stored(self):
        payload = bytes(range(256)) * (12 * 1024)              # 3 MB, not a valid image: the proxy only stores bytes
        url = self.init_upload(len(payload))
        self.client.generic('PUT', url, data=payload, content_type='image/jpeg')
        asset = MediaAsset.objects.get()
        from media_assets.storage import get_media_backend
        with open(get_media_backend().local_path_for(asset.quarantine_storage_key), 'rb') as stored:
            self.assertEqual(stored.read(), payload)

    @override_settings(MEDIA_ASSETS_IMAGE_MAX_BYTES=1000, MEDIA_ASSETS_VIDEO_MAX_BYTES=1000,
                       MEDIA_ASSETS_DOCUMENT_MAX_BYTES=1000)
    def test_payloads_over_the_media_limit_are_still_refused(self):
        url = self.init_upload(500)
        response = self.client.generic('PUT', url, data=b'x' * 4096, content_type='image/jpeg')
        self.assertEqual(response.status_code, 413)
        self.assertFalse(MediaAsset.objects.filter(status=MediaAsset.Status.READY).exists())
