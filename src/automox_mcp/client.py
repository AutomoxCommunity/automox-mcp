"""Lightweight Automox HTTP client used by the MCP server."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from .middleware import get_correlation_id

logger = logging.getLogger(__name__)

# Automox API responses are always objects or arrays at the top level
JsonDict = Mapping[str, Any]
JsonList = Sequence[Any]
AutomoxResponse = JsonDict | JsonList


def _resolve_user_agent() -> str:
    """Return a descriptive User-Agent string for Automox API requests."""

    try:
        package_version = importlib.metadata.version("automox-mcp")
    except importlib.metadata.PackageNotFoundError:
        package_version = os.environ.get("AUTOMOX_MCP_VERSION", "0.0.0+dev")
    return f"automox-mcp/{package_version}"


USER_AGENT = _resolve_user_agent()


class AutomoxAPIError(RuntimeError):
    """Raised for non-success Automox responses."""

    def __init__(self, message: str, status_code: int, payload: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class AutomoxRateLimitError(AutomoxAPIError):
    """Raised when Automox signals rate limiting."""


class AutomoxClient:
    """Small HTTP client for the various Automox APIs."""

    __slots__ = (
        "_api_key",
        "account_uuid",
        "org_id",
        "org_uuid",
        "_http",
        "_base_url_str",
    )

    def __repr__(self) -> str:
        return f"AutomoxClient(org_id={self.org_id!r})"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        account_uuid: str | None = None,
        org_id: int | None = None,
        org_uuid: str | None = None,
    ) -> None:
        # Read from environment if not provided
        try:
            self._api_key = (api_key or os.environ["AUTOMOX_API_KEY"]).strip()
        except KeyError as exc:
            raise ValueError(
                "AUTOMOX_API_KEY environment variable is required. "
                "Set it to your Automox API token. "
                "You can generate one at: https://console.automox.com/settings/api"
            ) from exc

        try:
            raw_account_uuid = (account_uuid or os.environ["AUTOMOX_ACCOUNT_UUID"]).strip()
        except KeyError as exc:
            raise ValueError(
                "AUTOMOX_ACCOUNT_UUID environment variable is required. "
                "Set it to your Automox account UUID. "
                "You can find it in the Automox console URL or API responses."
            ) from exc
        # V-157: Validate format before using in URL paths to prevent path injection.
        # Allow hex digits, hyphens, and lowercase letters (Automox UUIDs).
        # Block path separators, dots, and control characters.
        if not re.fullmatch(r"[a-zA-Z0-9\-]+", raw_account_uuid):
            raise ValueError(
                f"AUTOMOX_ACCOUNT_UUID contains invalid characters: {raw_account_uuid!r}. "
                "Expected alphanumeric characters and hyphens only."
            )
        self.account_uuid = raw_account_uuid

        self.org_id: int | None
        if org_id is not None:
            self.org_id = org_id
        else:
            raw_org = os.environ.get("AUTOMOX_ORG_ID", "").strip()
            self.org_id = int(raw_org) if raw_org else None
        env_org_uuid = os.environ.get("AUTOMOX_ORG_UUID")
        self.org_uuid = (org_uuid or env_org_uuid or "").strip() or None

        logger.debug(
            "AutomoxClient initialized with org_id=%s org_uuid=%s",
            self.org_id,
            self.org_uuid,
        )

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(15.0)

        self._http = httpx.AsyncClient(
            base_url="https://console.automox.com/api",
            headers=headers,
            timeout=timeout,
            auth=self._bearer_auth,
        )
        self._base_url_str = str(self._http.base_url)

    def _bearer_auth(self, request: httpx.Request) -> httpx.Request:
        """Inject the Bearer token per-request to avoid storing it in shared headers."""
        request.headers["Authorization"] = f"Bearer {self._api_key}"
        return request

    async def __aenter__(self) -> AutomoxClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AutomoxResponse:
        return await self._request(
            "GET",
            path,
            params=params,
            headers=headers,
        )

    async def post(
        self,
        path: str,
        *,
        json_data: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AutomoxResponse:
        return await self._request(
            "POST",
            path,
            params=params,
            json_data=json_data,
            headers=headers,
        )

    async def put(
        self,
        path: str,
        *,
        json_data: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AutomoxResponse:
        return await self._request(
            "PUT",
            path,
            params=params,
            json_data=json_data,
            headers=headers,
        )

    async def delete(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AutomoxResponse:
        return await self._request(
            "DELETE",
            path,
            params=params,
            headers=headers,
        )

    async def patch(
        self,
        path: str,
        *,
        json_data: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AutomoxResponse:
        return await self._request(
            "PATCH",
            path,
            params=params,
            json_data=json_data,
            headers=headers,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
        json_data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AutomoxResponse:
        merged_headers: dict[str, str] = dict(headers) if headers else {}
        correlation_id = get_correlation_id()
        if correlation_id:
            merged_headers["X-Correlation-ID"] = correlation_id

        logger.debug(
            "Request: %s %s%s correlation_id=%s",
            method,
            self._base_url_str,
            path,
            correlation_id,
        )

        try:
            response = await self._http.request(
                method,
                path,
                params=params,  # type: ignore[arg-type]
                json=json_data,
                headers=merged_headers or None,
            )
        except httpx.RequestError as exc:
            raise AutomoxAPIError(
                f"network error calling Automox API at {self._base_url_str}", status_code=0
            ) from exc

        if response.status_code == 429:
            payload = self._extract_error_payload(response)
            raise AutomoxRateLimitError(
                "automox rate limit exceeded",
                status_code=response.status_code,
                payload=payload,
            )

        if response.status_code >= 400:
            raise self._build_error(response)

        if response.status_code == 204 or not response.content:
            return {}

        try:
            data: AutomoxResponse = response.json()
            return data
        except json.JSONDecodeError as exc:
            raise AutomoxAPIError(
                "invalid JSON response from Automox", response.status_code
            ) from exc

    @staticmethod
    def _extract_error_payload(response: httpx.Response) -> Mapping[str, Any]:
        try:
            data = response.json()
            if isinstance(data, Mapping):
                return data
        except json.JSONDecodeError:
            pass
        # Truncate raw text to avoid leaking verbose upstream error pages.
        raw = response.text[:500] if response.text else ""
        return {"message": raw}

    def _build_error(self, response: httpx.Response) -> AutomoxAPIError:
        payload = self._extract_error_payload(response)
        message = payload.get("message") or payload.get("title") or "automox API error"
        error_cls = AutomoxAPIError
        logger.warning(
            "automox request failed",
            extra={
                "status": response.status_code,
                "code": payload.get("code"),
                "error_message": message,
            },
        )
        return error_cls(message, status_code=response.status_code, payload=payload)


__all__ = ["AutomoxClient", "AutomoxAPIError", "AutomoxRateLimitError"]
