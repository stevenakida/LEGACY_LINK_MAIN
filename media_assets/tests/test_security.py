from unittest.mock import patch

from django.core import signing
from django.urls import reverse

from media_assets.models import MediaAsset
from media_assets.storage import LocalMediaBackend

from .base import MediaAssetTestCase, make_jpeg_bytes, make_user


class UnauthenticatedAccessTests(MediaAssetTestCase):
    def test_unauthenticated_upload_init_rejected(self):
        response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE,
            'filename': 'photo.jpg',
            'declared_mime_type': 'image/jpeg',
            'declared_size_bytes': 100,
        }, format='json')
        self.assertIn(response.status_code, (401, 403))


class CrossUserAccessTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.owner = make_user(identifier='+255700000010', full_name='Owner')
        self.other = make_user(identifier='+255700000020', full_name='Other User')

        self.client.force_authenticate(user=self.owner)
        data = make_jpeg_bytes()
        init_response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE,
            'filename': 'photo.jpg',
            'declared_mime_type': 'image/jpeg',
            'declared_size_bytes': len(data),
        }, format='json')
        self.media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type='image/jpeg')
        self.client.post(reverse('media_complete', kwargs={'media_id': self.media_id}))

    def test_other_user_cannot_view_status(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.get(reverse('media_status', kwargs={'media_id': self.media_id}))
        self.assertEqual(response.status_code, 403)

    def test_other_user_cannot_preview_or_download(self):
        self.client.force_authenticate(user=self.other)
        self.assertEqual(
            self.client.get(reverse('media_preview', kwargs={'media_id': self.media_id})).status_code, 403,
        )
        self.assertEqual(
            self.client.get(reverse('media_download', kwargs={'media_id': self.media_id})).status_code, 403,
        )

    def test_other_user_cannot_cancel_or_delete(self):
        self.client.force_authenticate(user=self.other)
        self.assertEqual(
            self.client.post(reverse('media_cancel', kwargs={'media_id': self.media_id})).status_code, 403,
        )
        self.assertEqual(
            self.client.delete(reverse('media_delete_orphan', kwargs={'media_id': self.media_id})).status_code, 403,
        )
        # And it must still exist/untouched afterward.
        asset = MediaAsset.objects.get(pk=self.media_id)
        self.assertEqual(asset.status, MediaAsset.Status.READY)

    def test_knowing_the_uuid_alone_is_not_sufficient(self):
        """A UUID alone must never grant access — repeats the point across
        every read/write endpoint, not just one, since each view wires its
        own permission check."""
        self.client.force_authenticate(user=self.other)
        for name in ('media_status', 'media_preview', 'media_download', 'media_cancel'):
            response = self.client.get(reverse(name, kwargs={'media_id': self.media_id})) if name != 'media_cancel' \
                else self.client.post(reverse(name, kwargs={'media_id': self.media_id}))
            self.assertEqual(response.status_code, 403, name)


class ExpiredSignedUrlTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def test_unsign_download_token_raises_once_expired(self):
        token = signing.dumps({'key': 'private/ready/x.jpg', 'filename': '', 'content_type': ''},
                               salt=LocalMediaBackend._DOWNLOAD_SALT)
        with self.assertRaises(signing.SignatureExpired):
            LocalMediaBackend.unsign_download_token(token, max_age=-1)

    def test_expired_download_proxy_url_returns_403(self):
        data = make_jpeg_bytes()
        init_response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE,
            'filename': 'photo.jpg',
            'declared_mime_type': 'image/jpeg',
            'declared_size_bytes': len(data),
        }, format='json')
        media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type='image/jpeg')
        self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))

        download_response = self.client.get(reverse('media_download', kwargs={'media_id': media_id}))
        signed_url = download_response.url  # the 302 Location, carries the real token

        with self.settings(MEDIA_ASSETS_SIGNED_URL_TTL_SECONDS=-1):
            proxy_response = self.client.get(signed_url)
        self.assertEqual(proxy_response.status_code, 403)


class StorageFailureTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def test_storage_failure_during_download_marks_failed(self):
        data = make_jpeg_bytes()
        init_response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE,
            'filename': 'photo.jpg',
            'declared_mime_type': 'image/jpeg',
            'declared_size_bytes': len(data),
        }, format='json')
        media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type='image/jpeg')

        with patch.object(LocalMediaBackend, 'download_to_path', side_effect=Exception('simulated disk failure')):
            complete_response = self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))

        self.assertEqual(complete_response.data['status'], MediaAsset.Status.FAILED)
        asset = MediaAsset.objects.get(pk=media_id)
        self.assertFalse(asset.is_downloadable)
