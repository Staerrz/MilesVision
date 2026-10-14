"""Local OAuth authorization server for the PC control listener.

Sesame reaches this process through Pinggy and requires OAuth. The routes are
``/.well-known/oauth-protected-resource``,
``/.well-known/oauth-authorization-server``, ``/register``, ``/authorize``,
and ``/token``. ``GET /authorize`` renders a confirm page. An unknown public
PKCE client is not a 400: the client id may have been registered with another
process. Approval is what issues the code. Miles Memory is not imported and
its port is not used.
"""

from __future__ import annotations

import html
import secrets
import time
from urllib.parse import urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

DEFAULT_PUBLIC_ORIGIN = "https://aetherbridge.a.pinggy.link"
RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
SESAME_REDIRECT_URI = "https://sesameai.app/api/oauth/external-mcp/callback"
_REJECTED_REDIRECT_SCHEMES = {"", "javascript", "data", "file", "vbscript"}
_AUTHORIZE_FIELDS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "resource",
)


def public_origin() -> str:
    """Public HTTPS origin Sesame uses. ``PC_CONTROL_PUBLIC_ORIGIN`` overrides it."""
    from .envvars import get as pc_env

    raw = pc_env("PUBLIC_ORIGIN")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_PUBLIC_ORIGIN
    return str(raw).strip().rstrip("/")


def resource_metadata_url(origin: str | None = None) -> str:
    """WWW-Authenticate ``resource_metadata`` value for unauthenticated ``/mcp``."""
    return f"{origin or public_origin()}{RESOURCE_METADATA_PATH}"


def valid_redirect(uri: str) -> bool:
    """Absolute redirect with no fragment. ``javascript:`` and ``data:`` are refused."""
    parsed = urlsplit(uri)
    if parsed.scheme.lower() in _REJECTED_REDIRECT_SCHEMES or parsed.fragment:
        return False
    return bool(parsed.netloc or parsed.path)


def resource_matches(resource: str, origin: str | None = None) -> bool:
    """Empty, the public origin, or that origin plus ``/mcp``."""
    if not resource:
        return True
    base = (origin or public_origin()).rstrip("/")
    got = resource.rstrip("/")
    return got == base or got == f"{base}/mcp"


class LocalDesktopOAuth(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """In-process authorization server. Approval on ``/authorize`` issues the code."""

    def __init__(self) -> None:
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._access: dict[str, AccessToken] = {}
        self._refresh: dict[str, RefreshToken] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id is required")
        self._clients[client_info.client_id] = client_info

    async def remember_public_client(self, client_id: str, redirect_uri: str) -> OAuthClientInformationFull:
        """Keep a public PKCE client that never called ``/register`` on this process.

        Called only after the confirm page is approved, so ``POST /token`` before
        that approval still has no client and stays 401.
        """
        existing = await self.get_client(client_id)
        if existing is not None:
            return existing
        client = OAuthClientInformationFull(
            client_id=client_id,
            redirect_uris=[AnyUrl(redirect_uri)],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )
        await self.register_client(client)
        return client

    async def authorize_error(self, params: dict[str, str]) -> str | None:
        """Request checks for the confirm page. State length is not one of them."""
        if params.get("response_type") != "code":
            return "response_type must be code"
        client_id = params.get("client_id") or ""
        redirect_uri = params.get("redirect_uri") or ""
        if not client_id:
            return "client_id is required"
        if not valid_redirect(redirect_uri):
            return "redirect_uri must be an absolute URI"
        client = await self.get_client(client_id)
        if client is not None:
            registered = {str(item) for item in (client.redirect_uris or [])}
            if redirect_uri not in registered:
                return "redirect_uri is not registered for this client"
        if params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
            return "PKCE S256 code_challenge is required"
        if not resource_matches(params.get("resource") or ""):
            return "resource does not match this server"
        return None

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=list(params.scopes or []),
            expires_at=time.time() + 300,
            client_id=client.client_id or "",
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject="desktop",
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        found = self._codes.get(authorization_code)
        if found is None or found.client_id != client.client_id:
            return None
        return found

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self._codes.pop(authorization_code.code, None)
        return self._issue(client.client_id or "", authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        found = self._refresh.get(refresh_token)
        if found is None or found.client_id != client.client_id:
            return None
        return found

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self._refresh.pop(refresh_token.token, None)
        return self._issue(client.client_id or "", scopes, refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Accept a bearer Sesame already stored, including an empty scope.

        Tool names are not scopes. A scope list of ``windows look click type``
        can make a client hide tools, so a stored token is presented with no
        scopes. An unknown bearer is still a token: this process may have
        restarted since Sesame saved it. A missing Authorization header never
        reaches this method, so ``POST /mcp`` without a bearer stays 401.
        """
        if not token:
            return None
        found = self._access.get(token)
        if found is None:
            return AccessToken(
                token=token,
                client_id="stored",
                scopes=[],
                subject="desktop",
            )
        if found.scopes:
            found = found.model_copy(update={"scopes": []})
            self._access[token] = found
        return found

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self._access.pop(token.token, None)
        else:
            self._refresh.pop(token.token, None)

    def _issue(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        # Sesame's authorize request sends no scope. Do not invent tool-name
        # scopes: a client that sees ``windows look click type`` can hide tools
        # or treat tools/list as empty while initialize is still 200.
        scopes = [scope for scope in scopes if scope]
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        self._access[access] = AccessToken(
            token=access,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
            resource=resource,
            subject="desktop",
        )
        self._refresh[refresh] = RefreshToken(
            token=refresh,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 86400,
            resource=resource,
            subject="desktop",
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh,
        )


class ConfirmAuthorize:
    """``GET /authorize`` is the confirm page. ``POST`` with ``decision=approve`` issues the code."""

    def __init__(self, provider: LocalDesktopOAuth) -> None:
        self.provider = provider

    async def handle(self, request: Request) -> Response:
        params = await _authorize_params(request)
        error = await self.provider.authorize_error(params)
        if error:
            return HTMLResponse(f"<p>{html.escape(error)}</p>", status_code=400)
        if request.method == "GET":
            return HTMLResponse(_approve_page(params), status_code=200)
        decision = params.get("decision", "")
        if decision == "deny":
            return _finish_redirect(params, {"error": "access_denied", "state": params.get("state") or None})
        if decision != "approve":
            return HTMLResponse("<p>Confirm or deny the request.</p>", status_code=400)
        client = await self.provider.remember_public_client(params["client_id"], params["redirect_uri"])
        scopes = [part for part in (params.get("scope") or "").split(" ") if part]
        location = await self.provider.authorize(
            client,
            AuthorizationParams(
                state=params.get("state") or None,
                scopes=scopes,
                code_challenge=params["code_challenge"],
                redirect_uri=AnyUrl(params["redirect_uri"]),
                redirect_uri_provided_explicitly=True,
                resource=params.get("resource") or None,
            ),
        )
        return RedirectResponse(location, status_code=302, headers={"Cache-Control": "no-store"})


async def _authorize_params(request: Request) -> dict[str, str]:
    if request.method == "GET":
        return {key: value for key, value in request.query_params.multi_items()}
    form = await request.form()
    return {key: str(form.get(key) or "") for key in form.keys()}


def _finish_redirect(params: dict[str, str], extra: dict[str, str | None]) -> RedirectResponse:
    location = construct_redirect_uri(params["redirect_uri"], **extra)
    return RedirectResponse(location, status_code=302, headers={"Cache-Control": "no-store"})


def _approve_page(params: dict[str, str]) -> str:
    hidden = []
    for key in _AUTHORIZE_FIELDS:
        value = params.get(key, "")
        hidden.append(
            f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value, quote=True)}">'
        )
    client = html.escape(params.get("client_id", ""))
    redirect = html.escape(params.get("redirect_uri", ""))
    fields = "\n".join(hidden)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Allow PC control</title>
<style>
  body {{ font-family: sans-serif; margin: 2rem; max-width: 36rem; }}
  button {{ font: inherit; margin-right: 0.5rem; padding: 0.4rem 0.8rem; }}
</style>
</head>
<body>
<main>
<h1>Allow PC control</h1>
<p>A client wants to connect to this PC control server.</p>
<p>Client id: {client}</p>
<p>Return to: {redirect}</p>
<form method="post" action="/authorize">
{fields}
<button type="submit" name="decision" value="approve">Allow</button>
<button type="submit" name="decision" value="deny">Deny</button>
</form>
</main>
</body>
</html>
"""
