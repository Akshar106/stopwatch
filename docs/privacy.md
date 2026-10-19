# Privacy policy

*Effective 2026-10-18. Stopwatch is a personal, non-commercial project. Contact: **[privacy contact email — to be added before launch]**.*

The short version:

- You can use every public page (stop search, "near me", reliability heatmaps, live predictions, data health) **without an account**, and we store nothing about you when you do.
- If you sign in, we store your Google account's email, name and ID, and the commutes you save. That's it.
- **Your location never leaves your phone.** "Near me" works entirely in your browser.
- **No ads, no analytics, no trackers.** The only cookies are the ones needed to keep you signed in.
- You can **download** or **delete** everything we hold about you at any time.

## What we collect and why

| Data | Why we need it | How sensitive | How long we keep it | Who can see it |
|---|---|---|---|---|
| Email address, Google account ID, display name | To sign you in and recognise your account | Personal | Until you delete your account | You; the operator only when investigating an incident |
| Saved commutes (route, direction, stop, days, time window, optional label) | To show your personal reliability summaries and, if you turn them on, alerts | **High**: they can reveal where and when you usually travel | Until you delete the commute or your account | You only |
| Sign-in sessions: a hashed session token, the first part of your IP address (/24 for IPv4, /48 for IPv6), your browser's user-agent string | To keep you signed in and to spot misuse of your account | Personal | 30 days at most (24 hours for demo accounts); expired sessions are deleted daily | Our systems |
| Security audit log: your account's internal ID (not your email), what action happened (for example "signed in", "deleted a commute"), whether it succeeded, the first part of your IP address | To investigate security problems and abuse | Pseudonymous | 365 days | The operator |
| Push notification subscription *(only if you turn on alerts)* | To send you delay alerts | Personal | Until you turn alerts off, or your browser tells us the subscription has ended | Our systems |
| Questions you type into "Ask Stopwatch" *(if that feature is enabled)* | To answer them | May contain whatever you type | Not stored. We keep only a daily count of how many questions you asked and their cost | — |
| Your precise location ("near me") | To find stops near you | High | **Never collected.** Your browser computes the nearest stops from a list of all stops it has already downloaded | — |

**Demo accounts** (the "try it without Google" button) hold no email or name. A demo account and everything in it are deleted automatically after 24 hours.

We do not collect: passwords, phone numbers, payment details, contacts, browsing history, or anything from other websites.

## Cookies

There is no cookie banner because we only use cookies that are strictly necessary:

| Cookie | Purpose | Lifetime |
|---|---|---|
| `__Host-sw_session` | Keeps you signed in. Contains a random token; not readable by page scripts | Until you sign out, or 7 days of inactivity, or 30 days at most (24 h for demo accounts) |
| `sw_oidc` | Protects the Google sign-in step against forgery; only sent to our sign-in pages | 10 minutes |

We do not use analytics, advertising or social-media cookies, pixels or SDKs.

## Who else is involved

Stopwatch does not sell or share your data. A few services are involved in running it, and some of them see technical information as a result:

| Service | What they see | Why |
|---|---|---|
| **Amazon Web Services** (US, us-east-1) | Everything we store, encrypted at rest; your IP address in web and API request logs | Hosting, storage and processing |
| **Neon** (hosted PostgreSQL, US) | Account and commute data, encrypted in transit | Database |
| **Google** | That you are signing in to Stopwatch | Only if you choose "Sign in with Google"; Google's privacy policy applies |
| **MBTA** (`api-v3.mbta.com`) | Your IP address and the stop you are viewing | The "right now" live predictions panel is loaded by **your browser directly from the MBTA**, so our servers are not involved. The MBTA's privacy policy applies |
| **Your browser's push service** (for example Google, Mozilla or Apple) | The alert message and when it was sent | Only if you turn on alerts |
| **Groq** (GroqCloud API) *(Ask Stopwatch, if enabled)* | The text of your question, without your name, email or account ID | To generate an answer from Stopwatch's published data |

## Logs

Our servers keep technical logs for **14 days** to debug problems. They contain request IDs, timings, internal account IDs and, in request logs, IP addresses. Your IP address is taken from the connection our CDN (CloudFront) sees, and wherever we store it in the database it is shortened to its first part (/24 for IPv4, /48 for IPv6). They never contain your email address, your saved commutes or commute labels, or session tokens; an automated test checks that these fields are removed from logs.

## Your rights and choices

- **See and download your data:** *Account → Download my data* gives you a JSON file with your profile, commutes, active sessions (dates and browser only), push subscriptions and your security history.
- **Correct it:** edit or delete any saved commute at any time.
- **Delete it:** *Account → Delete my account* deletes your account, commutes, sessions and push subscriptions **immediately**. We keep one audit record that an account was deleted, tied only to the internal ID, for security purposes (365 days).
- **Backups:** we keep nightly database backups for up to **30 days**. Deleted data disappears from backups as they age out; we only restore a backup to recover from a failure, and if we ever had to, we would re-delete accounts that had asked to be deleted.
- **Sign out everywhere:** ends all your sessions on all devices.

If you can't use these buttons, email the contact address above and we will do it for you.

## Security

Connections use HTTPS (TLS) everywhere. Session tokens are stored only as one-way hashes. Secrets are kept in an encrypted parameter store, never in code. Only the operator can access production systems, with multi-factor authentication. If we learn that your personal data was likely accessed without authorisation, **we will tell you** by email (or in the app for demo accounts, which have no email) without undue delay, along with what happened and what we did about it. To report a security problem, see [SECURITY.md](../SECURITY.md).

## Children

Stopwatch is not aimed at children under 13 and we do not knowingly collect their data. Public pages need no account.

## Changes to this policy

We will update this page when what we collect or how we use it changes, change the date at the top, and note it in the [changelog](../CHANGELOG.md). If a change means collecting new kinds of personal data, we will ask signed-in users before applying it to them.

## About the numbers on this site

Reliability figures are **independent, unofficial estimates** computed from the MBTA's public real-time feeds. They are not official MBTA statistics. See the [methodology](methodology.md).
