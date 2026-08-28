# Local Account Authentication and Session Isolation

## Goal

Restore real user isolation for the public TopoMind workbench. Each contributor
must register and sign in with an independent local account, and must only see
their own jobs, history, uploads, graph versions, exports, and refinements.
Deployment access keys are not part of the user-facing authentication flow.

## Design

The backend stores users and opaque web sessions in a small SQLite auth store
next to the existing blackboard database. Passwords are stored as salted
`hashlib.scrypt` digests. A successful registration or login creates a random
session token; only its SHA-256 digest is persisted, and the raw token is sent
in an HttpOnly cookie. The cookie uses `SameSite=Lax`, a bounded lifetime, and
sets `Secure` when the request is HTTPS.

Public endpoints are limited to health and account registration/login/logout
status operations. All job and graph endpoints continue to use the existing
`owner_id` filters, but `require_api_principal()` now resolves the owner from
the authenticated account. Unauthenticated protected requests return 401.

Existing jobs written under the temporary `public-workbench` owner are claimed
by the first account registered after this change. The claim is transactional
and happens once, preserving current data for the original operator while
keeping subsequent accounts empty and isolated.

## Frontend Flow

The existing server-token dialog becomes an account dialog with login and
registration modes. It submits credentials to the backend, relies on the
HttpOnly cookie, then reloads the workbench. A 401 clears the local account
state and reopens the dialog. Sign-out calls the account logout endpoint,
clears in-memory client state, and returns to the account dialog.

The existing provider/Qwen readiness state remains separate from account
authentication; account login only gates access to the public workbench.

## Verification

Backend tests cover password/session behavior, first-account legacy migration,
401 responses, and two-account owner isolation. Frontend checks cover the
account API calls and TypeScript/build validation. The deployed service is
verified with two independent cookie jars: each account sees only its own
history and cannot fetch the other account's task.
