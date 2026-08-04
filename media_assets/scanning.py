"""Antivirus scanning interface for document (PDF) uploads.

ClamAV is NOT currently provisioned anywhere in this project (confirmed in
the Phase 0 audit) — CLAMD_HOST defaults to blank, in which case NullScanner
is used and every scan fails closed with ScanStatus.ERROR. A document only
ever reaches ScanStatus.CLEAN if a real clamd daemon is reachable and
returns a clean result; nothing here ever fabricates a CLEAN status.

Recommended deployment if/when this is provisioned: a `clamd` daemon
(ClamAV's scanning service) reachable over TCP from the Django app — e.g. a
sidecar container/process on the same host or a small internal service,
with CLAMD_HOST/CLAMD_PORT pointed at it. Scanning runs synchronously in the
complete-upload request (pilot-sized PDFs scan in well under a second), so
no task queue is required to add this.
"""
from dataclasses import dataclass

from django.conf import settings

from .models import MediaAsset


@dataclass
class ScanOutcome:
    status: str  # one of MediaAsset.ScanStatus
    reason: str = ''


class BaseScanner:
    def scan_file(self, path: str) -> ScanOutcome:
        raise NotImplementedError


class ClamdScanner(BaseScanner):
    def __init__(self, host: str, port: int, timeout: int):
        self.host = host
        self.port = port
        self.timeout = timeout

    def scan_file(self, path: str) -> ScanOutcome:
        import clamd
        try:
            client = clamd.ClamdNetworkSocket(host=self.host, port=self.port, timeout=self.timeout)
            result = client.scan(path)
        except Exception:
            return ScanOutcome(MediaAsset.ScanStatus.ERROR, 'antivirus scanner unreachable')

        if not result:
            return ScanOutcome(MediaAsset.ScanStatus.ERROR, 'antivirus scanner returned no result')

        status, detail = next(iter(result.values()))
        if status == 'OK':
            return ScanOutcome(MediaAsset.ScanStatus.CLEAN)
        if status == 'FOUND':
            return ScanOutcome(MediaAsset.ScanStatus.INFECTED, detail or 'malware signature matched')
        return ScanOutcome(MediaAsset.ScanStatus.ERROR, f'unexpected scanner status: {status}')


class NullScanner(BaseScanner):
    """Fail-closed default when no scanner is configured. Never returns
    CLEAN — rule 13 (fail closed) applies directly here."""

    def scan_file(self, path: str) -> ScanOutcome:
        return ScanOutcome(
            MediaAsset.ScanStatus.ERROR,
            'antivirus scanning is not configured on this host — document sharing is disabled until it is',
        )


def get_scanner() -> BaseScanner:
    if settings.MEDIA_ASSETS_CLAMD_HOST:
        return ClamdScanner(
            settings.MEDIA_ASSETS_CLAMD_HOST,
            settings.MEDIA_ASSETS_CLAMD_PORT,
            settings.MEDIA_ASSETS_CLAMD_TIMEOUT_SECONDS,
        )
    return NullScanner()
