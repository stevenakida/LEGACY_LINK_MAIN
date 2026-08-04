import io
from unittest.mock import patch

from django.urls import reverse

from media_assets.models import MediaAsset

from .base import MediaAssetTestCase, make_jpeg_bytes, make_user


class ValidationFailureTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def _init_and_upload(self, category, filename, declared_mime, data, declared_size=None):
        init_response = self.client.post(reverse('media_init'), {
            'category': category,
            'filename': filename,
            'declared_mime_type': declared_mime,
            'declared_size_bytes': declared_size if declared_size is not None else len(data),
        }, format='json')
        if init_response.status_code != 201:
            return init_response, None
        media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type=declared_mime)
        complete_response = self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))
        return init_response, complete_response

    def test_declared_size_over_limit_rejected_at_init(self):
        response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE,
            'filename': 'huge.jpg',
            'declared_mime_type': 'image/jpeg',
            'declared_size_bytes': 999_999_999,
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_actual_size_over_limit_rejected_at_completion(self):
        data = make_jpeg_bytes()
        # Declare a size that passes init, then shrink the actual byte cap
        # before completion — the actual-size check re-measures the real
        # object, so a client can't declare its way past this.
        init_response = self.client.post(reverse('media_init'), {
            'category': MediaAsset.Category.IMAGE,
            'filename': 'photo.jpg',
            'declared_mime_type': 'image/jpeg',
            'declared_size_bytes': len(data),
        }, format='json')
        media_id = init_response.data['media']['id']
        self.client.generic('PUT', init_response.data['upload_url'], data=data, content_type='image/jpeg')

        with self.settings(MEDIA_ASSETS_IMAGE_MAX_BYTES=1):
            complete_response = self.client.post(reverse('media_complete', kwargs={'media_id': media_id}))
        self.assertEqual(complete_response.data['status'], MediaAsset.Status.REJECTED)
        self.assertIn('exceeds', complete_response.data['failure_reason'])

    def test_corrupt_image_rejected(self):
        garbage = b'this is not actually an image' * 10
        _init, complete = self._init_and_upload(
            MediaAsset.Category.IMAGE, 'photo.jpg', 'image/jpeg', garbage,
        )
        self.assertEqual(complete.data['status'], MediaAsset.Status.REJECTED)
        self.assertIn('corrupt', complete.data['failure_reason'])

    def test_fake_extension_pdf_content_declared_as_image(self):
        from .base import make_pdf_bytes
        pdf_bytes = make_pdf_bytes()
        _init, complete = self._init_and_upload(
            MediaAsset.Category.IMAGE, 'photo.jpg', 'image/jpeg', pdf_bytes,
        )
        self.assertEqual(complete.data['status'], MediaAsset.Status.REJECTED)

    def test_unsupported_image_format_gif_rejected(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (10, 10)).save(buf, format='GIF')
        _init, complete = self._init_and_upload(
            MediaAsset.Category.IMAGE, 'photo.gif', 'image/gif', buf.getvalue(),
        )
        self.assertEqual(complete.data['status'], MediaAsset.Status.REJECTED)
        self.assertIn('unsupported', complete.data['failure_reason'])

    def test_wrong_declared_mime_type_is_ignored_actual_content_wins(self):
        """Client lies and declares image/jpeg, but the bytes are really a
        PNG — the server must detect and process it as what it actually is,
        never trusting the declared Content-Type."""
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (32, 32)).save(buf, format='PNG')
        png_bytes = buf.getvalue()

        _init, complete = self._init_and_upload(
            MediaAsset.Category.IMAGE, 'photo.jpg', 'image/jpeg', png_bytes,
        )
        self.assertEqual(complete.data['status'], MediaAsset.Status.READY)
        self.assertEqual(complete.data['detected_mime_type'], 'image/png')

    def test_oversized_dimensions_are_resized_not_rejected(self):
        big = make_jpeg_bytes(width=3000, height=2500)
        _init, complete = self._init_and_upload(
            MediaAsset.Category.IMAGE, 'big.jpg', 'image/jpeg', big,
        )
        self.assertEqual(complete.data['status'], MediaAsset.Status.READY)
        self.assertLessEqual(complete.data['width'], 2048)
        self.assertLessEqual(complete.data['height'], 2048)

    def test_video_without_ffprobe_available_fails_closed(self):
        """No ffprobe binary is installed in this environment — this
        exercises the real fail-closed path (not a mock) for hosts where
        the new ffprobe infra hasn't been provisioned yet."""
        _init, complete = self._init_and_upload(
            MediaAsset.Category.VIDEO, 'clip.mp4', 'video/mp4', b'not a real mp4 file',
        )
        self.assertEqual(complete.data['status'], MediaAsset.Status.REJECTED)

    def test_video_longer_than_60_seconds_rejected(self):
        fake_probe_output = {
            'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '75.0'},
            'streams': [{'codec_type': 'video'}],
        }
        with patch('media_assets.validation._run_ffprobe', return_value=fake_probe_output):
            _init, complete = self._init_and_upload(
                MediaAsset.Category.VIDEO, 'clip.mp4', 'video/mp4', b'stand-in mp4 bytes',
            )
        self.assertEqual(complete.data['status'], MediaAsset.Status.REJECTED)
        self.assertIn('60', complete.data['failure_reason'])

    def test_video_within_limit_succeeds(self):
        fake_probe_output = {
            'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '12.5'},
            'streams': [{'codec_type': 'video'}],
        }
        with patch('media_assets.validation._run_ffprobe', return_value=fake_probe_output):
            _init, complete = self._init_and_upload(
                MediaAsset.Category.VIDEO, 'clip.mp4', 'video/mp4', b'stand-in mp4 bytes',
            )
        self.assertEqual(complete.data['status'], MediaAsset.Status.READY)
        self.assertAlmostEqual(complete.data['duration_seconds'], 12.5)

    def test_malformed_video_container_rejected(self):
        fake_probe_output = {
            'format': {'format_name': 'avi'},
            'streams': [{'codec_type': 'video'}],
        }
        with patch('media_assets.validation._run_ffprobe', return_value=fake_probe_output):
            _init, complete = self._init_and_upload(
                MediaAsset.Category.VIDEO, 'clip.avi', 'video/mp4', b'stand-in bytes',
            )
        self.assertEqual(complete.data['status'], MediaAsset.Status.REJECTED)
        self.assertIn('MP4', complete.data['failure_reason'])
