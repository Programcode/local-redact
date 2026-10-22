"""Batch folder walker: mirrors supported files into an output tree and
emits a summary report. Fail-closed: unsupported/corrupt files are reported
and never copied un-redacted."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .formats import redact_file


@dataclass
class BatchReport:
    input_dir: str
    output_dir: str
    files: list[dict] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.files:
            out[f["status"]] = out.get(f["status"], 0) + 1
        return out

    def to_json(self) -> str:
        return json.dumps(
            {
                "input_dir": self.input_dir,
                "output_dir": self.output_dir,
                "summary": self.counts,
                "files": self.files,
            },
            indent=2,
            ensure_ascii=False,
        )


def batch_redact(
    input_dir: Path,
    output_dir: Path,
    engine,
    *,
    write_report: bool = True,
) -> BatchReport:
    """Walk input_dir recursively; redact every supported file into a mirrored
    path under output_dir. .msg outputs are written as .eml alongside notes.
    """
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input dir not found: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    report = BatchReport(str(input_dir), str(output_dir))
    for src in sorted(input_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(input_dir)
        # map .msg -> .eml on disk so consumers open a real message format
        if src.suffix.lower() == ".msg":
            dst = output_dir / rel.with_suffix(".eml")
            rel_doc = str(rel.with_suffix(".eml"))
        else:
            dst = output_dir / rel
            rel_doc = str(rel)
        result = redact_file(src, dst, engine, rel_doc)
        report.files.append(
            {
                "source": str(rel),
                "output": str(dst.relative_to(output_dir))
                if result.status in ("redacted", "partial") and dst.exists()
                else None,
                "status": result.status,
                "reason": result.reason,
                "counts": result.counts,
                "notes": result.notes,
            }
        )

    if write_report:
        (output_dir / "redaction_report.json").write_text(
            report.to_json(), encoding="utf-8"
        )
    engine.db.log_action(
        "batch_redact",
        detail={
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "summary": report.counts,
            "file_count": len(report.files),
        },
    )
    return report
