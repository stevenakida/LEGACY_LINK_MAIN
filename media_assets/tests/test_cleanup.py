import io
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from media_assets.models import MediaAsset
from media_assets.storage import get_media_backend

from .base import MediaAssetTestCase, make_user


class CleanupCommandTests(MediaAssetTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user()

    def _make_asset(self, **overrides):
        defaults = dict(
            owner=self.user,
            category=MediaAsset.Category.IMAGE,
            original_filename='photo.jpg',
            sanitized_filename='photo.jpg',
            declared_size_bytes=100,
            quarantine_storage_key=f"private/quarantine/{overrides.get('_suffix', 'x')}",
        )
        defaults.update({k: v for k, v in overrides.items() if k != '_suffix'})
        return MediaAsset.objects.create(**defaults)

    def test_cleanup_purges_expired_initialized_upload(self):
        asset = self._make_asset(
            _suffix='a',
            status=MediaAsset.Status.INITIALIZED,
            upload_url_expires_at=timezone.now() - timedelta(hours=1),
        )
        call_command('cleanup_media')
        asset.refresh_from_db()
        self.assertEqual(asset.status, MediaAsset.Status.DELETED)
        self.assertIsNotNone(asset.deleted_at)

    def test_cleanup_purges_terminal_failed_past_retention(self):
        asset = self._make_asset(
            _suffix='b',
            status=MediaAsset.Status.FAILED,
            failure_reason='processing failed unexpectedly',
            purge_at=timezone.now() - timedelta(hours=1),
        )
        call_command('cleanup_media')
        asset.refresh_from_db()
        self.assertEqual(asset.status, MediaAsset.Status.DELETED)

    def test_cleanup_purges_orphaned_ready_media_and_its_storage_object(self):
        backend = get_media_backend()
        ready_key = 'private/ready/orphan-test.jpg'
        # Write a real object so we can prove the cleanup command actually
        # removes it, not just flips the DB status.
        tmp = io.BytesIO(b'fake jpeg bytes')
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(tmp.getvalue())
            tmp_path = f.name
        backend.upload_from_path(tmp_path, ready_key, 'image/jpeg')

        asset = self._make_asset(
            _suffix='c',
            status=MediaAsset.Status.READY,
            storage_key=ready_key,
            is_attached=False,
            purge_at=timezone.now() - timedelta(hours=1),
        )
        self.assertIsNotNone(backend.head_object(ready_key))

        call_command('cleanup_media')

        asset.refresh_from_db()
        self.assertEqual(asset.status, MediaAsset.Status.DELETED)
        self.assertIsNotNone(asset.deleted_at)
        self.assertIsNone(get_media_backend().head_object(ready_key))

    def test_cleanup_leaves_attached_media_alone(self):
        asset = self._make_asset(
            _suffix='d',
            status=MediaAsset.Status.READY,
            is_attached=False,
            purge_at=timezone.now() - timedelta(hours=1),
        )
        asset.mark_attached()  # clears purge_at, as messaging/posts will do in a later phase
        call_command('cleanup_media')
        asset.refresh_from_db()
        self.assertEqual(asset.status, MediaAsset.Status.READY)
        self.assertTrue(asset.is_attached)

    def test_cleanup_dry_run_makes_no_changes(self):
        asset = self._make_asset(
            _suffix='e',
            status=MediaAsset.Status.INITIALIZED,
            upload_url_expires_at=timezone.now() - timedelta(hours=1),
        )
        call_command('cleanup_media', '--dry-run')
        asset.refresh_from_db()
        self.assertEqual(asset.status, MediaAsset.Status.INITIALIZED)

    def test_soft_delete_preserves_the_row(self):
        """Deleting owned orphan media must be a soft delete — the row
        stays for audit/moderation, only status/deleted_at change and the
        storage objects are actually removed."""
        from media_assets import services
        asset = self._make_asset(_suffix='f', status=MediaAsset.Status.READY, is_attached=False)
        services.delete_orphan(asset)

        still_exists = MediaAsset.objects.filter(pk=asset.pk).exists()
        self.assertTrue(still_exists)
        asset.refresh_from_db()
        self.assertEqual(asset.status, MediaAsset.Status.DELETED)
        self.assertIsNotNone(asset.deleted_at)
