"""Lightweight Automox HTTP client used by the MCP server."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

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
            self.api_key = api_key or os.environ["AUTOMOX_API_KEY"]
        except KeyError as exc:
            raise ValueError(
                "AUTOMOX_API_KEY environment variable is required. "
                "Set it to your Automox API token. "
                "You can generate one at: https://console.automox.com/settings/api"
            ) from exc

        try:
            self.account_uuid = account_uuid or os.environ["AUTOMOX_ACCOUNT_UUID"]
        except KeyError as exc:
            raise ValueError(
                "AUTOMOX_ACCOUNT_UUID environment variable is required. "
                "Set it to your Automox account UUID. "
                "You can find it in the Automox console URL or API responses."
            ) from exc

        self.org_id = org_id or (
            int(os.environ["AUTOMOX_ORG_ID"]) if os.environ.get("AUTOMOX_ORG_ID") else None
        )
        env_org_uuid = os.environ.get("AUTOMOX_ORG_UUID")
        self.org_uuid = (org_uuid or env_org_uuid or "").strip() or None

        logger.debug(
            f"AutomoxClient initialized with org_id={self.org_id} org_uuid={self.org_uuid}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(15.0)

        self._http = httpx.AsyncClient(
            base_url="https://console.automox.com/api",
            headers=headers,
            timeout=timeout,
        )

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
        params: Mapping[str, Any] | None = None,
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
        params: Mapping[str, Any] | None = None,
        json_data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AutomoxResponse:
        target = str(self._http.base_url)

        # Log the request for debugging (omit params to avoid leaking sensitive values)
        logger.debug("Request: %s %s%s", method, target, path)

        try:
            response = await self._http.request(
                method,
                path,
                params=params,
                json=json_data,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise AutomoxAPIError(
                f"network error calling Automox API at {target}", status_code=0
            ) from exc

        if response.status_code == 429:
            raise AutomoxRateLimitError(
                "automox rate limit exceeded", status_code=response.status_code
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
        return {"message": response.text}

    def _build_error(self, response: httpx.Response) -> AutomoxAPIError:
        payload = self._extract_error_payload(response)
        message = payload.get("message") or payload.get("title") or "automox API error"
        error_cls = AutomoxRateLimitError if response.status_code == 429 else AutomoxAPIError
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
