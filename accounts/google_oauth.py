"""Minimal Google Sign-In (OAuth2 Authorization Code flow), implemented
directly against Google's plain REST endpoints rather than django-allauth
— an earlier attempt (see git history / the old SOCIAL_LOGIN_SETUP.md)
got stuck on allauth's assumptions about the user model (this app's User
has no `username` field and uses phone_or_email as USERNAME_FIELD) on top
of a `cryptography` build issue on Windows that was never the real
blocker. This needs nothing beyond `requests` (already a project
dependency) — the code<->token exchange and userinfo fetch are plain
JSON/form-encoded HTTP calls to Google's own endpoints, verified against
https://developers.google.com/identity/protocols/oauth2/web-server."""
import logging
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

AUTHORIZATION_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
REQUEST_TIMEOUT = 10


class GoogleOAuthNotConfigured(Exception):
    """GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET aren't set —
    see config/settings.py for where to get real values."""


class GoogleOAuthError(Exception):
    """The code<->token exchange or userinfo fetch failed, or returned
    something we didn't expect."""


def is_configured():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def new_state():
    """A random per-attempt value stashed in the session and echoed back
    by Google on the callback — mitigates CSRF on the OAuth callback
    (someone can't hand a victim a crafted callback URL carrying an
    attacker's authorization code)."""
    return secrets.token_urlsafe(32)


def build_authorization_url(redirect_uri, state):
    if not is_configured():
        raise GoogleOAuthNotConfigured(
            'GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set.'
        )
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    }
    return f'{AUTHORIZATION_URL}?{urlencode(params)}'


def fetch_userinfo(code, redirect_uri):
    """Exchanges an authorization `code` for Google's userinfo (email,
    name, and whether Google itself has verified that email address).
    Raises GoogleOAuthError on any failure — the caller shows a generic
    "couldn't sign in with Google" message rather than leaking exchange
    details to the user."""
    if not is_configured():
        raise GoogleOAuthNotConfigured(
            'GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set.'
        )
    try:
        token_response = requests.post(
            TOKEN_URL,
            data={
                'code': code,
                'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=REQUEST_TIMEOUT,
        )
        token_response.raise_for_status()
        access_token = token_response.json()['access_token']

        userinfo_response = requests.get(
            USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=REQUEST_TIMEOUT,
        )
        userinfo_response.raise_for_status()
        return userinfo_response.json()
    except requests.RequestException as exc:
        logger.exception('Google OAuth code/userinfo exchange failed')
        raise GoogleOAuthError(str(exc)) from exc
    except (KeyError, ValueError) as exc:
        logger.exception('Google OAuth returned an unexpected response shape')
        raise GoogleOAuthError('Unexpected response from Google') from exc
