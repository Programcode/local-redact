"""Local FastAPI server for the standalone web UI.

Single-user, single-process, in-memory unlocked state — no session/multi-user
auth system. Binds 127.0.0.1 only. Every endpoint except /api/status and
/api/unlock requires the DB to be unlocked (app-level authentication gate,
on top of DB encryption — matches the design spec's security review gaps).

Nothing here re-implements redaction logic: every endpoint is a thin wrapper
around the existing, tested `MappingDB` / `RedactionEngine` / `batch` /
`formats` modules.
"""

from __future__ import annotations

import io
import secrets
import shutil
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from .batch import batch_redact
from .categories import CATEGORY_DEFAULTS
from .config import default_db_path
from .db import DatabaseError, MappingDB
from .engine import Detection, RedactionEngine
from .formats import redact_file
from .util import scrub_file

WEB_DIST = Path(__file__).resolve().parent.parent.parent / "web" / "out"


def create_engine(db: MappingDB) -> RedactionEngine:
    """Factory for the engine held in server state. Tests monkeypatch this
    to inject a spaCy-free stub without touching endpoint logic."""
    return RedactionEngine(db)


class ServerState:
    def __init__(self) -> None:
        self.db: MappingDB | None = None
        self.engine: RedactionEngine | None = None
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="local-redact-web-"))
        # token -> (path, download filename)
        self.downloads: dict[str, tuple[Path, str]] = {}

    def unlock(self, path: Path, passphrase: str, create: bool) -> None:
        """`create` is exactly what the caller asked for — "open existing"
        must fail closed (not silently create) if the path doesn't exist yet,
        matching the explicit open/create choice the UI presents.

        The previous session is replaced only after the new database opens,
        so a wrong passphrase leaves the current unlock in place.
        """
        db = MappingDB(
            path,
            passphrase,
            create=create,
            check_same_thread=False,
        )
        try:
            engine = create_engine(db)
        except Exception:
            db.close()
            raise
        previous = self.db
        old_downloads = list(self.downloads.values())
        self.downloads.clear()
        self.db = db
        self.engine = engine
        if previous is not None:
            previous.close()
        for old_path, _name in old_downloads:
            if old_path.exists():
                scrub_file(old_path)

    def lock(self) -> None:
        if self.db is not None:
            self.db.close()
        self.db = None
        self.engine = None
        for path, _name in self.downloads.values():
            if path.exists():
                scrub_file(path)
        self.downloads.clear()

    def cleanup(self) -> None:
        self.lock()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


state = ServerState()

app = FastAPI(title="local-redact")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_engine() -> RedactionEngine:
    if state.engine is None or state.db is None:
        raise HTTPException(status_code=401, detail="locked")
    return state.engine


# -- unlock / lock / status --------------------------------------------------


class UnlockRequest(BaseModel):
    passphrase: str
    db_path: str | None = None
    create: bool = False


@app.get("/api/status")
def status() -> dict:
    return {"unlocked": state.engine is not None}


@app.post("/api/unlock")
def unlock(req: UnlockRequest) -> dict:
    path = Path(req.db_path).expanduser() if req.db_path else default_db_path()
    try:
        state.unlock(path, req.passphrase, req.create)
    except DatabaseError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"unlocked": True}


@app.post("/api/lock")
def lock() -> dict:
    state.lock()
    return {"unlocked": False}


# -- categories ---------------------------------------------------------------


class CategoryToggle(BaseModel):
    category: str
    enabled: bool


@app.get("/api/categories")
def get_categories(engine: RedactionEngine = Depends(require_engine)) -> dict:
    return {"toggles": engine.db.get_toggles(), "defaults": CATEGORY_DEFAULTS}


@app.post("/api/categories")
def set_category(
    body: CategoryToggle, engine: RedactionEngine = Depends(require_engine)
) -> dict:
    if body.category not in CATEGORY_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"unknown category: {body.category}")
    engine.db.set_toggle(body.category, body.enabled)
    engine.db.log_action(
        "set_toggle", detail={"category": body.category, "enabled": body.enabled}
    )
    return {"toggles": engine.db.get_toggles()}


# -- custom terms ---------------------------------------------------------------


class TermRequest(BaseModel):
    term: str


@app.get("/api/terms")
def list_terms(engine: RedactionEngine = Depends(require_engine)) -> dict:
    return {"terms": engine.db.list_terms()}


@app.post("/api/terms")
def add_term(body: TermRequest, engine: RedactionEngine = Depends(require_engine)) -> dict:
    added = engine.db.add_term(body.term)
    engine.db.log_action("terms_add", detail={"terms": [body.term]})
    return {"added": added, "terms": engine.db.list_terms()}


@app.delete("/api/terms")
def remove_term(term: str, engine: RedactionEngine = Depends(require_engine)) -> dict:
    removed = engine.db.remove_term(term)
    engine.db.log_action("terms_remove", detail={"terms": [term]})
    return {"removed": removed, "terms": engine.db.list_terms()}


# -- redact: text preview / confirm -------------------------------------------


class PreviewRequest(BaseModel):
    text: str


class DetectionOut(BaseModel):
    start: int
    end: int
    entity_type: str
    text: str


@app.post("/api/redact/preview", response_model=list[DetectionOut])
def redact_preview(
    body: PreviewRequest, engine: RedactionEngine = Depends(require_engine)
) -> list[DetectionOut]:
    detections = engine.analyze(body.text)
    return [
        DetectionOut(
            start=d.start, end=d.end, entity_type=d.entity_type, text=body.text[d.start : d.end]
        )
        for d in detections
    ]


class DetectionIn(BaseModel):
    start: int
    end: int
    entity_type: str


class ConfirmRequest(BaseModel):
    text: str
    detections: list[DetectionIn]
    doc: str | None = None


@app.post("/api/redact/confirm")
def redact_confirm(
    body: ConfirmRequest, engine: RedactionEngine = Depends(require_engine)
) -> dict:
    detections = [Detection(d.entity_type, d.start, d.end, 1.0) for d in body.detections]
    result = engine.apply_redactions(body.text, detections, doc=body.doc)
    return {
        "text": result.text,
        "replacements": len(result.replacements),
        "by_type": result.counts_by_type,
    }


# -- reveal ---------------------------------------------------------------------


class RevealRequest(BaseModel):
    text: str


@app.post("/api/reveal")
def reveal(body: RevealRequest, engine: RedactionEngine = Depends(require_engine)) -> dict:
    revealed, n = engine.reveal_text(body.text)
    return {"text": revealed, "restored": n}


# -- file redact: upload / download -------------------------------------------

_TEXT_LIKE_EXTS = {".txt", ".md", ".csv"}


@app.post("/api/redact/upload")
async def redact_upload(
    file: UploadFile, engine: RedactionEngine = Depends(require_engine)
) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    data = await file.read()
    if ext in _TEXT_LIKE_EXTS:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"not valid utf-8: {exc}") from exc
        return {"mode": "text", "text": text}

    # .msg cannot be written back as Outlook binary; batch and CLI already
    # emit .eml. Match that here so the download points at the file that
    # was actually written.
    out_ext = ".eml" if ext == ".msg" else ext
    src = state.tmp_dir / f"in-{uuid.uuid4().hex}{ext}"
    dst = state.tmp_dir / f"out-{uuid.uuid4().hex}{out_ext}"
    src.write_bytes(data)
    try:
        report = redact_file(src, dst, engine, file.filename or src.name)
    finally:
        if src.exists():
            scrub_file(src)

    token = None
    download_name = _download_name(file.filename, dst.suffix)
    if report.status in ("redacted", "partial") and dst.exists():
        token = secrets.token_urlsafe(24)
        state.downloads[token] = (dst, download_name)
    else:
        if dst.exists():
            scrub_file(dst)

    return {
        "mode": "file",
        "status": report.status,
        "reason": report.reason,
        "counts": report.counts,
        "notes": report.notes,
        "download_token": token,
        "filename": download_name,
    }


def _download_name(original: str | None, output_suffix: str) -> str:
    """Basename only, and follow a handler that changed the extension
    (`.msg` is written out as `.eml`)."""
    name = Path(original or "redacted").name.replace("\r", "").replace("\n", "")
    name = name.replace('"', "") or "redacted"
    if output_suffix and Path(name).suffix.lower() != output_suffix.lower():
        name = f"{Path(name).stem}{output_suffix}"
    return name


@app.get("/api/redact/download/{token}")
def redact_download(token: str, engine: RedactionEngine = Depends(require_engine)) -> StreamingResponse:
    item = state.downloads.pop(token, None)
    if item is None:
        raise HTTPException(status_code=404, detail="download not found or already used")
    path, filename = item
    if not path.exists():
        raise HTTPException(status_code=404, detail="download not found or already used")
    # Read into memory and scrub immediately. Streaming the path itself
    # would leave the plaintext file on disk until the response finished.
    data = path.read_bytes()
    scrub_file(path)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -- batch ----------------------------------------------------------------------


class BatchRequest(BaseModel):
    input_dir: str
    output_dir: str


@app.post("/api/batch")
def batch(body: BatchRequest, engine: RedactionEngine = Depends(require_engine)) -> dict:
    input_dir = Path(body.input_dir).expanduser()
    output_dir = Path(body.output_dir).expanduser()
    if not input_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"input dir not found: {input_dir}")
    report = batch_redact(input_dir, output_dir, engine)
    return {
        "input_dir": report.input_dir,
        "output_dir": report.output_dir,
        "summary": report.counts,
        "files": report.files,
    }


# -- audit ------------------------------------------------------------------------


@app.get("/api/audit")
def audit(engine: RedactionEngine = Depends(require_engine)) -> dict:
    return {"chain_valid": engine.db.verify_audit_chain(), "entries": engine.db.audit_entries()}


# -- wipe ---------------------------------------------------------------------------


class WipeRequest(BaseModel):
    confirm: Literal[True]


@app.post("/api/wipe")
def wipe(body: WipeRequest, engine: RedactionEngine = Depends(require_engine)) -> dict:
    engine.db.wipe()
    return {"wiped": True}


class ExportStaticFiles(StaticFiles):
    """Next's static export writes `unlock.html` and an `unlock/` directory
    of flight data, while the app navigates to `/unlock`. HTML mode then
    serves `404.html` for that directory. If the extensionless path is not a
    real page, serve the sibling `.html` file instead."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            response = None
        if response is not None and response.status_code != 404:
            return response
        if path.endswith(".html") or path in ("", "."):
            if response is None:
                raise StarletteHTTPException(status_code=404)
            return response
        full_path, stat_result = self.lookup_path(f"{path}.html")
        if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
            return self.file_response(full_path, stat_result, scope)
        if response is None:
            raise StarletteHTTPException(status_code=404)
        return response


# -- static frontend (production: FastAPI serves the Next.js static export) ----

if WEB_DIST.is_dir():
    app.mount("/", ExportStaticFiles(directory=str(WEB_DIST), html=True), name="web")


def main() -> None:
    import atexit

    import uvicorn

    atexit.register(state.cleanup)
    uvicorn.run(app, host="127.0.0.1", port=8420)


if __name__ == "__main__":
    main()
