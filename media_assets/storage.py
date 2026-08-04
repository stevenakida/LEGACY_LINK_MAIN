"""Private media storage backends for the media_assets pipeline.

Deliberately bypasses django-storages/the `default` STORAGES entry: that
backend is configured globally as public-read/unsigned (see
config/settings.py, used for avatars), and this pipeline's whole point is
the opposite — private objects, served only via short-lived signed URLs
after backend authorization. Talking to boto3 directly keeps this app's ACLs
and signing independent of that global, shared config.

Two backends implement the same interface:
- S3MediaBackend: real object storage (DigitalOcean Spaces / any
  S3-compatible endpoint), used whenever R2_* credentials are configured —
  true direct-to-storage presigned upload/download.
- LocalMediaBackend: filesystem fallback for local dev/tests when no bucket
  credentials exist, so this feature doesn't require cloud credentials to
  develop against (same fallback philosophy as the existing default
  storage). "Presigned URLs" become signed, expiring Django URLs that proxy
  through the server instead of a real object store — the only place this
  pipeline is server-proxied rather than direct-to-storage, and only because
  there is no object store to be direct to in that environment.
"""
import os
import shutil
from dataclasses import dataclass

from django.conf import settings
from django.core import signing


class ObjectNotFound(Exception):
    pass


@dataclass
class ObjectMeta:
    size: int
    content_type: str = ''


class S3MediaBackend:
    def __init__(self):
        import boto3
        from botocore.config import Config as BotoConfig

        self._bucket = settings.MEDIA_ASSETS_S3_BUCKET_NAME
        self._client = boto3.client(
            's3',
            endpoint_url=settings.MEDIA_ASSETS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.MEDIA_ASSETS_S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.MEDIA_ASSETS_S3_SECRET_ACCESS_KEY,
            region_name=settings.MEDIA_ASSETS_S3_REGION,
            config=BotoConfig(signature_version='s3v4'),
        )

    def generate_upload_url(self, key: str, content_type: str, ttl_seconds: int) -> str:
        return self._client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': self._bucket,
                'Key': key,
                'ContentType': content_type,
                'ACL': 'private',
            },
            ExpiresIn=ttl_seconds,
        )

    def generate_download_url(self, key: str, ttl_seconds: int, filename: str = None,
                               content_type: str = None) -> str:
        params = {'Bucket': self._bucket, 'Key': key}
        if filename:
            params['ResponseContentDisposition'] = f'attachment; filename="{filename}"'
        if content_type:
            params['ResponseContentType'] = content_type
        return self._client.generate_presigned_url('get_object', Params=params, ExpiresIn=ttl_seconds)

    def head_object(self, key: str) -> ObjectMeta | None:
        from botocore.exceptions import ClientError
        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError:
            return None
        return ObjectMeta(size=resp['ContentLength'], content_type=resp.get('ContentType', ''))

    def download_to_path(self, key: str, local_path: str) -> None:
        self._client.download_file(self._bucket, key, local_path)

    def upload_from_path(self, local_path: str, key: str, content_type: str) -> None:
        self._client.upload_file(
            local_path, self._bucket, key,
            ExtraArgs={'ContentType': content_type, 'ACL': 'private'},
        )

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


class LocalMediaBackend:
    """Filesystem-backed fallback used when no S3-compatible bucket is
    configured. Signed URLs point at media_assets' own proxy views
    (local_upload_proxy/local_download_proxy) rather than a real object
    store. Never placed under MEDIA_ROOT — it must not be reachable through
    the public /media/ serving path."""

    _UPLOAD_SALT = 'media_assets.local_upload'
    _DOWNLOAD_SALT = 'media_assets.local_download'

    def __init__(self):
        self._root = settings.MEDIA_ASSETS_LOCAL_ROOT
        os.makedirs(self._root, exist_ok=True)

    def _path_for(self, key: str) -> str:
        # `key` is always one of our own generated tokens (see
        # utils.new_storage_key) — never derived from client input — so a
        # plain join is safe; still normalize defensively against traversal.
        path = os.path.normpath(os.path.join(str(self._root), key))
        if not path.startswith(str(self._root)):
            raise ValueError('invalid storage key')
        return path

    def generate_upload_url(self, key: str, content_type: str, ttl_seconds: int) -> str:
        from django.urls import reverse
        token = signing.dumps({'key': key, 'content_type': content_type}, salt=self._UPLOAD_SALT)
        return reverse('media_local_upload') + f'?token={token}'

    def generate_download_url(self, key: str, ttl_seconds: int, filename: str = None,
                               content_type: str = None) -> str:
        from django.urls import reverse
        token = signing.dumps(
            {'key': key, 'filename': filename or '', 'content_type': content_type or ''},
            salt=self._DOWNLOAD_SALT,
        )
        return reverse('media_local_download') + f'?token={token}'

    @classmethod
    def unsign_upload_token(cls, token: str, max_age: int):
        return signing.loads(token, salt=cls._UPLOAD_SALT, max_age=max_age)

    @classmethod
    def unsign_download_token(cls, token: str, max_age: int):
        return signing.loads(token, salt=cls._DOWNLOAD_SALT, max_age=max_age)

    def head_object(self, key: str) -> ObjectMeta | None:
        path = self._path_for(key)
        if not os.path.isfile(path):
            return None
        return ObjectMeta(size=os.path.getsize(path))

    def download_to_path(self, key: str, local_path: str) -> None:
        src = self._path_for(key)
        if not os.path.isfile(src):
            raise ObjectNotFound(key)
        shutil.copyfile(src, local_path)

    def upload_from_path(self, local_path: str, key: str, content_type: str) -> None:
        dest = self._path_for(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(local_path, dest)

    def delete_object(self, key: str) -> None:
        path = self._path_for(key)
        if os.path.isfile(path):
            os.remove(path)

    def write_bytes(self, key: str, data: bytes) -> int:
        """Used only by local_upload_proxy (the dev fallback for a
        presigned PUT)."""
        dest = self._path_for(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(data)
        return len(data)

    def local_path_for(self, key: str) -> str:
        """Public accessor for local_download_proxy — avoids that view
        reaching into the underscored path-building method directly."""
        return self._path_for(key)


def get_media_backend():
    if settings.MEDIA_ASSETS_S3_ENABLED:
        return S3MediaBackend()
    return LocalMediaBackend()
