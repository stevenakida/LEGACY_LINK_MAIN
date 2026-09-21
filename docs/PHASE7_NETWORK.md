# Phase 7 — Network discovery & connection experience

Branch: `feature/phase7-network-experience` (not merged, not deployed).

## Where things live

| Concern | File |
|---|---|
| Why two people match (single source of truth) | `connections/matching.py` |
| State machine, integrity rules, counts, Discover/Connected/Pending queries, WhatsApp invite | `connections/services.py` |
| Web views (tabs, group page, actions, report-a-person, event beacon) | `config/network_views.py` |
| JSON/API (thin wrappers over the same service) | `connections/views.py` |
| Templates | `templates/connections.html`, `templates/network/*` |
| Styles / progressive-enhancement JS | `static/css/network.css`, `static/js/network.js` |
| Product events | `analytics/` (new, tiny — see "Analytics") |

## Education matching rules (`connections/matching.py`)

Education is four `(School FK, completion year)` pairs on `User`: Primary, O-Level
(`secondary_school`), A-Level (`high_school`), University (`tertiary_school`).
Matching always compares `School` primary keys, never typed names (two schools with
the same name do not match). Strongest wins; every match is kept in `all_matches`.

| Rank | Code | Rule |
|---|---|---|
| 0 | `CLASSMATE` | same institution + same level + same known year |
| 1 | `SAME_PRIMARY` | same primary institution, year differs/unknown |
| 2 | `SAME_O_LEVEL` | same O-Level institution, year differs/unknown |
| 3 | `SAME_A_LEVEL` | same A-Level institution, year differs/unknown |
| 4 | `SAME_UNIVERSITY` | same university, year differs/unknown |
| 5 | `SAME_SCHOOL` | same institution row under *different* levels |

**When each code fires** (`_pair_reason` in `connections/matching.py`; a pair of records is
compared only when both point at the same `School` id):

- *Same level, both years present and equal* → `CLASSMATE`.
- *Same level, any other year situation* (years differ, one missing, both missing) → the
  level code (`SAME_PRIMARY` / `SAME_O_LEVEL` / `SAME_A_LEVEL` / `SAME_UNIVERSITY`). Incomplete
  years therefore never make a same-school match disappear; they only stop it being
  `CLASSMATE`. O-Level 2004 vs O-Level (no year) → `SAME_O_LEVEL`.
- *Same school id under different levels* → `SAME_SCHOOL`. Level is always known here (it is
  the slot the school sits in), so "insufficient detail" can only mean the school shows up
  in two different slots. Every write path enforces `School.school_type == slot`
  (`profile_edit`, onboarding, API), and a `School` has one type, so this cannot arise
  from normal data today; it is a safety net for imports/legacy rows and is shown only on
  Connected/Pending cards (Discover compares same-level slots).

**Known data-quality risk (not a Phase 7 bug):** matching is by `School` id, so two alumni
who picked *different rows for the same real school* will not match. Measured on the
local staging school table (29,431 rows): 2,051 name+type collisions, but only 138 also
share region+district (96 primary, 42 secondary) and are likely true duplicates (e.g.
"14 Kambarage" ids 29379 and 3396, both Geita TC). The rest are mostly different schools
with common names, so a name-only merge would be wrong. Production impact is unmeasured.
Fix belongs in a separate school-dedup task (canonical id / alias mapping).

`MatchReason` is structured (`reason_code`, `display_label`, `institution_id`,
`institution_name`, `education_level`, `cohort_year`, `as_dict()`); templates render it,
never derive labels themselves. The year on a card is the *other* person's.

## Connection state machine

```
NONE ──send──▶ PENDING_OUTGOING (requester) / PENDING_INCOMING (receiver)
PENDING_INCOMING ──accept──▶ CONNECTED
PENDING_INCOMING ──decline─▶ DECLINED  (final, existing policy)
CONNECTED ──remove──▶ NONE             (row deleted, may reconnect)
any ──block──▶ BLOCKED                 (rows deleted; nothing possible until unblocked)
NONE ──dismiss ✕──▶ DECLINED           (one-sided, silent)
```

Refused by the backend (`services.send_request`): self, unknown/inactive target, blocked
either way, already connected, already pending, *they already asked you*, previously
declined/dismissed, rate limit (20 per 10 min, `RATE_LIMIT_CONNECTION_REQUEST_*`).
`respond_to_request` only lets the receiver act on a still-`pending` request (someone
else's or a missing request both return "not found"; answered requests return
`already_resolved` and can't be flipped) and refuses if a block exists.
Concurrent writes between one pair are serialised with row locks on the two users
(`select_for_update`, effective on Postgres).

Counts (`services.network_state`): **Connections** = accepted, both sides active,
neither blocked; **Pending** = *incoming* pending only. The dashboard uses the same
function.

## Discover

Candidates = active users at the same institution + same level as one of *your*
education records, minus: yourself, blocked (either way), accepted, declined/dismissed,
and people who already sent *you* a request (they're in Pending). People you already
asked stay visible as **Request Sent**. Per education record you get up to two groups:
*Class of Y* (`CLASSMATE`) then *Other years* (`SAME_*`); a record with no year yields one
*All years* group. 4 profiles per group, **View all** →
`/connections/discover/<level>/<school_id>/<cohort|other|all>/` (paginated, 20/page,
404 unless the group belongs to your own journey). Search: name, school, or 4-digit
class year; filters: All/Primary/O-Level/A-Level/University.

## Optional connection note

`Connection.message` (≤300 chars, plain text, control characters stripped, HTML-escaped on
output, never marked safe). Tapping **Connect** opens a sheet with an optional note. With
JS off the form still posts (no note). Pending shows the note, or "Wants to connect with
you." when there is none.

## Endpoints

Web (all POST + CSRF, session auth; XHR gets JSON, others get flash + redirect):
`/connections/` (GET, `?tab=&level=&q=&page=`), `/connections/discover/<level>/<id>/<mode>/`,
`connect/<uuid>/`, `respond/<uuid>/`, `remove/<uuid>/`, `dismiss/<uuid>/`,
`report/<uuid>/` (GET form + POST, reuses `moderation.file_report`), `track/` (allowlisted
client events). Unchanged: block/unblock/mute/unmute, `messages/start/`.
API: `/api/connections/send/<id>/` (optional `message`), `<id>/respond/` (now 409 when
already answered), `/api/connections/?tab=` — same service, same rules.

## Analytics

The Phase 7 brief said to reuse "Phase 6 analytics". Checked 2026-09-21: **no analytics
system exists in this repository** (no code in any branch, stash or git history). The
repo's own roadmap (`Phase 0.docx`) defines Phase 6 as *rate limits + upload-limit
verification + final auth/signed-URL review* — that is what shipped as Phase 6 — so the
"Analytics & Monetization Foundation" phase from the product roadmap was never built here;
the two numbering schemes diverged.

`analytics.ProductEvent` is therefore a new, deliberately generic, allowlisted
append-only log: columns `name`, `actor` (nullable FK), `properties` (JSON), `created_at`.
`analytics.services.EVENT_DOMAINS` is the registry of allowed event names by domain
(`network`, `account`, `education`, `matching`, `messaging`, `posts`, `opportunities`,
`notifications`); only `network` is emitted so far, the rest are declared but unwired.
Property keys are allowlisted too (`tab`, `education_level`, `match_reason_code`,
`has_results`, `result_count_bucket`) — never names, contacts or note text. Network
events: `network_opened`, `discover_opened`, `discover_search`,
`education_filter_selected`, `discover_group_view_all`, `profile_opened_from_network`,
`connection_request_sent|accepted|declined`, `connection_removed`,
`connected_message_clicked`, `whatsapp_invite_clicked`, `pending_opened`. Swap
`analytics.services.record_event` for the real Phase 6 sink if/when it exists.

Metric derivations (no dashboard built): *classmate discovery rate* = users with ≥1
`CLASSMATE` candidate / users with education; *request rate* = users who sent ≥1
`connection_request_sent` / users with candidates; *activation* = users with ≥1 accepted
`Connection`; *conversion* = accepted / sent (`Connection.status`); *cohort density* =
`User` count per `(school, year)`.

## Performance

Measured (query counts, constant regardless of list size, asserted in tests): Discover 18,
Connected 12, Pending 14 (includes session/auth/context-processor and event-insert
queries). New indexes: `conn_receiver_status_idx (receiver, status, -created_at)`,
`conn_requester_status_idx (requester, status)`. No `User` indexes added: Discover
filters on the indexed school FK; add `(school, year)` composites when a school's alumni
count reaches the tens of thousands. Connected filters/searches in Python over the
user's own (small) connection set, then paginates.

## Deployment / rollback

Deploy: merge → migrations `connections.0003`, `analytics.0001` run automatically →
`collectstatic` (new `network.css`, `network.js`). Optional env: `PUBLIC_APP_URL`,
`RATE_LIMIT_CONNECTION_REQUEST_MAX/_WINDOW_SECONDS`. Rollback: revert the merge;
`migrate connections 0002` and `migrate analytics zero` drop the field, indexes and table
(both migrations are reversible; only request notes and events are lost).
Pre-deploy check worth running on production: duplicate opposite-direction Connection
rows (`A→B` and `B→A`) predate the shared service; the code tolerates them
(accepted > pending > declined), but they should be cleaned up before adding a unique
unordered-pair constraint.
