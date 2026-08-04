from unittest.mock import patch

from django.urls import reverse

from media_assets.models import MediaAsset
from media_assets.scanning import ScanOutcome

from .base import MediaAssetTestCase, make_pdf_bytes, make_user


class DocumentScanningTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def _init_and_upload_pdf(self):
        data = make_pdf_bytes()
        init_response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.DOCUMENT,
            'filename': 'transcript.pdf',
            'declared_mime_type': 'application/pdf',
            'declared_size_bytes': len(data),
        }, format='json')
        media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type='application/pdf')
        return media_id

    def test_document_uploads_disabled_by_default_flag(self):
        with self.settings(FEATURE_DOCUMENT_MEDIA_ENABLED=False):
            response = self.client.post(reverse('media_init'), {
                'category': MediaAsset.Category.DOCUMENT,
                'filename': 'transcript.pdf',
                'declared_mime_type': 'application/pdf',
                'declared_size_bytes': 1000,
            }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_pdf_pending_scan_is_not_downloadable(self):
        """No CLAMD_HOST configured -> NullScanner -> scan_status ERROR,
        never CLEAN. The PDF must fail closed (rejected/unavailable), not
        sit around servable while 'pending'."""
        media_id = self._init_and_upload_pdf()
        with self.settings(CLAMD_HOST=''):
            complete_response = self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))
        self.assertNotEqual(complete_response.data['status'], MediaAsset.Status.READY)
        asset = MediaAsset.objects.get(pk=media_id)
        self.assertFalse(asset.is_downloadable)
        self.assertNotEqual(asset.scan_status, MediaAsset.ScanStatus.CLEAN)

    def test_pdf_rejected_by_scan_is_quarantined(self):
        media_id = self._init_and_upload_pdf()
        with patch('media_assets.services.get_scanner') as mock_get_scanner:
            mock_get_scanner.return_value.scan_file.return_value = ScanOutcome(
                MediaAsset.ScanStatus.INFECTED, 'Eicar-Test-Signature',
            )
            complete_response = self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))

        self.assertEqual(complete_response.data['status'], MediaAsset.Status.REJECTED)
        self.assertEqual(complete_response.data['scan_status'], MediaAsset.ScanStatus.INFECTED)
        asset = MediaAsset.objects.get(pk=media_id)
        self.assertFalse(asset.is_downloadable)
        # Quarantine object must actually be gone, not just marked rejected.
        from media_assets.storage import get_media_backend
        self.assertIsNone(get_media_backend().head_object(asset.quarantine_storage_key))

    def test_pdf_clean_scan_becomes_downloadable(self):
        media_id = self._init_and_upload_pdf()
        with patch('media_assets.services.get_scanner') as mock_get_scanner:
            mock_get_scanner.return_value.scan_file.return_value = ScanOutcome(MediaAsset.ScanStatus.CLEAN)
            complete_response = self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))

        self.assertEqual(complete_response.data['status'], MediaAsset.Status.READY)
        self.assertEqual(complete_response.data['scan_status'], MediaAsset.ScanStatus.CLEAN)
        asset = MediaAsset.objects.get(pk=media_id)
        self.assertTrue(asset.is_downloadable)

        download_response = self.client.get(reverse('media_download', kwargs={'media_id': media_id}))
        self.assertEqual(download_response.status_code, 302)

    def test_scanner_error_never_marks_clean(self):
        media_id = self._init_and_upload_pdf()
        with patch('media_assets.services.get_scanner') as mock_get_scanner:
            mock_get_scanner.return_value.scan_file.return_value = ScanOutcome(
                MediaAsset.ScanStatus.ERROR, 'scanner unreachable',
            )
            complete_response = self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))

        self.assertEqual(complete_response.data['status'], MediaAsset.Status.FAILED)
        self.assertNotEqual(complete_response.data['scan_status'], MediaAsset.ScanStatus.CLEAN)
