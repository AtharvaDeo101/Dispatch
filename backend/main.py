import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_session import Session
from huggingface_hub import InferenceClient
from sqlalchemy import text

# NEW: import DB base and session
from db import Base, engine

from email_service import email_bp
from gateway import install_gateway
from OAuth import oauth_bp

load_dotenv()

# One signal drives every http-vs-https decision: the redirect URI Google is
# configured with. http => local dev, https => deployed.
IS_HTTPS = os.environ.get("REDIRECT_URI", "").startswith("https://")

# OAuthlib refuses a plaintext OAuth exchange unless told otherwise; only tell it
# so in dev, never against a real https deployment.
if not IS_HTTPS:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"


def create_app():
    app = Flask(__name__)
    # a random fallback silently invalidates every session on restart, which is
    # tolerable in dev and a bug report factory in production
    secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not secret_key and IS_HTTPS:
        raise RuntimeError("FLASK_SECRET_KEY must be set when REDIRECT_URI is https")
    app.secret_key = secret_key or os.urandom(24)

    # .env ships ALLOWED_ORIGINS; accept both names so a deploy that sets only
    # one does not silently fall back to localhost and CORS-block the frontend.
    origins = [
        o.strip()
        for o in (
            os.environ.get("FRONTEND_ORIGIN")
            or os.environ.get("ALLOWED_ORIGINS")
            or "http://localhost:3000"
        ).split(",")
        if o.strip()
    ]

    # --- Flask session & Gmail / HF config ---
    app.config.update(
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR="./flask_session",
        SESSION_PERMANENT=True,
        SESSION_USE_SIGNER=True,
        SESSION_COOKIE_NAME="session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=IS_HTTPS,
        # deployed, the frontend may sit on another domain, and a Lax cookie is
        # never sent on those cross-site fetches. None requires Secure.
        SESSION_COOKIE_SAMESITE="None" if IS_HTTPS else "Lax",
        # flask-session uses this as the session *file* TTL too, so 1800 logged
        # you out after 30 idle minutes. Refreshed on every request.
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID"),
        GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET"),
        SCOPES=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
        FRONTEND_URL=os.environ.get("FRONTEND_URL", "http://localhost:3000/generate"),
        REDIRECT_URI=os.environ.get("REDIRECT_URI", "http://localhost:5000/oauth2callback"),
        HF_API_TOKEN=os.environ.get("HF_API_TOKEN"),
        HF_MODEL="meta-llama/Llama-3.1-8B-Instruct",
    )

    # Make sure the session directory exists
    os.makedirs("./flask_session", exist_ok=True)

    # Initialize server-side sessions
    Session(app)

    # CORS for Next.js frontend
    CORS(
        app,
        supports_credentials=True,
        resources={
            r"/*": {
                "origins": origins,
            }
        },
    )

    # Hugging Face client
    app.hf_client = InferenceClient(token=app.config["HF_API_TOKEN"])

    # --- NEW: Create tables on startup ---
    with app.app_context():
        Base.metadata.create_all(bind=engine)
        # create_all never alters an existing table, so columns added to a model
        # after the volume was created stay missing and every SELECT 500s.
        # ponytail: hand-written idempotent ALTER; swap for Alembic if this grows
        # past a couple of added columns.
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE emails"
                    " ADD COLUMN IF NOT EXISTS gmail_message_id VARCHAR(255),"
                    " ADD COLUMN IF NOT EXISTS gmail_draft_id VARCHAR(255)"
                ))

    # Health check endpoint
    @app.get("/health")
    def health():
        # /health is public: no DATABASE_URL here, it carries the db password
        return jsonify({"ok": True, "frontend_origin": origins})

    # Auth gate, rate limits, response cache and security headers for every route
    install_gateway(app)

    # Register blueprints
    app.register_blueprint(oauth_bp)
    app.register_blueprint(email_bp)

    return app


app = create_app()

if __name__ == "__main__":
    # dev entry point only — the image runs gunicorn. debug is off once the
    # redirect URI is https, so this can never serve the Werkzeug debugger live.
    app.run(host="0.0.0.0", debug=not IS_HTTPS, port=5000)