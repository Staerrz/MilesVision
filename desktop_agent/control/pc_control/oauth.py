"""Local OAuth authorization server for the PC control listener.

Sesame reaches this process through Pinggy and requires OAuth. The routes are
the SDK's ``/.well-known/oauth-protected-resource``,
``/.well-known/oauth-authorization-server``, ``/register``, ``/authorize``,
and ``/token``. Miles Memory is not imported and its port is not used.
"""

from __future__ import annotations

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

DEFAULT_PUBLIC_ORIGIN = "https://aetherbridge.a.pinggy.link"
RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"


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


class LocalDesktopOAuth(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """In-process authorization server. ``/authorize`` issues a code immediately."""

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
        return self._access.get(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self._access.pop(token.token, None)
        else:
            self._refresh.pop(token.token, None)

    def _issue(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
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
            scope=" ".join(scopes),
            refresh_token=refresh,
        )
