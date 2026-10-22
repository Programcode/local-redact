"""CLI for the Phase 1 redaction core.

Commands:
  init, categories, terms, redact-text, redact, reveal, batch, audit, wipe
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from . import __version__
from .batch import batch_redact
from .categories import CATEGORY_DEFAULTS
from .config import KEYRING_SERVICE, KEYRING_USERNAME, PASSPHRASE_ENV, default_db_path
from .db import DatabaseError, MappingDB
from .engine import RedactionEngine
from .formats import redact_file


def _resolve_passphrase(prompt: str = "DB passphrase: ") -> str:
    env = os.environ.get(PASSPHRASE_ENV)
    if env:
        return env
    try:
        import keyring

        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if stored:
            return stored
    except Exception:
        pass
    if not sys.stdin.isatty():
        raise SystemExit(
            f"No passphrase: set {PASSPHRASE_ENV} or run in a TTY for a prompt."
        )
    return getpass.getpass(prompt)


def _open_db(args, *, create: bool = False) -> MappingDB:
    path = Path(args.db) if getattr(args, "db", None) else default_db_path()
    passphrase = _resolve_passphrase("Create DB passphrase: " if create else "DB passphrase: ")
    try:
        db = MappingDB(path, passphrase, create=create or not path.exists())
    except DatabaseError as exc:
        raise SystemExit(str(exc)) from exc
    if create or getattr(args, "store_keychain", False):
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, passphrase)
            print(f"Passphrase stored in OS keychain ({KEYRING_SERVICE}).", file=sys.stderr)
        except Exception as exc:
            print(f"Warning: could not store passphrase in keychain: {exc}", file=sys.stderr)
    return db


def cmd_init(args) -> int:
    path = Path(args.db) if args.db else default_db_path()
    if path.exists() and not args.force:
        print(f"DB already exists at {path}. Use --force to re-init (wipes).")
        return 1
    if path.exists() and args.force:
        path.unlink()
    db = _open_db(args, create=True)
    db.log_action("init", detail={"db_path": str(path)})
    print(f"Initialized encrypted mapping DB at {path}")
    print("Default category toggles:")
    for k, v in db.get_toggles().items():
        print(f"  {k}: {'ON' if v else 'OFF'}")
    db.close()
    return 0


def cmd_categories(args) -> int:
    db = _open_db(args)
    if args.set:
        cat, state = args.set
        if cat not in CATEGORY_DEFAULTS:
            print(f"Unknown category: {cat}")
            print("Valid:", ", ".join(CATEGORY_DEFAULTS))
            db.close()
            return 1
        normalized = state.lower()
        if normalized in ("on", "true", "1", "yes"):
            enabled = True
        elif normalized in ("off", "false", "0", "no"):
            enabled = False
        else:
            print(f"Expected on or off, got: {state}")
            db.close()
            return 1
        db.set_toggle(cat, enabled)
        db.log_action("set_toggle", detail={"category": cat, "enabled": enabled})
        print(f"{cat} = {'ON' if enabled else 'OFF'}")
    else:
        for k, v in db.get_toggles().items():
            default = CATEGORY_DEFAULTS[k]
            flag = "ON " if v else "OFF"
            dflag = "on" if default else "off"
            print(f"  {flag}  {k:20s} (default {dflag})")
    db.close()
    return 0


def cmd_terms(args) -> int:
    db = _open_db(args)
    if args.add:
        for term in args.add:
            added = db.add_term(term)
            print(("+" if added else "=") + f" {term}")
        db.log_action("terms_add", detail={"terms": args.add})
    elif args.remove:
        for term in args.remove:
            removed = db.remove_term(term)
            print(("-" if removed else "?") + f" {term}")
        db.log_action("terms_remove", detail={"terms": args.remove})
    else:
        terms = db.list_terms()
        if not terms:
            print("(no custom terms)")
        for t in terms:
            print(t)
    db.close()
    return 0


def cmd_redact_text(args) -> int:
    db = _open_db(args)
    engine = RedactionEngine(db)
    text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    result = engine.redact_text(text, doc=args.input or "<stdin>")
    if args.output:
        Path(args.output).write_text(result.text, encoding="utf-8")
    else:
        sys.stdout.write(result.text)
        if not result.text.endswith("\n"):
            sys.stdout.write("\n")
    print(
        f"# replacements={len(result.replacements)} by_type={result.counts_by_type}",
        file=sys.stderr,
    )
    db.close()
    return 0


def cmd_redact(args) -> int:
    db = _open_db(args)
    engine = RedactionEngine(db)
    src = Path(args.input)
    dst = Path(args.output) if args.output else src.with_name(src.stem + ".redacted" + src.suffix)
    if src.suffix.lower() == ".msg" and dst.suffix.lower() == ".msg":
        dst = dst.with_suffix(".eml")
    report = redact_file(src, dst, engine, str(src.name))
    print(json.dumps({
        "status": report.status,
        "output": str(dst) if report.status in ("redacted", "partial") else None,
        "reason": report.reason,
        "counts": report.counts,
        "notes": report.notes,
    }, indent=2, ensure_ascii=False))
    db.close()
    return 0 if report.status in ("redacted", "partial") else 1


def cmd_reveal(args) -> int:
    db = _open_db(args)
    engine = RedactionEngine(db)
    text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    revealed, n = engine.reveal_text(text)
    if args.output:
        Path(args.output).write_text(revealed, encoding="utf-8")
    else:
        sys.stdout.write(revealed)
        if not revealed.endswith("\n"):
            sys.stdout.write("\n")
    print(f"# restored={n}", file=sys.stderr)
    db.close()
    return 0


def cmd_batch(args) -> int:
    db = _open_db(args)
    engine = RedactionEngine(db)
    report = batch_redact(Path(args.input), Path(args.output), engine)
    print(report.to_json())
    db.close()
    # non-zero if any failed (partial is still ok)
    return 1 if report.counts.get("failed") else 0


def cmd_audit(args) -> int:
    db = _open_db(args)
    ok = db.verify_audit_chain()
    print(f"chain_valid={ok}")
    for e in db.audit_entries():
        if args.verbose:
            print(json.dumps(e, ensure_ascii=False))
        else:
            print(f"{e['id']:4d}  {e['ts']}  {e['action']:16s}  {e['doc'] or ''}")
    db.close()
    return 0 if ok else 2


def cmd_wipe(args) -> int:
    db = _open_db(args)
    if not args.yes:
        print("Refusing to wipe without --yes.")
        db.close()
        return 1
    db.wipe()
    print("Wiped entities, terms, settings, counters. Audit restarted with wipe entry.")
    db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="local-redact",
        description="Local-first bilingual document redaction engine (Phase 1 core).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--db",
        help="Path to encrypted mapping DB (default: platform user data dir).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="Create encrypted mapping DB")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--store-keychain", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("categories", help="Show or set category toggles")
    sp.add_argument(
        "--set",
        nargs=2,
        metavar=("CATEGORY", "on|off"),
        help="Set a category toggle",
    )
    sp.set_defaults(func=cmd_categories)

    sp = sub.add_parser("terms", help="List/add/remove custom redaction terms")
    sp.add_argument("--add", nargs="+", metavar="TERM")
    sp.add_argument("--remove", nargs="+", metavar="TERM")
    sp.set_defaults(func=cmd_terms)

    sp = sub.add_parser("redact-text", help="Redact plain text (file or stdin)")
    sp.add_argument("-i", "--input", help="Input file (default stdin)")
    sp.add_argument("-o", "--output", help="Output file (default stdout)")
    sp.set_defaults(func=cmd_redact_text)

    sp = sub.add_parser("redact", help="Redact a single file of any supported format")
    sp.add_argument("input")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_redact)

    sp = sub.add_parser("reveal", help="Restore placeholders using the mapping DB")
    sp.add_argument("-i", "--input")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_reveal)

    sp = sub.add_parser("batch", help="Redact a whole folder, mirror to output")
    sp.add_argument("input", help="Input directory")
    sp.add_argument("output", help="Output directory")
    sp.set_defaults(func=cmd_batch)

    sp = sub.add_parser("audit", help="Show/verify hash-chained audit log")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_audit)

    sp = sub.add_parser("wipe", help="Wipe mappings/terms/settings (manual only)")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_wipe)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
