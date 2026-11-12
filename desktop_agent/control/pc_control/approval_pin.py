"""Owner PIN for the ``/authorize`` approval page.

Only a salted PBKDF2-SHA256 hash of the PIN is stored, never the PIN. The
hash lives outside the repo at ``~/.milesvision/approval-pin`` unless
``PC_CONTROL_APPROVAL_PIN_PATH`` points somewhere else. When no valid hash
exists, approval fails closed: no authorization code is issued.

Set or change the PIN on the PC itself, in a terminal you type into:

    python -m desktop_agent.control.pc_control.approval_pin set

The PIN is read with ``getpass`` (not echoed, not logged, not an argument).
Forgot it? Run ``set`` again on the PC; it replaces the hash.

The same command can count (never print) the tokens in the OAuth store and,
only when you ask it to, back the store up and clear it:

    python -m desktop_agent.control.pc_control.approval_pin audit
    python -m desktop_agent.control.pc_control.approval_pin revoke-all
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path

MIN_PIN_LENGTH = 8
MAX_PIN_LENGTH = 128
PBKDF2_ITERATIONS = 600_000
FREE_FAILURES = 5
FIRST_LOCKOUT_SECONDS = 60.0
MAX_LOCKOUT_SECONDS = 3600.0
_SCHEME = "pbkdf2_sha256"


def pin_path() -> Path:
    """Where the PIN hash lives. ``PC_CONTROL_APPROVAL_PIN_PATH`` overrides it."""
    from .envvars import get as pc_env

    raw = pc_env("APPROVAL_PIN_PATH")
    if raw is not None and str(raw).strip():
        return Path(str(raw).strip())
    return Path.home() / ".milesvision" / "approval-pin"


def hash_pin(pin: str, *, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            _SCHEME,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def _parse(stored: str) -> tuple[int, bytes, bytes] | None:
    parts = stored.strip().split("$")
    if len(parts) != 4 or parts[0] != _SCHEME:
        return None
    try:
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2], validate=True)
        digest = base64.b64decode(parts[3], validate=True)
    except (ValueError, TypeError):
        return None
    if iterations < 100_000 or len(salt) < 16 or len(digest) != 32:
        return None
    return iterations, salt, digest


def verify_pin(pin: str, stored: str) -> bool:
    parsed = _parse(stored)
    if parsed is None or not pin or len(pin) > MAX_PIN_LENGTH:
        return False
    iterations, salt, expected = parsed
    got = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(got, expected)


def load_pin_hash(path: Path | None = None) -> str | None:
    """The stored hash, or None when missing or malformed (approval then fails closed)."""
    try:
        raw = (path or pin_path()).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    return raw if _parse(raw) is not None else None


def save_pin_hash(stored: str, path: Path | None = None) -> Path:
    target = path or pin_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(stored + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    os.chmod(target, 0o600)
    return target


class ApprovalGuard:
    """PIN check with a global lockout. Global on purpose: behind the tunnel,
    every caller looks like the same address, and a forged header must not
    buy extra guesses. The cost is that a stranger can lock you out for a
    while; they still cannot get in.
    """

    def __init__(self, path: Path | None = None, clock=time.monotonic) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        # One PIN check at a time, so parallel guesses cannot all slip in
        # before the lockout is recorded.
        self._verify_lock = threading.Lock()
        self._failures = 0
        self._locked_until = 0.0

    def configured(self) -> bool:
        return load_pin_hash(self._path) is not None

    def retry_after(self) -> int:
        with self._lock:
            remaining = self._locked_until - self._clock()
        return max(0, int(remaining + 0.999))

    def check(self, pin: str) -> str:
        """Returns ``ok``, ``unset``, ``locked``, or ``wrong``."""
        with self._verify_lock:
            return self._check(pin)

    def _check(self, pin: str) -> str:
        stored = load_pin_hash(self._path)
        if stored is None:
            return "unset"
        with self._lock:
            if self._clock() < self._locked_until:
                return "locked"
        good = verify_pin(pin or "", stored)
        with self._lock:
            if good:
                self._failures = 0
                self._locked_until = 0.0
                return "ok"
            self._failures += 1
            if self._failures >= FREE_FAILURES:
                extra = self._failures - FREE_FAILURES
                wait = min(MAX_LOCKOUT_SECONDS, FIRST_LOCKOUT_SECONDS * (2 ** min(extra, 16)))
                self._locked_until = self._clock() + wait
            return "wrong"


class ApprovalTickets:
    """One-use, ten-minute form tickets bound to the exact request shown.

    The page carries a ticket; the approve POST must return it with the same
    client, redirect, PKCE challenge, state, scope, and resource. A POST built
    by hand without loading the page, or with any field changed, is refused.
    """

    def __init__(self, ttl: float = 600.0, limit: int = 256, clock=time.monotonic) -> None:
        self._ttl = ttl
        self._limit = limit
        self._clock = clock
        self._lock = threading.Lock()
        self._tickets: dict[str, tuple[str, float]] = {}

    @staticmethod
    def binding(params: dict[str, str], fields: tuple[str, ...]) -> str:
        canonical = json.dumps([params.get(key, "") for key in fields], separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def issue(self, binding: str) -> str:
        ticket = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            for key in [k for k, (_b, exp) in self._tickets.items() if exp <= now]:
                del self._tickets[key]
            while len(self._tickets) >= self._limit:
                del self._tickets[next(iter(self._tickets))]
            self._tickets[ticket] = (binding, now + self._ttl)
        return ticket

    def peek(self, ticket: str, binding: str) -> bool:
        with self._lock:
            found = self._tickets.get(ticket or "")
        if found is None:
            return False
        bound, expires = found
        return expires > self._clock() and hmac.compare_digest(bound, binding)

    def consume(self, ticket: str) -> None:
        with self._lock:
            self._tickets.pop(ticket or "", None)


def audit_store(path: Path) -> dict:
    """Counts only. No token, refresh token, or code is printed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {"store": str(path), "readable": False}
    access = payload.get("access") or {}
    by_client: dict[str, int] = {}
    for value in access.values():
        client = str((value or {}).get("client_id") or "?")
        by_client[client] = by_client.get(client, 0) + 1
    return {
        "store": str(path),
        "readable": True,
        "clients": sorted((payload.get("clients") or {}).keys()),
        "access_tokens_by_client": by_client,
        "unapproved_stored_bearers": by_client.get("stored", 0),
        "refresh_tokens": len(payload.get("refresh") or {}),
        "pending_codes": len(payload.get("codes") or {}),
    }


def revoke_all(path: Path) -> Path | None:
    """Back the store up beside itself, then empty it. Every client must reconnect."""
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.backup-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)
    empty = {"clients": {}, "codes": {}, "access": {}, "refresh": {}}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(empty), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return backup


def _cli_set() -> int:
    if not sys.stdin.isatty():
        print("Run this in a terminal on the PC so the PIN is typed, not piped.")
        return 2
    first = getpass.getpass(f"New approval PIN ({MIN_PIN_LENGTH}+ characters): ")
    if len(first) < MIN_PIN_LENGTH or len(first) > MAX_PIN_LENGTH:
        print(f"Use {MIN_PIN_LENGTH} to {MAX_PIN_LENGTH} characters. Nothing was saved.")
        return 1
    second = getpass.getpass("Type it again: ")
    if not hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8")):
        print("The two entries did not match. Nothing was saved.")
        return 1
    target = save_pin_hash(hash_pin(first))
    print(f"Saved the PIN hash to {target}. The PIN itself was not saved.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else ""
    if command == "set":
        return _cli_set()
    if command in ("audit", "revoke-all"):
        from .oauth import oauth_store_path

        store = oauth_store_path()
        if command == "audit":
            print(json.dumps(audit_store(store), indent=2))
            return 0
        if input("This disconnects every client, Sesame included. Type REVOKE to go on: ") != "REVOKE":
            print("Nothing changed.")
            return 1
        backup = revoke_all(store)
        print(f"Store cleared. Backup: {backup}. Restart the server, then reconnect Sesame.")
        return 0
    print("usage: python -m desktop_agent.control.pc_control.approval_pin set|audit|revoke-all")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
