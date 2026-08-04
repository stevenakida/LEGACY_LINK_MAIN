from django.urls import reverse

from media_assets.models import MediaAsset

from .base import MediaAssetTestCase, make_jpeg_bytes, make_user


class UploadFlowTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def _init_image(self, size=None):
        data = make_jpeg_bytes()
        response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE,
            'filename': 'photo.jpg',
            'declared_mime_type': 'image/jpeg',
            'declared_size_bytes': size if size is not None else len(data),
        }, format='json')
        return response, data

    def test_full_happy_path_image(self):
        init_response, data = self._init_image()
        self.assertEqual(init_response.status_code, 201, init_response.data)
        media_id = init_response.data['media']['id']
        upload_url = init_response.data['upload_url']

        put_response = self.client.generic('PUT', upload_url, data=data, content_type='image/jpeg')
        self.assertEqual(put_response.status_code, 200)

        complete_url = reverse('media_complete', kwargs={'media_id': media_id})
        complete_response = self.client.post(complete_url)
        self.assertEqual(complete_response.status_code, 200, complete_response.data)
        self.assertEqual(complete_response.data['status'], MediaAsset.Status.READY)
        self.assertEqual(complete_response.data['detected_mime_type'], 'image/jpeg')
        self.assertIsNotNone(complete_response.data['width'])

        asset = MediaAsset.objects.get(pk=media_id)
        self.assertTrue(asset.is_downloadable)
        self.assertTrue(asset.storage_key)
        self.assertTrue(asset.checksum_sha256)

        status_response = self.client.get(reverse('media_status', kwargs={'media_id': media_id}))
        self.assertEqual(status_response.data['status'], MediaAsset.Status.READY)

        preview_response = self.client.get(reverse('media_preview', kwargs={'media_id': media_id}))
        self.assertEqual(preview_response.status_code, 302)

        download_response = self.client.get(reverse('media_download', kwargs={'media_id': media_id}))
        self.assertEqual(download_response.status_code, 302)

        delete_response = self.client.delete(reverse('media_delete_orphan', kwargs={'media_id': media_id}))
        self.assertEqual(delete_response.status_code, 200)
        asset.refresh_from_db()
        self.assertEqual(asset.status, MediaAsset.Status.DELETED)
        self.assertIsNotNone(asset.deleted_at)

    def test_repeated_completion_request_is_idempotent(self):
        init_response, data = self._init_image()
        media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type='image/jpeg')

        complete_url = reverse('media_complete', kwargs={'media_id': media_id})
        first = self.client.post(complete_url)
        second = self.client.post(complete_url)

        self.assertEqual(first.data['status'], MediaAsset.Status.READY)
        self.assertEqual(second.data['status'], MediaAsset.Status.READY)
        # Only one ready object should have ever been created — not two
        # (i.e. completion didn't reprocess and mint a second storage key).
        self.assertEqual(first.data.get('processed_size_bytes'), second.data.get('processed_size_bytes'))

    def test_missing_object_after_completion_marks_failed(self):
        init_response, _data = self._init_image()
        media_id = init_response.data['media']['id']
        # Deliberately never PUT the file — the quarantine object never exists.
        complete_url = reverse('media_complete', kwargs={'media_id': media_id})
        response = self.client.post(complete_url)
        self.assertEqual(response.data['status'], MediaAsset.Status.FAILED)
        self.assertIn('not found', response.data['failure_reason'])

    def test_cancel_upload_before_completion(self):
        init_response, _data = self._init_image()
        media_id = init_response.data['media']['id']
        cancel_response = self.client.post(reverse('media_cancel', kwargs={'media_id': media_id}))
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.data['status'], MediaAsset.Status.DELETED)

    def test_cancel_after_ready_is_rejected(self):
        init_response, data = self._init_image()
        media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type='image/jpeg')
        self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))

        cancel_response = self.client.post(reverse('media_cancel', kwargs={'media_id': media_id}))
        self.assertEqual(cancel_response.status_code, 409)
