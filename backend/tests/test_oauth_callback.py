from unittest.mock import patch

import OAuth


def _callback(client, app, redirect_uri):
    """Drive /oauth2callback with a primed session, capturing fetch_token's args."""
    app.config["REDIRECT_URI"] = redirect_uri
    with client.session_transaction() as sess:
        sess["state"] = "st"
        sess["code_verifier"] = "cv"

    captured = {}

    class FakeFlow:
        credentials = type(
            "C", (), {
                "token": "t", "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "c", "client_secret": "s", "scopes": [],
            },
        )()

        def fetch_token(self, **kwargs):
            captured.update(kwargs)

    with patch.object(OAuth, "build_google_flow", return_value=FakeFlow()):
        client.get("/oauth2callback?state=st&code=abc")
    return captured


def test_callback_keeps_https_behind_a_tls_terminating_proxy(client, app):
    # Render forwards plaintext to gunicorn, so request.url reports http and
    # oauthlib would refuse it. The scheme must come from REDIRECT_URI instead.
    captured = _callback(client, app, "https://api.example.com/oauth2callback")
    assert captured["authorization_response"].startswith(
        "https://api.example.com/oauth2callback?"
    )
    # the authorization code still has to survive the rebuild
    assert "code=abc" in captured["authorization_response"]
    assert captured["code_verifier"] == "cv"


def test_callback_still_works_on_plain_http_in_dev(client, app):
    captured = _callback(client, app, "http://localhost:5000/oauth2callback")
    assert captured["authorization_response"].startswith(
        "http://localhost:5000/oauth2callback?"
    )


def test_callback_rejects_a_mismatched_state(client, app):
    app.config["REDIRECT_URI"] = "https://api.example.com/oauth2callback"
    with client.session_transaction() as sess:
        sess["state"] = "st"
        sess["code_verifier"] = "cv"
    assert client.get("/oauth2callback?state=WRONG&code=abc").status_code == 400
