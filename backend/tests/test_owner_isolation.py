"""One account must never see or touch another account's stored rows.

`emails`, `folders` and `scheduled_emails` are shared tables; the only thing
keeping them apart is the owner filter on every query. These tests fail loudly
if any of those filters is dropped.
"""

from datetime import datetime, timedelta, timezone

ALICE = "alice@example.com"
BOB = "bob@example.com"


def _make_draft(client, subject):
    """Create a stored draft as whoever `client` is signed in as."""
    when = datetime.now(timezone.utc) + timedelta(hours=2)
    created = client.post(
        "/scheduled_emails",
        json={
            "to": "someone@example.com",
            "subject": subject,
            "body": "body",
            "scheduled_for": when.isoformat().replace("+00:00", "Z"),
        },
    )
    assert created.status_code == 200
    payload = created.get_json()
    return payload["email_id"], payload["id"]


def _land_email(client, subject):
    """A plain row in `emails`: schedule one, then mark the send as done.

    /stored_emails hides rows whose schedule is still pending, so a scheduled
    draft would drop out of that listing for reasons other than ownership and
    the owner filter would go untested.
    """
    email_id, sched_id = _make_draft(client, subject)
    assert client.delete(f"/scheduled_emails/{sched_id}?sent=true").status_code == 200
    return email_id


def test_stored_emails_are_invisible_to_another_account(client, login):
    login(client, ALICE)
    alice_email_id = _land_email(client, "Alice private")
    # visible to its owner, so the assertions below are about ownership only
    assert alice_email_id in [
        e["id"] for e in client.get("/stored_emails").get_json()["emails"]
    ]

    login(client, BOB)
    listed = client.get("/stored_emails").get_json()["emails"]
    assert alice_email_id not in [e["id"] for e in listed]
    assert "Alice private" not in [e["subject"] for e in listed]


def test_another_account_cannot_read_or_write_a_stored_email(client, login):
    login(client, ALICE)
    alice_email_id = _land_email(client, "Alice private")

    login(client, BOB)
    assert client.patch(
        f"/stored_emails/{alice_email_id}", json={"subject": "pwned"}
    ).status_code == 404
    assert client.delete(f"/stored_emails/{alice_email_id}").status_code == 404

    # and the row is genuinely untouched, not merely reported as missing
    login(client, ALICE)
    mine = client.get("/stored_emails").get_json()["emails"]
    assert [e["subject"] for e in mine if e["id"] == alice_email_id] == ["Alice private"]


def test_another_account_cannot_cancel_a_pending_schedule(client, login):
    login(client, ALICE)
    _, alice_sched_id = _make_draft(client, "Alice scheduled")

    login(client, BOB)
    assert client.delete(f"/scheduled_emails/{alice_sched_id}").status_code == 404
    assert client.get("/scheduled_emails").get_json()["scheduled"] == []

    login(client, ALICE)
    assert alice_sched_id in [
        s["id"] for s in client.get("/scheduled_emails").get_json()["scheduled"]
    ]


def test_folders_are_per_account(client, login):
    login(client, ALICE)
    assert client.post("/folders", json={"name": "Work"}).status_code == 200
    alice_folder = client.get("/folders").get_json()["folders"][0]["id"]

    login(client, BOB)
    assert client.get("/folders").get_json()["folders"] == []
    # the same name must still be free for a second account
    assert client.post("/folders", json={"name": "Work"}).status_code == 200

    # and Bob cannot file his mail into Alice's folder by naming its id
    bob_email_id, _ = _make_draft(client, "Bob draft")
    assert client.patch(
        f"/stored_emails/{bob_email_id}", json={"folder_id": alice_folder}
    ).status_code == 404
