# Dispatch — developer guide

Companion to [README.md](README.md). The README describes *what the app does*;
this file describes *how the code is put together and how to work on it*.

---

## 1. Shape of the system

Three processes, defined in [docker-compose.yml](docker-compose.yml):

| Service | Image / dir | Port | Notes |
|---|---|---|---|
| `frontend` | `./frontend` (Next.js 16, React 19, pnpm) | 3000 | dev server even in the image |
| `backend` | `./backend` (Flask, gunicorn) | 5000 | **1 worker, 8 threads** — deliberate, see §6 |
| `db` | `postgres:16` | 5432 | volume `pgdata`, healthchecked |

The backend holds all secrets and all Google/HF credentials. The frontend never
talks to Gmail or Hugging Face directly — it only calls Flask with
`credentials: "include"`, and the Flask session cookie is the only auth token
the browser ever holds.

```
browser ──cookie──▶ Flask ──OAuth creds──▶ Gmail API
                      │
                      ├──token──▶ HF Inference (Llama-3.1-8B-Instruct)
                      └──SQLAlchemy──▶ Postgres
```

---

## 2. Backend

`backend/` — ~2,100 lines of Python, six modules. No framework beyond Flask.

| File | Responsibility |
|---|---|
| [main.py](backend/main.py) | app factory: config, CORS, sessions, table creation, blueprint wiring |
| [gateway.py](backend/gateway.py) | one `before_request`/`after_request` pair: auth gate, rate limit, response cache, security headers |
| [OAuth.py](backend/OAuth.py) | Google OAuth 2.0 + PKCE, `/me`, `/logout`, `get_gmail_service()` |
| [email_service.py](backend/email_service.py) | every mail/folder/schedule/settings route, plus the two LLM helpers |
| [known_names.py](backend/known_names.py) | pure string logic for name extraction and placeholder filling |
| [models.py](backend/models.py) / [db.py](backend/db.py) | SQLAlchemy models, engine, session factory |

### The request path

Every request goes through `install_gateway()` before it reaches a view, so
individual routes carry no auth or rate-limit code:

1. `OPTIONS` → passes straight through (CORS preflight has no cookie).
2. Path not in `PUBLIC_PATHS` and no `credentials` in session → `401 not_authenticated`.
3. Rate limit: 120 req/60 s globally per IP, plus 10/60 s on `/generate_email`
   and `/summarize_email`, 20/60 s on `/send_email` → `429` with `Retry-After`.
4. GET response cache for `/list_emails` (30 s), `/list_labels` (300 s),
   `/folders` (60 s), keyed by **session id + full path**. Cache hits set
   `X-Cache: HIT`.
5. Any non-GET response flushes that viewer's whole cache.

`/get_email/<id>` is intentionally **not** cached: reading a message marks it
read in Gmail, so a cached read would desync the unread state.

Rate-limit identity is the IP; cache identity is the session. Dropping your
cookie must not reset your quota, and two users must never share a cache entry.

### Config that matters

`main.py` derives one boolean from `REDIRECT_URI`:

```python
IS_HTTPS = os.environ.get("REDIRECT_URI", "").startswith("https://")
```

That single signal drives `SESSION_COOKIE_SECURE`, `SAMESITE`
(`None` deployed / `Lax` local), `OAUTHLIB_INSECURE_TRANSPORT`, Flask debug
mode, and whether a missing `FLASK_SECRET_KEY` is fatal. **If you set an https
redirect URI, you must set `FLASK_SECRET_KEY`** or startup raises.

Origins come from `FRONTEND_ORIGIN` *or* `ALLOWED_ORIGINS` (comma-separated);
both names are accepted so a deploy that sets only one doesn't silently fall
back to localhost and CORS-block itself.

### Schema changes

There is no Alembic. `main.py` calls `Base.metadata.create_all()`, then runs a
hand-written idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for columns
added after the volume existed (`create_all` never alters an existing table).

If you add a column to an existing model, you must either extend that `ALTER`
block or wipe the volume:

```bash
docker compose down -v
```

Adding a *preference* needs no migration at all — `UserSettings.data` is a JSON
blob owned by the settings page.

---

## 3. Frontend

`frontend/app/generate/` is the real application; everything else is marketing
pages and shadcn/ui primitives (`components/ui/`, generated — don't hand-edit).

```
generate/
  page.tsx                 1,237 lines: all state, queries, drain loops
  providers.tsx            TanStack Query client + localStorage persister
  _components/             list (1,602) · compose (694) · todo (636) · sidebar (629) · settings (403) · notes (225)
  _lib/api.ts              every fetch to Flask
  _lib/settings.ts         Settings type + defaults — mirrors the backend
  _lib/use-persistent-state.ts   localStorage-backed useState
```

### API base URL

`_lib/api.ts` picks a different base per environment, because server components
resolve `backend` on the Docker network and the browser cannot:

```ts
export const API =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_BASE_URL || "http://backend:5000"
    : process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:5000";
```

### Client-side loops

Two timers live in `page.tsx`. Both require an open tab:

- **New mail poll** — 60 s `refetchInterval`, gated on `settings.notifications.enabled`.
- **Schedule drain** — 15 s `setInterval` that sends due rows from `scheduled_emails`.

That second one is why scheduled sends don't fire with the app closed. Moving it
to a backend worker hitting a `/run_due` endpoint is the fix, not more frontend code.

### Persistence split

| Where | What |
|---|---|
| Postgres (per Google account) | folders, stored emails, schedules, settings, learned names |
| localStorage | `mailly-folder-assignments`, `mailly-read-later`, `mailly-todo-lists`, `mailly-notes-list`, and the query cache `generate-email-cache-v1` |

Anything in the second column does not follow the user between devices. That is
current behaviour, not an oversight — but it is the reason a bug report saying
"my to-dos vanished" usually means "different browser".

### Settings contract

`_lib/settings.ts` `DEFAULT_SETTINGS` **must** stay in sync with
`DEFAULT_SETTINGS` in `email_service.py`. The backend's `_clean_settings()`
silently drops unknown keys, so a frontend-only addition round-trips as if it
saved and then disappears on reload. Add the field on both sides in the same change.

`PUT /settings` is partial — send only what changed. The UI debounces 400 ms.

---

## 4. Running it

### Docker (matches CI/deploy most closely)

```bash
docker compose up --build
```

Requires `.env` (Postgres provisioning), `backend/.env`, and
`frontend/.env.local` to exist first.

### Local, without Docker

```bash
cd backend && pip install -r requirements-dev.txt && python main.py
```

```bash
cd frontend && pnpm install && pnpm dev
```

Postgres still has to be reachable — `db.py` builds its engine from
`DATABASE_URL` **at import time**, so an unset or unreachable URL fails at
import, not on first query.

### Environment

`backend/.env` — see [.env.example](.env.example) for the compose-level vars and
[README.md](README.md#environment) for the full backend list. The ones that
change behaviour rather than just credentials:

| Var | Effect |
|---|---|
| `REDIRECT_URI` | http vs https flips cookie security, debug mode, OAuth strictness |
| `FLASK_SECRET_KEY` | required when https; random fallback in dev invalidates sessions on restart |
| `ALLOWED_ORIGINS` / `FRONTEND_ORIGIN` | CORS allowlist, comma-separated |
| `DATABASE_URL` | full Postgres URL, read at import by `db.py`; percent-encode `@` etc. in the password |

---

## 5. Tests, lint, format

```bash
cd backend && python -m pytest tests -q
```

54 tests across 6 files. `conftest.py` stubs every required env var and points
`DATABASE_URL` at `sqlite://`, so the suite never needs Postgres. The `login`
fixture injects a fake `credentials` blob to get past the gateway — use it for
any new authenticated route.

```bash
python backend/known_names.py     # standalone assert-based self-check
```

Pure-logic modules carry their own `_self_check()` rather than a test file.
Keep that pattern for new pure helpers.

```bash
black backend && isort backend && flake8
```

Line length 120 everywhere (`pyproject.toml`, `.flake8`). `flask_session*` dirs
are excluded from all three — they're runtime session files, not source.

Frontend: `pnpm lint`. Note `next.config.mjs` sets
`typescript.ignoreBuildErrors: true`, so **a type error will not fail the
build** — run `tsc` yourself if you care.

---

## 6. Deliberate constraints (read before "fixing" them)

Marked in-source with `ponytail:` comments.

- **One gunicorn worker.** `gateway.py`'s rate limiter and response cache are
  in-process dicts under a single `Lock`, and sessions are files on the
  container's disk. A second worker doubles the effective rate limits and splits
  the session store. Threads scale this fine; scaling out means moving both to
  Redis *first*.
- **Filesystem sessions on a named volume.** The `sessions:` volume exists
  because rebuilding without it logs everyone out.
- **No Alembic.** Two hand-written `ADD COLUMN IF NOT EXISTS` statements. Worth
  swapping the day a third is needed.
- **Placeholders survive unfilled.** `fill_placeholders()` leaves `[Company]`
  visible rather than guessing — a visible bracket beats a confidently wrong name.
- **`_NOT_A_NAME` rejects role words.** Learning "Team" or "Regards" as a name
  would poison every subsequent draft, so the filter is a correctness measure,
  not a nicety. Extend the set rather than loosening the regex.

Run `/ponytail-debt` (or grep `ponytail:`) to list them all.

---

## 7. Common tasks

**Add an endpoint** → new route on `email_bp` in `email_service.py`. Auth and
rate limiting are free via the gateway; add a `ROUTE_LIMITS` entry only if it
hits an external API, and a `CACHE_TTL` entry only if the GET has no side
effects. Add a test in `backend/tests/test_routes.py` using the `login` fixture.

**Add a setting** → `DEFAULT_SETTINGS` in *both* `settings.ts` and
`email_service.py`, a validation branch in `_clean_settings()`, a control in
`settings-view.tsx`. No migration needed.

**Add a model column** → `models.py`, plus the `ALTER TABLE` block in `main.py`
or a volume wipe.

**Debug a 401 loop** → almost always cookie policy. Check `REDIRECT_URI`'s
scheme against where the frontend is served from, then `ALLOWED_ORIGINS`.

**Debug a stale list** → check the `X-Cache` header. `HIT` means the gateway
served it; a write should have flushed it.

---

## 8. Known gaps

Full list in [README.md](README.md#known-limits). The two with the largest
blast radius for a developer:

- **Folders and stored emails are not scoped per user.** There is no user table —
  the schema assumes a single-tenant deployment. A shared deployment leaks them
  between accounts. Settings and learned names *are* scoped (by Gmail address).
- **Scheduled sends and notifications both depend on an open browser tab.**
