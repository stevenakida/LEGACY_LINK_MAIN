from django.conf import settings
from django.http import HttpResponsePermanentRedirect

# Still answered on the legacy host, so its Search Console property stays
# verifiable after everything else moves to the canonical domain.
_KEEP_ON_LEGACY_HOST = ('/google53e347c5788d485a.html',)


class CanonicalHostMiddleware:
    """Send every request for a legacy host (the default *.ondigitalocean.app
    address, which DigitalOcean keeps serving after a custom domain is added)
    to the same path on CANONICAL_HOST. Google Safe Browsing flagged the
    shared-hosting address; once it only redirects, it serves no login form
    left to flag."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.META.get('HTTP_HOST', '').split(':')[0].lower()
        if (
            settings.CANONICAL_HOST
            and host in settings.LEGACY_HOSTS
            and request.path not in _KEEP_ON_LEGACY_HOST
        ):
            response = HttpResponsePermanentRedirect(
                f'https://{settings.CANONICAL_HOST}{request.get_full_path()}'
            )
            if request.method not in ('GET', 'HEAD'):
                response.status_code = 308  # keep the method and body of POSTs
            return response
        return self.get_response(request)
