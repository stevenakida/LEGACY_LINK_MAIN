# Google Play listing and Play Console answers (draft, 2026-11-20)

Everything here is meant to be pasted into Play Console. Items marked **CONFIRM**
need the owner's decision. Google's limits are noted in brackets; check them
against the Console as it can change.

## App details

| Field | Value |
|---|---|
| App name [30 chars] | `LegacyLink Africa` |
| Package | `africa.legacylink.app` (version 1.0.1, versionCode 2) |
| Default language | English (United Kingdom or Tanzania); add Swahili (`sw`) as a second language if wanted |
| App or game | App |
| Free or paid | Free |
| Category | Social (alternative: Communication) **CONFIRM** |
| Contact email | developer@legacylink.africa |
| Website | https://app.legacylink.africa |
| Privacy policy URL | https://app.legacylink.africa/privacy/ (redirects to the policy section of /terms/) |
| Account deletion URL | https://app.legacylink.africa/account-deletion/ (public, no login) |

## Short description [80 chars]

> Reconnect with your school classmates and alumni across Tanzania and Africa.

(75 characters)

## Full description [4000 chars]

```
LegacyLink Africa helps you find and stay connected with the people you went to school with.

Add the schools you attended, from primary school to university, and LegacyLink Africa shows you classmates (same school, level and year) and schoolmates (same school, other years) so you can reconnect.

WHAT YOU CAN DO
• Find classmates and schoolmates and send connection requests
• Chat one-to-one with your connections, and share photos
• Post news to your connections, your cohort, your school, or publicly
• Follow what your cohort is up to in your Home feed
• Browse opportunities and events shared by the community
• Get notifications for new messages, requests and activity
• Use the app in English or Kiswahili

BUILT FOR COMMUNITY
• Over 28,000 Tanzanian schools to choose from, and a request form if yours is missing
• Block and report tools on posts and people
• Delete your account and your data at any time from Settings

YOUR PRIVACY
You choose who sees each post. You can delete your account whenever you like, and your profile, posts, chats and photos are removed.

Privacy policy: https://app.legacylink.africa/privacy/
Questions: developer@legacylink.africa
```

## Graphics to prepare (not yet made)

- App icon: 512 x 512 PNG, 32-bit, up to 1 MB (use the LegacyLink mark on the navy background).
- Feature graphic: 1024 x 500 PNG or JPG.
- Phone screenshots: at least 2, up to 8, JPG or PNG, 16:9 or 9:16 with each side 320 to 3840 px. Suggested screens: Home, Network (Discover), a chat, a profile, Opportunities.

## App access (login-required app)

Select "All or some functionality is restricted" and add one instruction set:

- Name: `Google Play reviewer`
- Instructions: "Open the app and sign in on the first screen with the phone number or email and password below. No other steps or codes are needed. After signing in you can see Home, Network, Messages, Opportunities and Profile."
- Username and password: **the owner registers this account through the app's own sign-up page and pastes the credentials here. Use a password used nowhere else, and delete the account after approval.**

## Content rating (IARC questionnaire) **CONFIRM each answer**

- Category: social / communication app.
- Users can interact or exchange content with each other: **Yes** (posts, chat).
- Users can share their location with each other: **No**.
- Violence, sexual content, profanity, controlled substances, gambling as app content: **No** (user-generated only).
- Digital purchases: **No**.

## Target audience and content

- Target age: **18 and over** (the Terms of Use require 18+ or lawful consent). Not designed for children, so the Families policy does not apply.
- Contains ads: **No**.
- News app: **No** (the app auto-posts NECTA exam announcements as a source, but it is not a news app).

## User-generated content policy (Play requirement)

The app has: Report and Block on posts and people, Report on photos, an admin moderation queue
(Django admin → Moderation), and the ability for staff to hide or reject posts. Mention these in
the Console's UGC section if asked.

## Data safety form (answers must stay true to the code)

Data is encrypted in transit (HTTPS): **Yes**. Users can request deletion: **Yes**, URL above.

| Data type | Collected | Shared | Required or optional | Purpose |
|---|---|---|---|---|
| Name | Yes | No | Required | Account management, app functionality |
| Email address | Yes | No | Optional | Account management, recovery |
| Phone number | Yes | No | Required (or email) | Account management |
| Other personal info (schools attended, years, location text, job, bio) | Yes | No | Optional | App functionality |
| Photos | Yes | No | Optional | App functionality (profile and post photos) |
| Messages / other user content (posts, comments, chats) | Yes | No | Optional | App functionality |
| Device or other IDs (push notification token) | Yes | No | Required for notifications | App functionality |
| App interactions (first-party product events, no names or message text) | Yes | No | Required | Analytics |

Notes for the owner:
- "Shared" is No: Firebase Cloud Messaging (push) and DigitalOcean (hosting) act as service
  providers on our behalf. **CONFIRM** this reading against Google's definition.
- Video and document uploads are switched off in production, so do not declare them.
- Not collected: precise or approximate location from the device, contacts, financial info,
  health info, audio, files from the device other than the photo the user picks.

## Permissions the app asks for

- Internet and network state (loads the site).
- Notifications (Android 13 and later asks the first time the user reaches Home).
- No camera, contacts, location or storage permissions: photos are picked with the system file picker.

## Release notes (first release)

> First release of LegacyLink Africa: find classmates, chat, post to your cohort, and get notifications.

## Review-risk note

Play can reject apps that are only a website in a frame ("minimum functionality"). Points to stress
in the listing and in any appeal: push notifications, photo sharing from the device, the offline
screen, native notification permission handling, report/block moderation, account deletion in-app.
