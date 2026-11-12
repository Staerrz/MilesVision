"""Approval PIN on /authorize, and no more unknown bearers on /mcp."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from desktop_agent.control.pc_control import approval_pin
from desktop_agent.control.pc_control.approval_pin import (
    FREE_FAILURES,
    ApprovalGuard,
    ApprovalTickets,
    hash_pin,
    save_pin_hash,
    verify_pin,
)
from desktop_agent.control.pc_control.oauth import ConfirmAuthorize, LocalDesktopOAuth

PIN = "correct-horse-42"
REDIRECT = "https://sesameai.app/api/oauth/external-mcp/callback"
RESOURCE = "https://vision.miles-n-erica.win/mcp"
# Fast hash for tests only; production uses PBKDF2_ITERATIONS.
FAST = 100_000


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _params(challenge: str, **over: str) -> dict[str, str]:
    base = {
        "response_type": "code",
        "client_id": "fGTSoieUnojA4VEH36u1nRV5mBtM57E4",
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
        "state": "v1.gAAAA" + "A" * 2048,
    }
    base.update(over)
    return base


@pytest.fixture()
def env(tmp_path: Path):
    pin_file = tmp_path / "approval-pin"
    clock = Clock()
    provider = LocalDesktopOAuth(tmp_path / "pc-oauth.json")
    guard = ApprovalGuard(pin_file, clock=clock)
    tickets = ApprovalTickets(clock=clock)
    confirm = ConfirmAuthorize(provider, guard, tickets)
    app = Starlette(routes=[Route("/authorize", confirm.handle, methods=["GET", "POST"])])
    client = TestClient(app, follow_redirects=False)
    return {
        "pin_file": pin_file,
        "clock": clock,
        "provider": provider,
        "client": client,
        "store": tmp_path / "pc-oauth.json",
    }


def _set_pin(env) -> None:
    save_pin_hash(hash_pin(PIN, iterations=FAST), env["pin_file"])


def _ticket(env, params: dict[str, str]) -> str:
    page = env["client"].get("/authorize", params=params)
    assert page.status_code == 200, page.text[:300]
    found = re.search(r'name="ticket" value="([^"]+)"', page.text)
    assert found
    return found.group(1)


def _approve(env, params: dict[str, str], **extra: str):
    return env["client"].post("/authorize", data={**params, "decision": "approve", **extra})


# --- unset config fails closed -------------------------------------------

def test_unset_pin_shows_setup_page_and_issues_nothing(env) -> None:
    _v, challenge = _pkce()
    params = _params(challenge)
    page = env["client"].get("/authorize", params=params)
    assert page.status_code == 503
    assert "not set up" in page.text
    assert 'name="ticket"' not in page.text
    # No page means no ticket, so a hand-built POST is refused.
    posted = _approve(env, params, pin="anything-123")
    assert posted.status_code == 403
    assert env["provider"]._codes == {}


def test_unset_pin_with_valid_ticket_still_refuses(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    env["pin_file"].unlink()
    posted = _approve(env, params, ticket=ticket, pin=PIN)
    assert posted.status_code == 503
    assert env["provider"]._codes == {}


def test_malformed_hash_counts_as_unset(env) -> None:
    env["pin_file"].write_text("1234\n", encoding="utf-8")
    _v, challenge = _pkce()
    assert env["client"].get("/authorize", params=_params(challenge)).status_code == 503


# --- missing / wrong / direct POST ----------------------------------------

def test_missing_pin_is_refused(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    posted = _approve(env, params, ticket=ticket)
    assert posted.status_code == 401
    assert "Wrong PIN" in posted.text
    assert env["provider"]._codes == {}


def test_wrong_pin_is_refused(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    posted = _approve(env, params, ticket=ticket, pin="correct-horse-43")
    assert posted.status_code == 401
    assert env["provider"]._codes == {}


def test_direct_post_without_page_is_refused_even_with_right_pin(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    posted = _approve(env, _params(challenge), pin=PIN)
    assert posted.status_code == 403
    forged = _approve(env, _params(challenge), pin=PIN, ticket="made-up")
    assert forged.status_code == 403
    assert env["provider"]._codes == {}


@pytest.mark.parametrize("field", ["redirect_uri", "code_challenge", "client_id", "state", "resource"])
def test_ticket_is_bound_to_the_request_shown(env, field: str) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    changed = {
        "redirect_uri": "https://attacker.example/cb",
        "code_challenge": _pkce()[1],
        "client_id": "other-client",
        "state": "other",
        "resource": "https://vision.miles-n-erica.win",
    }[field]
    posted = _approve(env, {**params, field: changed}, ticket=ticket, pin=PIN)
    assert posted.status_code == 403
    assert env["provider"]._codes == {}


def test_expired_ticket_is_refused(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    env["clock"].now += 601
    assert _approve(env, params, ticket=ticket, pin=PIN).status_code == 403


# --- correct PIN, full OAuth round trip -----------------------------------

def test_correct_pin_issues_code_and_token_round_trip(env) -> None:
    _set_pin(env)
    verifier, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    posted = _approve(env, params, ticket=ticket, pin=PIN)
    assert posted.status_code == 302
    query = parse_qs(urlparse(posted.headers["location"]).query)
    assert posted.headers["location"].startswith(REDIRECT)
    assert query["state"][0] == params["state"]
    code = query["code"][0]

    provider = env["provider"]

    async def exchange():
        client = await provider.get_client(params["client_id"])
        loaded = await provider.load_authorization_code(client, code)
        assert loaded is not None and loaded.code_challenge == challenge
        token = await provider.exchange_authorization_code(client, loaded)
        return token

    token = asyncio.run(exchange())
    assert asyncio.run(provider.load_access_token(token.access_token)) is not None
    # Survives a restart: a new provider on the same store still knows it.
    again = LocalDesktopOAuth(env["store"])
    assert asyncio.run(again.load_access_token(token.access_token)) is not None
    # The ticket was one-use.
    assert _approve(env, params, ticket=ticket, pin=PIN).status_code == 403


def test_deny_needs_no_pin(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge)
    denied = env["client"].post("/authorize", data={**params, "decision": "deny"})
    assert denied.status_code == 302
    assert "error=access_denied" in denied.headers["location"]
    assert env["provider"]._codes == {}


# --- repeated guesses ------------------------------------------------------

def test_lockout_after_repeated_wrong_pins_blocks_even_the_right_one(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    for _ in range(FREE_FAILURES):
        assert _approve(env, params, ticket=ticket, pin="nope-nope-1").status_code == 401
    locked = _approve(env, params, ticket=ticket, pin=PIN)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) == 60
    assert env["provider"]._codes == {}
    env["clock"].now += 61
    # One more wrong guess doubles the wait.
    assert _approve(env, params, ticket=ticket, pin="nope-nope-2").status_code == 401
    assert _approve(env, params, ticket=ticket, pin=PIN).status_code == 429
    assert int(_approve(env, params, ticket=ticket, pin=PIN).headers["retry-after"]) == 120
    env["clock"].now += 121
    assert _approve(env, params, ticket=ticket, pin=PIN).status_code == 302


def test_lockout_is_capped_at_an_hour(tmp_path: Path) -> None:
    clock = Clock()
    pin_file = tmp_path / "p"
    save_pin_hash(hash_pin(PIN, iterations=FAST), pin_file)
    guard = ApprovalGuard(pin_file, clock=clock)
    for _ in range(40):
        guard.check("wrong-wrong")
        clock.now += 10_000
    guard.check("wrong-wrong")
    assert guard.retry_after() == 3600


# --- bearer tokens ---------------------------------------------------------

def test_unknown_bearer_is_refused_and_not_stored(env) -> None:
    provider = env["provider"]
    assert asyncio.run(provider.load_access_token("sesame-stored-empty-scope")) is None
    assert asyncio.run(provider.load_access_token("")) is None
    assert "sesame-stored-empty-scope" not in provider._access
    if env["store"].exists():
        assert "sesame-stored-empty-scope" not in env["store"].read_text(encoding="utf-8")


def test_previously_stored_bearer_still_works_until_revoked(tmp_path: Path) -> None:
    """Old ``client_id=stored`` entries keep working; the audit counts them."""
    store = tmp_path / "pc-oauth.json"
    store.write_text(
        json.dumps(
            {
                "clients": {},
                "codes": {},
                "access": {"old": {"token": "old", "client_id": "stored", "scopes": [], "subject": "desktop"}},
                "refresh": {},
            }
        ),
        encoding="utf-8",
    )
    provider = LocalDesktopOAuth(store)
    assert asyncio.run(provider.load_access_token("old")) is not None
    report = approval_pin.audit_store(store)
    assert report["unapproved_stored_bearers"] == 1
    assert "old" not in json.dumps(report["access_tokens_by_client"])  # counts only
    backup = approval_pin.revoke_all(store)
    assert backup is not None and backup.exists()
    assert asyncio.run(LocalDesktopOAuth(store).load_access_token("old")) is None


# --- unchanged OAuth checks still apply ----------------------------------

@pytest.mark.parametrize(
    "over, needle",
    [
        ({"code_challenge_method": "plain"}, "PKCE"),
        ({"response_type": "token"}, "response_type"),
        ({"redirect_uri": "javascript:alert(1)"}, "redirect_uri"),
        ({"resource": "https://evil.example/mcp"}, "resource"),
    ],
)
def test_existing_oauth_validation_still_runs_first(env, over: dict, needle: str) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    params = _params(challenge, **over)
    assert env["client"].get("/authorize", params=params).status_code == 400
    posted = _approve(env, params, pin=PIN)
    assert posted.status_code == 400 and needle in posted.text


def test_registered_client_redirect_still_enforced(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    asyncio.run(env["provider"].remember_public_client("fGTSoieUnojA4VEH36u1nRV5mBtM57E4", REDIRECT))
    params = _params(challenge, redirect_uri="https://attacker.example/cb")
    assert env["client"].get("/authorize", params=params).status_code == 400


# --- secrets stay secret ---------------------------------------------------

def test_pin_never_echoed_logged_or_stored(env, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    _set_pin(env)
    assert PIN not in env["pin_file"].read_text(encoding="utf-8")
    _v, challenge = _pkce()
    params = _params(challenge)
    ticket = _ticket(env, params)
    wrong = _approve(env, params, ticket=ticket, pin="wrong-but-secret-99")
    assert "wrong-but-secret-99" not in wrong.text
    ok = _approve(env, params, ticket=ticket, pin=PIN)
    assert PIN not in ok.headers["location"]
    assert PIN not in caplog.text and "wrong-but-secret-99" not in caplog.text
    store = env["store"].read_text(encoding="utf-8")
    assert PIN not in store


def test_page_cannot_be_framed_or_cached(env) -> None:
    _set_pin(env)
    _v, challenge = _pkce()
    page = env["client"].get("/authorize", params=_params(challenge))
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "form-action" not in page.headers["content-security-policy"]  # would block the Sesame redirect
    assert page.headers["cache-control"] == "no-store"
    assert 'type="password" name="pin"' in page.text


def test_hash_helpers() -> None:
    stored = hash_pin(PIN, iterations=FAST)
    assert stored.startswith("pbkdf2_sha256$100000$")
    assert verify_pin(PIN, stored)
    assert not verify_pin(PIN + "x", stored)
    assert not verify_pin("", stored)
    assert not verify_pin(PIN, "pbkdf2_sha256$10$AAAA$BBBB")
    assert approval_pin.PBKDF2_ITERATIONS >= 600_000
    assert approval_pin.MIN_PIN_LENGTH >= 8


def test_cli_set_refuses_piped_input(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PC_CONTROL_APPROVAL_PIN_PATH", str(tmp_path / "p"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert approval_pin.main(["set"]) == 2
    assert not (tmp_path / "p").exists()
