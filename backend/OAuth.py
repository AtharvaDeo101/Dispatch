import base64
import hashlib
import secrets

from flask import Blueprint, jsonify, redirect, request, session, current_app
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

oauth_bp = Blueprint("oauth_bp", __name__)


def _credentials_to_dict(creds: Credentials):
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
    }


def get_gmail_service():
    creds_data = session.get("credentials")
    if not creds_data:
        current_app.logger.warning("No credentials found in session")
        return None

    try:
        creds = Credentials(**creds_data)
    except Exception as e:
        current_app.logger.error(f"Failed to load credentials from session: {e}", exc_info=True)
        session.pop("credentials", None)
        return None

    try:
        if creds.expired and creds.refresh_token:
            current_app.logger.info("Refreshing expired Google access token")
            creds.refresh(Request())
            session["credentials"] = _credentials_to_dict(creds)
            session.modified = True

        elif creds.expired and not creds.refresh_token:
            current_app.logger.warning("Credentials expired and no refresh token available")
            session.pop("credentials", None)
            return None

        return build("gmail", "v1", credentials=creds)

    except Exception as e:
        current_app.logger.error(f"Failed to refresh/build Gmail service: {e}", exc_info=True)
        session.pop("credentials", None)
        return None


def build_google_flow(state=None):
    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": current_app.config["GOOGLE_CLIENT_ID"],
                "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [current_app.config["REDIRECT_URI"]],
            }
        },
        scopes=current_app.config["SCOPES"],
        state=state,
    )
    flow.redirect_uri = current_app.config["REDIRECT_URI"]
    return flow


@oauth_bp.route("/")
def index():
    if "credentials" in session:
        return jsonify({"status": "logged_in"})
    return jsonify({"status": "not_logged_in"})


@oauth_bp.route("/login")
def login():
    code_verifier = secrets.token_urlsafe(32)
    session["code_verifier"] = code_verifier

    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    flow = build_google_flow()

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

    session["state"] = state
    session.modified = True
    return redirect(authorization_url)


@oauth_bp.route("/oauth2callback")
def oauth2callback():
    if "state" not in session or session["state"] != request.args.get("state"):
        return "Invalid state parameter", 400

    if "code_verifier" not in session:
        return "Code verifier not found in session", 400

    code_verifier = session.pop("code_verifier")
    flow = build_google_flow(state=session["state"])

    # Rebuild the callback URL from REDIRECT_URI rather than request.url: behind
    # Render's TLS-terminating proxy gunicorn reports the scheme as http, and
    # oauthlib refuses a plaintext authorization_response once
    # OAUTHLIB_INSECURE_TRANSPORT is off. REDIRECT_URI is the exact URI
    # registered with Google, so it matches flow.redirect_uri by construction.
    flow.fetch_token(
        authorization_response=(
            f"{current_app.config['REDIRECT_URI']}?{request.query_string.decode()}"
        ),
        code_verifier=code_verifier,
    )

    creds = flow.credentials
    session["credentials"] = _credentials_to_dict(creds)
    session.modified = True

    return redirect(current_app.config["FRONTEND_URL"], code=302)


@oauth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "logged_out"})


@oauth_bp.route("/me")
def me():
    service = get_gmail_service()
    if service is None:
        return jsonify({"error": "not_authenticated"}), 401

    try:
        profile = service.users().getProfile(userId="me").execute()
        return jsonify(profile)
    except Exception as e:
        current_app.logger.error(f"/me error: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch profile"}), 500