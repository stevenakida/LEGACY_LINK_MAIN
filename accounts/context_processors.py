import re

from . import google_oauth

# Android System WebView adds "; wv)" to its User-Agent; regular Chrome never does.
_ANDROID_WEBVIEW_UA = re.compile(r'Android.*;\s*wv\)')


def _is_android_webview(request):
    return bool(_ANDROID_WEBVIEW_UA.search(request.META.get('HTTP_USER_AGENT', '')))


def google_sign_in(request):
    # Hide the Google button unless OAuth is configured: an unconfigured button
    # bounces back to /login/ instead of accounts.google.com, which Safe
    # Browsing flagged as a deceptive (fake Google sign-in) page.
    # Also hide it inside the Android app: its WebView hands accounts.google.com
    # to the system browser, so the callback lands there without the app's
    # session and the OAuth state check fails.
    return {
        'google_sign_in_enabled': google_oauth.is_configured() and not _is_android_webview(request),
    }
