import base64
import json
import re
import time
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import getaddresses
from html import unescape

from bs4 import BeautifulSoup
from flask import Blueprint, current_app, jsonify, request, session
from googleapiclient.errors import HttpError

from OAuth import get_gmail_service
from known_names import (
    clean_name,
    fill_placeholders,
    greeting_name,
    signature_name,
)

# NEW: import DB session and models
from db import SessionLocal
from models import (
    Email as EmailModel,
    Folder as FolderModel,
    ScheduledEmail as ScheduledEmailModel,
    UserSettings as UserSettingsModel,
)

email_bp = Blueprint("email_bp", __name__)


# ---------- LLM helpers ----------

def generate_with_api(prompt: str, sender: str = None, recipient: str = None) -> str:
    known = []
    if sender:
        known.append(f"The sender, who signs the email, is {sender}.")
    if recipient:
        known.append(f"The recipient is {recipient}.")
    if known:
        known.append(
            "Use these names directly and never write a bracketed placeholder "
            "for a name you have been given."
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a professional email writing assistant. "
                "When given a topic or instruction, write a complete professional email. "
                "Always format your response exactly as:\n"
                "Subject: <subject line>\n\n"
                "<email body starting with Dear...>\n\n"
                "Do not include any explanation outside the email itself."
                + ("\n" + " ".join(known) if known else "")
            ),
        },
        {"role": "user", "content": f"Write a professional email about: {prompt}"},
    ]

    response = current_app.hf_client.chat.completions.create(
        model=current_app.config["HF_MODEL"],
        messages=messages,
        max_tokens=400,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def summarize_with_api(content: str, summary_type: str = "brief") -> str:
    if summary_type == "brief":
        instruction = (
            "Give a brief 2-3 sentence summary of this email. "
            "Include the main point, any action items, and the tone."
        )
    else:
        instruction = (
            "Summarize this email in detail. Include:\n"
            "- Key Points (bullet list)\n"
            "- Action Items (bullet list)\n"
            "- Sentiment (one phrase describing the tone)"
        )

    messages = [
        {
            "role": "system",
            "content": "You are an expert email summarizer. Be concise and accurate.",
        },
        {"role": "user", "content": f"{instruction}\n\nEmail:\n{content}"},
    ]

    response = current_app.hf_client.chat.completions.create(
        model=current_app.config["HF_MODEL"],
        messages=messages,
        max_tokens=300,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


# ---------- decoding / parsing helpers ----------

def _decode_body(data: str) -> str:
    if not data:
        return ""
    try:
        padding = len(data) % 4
        if padding:
            data += "=" * (4 - padding)
        decoded = base64.urlsafe_b64decode(data.encode("utf-8")).decode(
            "utf-8", errors="ignore"
        )
        return unescape(decoded)
    except Exception:
        return ""


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _get_header(headers, name: str) -> str:
    if not headers:
        return ""
    return next(
        (
            h.get("value", "")
            for h in headers
            if h.get("name", "").lower() == name.lower()
        ),
        "",
    )


def extract_email_body(payload):
    plain_chunks = []
    html_chunks = []

    def walk_parts(part):
        if not part:
            return

        mime_type = (part.get("mimeType") or "").lower()
        filename = part.get("filename", "")
        body = part.get("body", {}) or {}
        body_data = body.get("data")
        parts = part.get("parts", []) or []

        if mime_type == "text/plain" and body_data:
            decoded = _decode_body(body_data)
            if decoded.strip():
                plain_chunks.append(decoded)

        elif mime_type == "text/html" and body_data:
            decoded = _decode_body(body_data)
            if decoded.strip():
                html_chunks.append(decoded)

        if not filename:
            for sub in parts:
                walk_parts(sub)

    # walk_parts handles the payload node itself before recursing, so the root
    # must not be decoded separately or single-part bodies come out doubled
    walk_parts(payload)

    html_body = "\n\n".join(chunk for chunk in html_chunks if chunk.strip()).strip()
    plain_body = "\n\n".join(chunk for chunk in plain_chunks if chunk.strip()).strip()

    if not plain_body and html_body:
        plain_body = _html_to_text(html_body)

    return {
        "plain_body": plain_body or "",
        "html_body": html_body or "",
    }


def _parse_http_error(e: HttpError):
    status_code = getattr(getattr(e, "resp", None), "status", 500)
    reason = ""

    try:
        if getattr(e, "content", None):
            parsed = json.loads(e.content.decode("utf-8"))
            reason = parsed.get("error", {}).get("message", "")
    except Exception:
        reason = ""

    # `reason` is Google's own message ("Invalid to header") and is worth
    # showing. str(e) is the HttpError repr, which carries the full request URI
    # — a generic fallback instead.
    return status_code, reason or "Google API request failed"


# ---------- DB helper ----------

def get_db_session():
    """Simple helper to get a SQLAlchemy session; caller must close it."""
    return SessionLocal()


def _server_error(where, e):
    """Log the detail, hand the client nothing that describes our internals.

    str(e) on an unexpected exception carries SQL fragments, file paths and
    library internals; the traceback belongs in the logs, not in the response.
    """
    current_app.logger.error(f"{where} error: {e}", exc_info=True)
    return jsonify({"error": "internal error"}), 500


def _require_owner():
    """The account owning every row this request may touch, or a 401 to return.

    Stricter than checking for `credentials` in the session: rows are keyed by
    Gmail address, so a session we cannot resolve to an address must not be
    allowed to read or write any of them.
    """
    address = _current_email_address()
    if not address:
        return None, (jsonify({"error": "not_authenticated"}), 401)
    return address, None


# ---------- Gmail send + DB store ----------

@email_bp.route("/send_email", methods=["POST"])
def send_email():
    service = get_gmail_service()
    if service is None:
        return jsonify({"error": "not_authenticated"}), 401

    try:
        content_type = request.content_type or ""

        if "multipart/form-data" in content_type:
            to = request.form.get("to", "").strip()
            subject = request.form.get("subject", "")
            body = request.form.get("body", "")
            uploaded_files = request.files.getlist("attachments")
        else:
            data = request.get_json(force=True, silent=True) or {}
            to = (data.get("to") or "").strip()
            subject = data.get("subject", "")
            body = data.get("body", "")
            uploaded_files = []

        if not to or not body:
            return jsonify({"error": "to and body are required"}), 400

        # Build MIME message
        if uploaded_files:
            message = MIMEMultipart()
            message["to"] = to
            message["subject"] = subject
            message.attach(MIMEText(body, "plain", "utf-8"))

            for f in uploaded_files:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{f.filename}"',
                )
                message.attach(part)
        else:
            message = MIMEText(body, "plain", "utf-8")
            message["to"] = to
            message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()

        gmail_id = sent.get("id")
        attachments_count = len(uploaded_files)

        # --- NEW: store sent email in Postgres ---
        account = _current_email_address()

        db = get_db_session()
        try:
            email_row = EmailModel(
                owner=account,
                subject=subject,
                body=body,
                to_address=to,
                from_address="me",  # or your Gmail account / user email
                is_draft=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                gmail_message_id=gmail_id,
            )
            db.add(email_row)
            db.commit()
            db.refresh(email_row)
        except Exception as db_exc:
            db.rollback()
            current_app.logger.error(f"DB error storing sent email: {db_exc}", exc_info=True)
        finally:
            db.close()

        # a sent email is the only place we see the names the user actually
        # wanted; remember them so the next generated draft fills itself in
        if account:
            _remember_names(account, _sole_address(to), body)

        return jsonify(
            {
                "message": "sent",
                "id": gmail_id,
                "attachments_count": attachments_count,
            }
        )

    except HttpError as e:
        current_app.logger.error(f"send_email HttpError: {e}", exc_info=True)
        status_code, reason = _parse_http_error(e)
        return jsonify({"error": reason, "status": status_code}), status_code

    except Exception as e:
        return _server_error("send_email", e)


# ---------- Gmail list (unchanged, still from Gmail) ----------

BATCH_CHUNK = 10


@email_bp.route("/list_emails", methods=["GET"])
def list_emails():
    service = get_gmail_service()
    if service is None:
        return jsonify({"error": "not_authenticated"}), 401

    max_results = min(request.args.get("max_results", 50, type=int) or 50, 50)
    query = request.args.get("q", "")
    page_token = request.args.get("page_token")

    try:
        list_request = (
            service.users()
            .messages()
            .list(
                userId="me",
                maxResults=max_results,
                q=query,
                pageToken=page_token,
                fields="messages/id,nextPageToken,resultSizeEstimate",
            )
        )

        result = list_request.execute()
        messages = result.get("messages", [])

        if not messages:
            return jsonify(
                {
                    "emails": [],
                    "nextPageToken": result.get("nextPageToken"),
                    "resultSizeEstimate": result.get("resultSizeEstimate", 0),
                }
            )

        email_map = {}
        failed_ids = []

        def _to_email(msg_id, response):
            headers = response.get("payload", {}).get("headers", [])
            return {
                "id": response.get("id", msg_id),
                "subject": _get_header(headers, "Subject"),
                "from": _get_header(headers, "From"),
                "to": _get_header(headers, "To"),
                "date": _get_header(headers, "Date"),
                "snippet": response.get("snippet", ""),
                "threadId": response.get("threadId", ""),
                "labelIds": response.get("labelIds", []),
            }

        def _get_meta(msg_id):
            return service.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
                fields="id,threadId,labelIds,snippet,payload/headers",
            )

        def batch_callback(request_id, response, exception):
            if exception is not None:
                current_app.logger.warning(
                    f"Batch get failed for message {request_id}: {exception}"
                )
                failed_ids.append(request_id)
                return

            email_map[request_id] = _to_email(request_id, response)

        # ponytail: 10 per batch. Gmail counts each sub-request against the
        # per-user concurrency limit, so a single 50-wide batch 429s most of
        # itself. Raise the chunk size only if Gmail stops complaining.
        for i in range(0, len(messages), BATCH_CHUNK):
            batch = service.new_batch_http_request()
            for m in messages[i:i + BATCH_CHUNK]:
                batch.add(
                    _get_meta(m["id"]), request_id=m["id"], callback=batch_callback
                )
            batch.execute()

        # ponytail: serial retry with backoff for the few that still 429.
        # Move to a second batch if the failure count ever gets large.
        for msg_id in failed_ids:
            for attempt in range(3):
                try:
                    email_map[msg_id] = _to_email(msg_id, _get_meta(msg_id).execute())
                    break
                except Exception as e:
                    if attempt == 2:
                        current_app.logger.warning(f"Retry get failed for {msg_id}: {e}")
                        # still list it, so the email isn't silently missing
                        email_map[msg_id] = _to_email(msg_id, {})
                    else:
                        time.sleep(0.5 * 2 ** attempt)

        email_list = [email_map[m["id"]] for m in messages if m["id"] in email_map]

        return jsonify(
            {
                "emails": email_list,
                "nextPageToken": result.get("nextPageToken"),
                "resultSizeEstimate": result.get("resultSizeEstimate", 0),
            }
        )

    except HttpError as e:
        current_app.logger.error(f"list_emails HttpError: {e}", exc_info=True)
        status_code, reason = _parse_http_error(e)
        return jsonify({"error": reason, "status": status_code}), status_code

    except Exception as e:
        return _server_error("list_emails", e)


# ---------- Gmail get (unchanged) ----------

@email_bp.route("/get_email/<string:email_id>", methods=["GET"])
def get_email(email_id):
    service = get_gmail_service()
    if service is None:
        return jsonify({"error": "not_authenticated"}), 401

    if not email_id or not email_id.strip():
        return jsonify({"error": "email_id is required"}), 400

    try:
        current_app.logger.info(f"GET /get_email called with id={email_id}")

        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=email_id,
                format="full",
                fields="id,threadId,labelIds,snippet,payload",
            )
            .execute()
        )

        label_ids = msg.get("labelIds", []) or []

        # Opening a message marks it read. A failure here must not break the
        # read itself, so it is logged and swallowed.
        if "UNREAD" in label_ids:
            try:
                service.users().messages().modify(
                    userId="me",
                    id=email_id,
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute()
                label_ids = [l for l in label_ids if l != "UNREAD"]
            except HttpError as e:
                current_app.logger.warning(f"Could not mark {email_id} read: {e}")

        payload = msg.get("payload", {}) or {}
        headers = payload.get("headers", []) or []
        bodies = extract_email_body(payload)

        subject = _get_header(headers, "Subject")
        from_value = _get_header(headers, "From")
        date_value = _get_header(headers, "Date")
        to_value = _get_header(headers, "To")
        cc_value = _get_header(headers, "Cc")

        plain_body = bodies.get("plain_body", "") or ""
        html_body = bodies.get("html_body", "") or ""

        if not plain_body and not html_body:
            plain_body = msg.get("snippet", "") or ""

        email = {
            "id": msg.get("id", email_id),
            "threadId": msg.get("threadId", ""),
            "labelIds": label_ids,
            "snippet": msg.get("snippet", ""),
            "subject": subject,
            "from": from_value,
            "to": to_value,
            "cc": cc_value,
            "date": date_value,
            "body": plain_body,
            "plain_body": plain_body,
            "html_body": html_body,
        }

        current_app.logger.info(
            "Fetched email successfully",
            extra={
                "email_id": email.get("id"),
                "subject": email.get("subject"),
                "has_plain_body": bool(email.get("plain_body")),
                "has_html_body": bool(email.get("html_body")),
            },
        )

        return jsonify({"email": email})

    except HttpError as e:
        current_app.logger.error(f"Gmail API HttpError in get_email: {e}", exc_info=True)
        status_code, reason = _parse_http_error(e)
        return jsonify({"error": reason, "status": status_code}), status_code

    except Exception as e:
        return _server_error("get_email", e)


# ---------- Gmail draft + DB store ----------

@email_bp.route("/create_draft", methods=["POST"])
def create_draft():
    service = get_gmail_service()
    if service is None:
        return jsonify({"error": "not_authenticated"}), 401

    data = request.get_json() or {}
    to, subject, body = data.get("to"), data.get("subject"), data.get("body")

    if not all([to, subject, body]):
        return jsonify({"error": "to, subject, body are required"}), 400

    try:
        message = MIMEText(body, "plain", "utf-8")
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )

        gmail_draft_id = draft.get("id")
        gmail_msg_id = draft.get("message", {}).get("id")

        # --- NEW: store draft email in Postgres ---
        db = get_db_session()
        try:
            email_row = EmailModel(
                owner=_current_email_address(),
                subject=subject,
                body=body,
                to_address=to,
                from_address="me",
                is_draft=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                gmail_message_id=gmail_msg_id,
                gmail_draft_id=gmail_draft_id,
            )
            db.add(email_row)
            db.commit()
            db.refresh(email_row)
        except Exception as db_exc:
            db.rollback()
            current_app.logger.error(f"DB error storing draft email: {db_exc}", exc_info=True)
        finally:
            db.close()

        return jsonify({"message": "draft_created", "id": gmail_draft_id})

    except HttpError as e:
        current_app.logger.error(f"create_draft HttpError: {e}", exc_info=True)
        status_code, reason = _parse_http_error(e)
        return jsonify({"error": reason, "status": status_code}), status_code

    except Exception as e:
        return _server_error("create_draft", e)


# ---------- Gmail labels (unchanged) ----------

@email_bp.route("/list_labels", methods=["GET"])
def list_labels():
    service = get_gmail_service()
    if service is None:
        return jsonify({"error": "not_authenticated"}), 401

    try:
        result = service.users().labels().list(userId="me").execute()
        return jsonify({"labels": result.get("labels", [])})

    except HttpError as e:
        current_app.logger.error(f"list_labels HttpError: {e}", exc_info=True)
        status_code, reason = _parse_http_error(e)
        return jsonify({"error": reason, "status": status_code}), status_code

    except Exception as e:
        return _server_error("list_labels", e)



@email_bp.route("/generate_email", methods=["POST"])
def generate_email():
    # the draft this stores is keyed by account, so refuse rather than write a
    # row with no owner that its author would never see again
    account, denied = _require_owner()
    if denied:
        return denied

    data = request.get_json() or {}
    prompt = data.get("prompt")
    folder_id = data.get("folder_id")  # optional folder for generated drafts
    to_address = _sole_address(data.get("to"))

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    try:
        settings = _load_settings(account)
        sender = settings["profile"].get("name") or None
        recipient = settings["contacts"].get(to_address) if to_address else None

        text = generate_with_api(prompt, sender, recipient)
        # the model emits placeholders even when told not to; this is the
        # part that actually guarantees the names land
        text = fill_placeholders(text, sender, recipient)

        lines = text.strip().splitlines()
        subject, body_lines = "", []

        for i, line in enumerate(lines):
            if line.lower().startswith("subject:"):
                subject = line[len("subject:") :].strip()
                body_lines = lines[i + 1 :]
                break

        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)

        body = "\n".join(body_lines).strip()

        if not subject:
            subject = prompt[:60]
        if not body:
            body = text.strip()

        # subject column is String(255); an overlong model subject would blow up
        # the insert below and get swallowed by the rollback handler
        subject = subject[:255]

        # --- NEW: store generated email as draft in Postgres ---
        db = get_db_session()
        try:
            email_row = EmailModel(
                owner=account,
                subject=subject,
                body=body,
                to_address=to_address or "",  # empty until the user picks one
                from_address="me",
                is_draft=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                folder_id=folder_id,
            )
            db.add(email_row)
            db.commit()
            db.refresh(email_row)
        except Exception as db_exc:
            db.rollback()
            current_app.logger.error(f"DB error storing generated email: {db_exc}", exc_info=True)
        finally:
            db.close()

        return jsonify({"subject": subject, "body": body, "raw_output": text})

    except Exception as e:
        return _server_error("generate_email", e)




@email_bp.route("/summarize_email", methods=["POST"])
def summarize_email():
    if "credentials" not in session:
        return jsonify({"error": "not_authenticated"}), 401

    data = request.get_json() or {}
    content = data.get("content")
    summary_type = data.get("type", "brief")

    if not content:
        return jsonify({"error": "content is required"}), 400

    try:
        summary = summarize_with_api(content, summary_type=summary_type)
        return jsonify(
            {
                "summary": summary,
                "type": summary_type,
                "original_length": len(content),
                "summary_length": len(summary),
            }
        )

    except Exception as e:
        return _server_error("summarize_email", e)


# ---------- NEW: list stored emails from Postgres ----------

@email_bp.route("/stored_emails", methods=["GET"])
def stored_emails():
    """
    List emails stored in Postgres (generated, drafts, sent).
    Optional query params:
      - is_draft=true/false
      - folder_id=<int>
    """
    account, denied = _require_owner()
    if denied:
        return denied

    is_draft_param = request.args.get("is_draft")
    folder_id = request.args.get("folder_id", type=int)

    db = get_db_session()
    try:
        query = db.query(EmailModel).filter(EmailModel.owner == account)

        if is_draft_param is not None:
            if is_draft_param.lower() in ("true", "1", "yes"):
                query = query.filter(EmailModel.is_draft.is_(True))
            elif is_draft_param.lower() in ("false", "0", "no"):
                query = query.filter(EmailModel.is_draft.is_(False))

        if folder_id is not None:
            query = query.filter(EmailModel.folder_id == folder_id)

        # A pending send parks its payload in `emails` as a draft; that row
        # belongs to the Scheduled view, not Drafts. Once it has gone out the
        # schedule is no longer pending and the row becomes ordinary sent mail.
        scheduled_ids = {
            row.email_id
            for row in db.query(ScheduledEmailModel.email_id)
            .filter(ScheduledEmailModel.status == "pending")
            .all()
        }

        emails = query.order_by(EmailModel.created_at.desc()).all()

        result = [
            _serialize_stored_email(e)
            for e in emails
            if e.id not in scheduled_ids
        ]

        return jsonify({"emails": result})

    except Exception as e:
        return _server_error("stored_emails", e)

    finally:
        db.close()


def _serialize_stored_email(e):
    return {
        "id": e.id,
        "subject": e.subject,
        "body": e.body,
        "to_address": e.to_address,
        "from_address": e.from_address,
        "is_draft": e.is_draft,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
        "folder_id": e.folder_id,
        "gmail_message_id": e.gmail_message_id,
        "gmail_draft_id": e.gmail_draft_id,
    }


@email_bp.route("/stored_emails/<int:email_id>", methods=["PATCH"])
def update_stored_email(email_id):
    """Edit a stored draft, or move any stored email into a folder."""
    account, denied = _require_owner()
    if denied:
        return denied

    data = request.get_json() or {}

    db = get_db_session()
    try:
        row = (
            db.query(EmailModel)
            .filter(EmailModel.id == email_id, EmailModel.owner == account)
            .first()
        )
        if row is None:
            return jsonify({"error": "email not found"}), 404

        if "subject" in data:
            row.subject = (data.get("subject") or "")[:255]
        if "body" in data:
            row.body = data.get("body") or ""
        if "to_address" in data:
            row.to_address = (data.get("to_address") or "")[:255]
        if "folder_id" in data:
            folder_id = data.get("folder_id")
            if folder_id is None:
                row.folder_id = None
            else:
                # otherwise a caller could file their mail into someone else's
                # folder just by naming its id
                folder = (
                    db.query(FolderModel)
                    .filter(FolderModel.id == int(folder_id),
                            FolderModel.owner == account)
                    .first()
                )
                if folder is None:
                    return jsonify({"error": "folder not found"}), 404
                row.folder_id = folder.id

        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)

        return jsonify(_serialize_stored_email(row))

    except Exception as e:
        db.rollback()
        return _server_error("update_stored_email", e)

    finally:
        db.close()


@email_bp.route("/stored_emails/<int:email_id>", methods=["DELETE"])
def delete_stored_email(email_id):
    account, denied = _require_owner()
    if denied:
        return denied

    db = get_db_session()
    try:
        row = (
            db.query(EmailModel)
            .filter(EmailModel.id == email_id, EmailModel.owner == account)
            .first()
        )
        if row is None:
            return jsonify({"error": "email not found"}), 404

        # scheduled_emails.email_id is NOT NULL, so its rows must go first
        db.query(ScheduledEmailModel).filter(
            ScheduledEmailModel.email_id == email_id
        ).delete()

        db.delete(row)
        db.commit()

        return jsonify({"message": "deleted", "id": email_id})

    except Exception as e:
        db.rollback()
        return _server_error("delete_stored_email", e)

    finally:
        db.close()


# ---------- Gmail trash ----------

@email_bp.route("/trash_email/<string:email_id>", methods=["POST"])
def trash_email(email_id):
    """Move a Gmail message to Trash (recoverable for 30 days)."""
    service = get_gmail_service()
    if service is None:
        return jsonify({"error": "not_authenticated"}), 401

    if not email_id or not email_id.strip():
        return jsonify({"error": "email_id is required"}), 400

    try:
        service.users().messages().trash(userId="me", id=email_id).execute()
        return jsonify({"message": "trashed", "id": email_id})

    except HttpError as e:
        current_app.logger.error(f"trash_email HttpError: {e}", exc_info=True)
        status_code, reason = _parse_http_error(e)
        return jsonify({"error": reason, "status": status_code}), status_code

    except Exception as e:
        return _server_error("trash_email", e)


# ---------- scheduled sends ----------
# ponytail: the queue is persisted here but drained by the open frontend tab,
# which is the behaviour that already existed. Move the drain into a worker
# (celery beat / cron hitting a /run_due endpoint) if sends must survive the
# tab being closed.

@email_bp.route("/scheduled_emails", methods=["GET"])
def list_scheduled_emails():
    account, denied = _require_owner()
    if denied:
        return denied

    db = get_db_session()
    try:
        rows = (
            db.query(ScheduledEmailModel, EmailModel)
            .join(EmailModel, ScheduledEmailModel.email_id == EmailModel.id)
            .filter(ScheduledEmailModel.status == "pending",
                    EmailModel.owner == account)
            .order_by(ScheduledEmailModel.scheduled_for.asc())
            .all()
        )

        result = [
            {
                "id": sched.id,
                "email_id": mail.id,
                "subject": mail.subject,
                "body": mail.body,
                "to_address": mail.to_address,
                "scheduled_for": sched.scheduled_for.isoformat() + "Z",
                "status": sched.status,
                "created_at": mail.created_at.isoformat() if mail.created_at else None,
            }
            for sched, mail in rows
        ]

        return jsonify({"scheduled": result})

    except Exception as e:
        return _server_error("list_scheduled_emails", e)

    finally:
        db.close()


@email_bp.route("/scheduled_emails", methods=["POST"])
def create_scheduled_email():
    account, denied = _require_owner()
    if denied:
        return denied

    data = request.get_json() or {}
    to = (data.get("to") or "").strip()
    subject = data.get("subject") or ""
    body = data.get("body") or ""
    scheduled_for = data.get("scheduled_for")

    if not to or not body:
        return jsonify({"error": "to and body are required"}), 400
    if not scheduled_for:
        return jsonify({"error": "scheduled_for is required"}), 400

    try:
        # accept ISO-8601 with or without a trailing Z; store naive UTC to match
        # the datetime.utcnow() used for every other timestamp in this module
        when = datetime.fromisoformat(str(scheduled_for).replace("Z", "+00:00"))
        if when.tzinfo is not None:
            when = when.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return jsonify({"error": "scheduled_for must be an ISO-8601 datetime"}), 400

    db = get_db_session()
    try:
        mail = EmailModel(
            owner=account,
            subject=subject[:255],
            body=body,
            to_address=to[:255],
            from_address="me",
            is_draft=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            folder_id=data.get("folder_id"),
        )
        db.add(mail)
        db.flush()

        sched = ScheduledEmailModel(
            email_id=mail.id,
            scheduled_for=when,
            status="pending",
        )
        db.add(sched)
        db.commit()
        db.refresh(sched)

        return jsonify(
            {
                "id": sched.id,
                "email_id": mail.id,
                "subject": mail.subject,
                "body": mail.body,
                "to_address": mail.to_address,
                "scheduled_for": sched.scheduled_for.isoformat() + "Z",
                "status": sched.status,
            }
        )

    except Exception as e:
        db.rollback()
        return _server_error("create_scheduled_email", e)

    finally:
        db.close()


@email_bp.route("/scheduled_emails/<int:scheduled_id>", methods=["DELETE"])
def delete_scheduled_email(scheduled_id):
    """Cancel a pending schedule, or clear it once the send has gone out."""
    account, denied = _require_owner()
    if denied:
        return denied

    sent = request.args.get("sent", "").lower() in ("true", "1", "yes")

    db = get_db_session()
    try:
        # a schedule is owned by the email it points at, so the join is what
        # keeps one account from cancelling another's pending send
        sched = (
            db.query(ScheduledEmailModel)
            .join(EmailModel, ScheduledEmailModel.email_id == EmailModel.id)
            .filter(ScheduledEmailModel.id == scheduled_id,
                    EmailModel.owner == account)
            .first()
        )
        if sched is None:
            return jsonify({"error": "schedule not found"}), 404

        email_id = sched.email_id

        if sent:
            # keep the mail row as a record of what went out
            sched.status = "sent"
            mail = db.query(EmailModel).filter(EmailModel.id == email_id).first()
            if mail is not None:
                mail.is_draft = False
                mail.updated_at = datetime.utcnow()
        else:
            # bulk delete, not db.delete(sched): the session is autoflush=False,
            # so an ORM delete stays pending and the emails DELETE below hits
            # the FK from the still-present schedule row
            db.query(ScheduledEmailModel).filter(
                ScheduledEmailModel.id == scheduled_id
            ).delete()
            db.query(EmailModel).filter(EmailModel.id == email_id).delete()

        db.commit()
        return jsonify({"message": "sent" if sent else "cancelled", "id": scheduled_id})

    except Exception as e:
        db.rollback()
        return _server_error("delete_scheduled_email", e)

    finally:
        db.close()


@email_bp.route("/folders", methods=["GET"])
def list_folders():
    account, denied = _require_owner()
    if denied:
        return denied

    db = get_db_session()
    try:
        folders = (
            db.query(FolderModel)
            .filter(FolderModel.owner == account)
            .order_by(FolderModel.name.asc())
            .all()
        )
        result = [
            {
                "id": f.id,
                "name": f.name,
                "description": f.description,
            }
            for f in folders
        ]
        return jsonify({"folders": result})
    except Exception as e:
        return _server_error("list_folders", e)
    finally:
        db.close()


@email_bp.route("/folders", methods=["POST"])
def create_folder():
    account, denied = _require_owner()
    if denied:
        return denied

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    description = data.get("description")

    if not name:
        return jsonify({"error": "name is required"}), 400

    db = get_db_session()
    try:
        # unique by name within the account, not across all of them
        existing = (
            db.query(FolderModel)
            .filter(FolderModel.name == name, FolderModel.owner == account)
            .first()
        )
        if existing:
            return jsonify({"error": "folder with this name already exists"}), 409

        folder = FolderModel(owner=account, name=name, description=description)
        db.add(folder)
        db.commit()
        db.refresh(folder)

        return jsonify(
            {
                "id": folder.id,
                "name": folder.name,
                "description": folder.description,
            }
        )

    except Exception as e:
        db.rollback()
        return _server_error("create_folder", e)

    finally:
        db.close()

# ---------- User settings ----------

DEFAULT_SETTINGS = {
    "language": "en",
    "fontFamily": "system",
    "fontSize": "browser",
    "appearance": "light",
    "themeColor": "#1a73c7",
    "leftPanelColor": "#f7f9fb",
    "notifications": {
        "enabled": True,
        "sound": "chime",
        "volume": 0.6,
        "silent": False,
        "silentFrom": "22:00",
        "silentTo": "07:00",
    },
    # who you are, and who you write to (address -> name). Learned from the
    # mail you send, so generated drafts stop asking for "[Your Name]".
    "profile": {"name": ""},
    "contacts": {},
}

# settings whose value is a dict: a partial update merges into it instead of
# replacing it, so saving one key never drops the others
_DICT_SETTINGS = ("notifications", "profile", "contacts")

_SETTING_CHOICES = {
    "language": {"en"},
    "fontFamily": {"system", "lato", "roboto", "georgia"},
    "fontSize": {"browser", "small", "medium", "large"},
    "appearance": {"light", "dark"},
}
_SOUND_CHOICES = {
    "chime",
    "ding",
    "pop",
    "bell",
    "tritone",
    "marimba",
    "bloop",
    "knock",
    "pulse",
    "none",
}
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _clean_settings(raw):
    """Keep only known keys with valid values — anything else is dropped."""
    if not isinstance(raw, dict):
        return {}

    clean = {}

    for key, choices in _SETTING_CHOICES.items():
        if raw.get(key) in choices:
            clean[key] = raw[key]

    for key in ("themeColor", "leftPanelColor"):
        value = raw.get(key)
        if isinstance(value, str) and _HEX_RE.match(value):
            clean[key] = value

    notifications = raw.get("notifications")
    if isinstance(notifications, dict):
        clean_notifications = {}

        for key in ("enabled", "silent"):
            if isinstance(notifications.get(key), bool):
                clean_notifications[key] = notifications[key]

        if notifications.get("sound") in _SOUND_CHOICES:
            clean_notifications["sound"] = notifications["sound"]

        volume = notifications.get("volume")
        if isinstance(volume, (int, float)) and not isinstance(volume, bool):
            clean_notifications["volume"] = min(1.0, max(0.0, float(volume)))

        for key in ("silentFrom", "silentTo"):
            value = notifications.get(key)
            if isinstance(value, str) and _TIME_RE.match(value):
                clean_notifications[key] = value

        if clean_notifications:
            clean["notifications"] = clean_notifications

    profile = raw.get("profile")
    if isinstance(profile, dict):
        name = clean_name(profile.get("name"))
        if name:
            clean["profile"] = {"name": name}

    contacts = raw.get("contacts")
    if isinstance(contacts, dict):
        clean_contacts = {}
        for address, name in contacts.items():
            name = clean_name(name)
            if name and isinstance(address, str) and "@" in address:
                clean_contacts[address.strip().lower()] = name
        if clean_contacts:
            clean["contacts"] = clean_contacts

    return clean


def _merged_settings(stored):
    merged = dict(DEFAULT_SETTINGS)
    for key in _DICT_SETTINGS:
        merged[key] = dict(DEFAULT_SETTINGS[key])

    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in _DICT_SETTINGS and isinstance(value, dict):
                merged[key].update(value)
            elif key in DEFAULT_SETTINGS:
                merged[key] = value

    return merged


def _current_email_address():
    """Gmail address of the signed-in user; cached in the session."""
    cached = session.get("email_address")
    if cached:
        return cached

    service = get_gmail_service()
    if service is None:
        return None

    # every caller treats "no address" as "not signed in"; a failed profile
    # lookup must not turn into a 500 halfway through an unrelated request
    try:
        address = service.users().getProfile(userId="me").execute().get("emailAddress")
    except Exception as e:
        current_app.logger.warning(f"_current_email_address failed: {e}")
        return None

    if address:
        session["email_address"] = address
        session.modified = True

    return address


# ---------- remembered names ----------

def _sole_address(value):
    """The one recipient address in `value`, or None if absent or ambiguous."""
    parsed = [addr.strip().lower() for _, addr in getaddresses([value or ""]) if "@" in addr]
    return parsed[0] if len(parsed) == 1 else None


def _load_settings(address):
    """Stored settings for `address` with defaults merged in."""
    db = get_db_session()
    try:
        row = (
            db.query(UserSettingsModel)
            .filter(UserSettingsModel.email_address == address)
            .first()
        )
        return _merged_settings(row.data if row else None)
    finally:
        db.close()


def _remember_names(address, to_address, body):
    """Learn the sender's and recipient's names from an email being sent.

    Every finished email carries them in fixed places — "Dear X," at the top
    and the signature at the bottom — so there is no need to diff the
    generated draft against what the user edited. Best effort: a failure here
    must never fail the send that just succeeded.

    ponytail: greeting/signature heuristic, learns nothing from mail that
    doesn't open with "Dear X," — diff the generated draft against the sent
    body if that turns out to miss too much.
    """
    sender = signature_name(body)
    recipient = greeting_name(body) if to_address else None
    if not sender and not recipient:
        return

    db = get_db_session()
    try:
        row = (
            db.query(UserSettingsModel)
            .filter(UserSettingsModel.email_address == address)
            .first()
        )
        if row is None:
            row = UserSettingsModel(email_address=address, data={})
            db.add(row)

        merged = _merged_settings(row.data)

        # your own name is learned once — later mail may be signed off by a
        # team name or an alias, and overwriting would be a regression
        if sender and not merged["profile"].get("name"):
            merged["profile"]["name"] = sender

        # contacts do change (people get renamed, addresses change hands)
        if recipient:
            merged["contacts"][to_address] = recipient

        row.data = merged
        db.commit()

    except Exception as e:
        db.rollback()
        current_app.logger.error(f"_remember_names error: {e}", exc_info=True)

    finally:
        db.close()


@email_bp.route("/settings", methods=["GET"])
def get_settings():
    address = _current_email_address()
    if not address:
        return jsonify({"error": "Not authenticated"}), 401

    db = get_db_session()
    try:
        row = (
            db.query(UserSettingsModel)
            .filter(UserSettingsModel.email_address == address)
            .first()
        )
        return jsonify({"settings": _merged_settings(row.data if row else None)})
    except Exception as e:
        return _server_error("get_settings", e)
    finally:
        db.close()


@email_bp.route("/settings", methods=["PUT"])
def update_settings():
    address = _current_email_address()
    if not address:
        return jsonify({"error": "Not authenticated"}), 401

    incoming = _clean_settings(request.get_json(silent=True))
    if not incoming:
        return jsonify({"error": "No valid settings supplied"}), 400

    db = get_db_session()
    try:
        row = (
            db.query(UserSettingsModel)
            .filter(UserSettingsModel.email_address == address)
            .first()
        )

        if row is None:
            row = UserSettingsModel(email_address=address, data={})
            db.add(row)

        # partial update: merge over what is already stored
        merged = _merged_settings(row.data)
        for key, value in incoming.items():
            if key in _DICT_SETTINGS:
                merged[key].update(value)
            else:
                merged[key] = value

        row.data = merged
        db.commit()

        return jsonify({"settings": merged})

    except Exception as e:
        db.rollback()
        return _server_error("update_settings", e)

    finally:
        db.close()
