"""Small shared helpers: text normalization, hashing, secure file scrubbing."""

from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path


def normalize(value: str) -> str:
    """Canonical key for a real value / custom term.

    Casefold + NFKC + collapsed whitespace so trivially-different spellings of
    the same entity share one stable placeholder.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scrub_file(path: Path) -> None:
    """Overwrite a file with random bytes before deleting (best effort).

    Used for plaintext intermediates (e.g. extracted nested .msg payloads) so
    they don't linger on disk. Not a guarantee against wear-leveling/CoW
    filesystems — the primary defence is that we process in memory and only
    fall back to temp files when a library demands a real path.
    """
    try:
        size = path.stat().st_size
        with open(path, "r+b", buffering=0) as fh:
            remaining = size
            while remaining > 0:
                chunk = min(remaining, 1 << 20)
                fh.write(os.urandom(chunk))
                remaining -= chunk
            os.fsync(fh.fileno())
    except OSError:
        pass
    finally:
        try:
            path.unlink()
        except OSError:
            pass
