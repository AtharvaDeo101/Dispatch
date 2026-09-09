import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("HF_API_TOKEN", "test-hf-token")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000/")
os.environ.setdefault("REDIRECT_URI", "http://localhost:5000/oauth2callback")
# db.py builds its engine at import time from this; keep the suite off Postgres
os.environ.setdefault("DATABASE_URL", "sqlite://")


@pytest.fixture
def app():
    from main import create_app

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR="./flask_session_test",
        SESSION_COOKIE_SECURE=False,
    )
    os.makedirs("./flask_session_test", exist_ok=True)
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login():
    """Give a client the session the app requires: login(client[, address]).

    Rows in `emails` and `folders` are keyed by Gmail address, so a signed-in
    session needs one. `email_address` is the cache _current_email_address()
    reads before it would otherwise call the Gmail API.
    """

    def _login(client, address="user@example.com"):
        with client.session_transaction() as sess:
            sess["credentials"] = {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "c",
                "client_secret": "s",
                "scopes": [],
            }
            sess["email_address"] = address

    return _login
