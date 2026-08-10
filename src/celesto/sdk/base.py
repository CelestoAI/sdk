"""Shared HTTP plumbing for every Celesto SDK namespace.

``_BaseConnection`` owns the API key and the ``httpx`` session; ``_BaseClient``
is the base class every namespace (computers, gatekeeper, agents, runs, ...)
extends so request building, error mapping, and timeouts live in one place.
"""

import json
import os
from collections.abc import Iterator
from typing import Any, Literal

import httpx
from typing_extensions import Self

from .exceptions import (
    CelestoAuthenticationError,
    CelestoNetworkError,
    CelestoNotFoundError,
    CelestoRateLimitError,
    CelestoServerError,
    CelestoValidationError,
)

_BASE_URL = os.environ.get("CELESTO_BASE_URL", "https://api.celesto.ai/v1")


class _BaseConnection:
    """Base class providing connection management for Celesto API.

    Handles API key resolution, HTTP session management, and resource cleanup.

    Args:
        api_key: Celesto API key. If not provided, reads from CELESTO_API_KEY
            environment variable.
        base_url: Base URL for the Celesto API. Defaults to https://api.celesto.ai/v1
            or CELESTO_BASE_URL environment variable.
        organization_id: Organization to act as, sent as the
            ``X-Current-Organization`` header. Optional: an organization-scoped
            API key already names one.

    Raises:
        CelestoAuthenticationError: If no API key is found.

    Example:
        # Explicit API key
        client = _CelestoClient(api_key="your-api-key")

        # From environment variable
        client = _CelestoClient()

        # With context manager for automatic cleanup
        with _CelestoClient() as client:
            deployments = client.deployment.list()
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        organization_id: str | None = None,
    ):
        self.base_url = base_url or _BASE_URL

        # Auto-detect API key from environment if not provided
        resolved_api_key = api_key or os.environ.get("CELESTO_API_KEY")
        if not resolved_api_key:
            raise CelestoAuthenticationError(
                "API key not found. Either pass api_key parameter or set the CELESTO_API_KEY "
                "environment variable. Get your API key at https://celesto.ai → Settings → Security."
            )

        self.api_key = resolved_api_key
        self.organization_id = organization_id
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if organization_id:
            headers["X-Current-Organization"] = organization_id
        self.session = httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
        )

    def __enter__(self) -> Self:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager and close resources."""
        self.close()

    def close(self) -> None:
        """Close the HTTP session and release resources.

        Call this method when you're done using the client, or use the
        context manager protocol instead.
        """
        self.session.close()


class _BaseClient:
    def __init__(self, base_connection: _BaseConnection):
        self._base_connection = base_connection

    @property
    def base_url(self):
        return self._base_connection.base_url

    @property
    def api_key(self):
        return self._base_connection.api_key

    @property
    def session(self):
        return self._base_connection.session

    def _request(
        self,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> Any:
        """Make an HTTP request with proper error handling.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: URL path (will be joined with base_url)
            params: Query parameters
            json_body: JSON request body
            data: Form data
            files: Files for multipart upload
            headers: Extra per-request headers
            timeout: Optional per-request timeout override

        Returns:
            Parsed JSON response

        Raises:
            CelestoAuthenticationError: For 401/403 responses
            CelestoNotFoundError: For 404 responses
            CelestoValidationError: For 400/422 responses
            CelestoRateLimitError: For 429 responses
            CelestoServerError: For 5xx responses
            CelestoNetworkError: For connection failures
        """
        url = f"{self.base_url}{path}"

        try:
            request_kwargs: dict[str, Any] = {
                "params": params,
                "json": json_body,
                "data": data,
                "files": files,
            }
            if headers is not None:
                request_kwargs["headers"] = headers
            if timeout is not None:
                request_kwargs["timeout"] = timeout

            response = self.session.request(method, url, **request_kwargs)
        except httpx.ConnectError as e:
            raise CelestoNetworkError(f"Failed to connect to Celesto API: {e}") from e
        except httpx.TimeoutException as e:
            raise CelestoNetworkError(f"Request to Celesto API timed out: {e}") from e
        except httpx.HTTPError as e:
            raise CelestoNetworkError(
                f"Network error while contacting Celesto API: {e}"
            ) from e

        return self._handle_response(response)

    def _stream_request(
        self,
        method: Literal["GET", "POST", "PUT", "DELETE"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream newline-delimited JSON or SSE-style events from the API."""
        url = f"{self.base_url}{path}"
        request_kwargs: dict[str, Any] = {"params": params, "json": json_body}
        if headers is not None:
            request_kwargs["headers"] = headers
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        try:
            with self.session.stream(method, url, **request_kwargs) as response:
                if response.status_code not in (200, 201, 204):
                    response.read()
                    self._handle_response(response)

                for line in response.iter_lines():
                    if not line:
                        continue
                    text = line.decode("utf-8") if isinstance(line, bytes) else line
                    text = text.strip()
                    if not text:
                        continue
                    if text.startswith("data:"):
                        text = text.removeprefix("data:").strip()
                    if text == "[DONE]":
                        break
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        yield {"type": "stdout", "data": text}
                        continue
                    if isinstance(parsed, dict):
                        yield parsed
                    else:
                        yield {"type": "stdout", "data": parsed}
        except httpx.ConnectError as e:
            raise CelestoNetworkError(f"Failed to connect to Celesto API: {e}") from e
        except httpx.TimeoutException as e:
            raise CelestoNetworkError(f"Request to Celesto API timed out: {e}") from e
        except httpx.HTTPError as e:
            raise CelestoNetworkError(
                f"Network error while contacting Celesto API: {e}"
            ) from e

    def _timeout_with_read(self, read_timeout: float) -> httpx.Timeout:
        return httpx.Timeout(connect=10, read=read_timeout, write=10, pool=10)

    def _handle_response(self, response: httpx.Response) -> Any:
        """Handle HTTP response and raise appropriate exceptions for errors."""
        status = response.status_code

        # Success responses
        if status in (200, 201, 204):
            if status == 204 or not response.content:
                return {}
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"raw_response": response.text}

        # Extract error message from response
        error_message = self._extract_error_message(response)

        # Authentication errors
        if status in (401, 403):
            raise CelestoAuthenticationError(
                f"Authentication failed: {error_message}",
                response=response,
            )

        # Not found
        if status == 404:
            raise CelestoNotFoundError(
                f"Resource not found: {error_message}",
                response=response,
            )

        # Validation errors
        if status in (400, 422):
            raise CelestoValidationError(
                f"Validation error: {error_message}",
                response=response,
            )

        # Rate limiting
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = (
                int(retry_after) if retry_after and retry_after.isdigit() else None
            )
            raise CelestoRateLimitError(
                f"Rate limit exceeded: {error_message}",
                response=response,
                retry_after=retry_seconds,
            )

        # Server errors
        if status >= 500:
            raise CelestoServerError(
                f"Server error ({status}): {error_message}",
                response=response,
            )

        # Unexpected status code
        raise CelestoServerError(
            f"Unexpected response ({status}): {error_message}",
            response=response,
        )

    def _extract_error_message(self, response: httpx.Response) -> str:
        """Extract error message from response body."""
        try:
            data = response.json()
            # Handle common API error formats
            if isinstance(data, dict):
                detail = data.get("detail")
                if isinstance(detail, dict):
                    message = detail.get("message") or detail.get("code")
                    if message:
                        return str(message)
                return (
                    data.get("error")
                    or data.get("message")
                    or (detail if isinstance(detail, str) else None)
                    or str(data)
                )
            return str(data)
        except (json.JSONDecodeError, ValueError):
            return response.text or f"HTTP {response.status_code}"
