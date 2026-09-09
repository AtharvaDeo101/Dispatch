import base64
import json
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError


class TestIndexRoute:
    def test_index_not_logged_in(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert json.loads(response.data)["status"] == "not_logged_in"

    def test_index_logged_in(self, client):
        with client.session_transaction() as sess:
            sess["credentials"] = {
                "token": "fake-token",
                "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "c",
                "client_secret": "s",
                "scopes": [],
            }
        response = client.get("/")
        assert json.loads(response.data)["status"] == "logged_in"


class TestLogoutRoute:
    def test_logout_clears_session(self, client):
        with client.session_transaction() as sess:
            sess["credentials"] = {"token": "fake"}
        response = client.post("/logout")
        assert response.status_code == 200
        assert json.loads(response.data)["status"] == "logged_out"

    def test_logout_without_session(self, client):
        assert client.post("/logout").status_code == 200


class TestMeRoute:
    def test_me_unauthenticated(self, client):
        response = client.get("/me")
        assert response.status_code == 401
        assert json.loads(response.data)["error"] == "not_authenticated"

    @patch("OAuth.build")
    @patch("OAuth.Credentials")
    def test_me_authenticated(self, mock_creds, mock_build, client):
        mock_service = MagicMock()
        mock_service.users().getProfile(userId="me").execute.return_value = {"emailAddress": "test@example.com"}
        mock_build.return_value = mock_service
        with client.session_transaction() as sess:
            sess["credentials"] = {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "c",
                "client_secret": "s",
                "scopes": [],
            }
        response = client.get("/me")
        assert response.status_code == 200
        assert json.loads(response.data)["emailAddress"] == "test@example.com"


class TestSendEmailRoute:
    def test_send_email_unauthenticated(self, client):
        assert client.post("/send_email", json={"to": "a@b.com", "subject": "Hi", "body": "Hello"}).status_code == 401

    def test_send_email_missing_fields(self, client):
        with client.session_transaction() as sess:
            sess["credentials"] = {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "c",
                "client_secret": "s",
                "scopes": [],
            }
        with patch("OAuth.build"), patch("OAuth.Credentials"):
            response = client.post("/send_email", json={"to": "a@b.com"})
        assert response.status_code == 400

    @patch("OAuth.build")
    @patch("OAuth.Credentials")
    def test_send_email_success(self, mock_creds, mock_build, client):
        mock_service = MagicMock()
        mock_service.users().messages().send().execute.return_value = {"id": "msg-123"}
        mock_build.return_value = mock_service
        with client.session_transaction() as sess:
            sess["credentials"] = {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "c",
                "client_secret": "s",
                "scopes": [],
            }
        response = client.post("/send_email", json={"to": "test@example.com", "subject": "Test", "body": "Body"})
        assert response.status_code == 200
        assert json.loads(response.data)["message"] == "sent"


class TestGenerateEmailRoute:
    def test_generate_unauthenticated(self, client):
        assert client.post("/generate_email", json={"prompt": "write"}).status_code == 401

    def test_generate_missing_prompt(self, client):
        with client.session_transaction() as sess:
            sess["credentials"] = {"token": "t"}
            sess["email_address"] = "user@example.com"
        assert client.post("/generate_email", json={}).status_code == 400

    @patch("email_service.generate_with_api")
    def test_generate_success(self, mock_gen, client):
        mock_gen.return_value = "Subject: Meeting\n\nDear John,\n\nLet's meet.\n\nBest,\nMe"
        with client.session_transaction() as sess:
            sess["credentials"] = {"token": "t"}
            sess["email_address"] = "user@example.com"
        response = client.post("/generate_email", json={"prompt": "schedule a meeting"})
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["subject"] == "Meeting"
        assert "Dear John" in data["body"]

    @patch("email_service.generate_with_api")
    def test_generate_api_error(self, mock_gen, client):
        mock_gen.side_effect = Exception("API down")
        with client.session_transaction() as sess:
            sess["credentials"] = {"token": "t"}
            sess["email_address"] = "user@example.com"
        response = client.post("/generate_email", json={"prompt": "hi"})
        assert response.status_code == 500
        # the exception text stays in the logs; a 500 body that echoes it hands
        # out SQL fragments and file paths
        assert "API down" not in response.get_data(as_text=True)
        assert json.loads(response.data)["error"] == "internal error"


class TestRemembersNames:
    """Sending an email teaches the generator the names it should reuse."""

    @patch("OAuth.build")
    @patch("OAuth.Credentials")
    def test_names_from_a_sent_email_land_in_the_next_draft(
        self, mock_creds, mock_build, client, login
    ):
        mock_service = MagicMock()
        mock_service.users().messages().send().execute.return_value = {"id": "m-1"}
        mock_build.return_value = mock_service
        # a MagicMock's .expired is truthy, which makes get_gmail_service write
        # unpicklable mock credentials back into the session
        mock_creds.return_value.expired = False

        login(client)
        with client.session_transaction() as sess:
            sess["email_address"] = "learner@example.com"

        sent = client.post(
            "/send_email",
            json={
                "to": "Priya Sharma <priya@example.com>",
                "subject": "Report",
                "body": "Dear Priya,\n\nThe report is attached.\n\nRegards,\nAtharva",
            },
        )
        assert sent.status_code == 200

        settings = json.loads(client.get("/settings").data)["settings"]
        assert settings["profile"]["name"] == "Atharva"
        assert settings["contacts"]["priya@example.com"] == "Priya"

        with patch("email_service.generate_with_api") as mock_gen:
            mock_gen.return_value = (
                "Subject: Follow-up\n\nDear [Recipient Name],\n\nAny update?"
                "\n\nRegards,\n[Your Name]"
            )
            response = client.post(
                "/generate_email",
                json={"prompt": "follow up", "to": "priya@example.com"},
            )

        assert response.status_code == 200
        body = json.loads(response.data)["body"]
        assert "Dear Priya," in body
        assert body.endswith("Atharva")
        # the names are handed to the model too, not just patched in afterwards
        assert mock_gen.call_args.args == ("follow up", "Atharva", "Priya")

    @patch("OAuth.build")
    @patch("OAuth.Credentials")
    def test_a_generic_greeting_is_not_learned_as_a_name(
        self, mock_creds, mock_build, client, login
    ):
        mock_service = MagicMock()
        mock_service.users().messages().send().execute.return_value = {"id": "m-2"}
        mock_build.return_value = mock_service
        # a MagicMock's .expired is truthy, which makes get_gmail_service write
        # unpicklable mock credentials back into the session
        mock_creds.return_value.expired = False

        login(client)
        with client.session_transaction() as sess:
            sess["email_address"] = "generic@example.com"

        client.post(
            "/send_email",
            json={
                "to": "team@example.com",
                "subject": "Notice",
                "body": "Dear Team,\n\nStandup moves to 10am.\n\nBest regards,",
            },
        )

        settings = json.loads(client.get("/settings").data)["settings"]
        assert settings["profile"]["name"] == ""
        assert settings["contacts"] == {}


class TestSummarizeEmailRoute:
    def test_summarize_unauthenticated(self, client):
        assert client.post("/summarize_email", json={"content": "text"}).status_code == 401

    def test_summarize_missing_content(self, client):
        with client.session_transaction() as sess:
            sess["credentials"] = {"token": "t"}
            sess["email_address"] = "user@example.com"
        assert client.post("/summarize_email", json={}).status_code == 400

    @patch("email_service.summarize_with_api")
    def test_summarize_brief(self, mock_sum, client):
        mock_sum.return_value = "This is about a meeting."
        with client.session_transaction() as sess:
            sess["credentials"] = {"token": "t"}
            sess["email_address"] = "user@example.com"
        response = client.post("/summarize_email", json={"content": "Long email...", "type": "brief"})
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["type"] == "brief"
        assert "summary" in data


class TestGetEmailRoute:
    @staticmethod
    def _login(client):
        with client.session_transaction() as sess:
            sess["credentials"] = {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "c",
                "client_secret": "s",
                "scopes": [],
            }

    @staticmethod
    def _message(label_ids):
        encoded = base64.urlsafe_b64encode(b"Hello").decode()
        return {
            "id": "m1",
            "threadId": "t1",
            "labelIds": list(label_ids),
            "snippet": "hi",
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": encoded},
                "headers": [
                    {"name": "Subject", "value": "Hi"},
                    {"name": "From", "value": "a@b.com"},
                ],
            },
        }

    def _open(self, client, label_ids, modify_error=None):
        self._login(client)
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.get.return_value.execute.return_value = self._message(label_ids)
        if modify_error:
            messages.modify.return_value.execute.side_effect = modify_error
        with patch("OAuth.build", return_value=service), patch("OAuth.Credentials"):
            return client.get("/get_email/m1"), messages

    def test_get_email_unauthenticated(self, client):
        assert client.get("/get_email/m1").status_code == 401

    def test_opening_unread_email_marks_it_read(self, client):
        response, messages = self._open(client, ["INBOX", "UNREAD"])
        assert response.status_code == 200
        assert json.loads(response.data)["email"]["labelIds"] == ["INBOX"]
        messages.modify.assert_called_once_with(
            userId="me", id="m1", body={"removeLabelIds": ["UNREAD"]}
        )

    def test_opening_read_email_does_not_write(self, client):
        response, messages = self._open(client, ["INBOX"])
        assert response.status_code == 200
        assert json.loads(response.data)["email"]["labelIds"] == ["INBOX"]
        messages.modify.assert_not_called()

    def test_failed_mark_read_still_returns_the_email(self, client):
        error = HttpError(MagicMock(status=403, reason="Forbidden"), b"{}")
        response, _ = self._open(client, ["INBOX", "UNREAD"], modify_error=error)
        assert response.status_code == 200
        email = json.loads(response.data)["email"]
        assert email["subject"] == "Hi"
        assert email["labelIds"] == ["INBOX", "UNREAD"]


class TestHelperFunctions:
    def test_decode_body(self):
        from email_service import _decode_body

        encoded = base64.urlsafe_b64encode(b"Hello World").decode()
        assert _decode_body(encoded) == "Hello World"

    def test_decode_body_empty(self):
        from email_service import _decode_body

        assert _decode_body("") == ""
        assert _decode_body(None) == ""

    def test_html_to_text(self):
        from email_service import _html_to_text

        result = _html_to_text("<p>Hello</p><p>World</p>")
        assert "Hello" in result and "World" in result

    def test_extract_plain_body(self):
        from email_service import extract_email_body

        encoded = base64.urlsafe_b64encode(b"Plain content").decode()
        result = extract_email_body({"mimeType": "text/plain", "body": {"data": encoded}})
        assert result["plain_body"] == "Plain content"

    def test_extract_multipart_body(self):
        from email_service import extract_email_body

        plain = base64.urlsafe_b64encode(b"Plain").decode()
        html = base64.urlsafe_b64encode(b"<p>HTML</p>").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain}},
                {"mimeType": "text/html", "body": {"data": html}},
            ],
        }
        result = extract_email_body(payload)
        assert result["plain_body"] == "Plain"
        assert "<p>HTML</p>" in result["html_body"]
