"""The FTPS password: from ``$CSVFTPS_PASSWORD`` or the system keyring, never the settings file.

On Windows the keyring is the Credential Manager, on macOS the Keychain and
on Linux the Secret Service (GNOME Keyring, KWallet).
"""

from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from csvftps.config import Server

PASSWORD_ENV = "CSVFTPS_PASSWORD"
SERVICE = "csvftps"


class CredentialsError(RuntimeError):
    pass


def account(server: Server) -> str:
    """Keyring entry name: one password per user and host."""
    return f"{server.user}@{server.host}"


def get_password(server: Server) -> str | None:
    """Return the password, or None if none is saved anywhere."""
    if PASSWORD_ENV in os.environ:
        return os.environ[PASSWORD_ENV]
    try:
        return keyring.get_password(SERVICE, account(server))
    except KeyringError:
        return None  # no keyring on this system, e.g. a headless Linux box


def set_password(server: Server, password: str) -> None:
    _require_target(server)
    try:
        keyring.set_password(SERVICE, account(server), password)
    except KeyringError as exc:
        raise CredentialsError(
            f"could not save the password in the system keyring ({exc}); "
            f"set the {PASSWORD_ENV} environment variable instead"
        ) from exc


def delete_password(server: Server) -> bool:
    """Forget the saved password; return False if there was none."""
    try:
        keyring.delete_password(SERVICE, account(server))
    except PasswordDeleteError:
        return False
    except KeyringError as exc:
        raise CredentialsError(f"could not reach the system keyring: {exc}") from exc
    return True


def _require_target(server: Server) -> None:
    if not server.host or not server.user:
        raise CredentialsError("set the server host and user first")
