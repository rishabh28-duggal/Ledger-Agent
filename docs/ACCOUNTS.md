# Username/password accounts

Ledger no longer uses Firebase Authentication. The browser sends username and
password to the same-origin backend over HTTPS in production. It does not load an
authentication SDK, request an email address, or offer password recovery.

## Storage and ownership

- Passwords: salted Argon2id hashes using `argon2-cffi` 25.1.0. Verification uses
  the library's high-level API, with rehashing after successful login when needed.
  A maximum of four password hash operations run concurrently per instance.
- Usernames: 3–32 letters/numbers/`_.-`, including all-numeric names. Uniqueness
  uses Unicode NFKC normalization and case folding, enforced atomically.
- Passwords: 8–1024 characters, without complexity rules or trimming.
  `12345678` is accepted and only that exact password authenticates its account.
- Every registration receives a fresh random `acct_…` ownership ID. Folder,
  invoice, source and export access continues to derive paths from the server's
  authenticated user, never a supplied username or owner ID.
- Existing invoice tables, Firestore user paths, original files and audit records
  are retained. Old Firebase/demo data is not claimed by newly registered names.
- SQLite uses the existing database with an additive `auth_records` table.
  Cloud mode uses Firestore `ledger_auth_accounts`, `ledger_auth_logins` and
  `ledger_auth_rates`, using transactions for concurrent updates.

## Login lifecycle and request protection

Login issues a random 256-bit opaque token. Only its SHA-256 hash is persisted;
the raw token is sent in an HttpOnly, SameSite=Lax cookie. Cookies are Secure on
Cloud Run or when `LEDGER_COOKIE_SECURE=1`. Expiry is absolute and checked on
every authenticated request (default 24 hours). Login rotates the browser's old
login; logout deletes its server record. Starting demo revokes the current login,
and signing in removes the demo cookie. Existing signed demos still expire after
24 hours and do not need registration.

All `/api/` mutations require a signed HttpOnly CSRF cookie and an equal
`X-CSRF-Token` header obtained through `GET /api/csrf`. Cross-origin and
`Sec-Fetch-Site: cross-site` writes are rejected. The internal invoice worker
continues to require its Google service-account OIDC identity, not browser cookies.

Login errors do not distinguish an unknown username from an incorrect password;
unknown names also perform an Argon2 verification. Durable 15-minute rate windows
allow 10 login attempts per normalized name and 60 per client IP. Signup permits
10 attempts per IP in 15 minutes. Successful attempts also count. Exhausted limits
return 429 with Retry-After. Forwarding headers must only be trusted behind the
intended hosting proxy. The supplied container runs behind Cloud Run.

## Validation on 6 November 2026

- `python -m pytest tests/test_accounts.py -q`: **16 passed**.
- `python -m pytest -q`: **38 passed, 1 failed**. The remaining existing
  `test_scan_ocr` failure is caused by native Tesseract being absent from PATH.
  Docker installs Tesseract; this Windows environment does not have it installed.
- Account coverage includes numeric usernames, minimum passwords, duplicate and
  case-insensitive names, exact password matching, generic failures, hashed tokens,
  logout, rotation, expiry, restart persistence, CSRF, persistent rate limits and
  expiry of rate windows, two-account isolation, legacy/demo separation and cookie
  flags. Source downloads, exports, uploads and mutations reject another owner.
- Live HTTP smoke test on a separate Uvicorn server with a temporary database:
  registration, numeric username, logout, wrong/correct password and demo passed.
- Python compilation and JavaScript syntax checks passed. The authentication-only
  frontend patch was separately syntax checked before staging.
- Live Firestore/Cloud Run and visual browser checks were not performed here.
  Browser tooling previously reported its access host unavailable. The cloud
  adapter is implemented using the server Firestore client and transactions;
  hosted integration remains a deployment verification step.

The UI redesign was subsequently published in a separate commit. Folders now
start with the repository vendor/PO list; existing empty, unapproved folders
receive it once. Existing invoices and account ownership are not migrated.
Secrets and invoice databases are excluded. The example environment configuration
is updated in Git while its pre-existing local deletion remains in the working tree.

Library references:
[argon2-cffi API](https://argon2-cffi.readthedocs.io/en/stable/api.html),
[Firestore transactions](https://firebase.google.com/docs/firestore/manage-data/transactions).
