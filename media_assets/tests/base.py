import io
import shutil
import tempfile

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User


def make_user(identifier='+255700000001', full_name='Test User', password='Testing2026!'):
    return User.objects.create_user(phone_or_email=identifier, password=password, full_name=full_name)


def make_jpeg_bytes(width=64, height=64, color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, format='JPEG')
    return buf.getvalue()


def make_pdf_bytes():
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# Feature flags enabled + forced onto the local filesystem backend so tests
# never touch real object storage, regardless of what's in the local .env.
# Note: size caps are the already-computed MEDIA_ASSETS_*_MAX_BYTES settings
# (see config/settings.py), not the raw MEDIA_*_MAX_MB env vars — override
# those *_BYTES settings directly (see test_validation_failures.py) if a
# test needs a different cap than the default.
MEDIA_TEST_OVERRIDES = dict(
    MEDIA_ASSETS_S3_ENABLED=False,
    FEATURE_MEDIA_UPLOADS_ENABLED=True,
    FEATURE_VIDEO_MEDIA_ENABLED=True,
    FEATURE_DOCUMENT_MEDIA_ENABLED=True,
)


@override_settings(**MEDIA_TEST_OVERRIDES)
class MediaAssetTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self._local_root = tempfile.mkdtemp(prefix='media_assets_test_')
        self._root_override = override_settings(MEDIA_ASSETS_LOCAL_ROOT=self._local_root)
        self._root_override.enable()
        self.client = APIClient()

    def tearDown(self):
        self._root_override.disable()
        shutil.rmtree(self._local_root, ignore_errors=True)
        super().tearDown()
