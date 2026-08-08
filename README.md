# Dispatch

<p align="center">
<img
  src="https://github.com/AtharvaDeo101/MailAPT/blob/main/frontend/public/icon.png"
  alt="Dispatch"
  width="100"
  height="100"></p>

## Overview

**Dispatch** is an AI-assisted Gmail client. It signs in with your Google
account, reads and sends real mail through the Gmail API, and adds the things a plain inbox is
missing: AI drafting, one-click summaries, scheduled sends, folders, and a side panel of to-do
lists and notes you can keep on screen while you work.

Everything runs against your own Gmail mailbox — nothing is mirrored to a third-party mail
service.

---

## Features

### Mail

- **Full inbox client** — Inbox, Sent, Drafts, Scheduled, custom Folders and Gmail Tags (labels),
  with search across sender and subject.
- **Message list** — unread emphasis, sender avatars (Gravatar with letter fallback), snippets,
  select-all with bulk delete / read-later / move, unread and read-later filters, newest/oldest sort.
- **Reading pane** — sanitized HTML rendering (DOMPurify), move to folder, delete to Gmail Trash.
- **Compose** — chat-style AI drafting, live preview, attachments, save as Gmail draft, send, or schedule.
- **Read later** and **folder tags** for Gmail messages that have no row of their own.

### AI

- **Email generation** — describe the email; the model returns a subject and full body.
- **Remembered names** — drafts stop coming back with `[Your Name]` and `[Manager's Name]`. Every email
  you send teaches the app two things: the greeting line names the recipient, the sign-off names you.
  Both are stored per Google account and filled into later drafts to the same address, automatically.
  Whatever the app has learned is listed and editable under Settings → Names.
- **Summarization** — brief (2–3 sentences) or detailed (key points, action items, sentiment) summaries
  of any open message, plus a dedicated `/summarize` page.
- Powered by `meta-llama/Llama-3.1-8B-Instruct` through the Hugging Face Inference API.

### Scheduling

- Pick a send time; the email is queued in Postgres with `pending` status.
- Due sends are drained every 15s by whichever browser tab is open, then filed into Sent.
- Pending schedules can be cancelled from the Scheduled section.

### Side rail — Mail · Settings · To-do · Notes

The leftmost icon rail switches what fills the screen. The folder pane belongs to **Mail** only;
the other tabs get the full width.

- **Settings** (see below) — a full settings page, saved per Google account.
- **To-do** — build lists out of blocks: header, sub-header, checklist (radio), bullet list, plain text.
  Any list can be **stuck to the screen**: it becomes a draggable card that floats above the app, so
  you can tick items off while working in the inbox. Cards remember their position and collapsed state.
- **Notes** — create, edit and delete free-form notes from a card grid.

### Settings (persisted server-side)

| Group | Options |
|---|---|
| Names | Your name, plus every recipient the app has learned a name for — both editable, so a bad capture is one correction away |
| Display | Language (English), font family (System / Lato / Roboto / Georgia), font size (Browser / Small / Medium / Large) |
| Theme | Appearance (light / dark), theme colour, left panel colour |
| Notifications | New-email alert on/off, sound, volume, silent hours with a from/to window |

- The theme colour also tints the top navigation bar, and the panel colour tints the rail and folder pane
  (mixed into the dark base when dark mode is on, so it stays readable).
- Changes apply instantly and are saved 400 ms later — dragging the volume slider is one request, not fifty.
- The top-bar light/dark toggle writes to the same stored setting, so the two can never disagree.

### New-mail notification

- While the app is open in a browser tab, the inbox is polled every 60 seconds — including when the tab
  sits in the background — and a sound plays when message ids appear that weren't there before.
- Ten choices: Chime, Ding, Pop, Bell, Tri-tone, Marimba, Bloop, Knock, Pulse, Silent. All are synthesised
  with the Web Audio API, so no audio files ship with the app.
- **Silent hours** mute alerts inside a time window (which may wrap past midnight). The Test button in
  Settings plays regardless, so you can hear what you picked.
- Limits by design: sound requires the site to be open — there is no service worker or push. A tab that has
  never been interacted with stays silent, because browsers refuse audio until the page has been clicked.

### Interface

- Zoho/Gmail-style dense layout: navy top bar, icon rail, folder pane, message list, sliding detail panel.
- Hover-expand feedback across the UI — rows grow from the left edge and lift above their neighbours,
  buttons pop, all with `prefers-reduced-motion` respected.
- Light and dark themes.

---

## How it works

1. **Sign in** — `/login` starts a Google OAuth 2.0 flow with PKCE; the callback stores credentials in a
   server-side Flask session cookie. Expired access tokens refresh automatically.
2. **Read** — the frontend calls the Flask API, which calls the Gmail API with those credentials. Message
   bodies are walked part-by-part, base64url-decoded, and HTML is converted to text for the summarizer.
3. **Write** — a prompt goes to the Hugging Face model, along with any names already known for you and
   the chosen recipient. Placeholders the model emits anyway are substituted afterwards, so the names
   land whether or not it followed instructions. The returned draft can be edited, previewed, saved as a
   Gmail draft, sent, or scheduled.
4. **Learn** — on send, the greeting and sign-off of the outgoing message are parsed for names and stored
   against your account. Generic openings (`Dear Team,`) and bare sign-offs (`Best regards,`) are rejected,
   so nothing meaningless gets remembered.
5. **Persist** — folders, stored emails, scheduled sends and user settings live in PostgreSQL. Read-later
   flags, folder assignments for Gmail messages, to-do lists and notes live in browser localStorage.

---

## Tech stack

**Frontend** — Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS v4 · TanStack Query
(with localStorage persistence) · next-themes · lucide-react · DOMPurify · `next/font` for Lato and Roboto

**Backend** — Python · Flask · Flask-Session (filesystem) · Flask-CORS · SQLAlchemy · PostgreSQL
(psycopg2) · google-auth-oauthlib + google-api-python-client (Gmail API) · huggingface_hub ·
BeautifulSoup

**Infrastructure** — Docker Compose (backend, frontend, Postgres 16), Gunicorn in the production image

---

## Project structure

```
backend/
  main.py            app factory, config, CORS, session, table creation
  OAuth.py           Google OAuth (PKCE), /me, /logout, Gmail service helper
  email_service.py   all mail, folder, schedule and settings endpoints + LLM helpers
  known_names.py     name parsing and placeholder filling (pure, self-checking)
  models.py          Folder, Email, ScheduledEmail, UserSettings
  db.py              SQLAlchemy engine and session factory
  tests/             pytest suite (54 tests)
frontend/app/
  page.tsx           landing page
  login/             sign-in screen
  summarize/         standalone summarizer
  generate/          the mail client
    page.tsx         state, queries, notification + schedule drains
    _components/     sidebar, list, compose, settings, to-do, notes
    _lib/            api client, settings model, helpers
docker-compose.yml
```

---

## API

All endpoints require the session cookie (`credentials: "include"`) unless noted.

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | session status (no auth) |
| GET | `/health` | health check (no auth) |
| GET | `/login`, `/oauth2callback` | Google OAuth flow |
| POST | `/logout` | clear the session |
| GET | `/me` | Gmail profile of the signed-in user |
| GET | `/list_emails?q=` | list messages for a Gmail query |
| GET | `/get_email/<id>` | full message with plain and HTML bodies |
| POST | `/send_email` | send (JSON or multipart with attachments) |
| POST | `/create_draft` | create a Gmail draft |
| POST | `/trash_email/<id>` | move a message to Trash |
| GET | `/list_labels` | Gmail labels |
| POST | `/generate_email` | AI draft from a prompt (optional `to`, used to look up the recipient's name) |
| POST | `/summarize_email` | brief or detailed summary |
| GET/PATCH/DELETE | `/stored_emails[/<id>]` | rows in the local `emails` table |
| GET/POST | `/folders` | list and create folders |
| GET/POST/DELETE | `/scheduled_emails[/<id>]` | schedule queue |
| GET/PUT | `/settings` | per-account preferences |

`PUT /settings` validates every field before storing: unknown keys are dropped, colours must be
`#rrggbb`, times must be `HH:MM`, volume is clamped to 0–1, enums must match the offered options, and a
name must look like one (1–3 words, letters only, not a role word such as "Team" or "Regards").
Updates are partial — send only what changed.

---

## Getting started

### With Docker (recommended)

```bash
# backend/.env and frontend/.env.local must exist first — see below
docker compose up --build
```

Frontend on `http://localhost:3000`, backend on `http://localhost:5000`, Postgres on `5432`.

### Local development

```bash
# backend
cd backend
pip install -r requirements.txt
python main.py                      # http://localhost:5000

# frontend
cd frontend
npm install
npm run dev                         # http://localhost:3000
```

Tables are created automatically on backend start.

### Environment

`backend/.env`

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
FLASK_SECRET_KEY=...
HF_API_TOKEN=...
FRONTEND_ORIGIN=http://localhost:3000
FRONTEND_URL=http://localhost:3000/generate
REDIRECT_URI=http://localhost:5000/oauth2callback
# db.py reads DATABASE_URL directly at import time — it must be set
DATABASE_URL=postgresql+psycopg2://mailapt:mailaptpassword@localhost:5432/mailapt
POSTGRES_USER=mailapt
POSTGRES_PASSWORD=mailaptpassword
POSTGRES_DB=mailapt
POSTGRES_HOST=localhost        # "db" inside Docker Compose
POSTGRES_PORT=5432
```

`frontend/.env.local`

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:5000
INTERNAL_API_BASE_URL=http://backend:5000
```

### Google Cloud setup

Enable the Gmail API and create an OAuth client (web application) with
`http://localhost:5000/oauth2callback` as an authorized redirect URI. The app requests
`gmail.send`, `gmail.readonly` and `gmail.modify`.

---

## Tests

```bash
cd backend
python -m pytest tests -q
python known_names.py          # standalone self-check for the name parsing
```

Covers the OAuth routes, mail endpoints, scheduling, settings validation/merge/round-trip, and the
send-then-generate loop that proves a learned name reaches the next draft.

---

## Known limits

- **Scheduled sends need an open tab.** The queue is persisted in Postgres, but it is drained by the
  frontend. Move the drain to a worker (cron or Celery beat hitting a `/run_due` endpoint) if sends must
  fire with the app closed.
- **Notification sound needs an open tab** — no service worker, no push notifications.
- **Names are learned from sent mail only, and only from a `Dear X,` opening or a signed sign-off.**
  Drafts teach nothing (half-finished mail would teach garbage), and your own name is captured once
  rather than overwritten, so a one-off alias signature cannot replace it. Both are editable in Settings.
- **To-do lists, notes, read-later flags and folder assignments are browser-local**, so they do not follow
  you between devices. Settings do, because they are stored per Google account.
- **Display language is English only.** The setting is persisted and sets `<html lang>`, but no
  translations exist yet.
- **Folders and stored emails are not scoped per user** — the schema has no user table, so a shared
  deployment would share them.

## Future improvements

- Backend worker for scheduled sends and server-side new-mail push.
- Per-user scoping for folders and stored emails.
- Sync to-do lists and notes to Postgres alongside settings.
- Tone options for generation, and smart reply suggestions.
- Seed remembered names from Gmail contacts instead of waiting for the first send.
- Real translations behind the language setting.
