# LegacyLink Africa — Documentation

> Living document. Update this file whenever a feature, flow, or setup step changes.
> Last updated: 2026-07-12

## 1. What the app does

LegacyLink Africa is a Django web app (server-rendered pages + a REST API) that
reconnects alumni from African schools. A user registers, picks their school(s)
and graduation year, and the app matches them into a **cohort** (same school +
same completion year) and lets them send/accept **connection requests** with
other alumni — similar in spirit to a school-focused LinkedIn/Classmates.com.

Core concepts:
- **User** (`accounts.User`) — custom user model, logs in with phone number
  or email (`phone_or_email`) instead of a username.
- **School** (`alumni.School`) — primary, secondary (O-Level), high school
  (A-Level), or university, scoped to region/district/country. Populated from
  a real Tanzania education master spreadsheet (27,007 schools) via
  `python manage.py import_school_database` — see §5 and §6 for the
  outstanding Render production import step.
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
3. **Dashboard (Home)** at `/dashboard/` — compact greeting header, a compact
   Identity Score card (ring + top profile-completion suggestion), a 4-stat
   row (Connections, Pending, Opportunities, Events — all four now backed by
   real querysets, see §6 history), a "Suggested for You" cohort carousel, and
   an Upcoming Events list drawn from real `Opportunity` rows. The old
   profile-hero/About/Verified-Identity sections that used to live on this
   page moved to the redesigned Profile page (item 6 below).
4. **Connections** at `/connections/` — one page, three tabs: **Pending**
   (accept/decline inline), **Connected** (with a Message button per person,
   opens a chat thread), and **Discover** (cohort matches — same school +
   graduation year — with mutual-connection counts and an actionable
   WhatsApp-invite empty state when no classmates have joined yet). This page
   absorbed the old standalone `/cohort/` page, which now just redirects to
   `/connections/?tab=discover`.
5. **Messages** at `/messages/` — conversation list (unread badges, last
   message preview) and a chat thread per conversation
   (`/messages/<conversation_id>/`). Starting a conversation
   (`/messages/start/<user_id>/`) is only allowed between users with an
   **accepted** Connection — enforced server-side, not just hidden in the UI.
   New messages arrive via 4-second polling (`/messages/<id>/poll/`), not
   WebSockets/Channels (this project has no channels/redis infra) — this
   matches the product roadmap's own recommendation for a first messaging
   MVP. Block/report is not built yet (see §6).
6. **Profile** at `/profile/` — view-mode by default (avatar, verified badge,
   bio, education timeline across all four school levels, profile-strength
   ring). Editing moved to `/profile/edit/` (name, bio, profile picture,
   current location, professional info, and the four searchable school
   autocomplete fields backed by `/schools/search/`).
7. **Opportunities** at `/opportunities/` (renamed from the old, confusingly-named
   `/schools/` URL — `/schools/` now just redirects here) — real `Opportunity`
   rows (Job / Mentorship / Event), filterable by type and by "My school".
   Apply/Join/RSVP records a lightweight `OpportunityInterest` row per user
   (not a full application workflow with resumes/review states — that's a
   later phase per the roadmap). Opportunities are posted via `/admin/` for
   now; no in-app posting flow yet.
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
| GET | `/api/alumni/schools/?q=&type=` | Search schools (JWT-authenticated) |
| PATCH | `/api/alumni/onboarding/` | Complete onboarding |
| GET | `/api/alumni/cohort/` | Get classmates |
| POST | `/api/connections/send/{user_id}/` | Send connection request |
| PATCH | `/api/connections/{id}/respond/` | Accept/decline request |
| GET | `/api/connections/?tab=pending` | List connections |
| GET | `/api/opportunities/?type=job\|mentorship\|event` | List active opportunities |
| GET | `/api/messaging/conversations/` | List the JWT user's conversations |
| GET/POST | `/api/messaging/conversations/{id}/messages/` | Read/send within a conversation |

`/api/auth/login/` was completely broken until 2026-07-07 (see §6/§7) — every
login attempt returned 401 regardless of credentials, for every user. Fixed.

There's also a plain (non-DRF) session-authenticated endpoint used only by the
browser-rendered school autocomplete widget, not part of the JWT API surface:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/schools/search/?type=&q=` | Session-auth school search (profile/onboarding autocomplete) |
| GET | `/messages/{id}/poll/?after={message_id}` | Session-auth chat polling (4s interval from the thread page) |
| POST | `/messages/{id}/send/` | Session-auth send a chat message |

## 4. Project structure

- `config/` — Django project settings, root URLconf, and the server-rendered
  views (home, login, register, dashboard, profile, opportunities,
  connections, messages/chat, onboarding, terms). All template-facing view
  logic lives here by convention — each app's own `views.py` is DRF-only, so
  the two never share (and can't collide on) URL names.
- `accounts/` — custom `User` model + auth API (register/login/JWT).
- `alumni/` — `School` model + schools/cohort/onboarding API.
- `connections/` — `Connection` model + connection request API.
- `opportunities/` — `Opportunity` + `OpportunityInterest` models (Jobs /
  Mentorship / Events) + a DRF list API.
- `messaging/` — `Conversation` / `Participant` / `Message` models (1:1
  messaging, restricted to accepted connections) + a DRF API for the Android
  app. Also provides `messaging.context_processors.unread_message_count` so
  the bottom nav's Messages badge works on every page.
- `templates/` — server-rendered HTML pages (mobile/Android-WebView
  friendly). `base.html` + `partials/bottom_nav.html` are the shared app
  shell (single 5-tab bottom nav: Home / Network / Messages / Opportunities /
  Profile) that `dashboard.html`, `connections.html`, `opportunities.html`,
  `profile.html`, `profile_edit.html`, `messages.html`, and `chat.html` all
  extend. Pre-auth pages (login/register/onboarding/terms) stay standalone.
  `static/css/theme.css` holds the one shared stylesheet (dark navy / gold /
  teal design system) — previously every page duplicated its own inline
  `<style>` block, which had already drifted (3 vs. 4 bottom-nav tabs across
  pages before this).
- `../legacy-link-android/` (sibling folder, separate Android Studio project)
  — the native WebView shell that loads this app on Android. See its README
  and [section 5](#5-setup--running-locally) for the testing/production split.

## 5. Setup / running locally

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py import_school_database --purge-legacy-seed
python manage.py createsuperuser
python manage.py runserver
```

`import_school_database` reads
`../LegacyLink_Africa_Tanzania_Education_Master_Database.xlsx` (project root,
sibling to `LEGACY AFRICA/`) and upserts all 27,007 real Tanzania schools,
matched by the spreadsheet's `legacy_school_id` so it's safe to re-run.
`--purge-legacy-seed` deletes any old `School` rows with no `external_id`
(i.e. the original hand-typed `seed_schools` list, now superseded). The older
`seed_schools` command still exists but should no longer be used — it
predates the real dataset and its ~65 rows have no `external_id`, so they'd
be recreated as name-collision duplicates alongside the real data.

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

## 5a. Admin dashboard, superusers & roles

The Django admin (`/admin/`) is the only admin dashboard — no separate
custom admin UI exists.

- **Superusers** have full unrestricted access regardless of groups/permissions.
  Created via `python manage.py createsuperuser` (or promoted via
  `user.is_staff = user.is_superuser = True`).
- **Staff users without superuser** only see/do what their assigned Groups or
  individual permissions allow.
- **Roles = Django Groups.** Create a Group under Admin → Authentication and
  Authorization → Groups, attach the model permissions that define the role
  (e.g. "Content Moderator" → add/change/delete on `alumni.School`), then
  assign users to that group from their User edit page (`accounts/admin.py`
  `UserAdmin` — the "Permissions" fieldset exposes `groups` and
  `user_permissions` via a filter_horizontal widget). No custom role model
  was built; this uses Django's built-in group/permission system as-is.
- Local dev superuser: `stevenakida@gmail.com` (created 2026-07-05). An
  older superuser `disheseka@gmail.com` also exists locally and was left
  untouched.
- Production (Render) admin accounts are managed separately, via Render's
  Shell tab running `python manage.py createsuperuser` — not from this repo.

## 6. Known limitations / in-progress work

- **RESOLVED (2026-07-08): `CORS_ALLOW_ALL_ORIGINS = True` and
  `ALLOWED_HOSTS` defaulting to `*`** let any website call the JWT API and
  let the app answer to any Host header. Confirmed there's no legitimate
  cross-origin caller — the Android app is a WebView that loads
  `legacy-link-main.onrender.com` directly (same-origin), and the only
  browser-side `fetch()` (`static/js/school-autocomplete.js`) hits a
  relative, same-origin endpoint. Replaced with
  `CORS_ALLOWED_ORIGINS`/`ALLOWED_HOSTS` defaulting to
  `legacy-link-main.onrender.com` (plus `localhost`/`127.0.0.1` for
  `ALLOWED_HOSTS`), both still overridable via env var if a real
  cross-origin frontend shows up later. **Still needed:** confirm Render's
  dashboard doesn't have its own `ALLOWED_HOSTS=*` env var overriding this
  default in production (dashboard env vars take precedence over the code
  default, same as `DATABASE_URL` was in the §6 entry below).
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
- **RESOLVED (2026-07-12): Opportunities now has a real backend model** — see
  change log entry below. `/schools/` (confusingly named) redirected to the
  new `/opportunities/`.
- **RESOLVED (2026-07-12): Dashboard's Opportunities/Events stat tiles are now real**,
  backed by `Opportunity` querysets — see change log below.
- **Kiswahili (EN/SW) toggle is not built.** No i18n scaffolding exists at
  all yet (no `LANGUAGES`, `LocaleMiddleware`, or `{% trans %}` anywhere) —
  every string is hardcoded English. Deliberately deferred as its own later
  pass (matches the roadmap doc's framing of translation as "parallel,
  ongoing," not a blocker) rather than bundled into the 2026-07-12 redesign.
- **Messaging has no block/report yet.** 1:1 messaging restricted to accepted
  connections shipped 2026-07-12; block/report was explicitly deferred as a
  fast-follow, not built in the same pass.
- **No general "view another alum's public profile" route.** `/profile/` is
  self-view only; Connect/Message entry points work from Connections list
  rows, but there's no `/profile/<user_id>/` page yet.
- Identity Score has no "Verification Status" component yet — deferred until
  there's an actual identity-verification flow (see product discussion in
  change log 2026-07-03). The dashboard's new "Confirmed by document" trust
  tier is deliberately shown as "Coming soon" for the same reason.
- Visibility tiers / search ranking / badges based on Identity Score were
  discussed but explicitly deferred — there's no alumni search feature to
  rank yet.
- **RESOLVED (2026-07-07): Render production school data.** Production now
  has the same 27,007-school dataset as local dev.
- **RESOLVED (2026-07-07): Render's deploy pipeline was auto-running
  `python manage.py seed_schools` on every deploy** (chained onto the end
  of the build command). `seed_schools` predates the real spreadsheet
  import and is idempotent-but-oblivious to it (`get_or_create` by name, no
  `external_id`), so every deploy silently re-added the old ~54-entry seed
  list as duplicate rows (e.g. a second "Azania Primary School" alongside
  the real spreadsheet one). Confirmed twice (two deploys after the manual
  production import each brought the 54 rows back), purged both times.
  Fixed at the source via Render's REST API (`PATCH /v1/services/{id}`) —
  build command is now
  `pip install -r requirements.txt && python manage.py collectstatic
  --noinput && python manage.py migrate`, `seed_schools` removed. See
  §7 and the `import_school_database` note above — that command is now the
  only thing that should ever populate `School` rows in this project.

## 7. Change log

Keep this brief — one line per notable change, newest first. Full detail lives
in git history.

- 2026-07-12: Major redesign driven by a user-supplied interactive mockup +
  product roadmap doc. Introduced a real shared app shell (`base.html` +
  `static/css/theme.css` + `partials/bottom_nav.html`) replacing 5 pages'
  worth of duplicated inline CSS/nav markup that had already drifted (3 vs 4
  bottom-nav tabs across pages). Rebuilt Dashboard, Connections (merged
  `/cohort/` into a Pending/Connected/Discover 3-tab page, added
  mutual-connection counts and actionable empty states), and Profile (split
  into view-mode `/profile/` + `/profile/edit/`). Shipped two new apps: 
  **`opportunities`** (real `Opportunity`/`OpportunityInterest` models —
  Jobs/Mentorship/Events with type + "My school" filters and lightweight
  Apply/Join/RSVP tracking, replacing the hardcoded mock data that used to
  live in `schools.html`) and **`messaging`** (real 1:1 messaging —
  `Conversation`/`Participant`/`Message` models, restricted to accepted
  connections, 4-second polling per the roadmap's own recommendation since
  this project has no channels/websocket infra). Renamed the confusingly-named
  `/schools/` URL to `/opportunities/` (old URL now redirects). Verified
  end-to-end with Playwright against a live local server: full nav/page
  render check, a two-user Connect → Message → send → poll → reply flow, and
  a security check that a non-participant is blocked from a conversation
  thread. Kiswahili i18n and messaging block/report were deliberately scoped
  out as later passes — see §6.
- 2026-07-08: Tightened `CORS_ALLOW_ALL_ORIGINS`/`ALLOWED_HOSTS` — see §6.
- 2026-07-07: Fixed Render's build command via its REST API (user supplied
  an API key) to stop auto-running `seed_schools` on every deploy — see §6.
  Also confirmed via Render's actual build logs that the `47f68bd` auto-deploy
  had genuinely `build_failed` on the `accounts.0006` cast bug, matching the
  diagnosis below exactly.
- 2026-07-07: Verified the school autocomplete live on production (real
  throwaway account via `/register/`, tested `/schools/search/` for all four
  types, deleted the account after). Found Render's deploy pipeline
  apparently auto-runs `seed_schools` on every deploy, re-adding 54
  duplicate legacy rows each time — purged twice, still needs a Render
  dashboard fix (remove `seed_schools` from the build/release command). See
  §6.
- 2026-07-07 (commit `170b0e6`): Ran the production school-data migration
  and import against Render directly (no Render CLI/shell available in the
  dev environment — used `manage.py` locally with `DATABASE_URL` overridden
  to Render's *External* Postgres connection string; the Internal one only
  resolves inside Render's network). `sqlmigrate`-ing `accounts.0006` against
  the real production connection before applying it caught a real bug: its
  `AlterField` (CharField→ForeignKey) made Postgres cast the column with
  `::bigint`, which fails on any non-numeric text (same class of
  SQLite-tolerates/Postgres-rejects bug as `accounts.0004`, see 2026-07-04
  below). Fixed by switching to `RemoveField`+`AddField` (no cast needed).
  Applied to Render, then ran
  `import_school_database --purge-legacy-seed` against production — 27,007
  schools imported, old 54-row seed purged, confirmed no real user's school
  selection was affected. Production and local dev now match.
- 2026-07-07 (commit `47f68bd`, pushed to `main`): Rebuilt the dashboard to
  match a new mobile mockup (greeting header with real logo, Identity Score
  ring, stat tiles, suggested-classmates carousel, trust-tier Verified
  Identity panel). Imported the real 27,007-row Tanzania education master
  database (primary/secondary/A-level/university), converted `high_school`
  from free text to a controlled `School` FK, and replaced all four school
  `<select>` dropdowns with a searchable autocomplete (`/schools/search/`) —
  the old dropdowns would have tried to render 20k+ `<option>` tags. See §6
  for the still-outstanding Render production data-import step.
- 2026-07-07: Fixed `config/settings.py` reading `DEBUG`/`ALLOWED_HOSTS` via
  raw `os.getenv` instead of `python-decouple`'s `config()` (unlike
  `SECRET_KEY`, which already used `config()`), so local `.env`'s
  `DEBUG=True` was silently ignored and the dev server never served static
  files. Switched both to `config()`.
- 2026-07-07: Fixed `accounts/backends.py`'s `PhoneOrEmailBackend` only
  reading the `username` kwarg passed to `authenticate()`. The web login form
  happens to call it that way so it worked, but DRF SimpleJWT calls
  `authenticate()` with the credential under the dynamic `USERNAME_FIELD`
  name (`phone_or_email`), which the backend silently ignored — so
  `/api/auth/login/` returned 401 for every user, always (registration still
  worked since it bypasses `authenticate()`). Also fixed a malformed
  `name=' api-register'` URL name (leading space) in `accounts/urls.py`.
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
