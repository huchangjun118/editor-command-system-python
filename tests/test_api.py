from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_search_endpoint():
    r = client.get("/terminal/search", params={"query": "save"})
    assert r.status_code == 200
    hits = r.json()
    assert any(h["id"] == "file.save" for h in hits)


def test_run_and_undo_roundtrip():
    r = client.post("/terminal/run", json={
        "command_id": "editor.insert", "args": {"text": "hello"}})
    assert r.json()["status"] == "succeeded"
    r = client.post("/terminal/undo")
    assert r.json()["status"] == "succeeded"


def test_permission_denied_visible_in_history():
    client.post("/terminal/run", json={"command_id": "admin.reset"})
    hist = client.get("/terminal/history").json()
    denied = [h for h in hist if h["command_id"] == "admin.reset"]
    assert denied and denied[-1]["status"] == "denied"
    assert denied[-1]["reason"] == "permission_denied"


def test_explain_endpoint():
    r = client.get("/terminal/explain/admin.reset")
    assert any("admin" in reason for reason in r.json()["reasons"])


def test_keybindings_report_layer():
    for b in client.get("/keybindings").json():
        assert b["layer"] in ("builtin", "extension", "user")
