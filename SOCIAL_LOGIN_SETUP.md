# Google Sign-In Setup

## Status: Implemented, needs real credentials

"Continue with Google" / "Sign up with Google" on the Login and Register
pages are fully wired up — a minimal OAuth2 Authorization Code flow
implemented directly against Google's own REST endpoints
(`accounts/google_oauth.py`), not django-allauth. An earlier attempt using
allauth is gone — it got stuck on allauth's assumptions about the user
model (this app's `User` has no `username` field and uses `phone_or_email`
as `USERNAME_FIELD`) on top of a `cryptography` build issue on Windows that
was never actually the real blocker.

**The only thing missing is a real Google OAuth Client ID/Secret.**

## How it works

1. `GET /auth/google/login/` (`google_login_start` in `config/views.py`)
   redirects to Google's consent screen, with a random `state` value
   stashed in the session (CSRF protection on the callback).
2. Google redirects back to `GET /auth/google/callback/`
   (`google_login_callback`) with an authorization `code`.
3. `accounts/google_oauth.py` exchanges that code for an access token,
   then calls Google's `userinfo` endpoint to get `email`, `email_verified`,
   and `name`. Google's own verification of that email is trusted directly
   — no separate LegacyLink Africa verification-link email is sent.
4. `User.resolve_google_account(email, full_name)` (`accounts/models.py`)
   finds-or-creates: matches an existing account by `phone_or_email` or a
   verified profile `email` first (same account-linking rule used
   elsewhere — see `find_by_login_identifier`), so someone who registered
   by phone and separately verified this same email from their profile
   lands on their existing account, not a duplicate. Only creates a new
   account if neither matches — with `email_verified=True` immediately
   (Google already verified it) and no usable password, since Google
   Sign-In is their only way in until they set one.

## Setting up real credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) →
   create a project (or use an existing one).
2. **APIs & Services → OAuth consent screen** — configure it (app name,
   support email, etc.). External user type unless this is Workspace-only.
3. **APIs & Services → Credentials → Create Credentials → OAuth 2.0
   Client ID** → Application type: **Web application**.
4. Add **Authorized redirect URIs**:
   - Local dev: `http://localhost:8000/auth/google/callback/`
   - Production: `https://legacylink-app-qs7gl.ondigitalocean.app/auth/google/callback/`
     (or the app's current domain — check `reference_digitalocean_production`
     memory / the DO dashboard if that's changed)
5. Copy the **Client ID** and **Client Secret**.
6. Set as env vars:
   - Local: add to `.env` — `GOOGLE_OAUTH_CLIENT_ID=...` /
     `GOOGLE_OAUTH_CLIENT_SECRET=...`
   - Production: DigitalOcean → Apps → legacylink-app → Settings →
     `legacy-link-main` → Environment Variables. `GOOGLE_OAUTH_CLIENT_SECRET`
     should be added as type **SECRET**.

Until these are set, clicking the Google button shows "Google sign-in is
not set up yet" instead of crashing (`google_oauth.is_configured()` /
`GoogleOAuthNotConfigured`).

## Notes

- Facebook was never implemented past a placeholder button (still shows
  "Social login is coming soon" — untouched, not part of this work).
- No new dependency was needed — the whole flow is plain HTTP calls via
  `requests`, already a project dependency.
- Scope requested: `openid email profile` — no Google Drive/Calendar/etc.
  access, just identity.
