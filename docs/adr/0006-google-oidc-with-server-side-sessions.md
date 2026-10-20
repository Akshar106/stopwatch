# ADR-006: Google OpenID Connect sign-in with server-side sessions

- **Status:** Accepted, 2026-10-18. ID-token verification uses PyJWT instead of Authlib, which earlier drafts of [04 §2](../04-architecture.md#2-technology-stack) and [05 §2](../05-security-reliability.md#2-authentication) named; both now match this ADR.
- **Deciders:** project author
- **Related:** [05 §2–3](../05-security-reliability.md#2-authentication), [contracts §4](../contracts.md#4-dynamic-api-apiv1), [ADR-005](0005-api-gateway-http-api-over-function-urls.md), RB-6

## Context

Accounts exist only so riders can save commutes (and, later, receive alerts). Saved commutes are the most sensitive data in the system: they reveal where and when a person routinely travels ([05 §1](../05-security-reliability.md#1-threat-model)). Requirements:

- No password storage, reset flows or email sending (each is a liability for a one-person project).
- Sessions that can be revoked instantly: logout, "sign out everywhere", incident response.
- Nothing readable by JavaScript that grants account access.
- Local development and a no-Google path for visitors (temporary demo accounts).

## Decision

**Identity:** Google OIDC, authorization-code flow with **PKCE**, `state` and `nonce`, scopes `openid email profile`.

- `GET /api/v1/auth/login` stores state, nonce, PKCE verifier and `next` in `sw_oidc`, an HMAC-signed cookie with a 10-minute TTL scoped to `Path=/api/v1/auth`.
- `GET /api/v1/auth/callback` exchanges the code at Google's token endpoint with **httpx** (the same hardened client used for feeds: strict timeouts, no cross-host redirects).
- The ID token is verified with **PyJWT** (`pyjwt[crypto]`): signature against Google's JWKS fetched and cached by `jwt.PyJWKClient`, plus explicit checks of `iss`, `aud` (our client ID), `exp`/`iat` and `nonce`. Users are keyed by `(oidc_issuer, oidc_subject)`, never by email.

**Sessions:** server-side rows in Postgres.

- A 256-bit random token in `__Host-sw_session` (Secure, HttpOnly, SameSite=Lax, Path=/); `sw_session` without `Secure` locally.
- Only a SHA-256 hash of the token is stored in `sessions`, so a database leak does not leak live sessions.
- Idle timeout 7 days; absolute limit 30 days (24 h for demo users). Rotated on login; logout deletes the row; `POST /auth/logout-all` deletes all of a user's rows.

**CSRF:** same-origin API (no CORS), SameSite=Lax, `X-Requested-With: stopwatch` required on state-changing requests (forces a preflight cross-site), and a double-submit `X-CSRF-Token` for signed-in state changes.

**Demo accounts:** `POST /auth/demo` creates an isolated `is_demo` user (3 per hour per IP prefix, 500 active, 3 commutes, no push or Ask), purged by `maintenance`.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Email + password** | Password storage, reset tokens, email deliverability and credential stuffing are all new attack surface for no product benefit. |
| **Amazon Cognito** | Heavier setup, hosted UI customization, harder to run locally; still needs a session strategy for the SPA. |
| **Hosted auth (Auth0, Clerk, …)** | Another vendor with free-tier MAU limits and its own SDK in the frontend; the flow we need is small. |
| **JWT access tokens in `localStorage`** | Readable by any XSS; not revocable before expiry without a denylist, which is a session table by another name. |
| **Stateless signed-cookie sessions** | Revocation (logout-all, incident response) would need a server-side denylist anyway. |
| **Authlib** (the plan in early drafts of 04/05) | The flow needs exactly two operations: one token-endpoint POST and one ID-token verification. PyJWT (already a dependency) and httpx (already used for feeds) cover them in a small module whose every check (bad `iss`, `aud`, `nonce`, expiry, signature) is unit-tested directly, without adopting a framework integration and its own session/cookie handling. |

## Consequences

**Positive**

- No password liability; Google handles MFA and account recovery.
- Sessions are revocable instantly and individually; a database leak exposes only token hashes.
- The `__Host-` prefix pins the cookie to our origin and path `/` with `Secure`, out of reach of JavaScript and subdomains.
- Authorization stays simple: every request has a server-resolved `user_id`, which repositories require as `owner_id` ([05 §3](../05-security-reliability.md#3-authorization)).

**Negative**

- **Dependency on Google:** riders without a Google account rely on demo accounts; an outage or policy change at Google blocks sign-in (public pages are unaffected).
- Every authenticated request reads `sessions` in Postgres, so a Neon wake-up can add ~0.5–1 s to the first request after idle.
- We own the OIDC code path, so correctness depends on our tests: the token-validation unit tests and the authorization matrix are release-blocking.
- JWKS caching is per warm container; a Google key rotation is handled by PyJWKClient refetching on an unknown `kid`, which needs outbound access to Google at that moment.

## Revisit when

- Users ask for a non-Google option: add GitHub as a second OIDC provider (the `users` table already keys on issuer + subject; no account linking in the MVP).
- The API moves off a single backend (several services would need to share session validation).
- Regulatory or data-sensitivity changes require stronger authentication (for example passkeys/WebAuthn).
