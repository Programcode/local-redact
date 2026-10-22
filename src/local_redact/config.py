"""Paths and environment configuration."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "local-redact"

#: Environment variable holding the DB passphrase (alternative to prompt/keychain).
PASSPHRASE_ENV = "LOCAL_REDACT_PASSPHRASE"

#: keyring service name for the OS-keychain-held DB passphrase.
KEYRING_SERVICE = "local-redact"
KEYRING_USERNAME = "db-passphrase"


def default_db_path() -> Path:
    override = os.environ.get("LOCAL_REDACT_DB")
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir(APP_NAME)) / "mapping.db"
