# LegacyLink Africa — Documentation

> Living document. Update this file whenever a feature, flow, or setup step changes.
> Last updated: 2026-07-04

## 1. What the app does

LegacyLink Africa is a Django web app (server-rendered pages + a REST API) that
reconnects alumni from African schools. A user registers, picks their school(s)
and graduation year, and the app matches them into a **cohort** (same school +
same completion year) and lets them send/accept **connection requests** with
other alumni — similar in spirit to a school-focused LinkedIn/Classmates.com.

Core concepts:
- **User** (`accounts.User`) — custom user model, logs in with phone number
  or email (`phone_or_email`) instead of a username.
- **School** (`alumni.School`) — primary, secondary, or university, scoped to
  a region/country (seeded data currently focused on Tanzania, e.g. Arusha region).
- **Cohort** — everyone sharing the same `secondary_school` +
  `secondary_completion_year` as the current user.
- **Connection** (`connections.Connection`) — a request between two users with
  status `pending` / `accepted` / `declined`.
- **Identity Score** (`User.identity_score`) — a 0–100 profile-completion meter
  (replaces the old ad-hoc "trust score"). Weighted: Profile Picture 10%, Bio
  10%, Primary School 12%, Secondary School 12%, University/Tertiary 11%,
  Current Location 10%, Profession 20%, Company/Organization 15%. Shown on the
  dashboard with a progress bar and up to 4 "complete your profile" suggestions
  (`User.identity_score_suggestions`), sorted by point value. Verification
  status is intentionally NOT scored yet — there's no identity verification
  flow, so it was dropped from v1 rather than faked.

## 2. How to use it (end-user flow)

1. **Register** at `/register/` with phone/email, full name, and a password.
   Accepting the Terms of Use, Privacy and Data Usage Policy is required to
   create an account (see `templates/terms.html`).
2. **Onboarding** at `/onboarding/` — pick your secondary school and
   graduation year. This sets `onboarding_complete = True` and is what powers
   cohort matching.
3. **Dashboard** at `/dashboard/` — shows Identity Score (with improvement
   suggestions), connection counts, cohort preview, and accepted connections.
4. **Profile** at `/profile/` — edit name, bio, profile picture, current
   location, professional info (current role, employment status, company/org
   name), and education history (Primary, Secondary, Advanced Level/A-Level,
   and University/Tertiary school + completion years).
5. **Schools** at `/schools/` — browse/search schools (also has a section
   reserved for future "opportunities" content, currently empty/mock).
6. **Cohort** at `/cohort/` — see all alumni who match your school + year.
7. **Connections** at `/connections/` — view pending and accepted connection
   requests; send/accept/decline.
8. **Login/Logout** at `/login/` and `/logout/`. Social login (Google/Facebook
   via django-allauth) is scaffolded in the UI but not fully wired for
   production OAuth yet — see `SOCIAL_LOGIN_SETUP.md` for status and setup
   steps.

Admin/staff use `/admin/` (Django admin) to manage users, schools, and
connections, plus a small custom stats page at `templates/admin/stats.html`.

## 3. REST API

Used by the mobile/Android-WebView client (templates are also built to be
WebView-friendly):

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/register/` | Register new user |
| POST | `/api/auth/login/` | Login, returns JWT |
| GET | `/api/alumni/schools/?q=` | Search schools |
| PATCH | `/api/alumni/onboarding/` | Complete onboarding |
| GET | `/api/alumni/cohort/` | Get classmates |
| POST | `/api/connections/send/{user_id}/` | Send connection request |
| PATCH | `/api/connections/{id}/respond/` | Accept/decline request |
| GET | `/api/connections/?tab=pending` | List connections |

## 4. Project structure

- `config/` — Django project settings, root URLconf, and the server-rendered
  views (home, login, register, dashboard, profile, schools, connections,
  cohort, onboarding, terms).
- `accounts/` — custom `User` model + auth API (register/login/JWT).
- `alumni/` — `School` model + schools/cohort/onboarding API.
- `connections/` — `Connection` model + connection request API.
- `templates/` — server-rendered HTML pages (mobile/Android-WebView friendly).
- `../legacy-link-android/` (sibling folder, separate Android Studio project)
  — the native WebView shell that loads this app on Android. See its README
  and [section 5](#5-setup--running-locally) for the testing/production split.

## 5. Setup / running locally

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_schools
python manage.py createsuperuser
python manage.py runserver
```

Database: SQLite by default; set `DATABASE_URL` env var to use Postgres
instead (falls back to SQLite if unset — see commit `36ef5a6`).

### Testing vs. production environments

Two fully separate environments:

| | Testing | Production |
|---|---|---|
| Where it runs | Your machine (`runserver`) | Render (`legacy-link-main.onrender.com`) |
| Database | Local `db.sqlite3` | Render Postgres |
| `DEBUG` | `True` (local `.env`) | `False` (Render env vars) |
| Android client | `testing` flavor → `http://10.0.2.2:8000/` | `production` flavor → the Render URL |

The local `.env` (gitignored, never deployed) controls the testing side;
Render's dashboard env vars control production independently — changing one
never affects the other.

To test from the Android emulator (see `../legacy-link-android/README.md`),
bind the dev server to all interfaces so the emulator's virtual network can
reach it:
```bash
python manage.py runserver 0.0.0.0:8000
```
`10.0.2.2` (the emulator's alias for your machine's `localhost`) and
`localhost`/`127.0.0.1` are the only hosts allowed to use cleartext HTTP on
the Android side — everything else requires HTTPS.

## 6. Known limitations / in-progress work

- **RESOLVED (2026-07-04): Render's `DATABASE_URL` was set to
  `sqlite:///db.sqlite3` instead of the Postgres instance**, wiping all users,
  connections, and seeded schools on every deploy. User swapped the env var
  to the Postgres Internal Database URL in Render's dashboard — confirmed
  fixed because the next deploy's migration step reached Postgres (raised a
  Postgres-specific SQL error rather than running against sqlite).
- **FIXED (2026-07-04): migration `accounts.0004_convert_schools_to_fk` used
  raw SQLite `PRAGMA foreign_keys = OFF/ON` via `RunSQL`**, which is invalid
  syntax on Postgres (`psycopg.errors.SyntaxError`) and blocked the first
  real deploy once `DATABASE_URL` was pointed at Postgres. Postgres wraps
  migrations in a transaction, so the failed deploy rolled back cleanly with
  no data loss. Fixed by switching those two `RunSQL` PRAGMA statements to
  `RunPython` functions that only execute on `schema_editor.connection.vendor
  == 'sqlite'`, so the migration is a no-op for FK toggling on Postgres but
  unchanged on SQLite (verified via `sqlmigrate`).
- **FIXED (2026-07-04): `alumni.School.slug` used Django's default
  `SlugField` `max_length=50`.** SQLite never enforces varchar length limits,
  so this went unnoticed locally, but Postgres does — `seed_schools` failed
  with `DataError: value too long for type character varying(50)` on
  "Nelson Mandela African Institution of Science and Technology" (slugifies
  to 60 chars). Widened to `max_length=300` (migration
  `alumni.0002_alter_school_slug`) to match `name`'s max length.
- Social login (Google/Facebook) UI is present but OAuth isn't fully live —
  blocked historically on the `cryptography` package build on Windows. See
  `SOCIAL_LOGIN_SETUP.md`.
- Schools page has a placeholder "opportunities" section with no backing model yet.
- School coverage currently seeded mainly for Arusha region, Tanzania (plus 10
  major Tanzanian universities for the University/Tertiary field).
- Identity Score has no "Verification Status" component yet — deferred until
  there's an actual identity-verification flow (see product discussion in
  change log 2026-07-03).
- Visibility tiers / search ranking / badges based on Identity Score were
  discussed but explicitly deferred — there's no alumni search feature to
  rank yet.

## 7. Change log

Keep this brief — one line per notable change, newest first. Full detail lives
in git history.

- 2026-07-04: Diagnosed the "database keeps erasing on every push" / "login
  not working" reports down to one cause — Render's `DATABASE_URL` was
  literally `sqlite:///db.sqlite3`, so it never used the attached Postgres
  instance; every deploy hit Render's ephemeral disk and started empty. Build
  command and app code confirmed already correct. User fixed it via the
  Render dashboard (swapped the env var to the Postgres Internal Database
  URL) — confirmed resolved (see §6).
- 2026-07-04: That fix surfaced a second bug — migration
  `accounts.0004_convert_schools_to_fk` used raw SQLite `PRAGMA` statements
  that are invalid on Postgres, blocking the first deploy against the real
  database. Rewrote the FK-toggle steps as `RunPython` guarded by
  `connection.vendor == 'sqlite'` so the migration works on both backends
  (see §6).
- 2026-07-04: Fixing that surfaced a third bug — `alumni.School.slug`'s
  default `SlugField` `max_length=50` was too short for some seeded school
  names once slugified; Postgres enforces the limit, SQLite silently didn't.
  Widened to `max_length=300` (see §6).
- 2026-07-04: Fixed a real bug found during that audit — `alumni/views.py`
  (`CompleteOnboardingView`, `CohortMatchView`) and `config/views.py`
  (`select_school`) referenced `user.school`/`user.graduation_year`, fields
  that don't exist on `accounts.User` (it's `secondary_school` /
  `secondary_completion_year`). Would have raised `FieldError` if ever hit;
  currently unreachable from the web UI or the Android WebView client, but
  fixed for correctness (commit `5a073a4`). Also deduped `.gitignore` and
  added `staticfiles/` to it.
- 2026-07-04: Fixed dashboard avatar sitting "pushed down" at desktop widths —
  `.hero-grid` used `align-items: center`, which vertically centered the
  avatar against the whole text column (name + bio + badges) rather than the
  name at its top. Changed to `align-items: start`. Mobile layout (single
  column, avatar stacked above the text) was unaffected.
- 2026-07-04: Recolored all 10 templates to a new dark navy/gold theme
  (reference: `../LLA New Theme` screenshots) — near-black navy backgrounds,
  warm amber/gold accents, emerald/teal verification badges, unified
  slate-gray body text. Colors only; no markup or layout changes.
- 2026-07-03: Scaffolded a native Android WebView shell app
  (`../legacy-link-android`) with `testing`/`production` build flavors, so
  in-progress work can be viewed in the Android Studio emulator against the
  local dev server without touching the production Render deployment. Local
  `.env` switched to `DEBUG=True` for this workflow (Render's own env vars,
  used in production, are unaffected).
- 2026-07-03: Added the Identity Score profile-completion meter (replaces the
  old ad-hoc trust score) plus the fields it scores: `tertiary_school` /
  `tertiary_completion_year` (University), `employment_status`, and
  `company_name` on `accounts.User` (migration `accounts/0005_...`). Seeded 10
  Tanzanian universities via `seed_schools`. Dashboard now shows a progress bar
  and up to 4 ranked "complete your profile" suggestions.
- 2026-07-03: UI copy pass — "School not set" → "Complete your education
  profile"; "Class of N/A" → "Class Year Pending" (dashboard/cohort/connections);
  bio on dashboard truncated to 3 lines with a "Read more" toggle; "Profile
  Photo" → "Profile Picture"; "High School" → "Advanced Level (A-Level)";
  login page logo/spacing tightened.
- 2026-07-03: Fixed success messages rendering red — `login.html` hardcoded
  every Django message into a red `.error` div regardless of type, and
  `dashboard.html` never rendered messages at all (so a success message set on
  profile update would silently carry over and surface wrongly-styled on the
  next page that did render messages). Both templates now use `message.tags`
  with proper success (green) / error (red) styling.
- 2026-07-03: Fixed profile photo not displaying — `templates/profile.html` had
  no `<img>` preview (just "✓ Photo uploaded" text), and `config/urls.py` only
  served `/media/` uploads when `DEBUG=True`, so avatars 404'd in production.
  Added a live avatar preview (shows current photo, updates instantly on file
  select) and made media files always served via an explicit `re_path`.
- 2026-07-03: Documentation created; established as the living doc for the project.
- Terms of Use / Privacy Policy acceptance required at signup.
- Fixed invisible school dropdown options; seeded Arusha region schools.
- Made templates mobile/Android-WebView friendly; fixed onboarding + admin gaps.
- Added Postgres support via `DATABASE_URL`, with SQLite fallback for local dev.
- Fixed CSRF verification failure on sign-in in production.
