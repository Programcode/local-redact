"""FastAPI server tests. Uses StubEngine (via server.create_engine monkeypatch)
so no spaCy model is loaded — fast, deterministic, matches the rest of the
format/CLI test suite's approach to avoiding NLP loads outside test_engine.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import StubEngine, TEST_PASSPHRASE
from local_redact import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    server.state.lock()
    db_path = tmp_path / "mapping.db"
    pairs_holder: dict = {"pairs": []}

    def _create_engine(db):
        return StubEngine(db, pairs_holder["pairs"])

    monkeypatch.setattr(server, "create_engine", _create_engine)
    c = TestClient(server.app)
    c.db_path = str(db_path)
    c.set_pairs = lambda pairs: pairs_holder.__setitem__("pairs", pairs)
    yield c
    # tear down through the API (same worker thread the DB connection was
    # opened in) rather than calling server.state.lock() directly from the
    # pytest thread — sqlite connections are thread-affine.
    c.post("/api/lock")


def _unlock(client, passphrase=TEST_PASSPHRASE, create=True):
    return client.post(
        "/api/unlock",
        json={"passphrase": passphrase, "db_path": client.db_path, "create": create},
    )


class TestAuthGate:
    def test_status_locked_initially(self, client):
        assert client.get("/api/status").json() == {"unlocked": False}

    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("get", "/api/categories", None),
            ("get", "/api/terms", None),
            ("post", "/api/redact/preview", {"text": "x"}),
            ("post", "/api/redact/confirm", {"text": "x", "detections": []}),
            ("post", "/api/reveal", {"text": "x"}),
            ("get", "/api/audit", None),
            ("post", "/api/batch", {"input_dir": "/tmp", "output_dir": "/tmp"}),
            ("post", "/api/wipe", {"confirm": True}),
        ],
    )
    def test_endpoints_401_before_unlock(self, client, method, path, body):
        resp = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert resp.status_code == 401

    def test_unlock_wrong_passphrase_fails_closed(self, client):
        assert _unlock(client, passphrase="correct-horse", create=True).status_code == 200
        client.post("/api/lock")
        resp = _unlock(client, passphrase="totally-wrong", create=False)
        assert resp.status_code == 401
        assert client.get("/api/status").json() == {"unlocked": False}

    def test_unlock_open_existing_does_not_silently_create(self, client):
        # "Open existing" (create=False) against a path with no DB yet must
        # fail closed, not silently create one — the UI presents open/create
        # as an explicit choice and a masked create-on-open would hide a
        # mistyped passphrase or wrong path as if it had worked.
        resp = _unlock(client, passphrase="anything", create=False)
        assert resp.status_code == 401
        assert client.get("/api/status").json() == {"unlocked": False}
        assert not Path(client.db_path).exists()

    def test_unlock_create_and_status(self, client):
        resp = _unlock(client)
        assert resp.status_code == 200
        assert resp.json() == {"unlocked": True}
        assert client.get("/api/status").json() == {"unlocked": True}

    def test_lock_clears_state(self, client):
        _unlock(client)
        client.post("/api/lock")
        assert client.get("/api/status").json() == {"unlocked": False}


class TestRedactPreviewConfirm:
    def test_preview_does_not_write_db(self, client):
        client.set_pairs([("Kovács János", "PERSON_00000")])
        _unlock(client)
        resp = client.post("/api/redact/preview", json={"text": "Kovács János elment."})
        assert resp.status_code == 200
        detections = resp.json()
        assert len(detections) == 1
        assert detections[0]["entity_type"] == "PERSON"
        assert detections[0]["text"] == "Kovács János"
        # preview must not touch the DB
        audit = client.get("/api/audit").json()
        assert audit["entries"] == []

    def test_confirm_creates_entities_and_reveal_roundtrip(self, client):
        client.set_pairs([("Kovács János", "PERSON_00000")])
        _unlock(client)
        text = "Kovács János elment."
        detections = client.post("/api/redact/preview", json={"text": text}).json()
        confirm = client.post(
            "/api/redact/confirm", json={"text": text, "detections": detections}
        )
        assert confirm.status_code == 200
        redacted = confirm.json()["text"]
        assert "Kovács János" not in redacted
        assert confirm.json()["replacements"] == 1

        reveal = client.post("/api/reveal", json={"text": redacted})
        assert reveal.status_code == 200
        assert reveal.json()["text"] == text
        assert reveal.json()["restored"] == 1

    def test_confirm_only_applies_accepted_detections(self, client):
        client.set_pairs([("Kovács János", "P1"), ("Nagy Éva", "P2")])
        _unlock(client)
        text = "Kovács János és Nagy Éva elmentek."
        detections = client.post("/api/redact/preview", json={"text": text}).json()
        assert len(detections) == 2
        only_first = [d for d in detections if d["text"] == "Kovács János"]
        confirm = client.post(
            "/api/redact/confirm", json={"text": text, "detections": only_first}
        )
        redacted = confirm.json()["text"]
        assert "Kovács János" not in redacted
        assert "Nagy Éva" in redacted

    def test_confirm_manual_selection(self, client):
        _unlock(client)
        client.set_pairs([])
        text = "Codename Blackbird is confidential."
        manual = [{"start": text.index("Blackbird"), "end": text.index("Blackbird") + len("Blackbird"), "entity_type": "MANUAL"}]
        confirm = client.post("/api/redact/confirm", json={"text": text, "detections": manual})
        assert confirm.status_code == 200
        redacted = confirm.json()["text"]
        assert "Blackbird" not in redacted
        assert redacted.split()[1].startswith("REDACT_")


class TestCategoriesAndTerms:
    def test_category_toggle(self, client):
        _unlock(client)
        resp = client.get("/api/categories").json()
        assert resp["toggles"]["financial_amounts"] is False
        set_resp = client.post(
            "/api/categories", json={"category": "financial_amounts", "enabled": True}
        )
        assert set_resp.status_code == 200
        assert set_resp.json()["toggles"]["financial_amounts"] is True

    def test_category_toggle_unknown_category_rejected(self, client):
        _unlock(client)
        resp = client.post("/api/categories", json={"category": "not_real", "enabled": True})
        assert resp.status_code == 400

    def test_terms_add_and_remove(self, client):
        _unlock(client)
        add = client.post("/api/terms", json={"term": "Project Falcon"})
        assert add.status_code == 200
        assert "Project Falcon" in add.json()["terms"]
        remove = client.request(
            "DELETE", "/api/terms", params={"term": "Project Falcon"}
        )
        assert remove.status_code == 200
        assert "Project Falcon" not in remove.json()["terms"]


class TestAudit:
    def test_audit_chain_valid_after_actions(self, client):
        _unlock(client)
        client.post("/api/terms", json={"term": "Project Falcon"})
        client.post("/api/categories", json={"category": "dates", "enabled": True})
        resp = client.get("/api/audit").json()
        assert resp["chain_valid"] is True
        actions = [e["action"] for e in resp["entries"]]
        assert "terms_add" in actions
        assert "set_toggle" in actions


def test_static_export_serves_extensionless_routes(tmp_path):
    site = tmp_path / "out"
    site.mkdir()
    (site / "index.html").write_text("<p>home</p>", encoding="utf-8")
    (site / "404.html").write_text("<p>missing-page</p>", encoding="utf-8")
    (site / "unlock.html").write_text("<p>unlock-page</p>", encoding="utf-8")
    (site / "unlock").mkdir()
    nested = site / "redact"
    nested.mkdir()
    (nested / "files.html").write_text("<p>files-page</p>", encoding="utf-8")
    (nested / "files").mkdir()
    mini = server.FastAPI()
    mini.mount("/", server.ExportStaticFiles(directory=site, html=True), name="web")
    with TestClient(mini) as static_client:
        unlock = static_client.get("/unlock")
        assert unlock.status_code == 200
        assert "unlock-page" in unlock.text
        files = static_client.get("/redact/files")
        assert files.status_code == 200
        assert "files-page" in files.text
        assert static_client.get("/").status_code == 200
        assert static_client.get("/missing").status_code == 404


class TestFileDownload:
    def test_docx_download_keeps_original_filename(self, client, tmp_path):
        from docx import Document

        _unlock(client)
        client.set_pairs([("Alice Example", "PERSON_00000")])
        doc = Document()
        doc.add_paragraph("Hello Alice Example")
        path = tmp_path / "memo.docx"
        doc.save(path)
        with path.open("rb") as fh:
            resp = client.post(
                "/api/redact/upload",
                files={
                    "file": (
                        "memo.docx",
                        fh,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "file"
        assert body["filename"] == "memo.docx"
        assert body["download_token"]
        downloaded = client.get(f"/api/redact/download/{body['download_token']}")
        assert downloaded.status_code == 200
        disposition = downloaded.headers["content-disposition"]
        assert 'filename="memo.docx"' in disposition
        assert b"Alice Example" not in downloaded.content
        # one-time token
        assert client.get(f"/api/redact/download/{body['download_token']}").status_code == 404


class TestWipe:
    def test_wipe_requires_confirm_true(self, client):
        _unlock(client)
        resp = client.post("/api/wipe", json={"confirm": False})
        assert resp.status_code == 422

    def test_wipe_clears_terms(self, client):
        _unlock(client)
        client.post("/api/terms", json={"term": "Project Falcon"})
        resp = client.post("/api/wipe", json={"confirm": True})
        assert resp.status_code == 200
        assert client.get("/api/terms").json()["terms"] == []
