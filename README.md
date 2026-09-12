<p align="center">
<img
  src="https://github.com/AtharvaDeo101/MailAPT/blob/main/frontend/public/icon.png"
  alt="Dispatch"
  width="100"
  height="100"></p>

<h1 align="center">Dispatch</h1>

<p align="center"><strong>Your inbox, minus the typing.</strong></p>

<p align="center">
An AI mail client that writes your email, summarises what lands, and sends on
your schedule &mdash; running on the Gmail account your team already uses, on
infrastructure you control.
</p>

---

## The business case

Routine email is unbilled work. Chasing an invoice, following up on a proposal,
asking for the numbers, declining politely &mdash; the same dozen messages,
written again every week, by people whose time is charged out by the hour.
Reading is worse: long threads consumed in full to extract one decision.

Dispatch removes the typing and the reading, without moving a single message out
of your Gmail.

**What that changes in practice**

- A message goes from one sentence of intent to a finished, signed draft.
- An incoming thread goes from minutes of reading to a two-sentence brief.
- Follow-ups leave at the right hour in the recipient's day, not whenever the
  sender happened to be at a keyboard.
- Nobody signs up for a new tool. They sign in with the Google account they
  already have.

---

## What it does

**Describe the email. Get the email.** Type "ask Priya for the Q3 numbers, we
need them by Friday" and Dispatch returns a finished subject line and a
complete, professional body, signed with the sender's real name. Edit it or
send it.

**Read the summary, not the thread.** Any message collapses to two sentences, or
to a structured brief with key points, action items and sentiment. Five seconds
to decide whether it needs a person.

**It learns who you write to.** Most AI drafting tools hand back `[Your Name]`
and `[Manager's Name]` and leave the user to fill in the blanks &mdash; every
single time. Dispatch reads the greeting and sign-off of the mail actually sent,
remembers both names against the account, and puts them in the next draft
automatically. No setup, no contact import, no placeholders.

**Send it later.** Pick a time. The message queues, goes out on schedule, and
files itself into Sent.

**And it is still a real mail client.** Inbox, Sent, Drafts, custom folders,
Gmail labels, search, bulk actions, read-later, attachments, light and dark
themes &mdash; plus a side rail of to-do lists and notes that pins over the
inbox while you work. Nobody has to keep a second app open.

---

## Who it is for

| | The recurring cost | What Dispatch does about it |
|---|---|---|
| **Sales and account teams** | dozens of near-identical follow-ups a week | one sentence per follow-up, sent on the prospect's clock |
| **Founders and operators** | an inbox read in full because any line might matter | summaries first, full thread only when it earns it |
| **Support and ops** | polite, careful replies written from scratch | drafted for review, edited rather than authored |
| **Professional services** | billable hours spent on unbillable mail | the same correspondence at a fraction of the keystrokes |
| **Privacy-sensitive teams** | AI tools that require copying mail to a vendor | self-hosted, and mail stays in Gmail |

---

## Why it is different

| | Typical AI email add-on | Dispatch |
|---|---|---|
| Where your mail lives | copied into a third-party service | **stays in your Gmail** |
| Names in drafts | `[Your Name]` placeholders, forever | learned from mail you send, filled in automatically |
| Scope | a compose box bolted onto your inbox | a full mail client &mdash; read, write, file, schedule |
| Sign-up | new account, new password | your Google account, standard OAuth |
| Where it runs | someone else's servers | yours &mdash; self-host the whole thing |
| What it costs per seat | a subscription per user, forever | your own Google and inference credentials |

---

## Data and security posture

The part worth putting in front of whoever signs off on new tooling.

- **No mail mirroring.** Messages are read from and sent through the Gmail API
  on the user's behalf. There is no external mail store to breach.
- **Standard Google sign-in.** OAuth 2.0 with PKCE. Dispatch requests
  `gmail.send`, `gmail.readonly` and `gmail.modify`, and nothing else. Access is
  revoked from the user's own Google account like any other connected app.
- **Credentials stay server-side.** Tokens live in a server-side session, never
  in the browser. The session cookie is signed and HTTP-only, marked Secure over
  HTTPS, and expires after seven days.
- **Per-account isolation.** Stored mail, folders and settings are owned by the
  signed-in Gmail address, and the response cache is keyed to that account, so
  one user is never served another's inbox.
- **Abuse limits built in.** Per-route rate limits on drafting, summarising and
  sending, plus a request body cap.
- **Your deployment, your boundary.** Web app, API and database all run on
  infrastructure you choose, under your own network and retention policy.

One dependency to disclose in review: drafting and summarising call a hosted
inference endpoint, so the prompt and the message being summarised leave your
network for that call. Pointing the backend at a self-hosted model removes even
that.

---





## What's in it

**Mail** &mdash; Inbox, Sent, Drafts, Scheduled, custom folders and Gmail labels ·
search across sender and subject · unread and read-later filters · bulk delete,
move and mark · sender avatars · sanitised HTML reading pane · attachments ·
save as Gmail draft · delete to Gmail Trash.

**AI** &mdash; one-line prompt to full email · remembered sender and recipient
names · brief or detailed summaries of any message · a standalone summariser
page · powered by Llama 3.1 8B Instruct.

**Scheduling** &mdash; pick a send time, cancel any time before it fires.

**Workspace** &mdash; pinnable to-do lists built from headers, checklists and
bullets, floating over the inbox as draggable cards · free-form notes ·
everything remembered between sessions.

**Made yours** &mdash; light and dark themes, theme and panel colours, four font
families, four text sizes, ten notification sounds, silent hours. Saved against
the Google account, so a user's setup follows them.

---

## Deploying it

Dispatch is self-hosted. One command brings up the web app, the API and the
database on a single Docker network, and a small VM is enough to start. You
supply three things: a Google Cloud OAuth client, a Hugging Face token with
access to Llama 3.1 8B Instruct, and somewhere to run Docker. There are no
per-seat fees to anyone.

<details>
<summary><strong>Full setup instructions</strong></summary>

You need Docker, a Google Cloud OAuth client, and a Hugging Face token with
access to Llama 3.1 8B Instruct.

**1. Google OAuth.** In Google Cloud Console create an OAuth 2.0 Web client,
enable the Gmail API, and add `http://localhost:5000/oauth2callback` as an
authorised redirect URI. The app requests `gmail.send`, `gmail.readonly` and
`gmail.modify`.

**2. Environment files.** Three of them:

`.env` in the repo root — Postgres credentials for the `db` service:

```bash
POSTGRES_USER=dispatch
POSTGRES_PASSWORD=change-me
POSTGRES_DB=dispatch
```

`backend/.env`:

| Variable | What it is |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from step 1 |
| `REDIRECT_URI` | `http://localhost:5000/oauth2callback` |
| `FRONTEND_URL` | where to land after sign-in, e.g. `http://localhost:3000/generate` |
| `ALLOWED_ORIGINS` | comma-separated origins allowed to call the API, e.g. `http://localhost:3000` |
| `DATABASE_URL` | `postgresql+psycopg2://dispatch:change-me@db:5432/dispatch` |
| `FLASK_SECRET_KEY` | any long random string; it signs the session cookie |
| `HF_API_TOKEN` | Hugging Face inference token |

`frontend/.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:5000
INTERNAL_API_BASE_URL=http://backend:5000
```

`NEXT_PUBLIC_API_BASE_URL` is what the browser calls; `INTERNAL_API_BASE_URL` is
what server-side rendering calls inside the Docker network.

**3. Start it.**

```bash
docker compose up --build
```

Frontend on `http://localhost:3000`, API on `http://localhost:5000`, Postgres on
`5432`. `GET /health` tells you the backend is up. Sessions live in a named
volume, so a rebuild does not log you out.

**Without Docker**

```bash
# backend
cd backend && pip install -r requirements.txt && python main.py

# frontend
cd frontend && pnpm install && pnpm dev
```

Point `DATABASE_URL` at a Postgres you are running yourself, and swap `db` for
`localhost` in it.





