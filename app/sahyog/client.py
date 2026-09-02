"""SAHYOGConfig and SAHYOGClient for routing disclosure/freeze requests.

Handles authenticated HTTP submission to the SAHYOG Portal API.
Requirements: 12.1, 12.3
"""

from __future__ import annotations

from typing import Literal

import httpx
from pydantic import BaseModel


class SAHYOGConfig(BaseModel):
    """Configuration for the SAHYOG Portal connection."""

    endpoint_url: str
    auth_type: Literal["api_key", "oauth2"] = "api_key"
    api_key: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_token_url: str | None = None
    timeout_seconds: int = 30


class SAHYOGSubmissionPayload(BaseModel):
    """Payload sent to the SAHYOG Portal for a disclosure or freeze request."""

    request_type: Literal["disclosure", "freeze"]
    case_id: str
    case_title: str
    wallet_addresses: list[str]
    report_id: str
    report_hash: str
    evidence_summary: str
    submitted_by: str


class SAHYOGSubmissionResponse(BaseModel):
    """Response received from the SAHYOG Portal API."""

    status: str  # acknowledged | rejected | error
    reference_number: str | None = None
    message: str | None = None


class SAHYOGClient:
    """HTTP client for the SAHYOG Portal disclosure/freeze API."""

    def __init__(self, config: SAHYOGConfig) -> None:
        self.config = config

    async def _get_oauth2_token(self) -> str:
        """Obtain a Bearer token via OAuth2 client credentials flow."""
        if not all(
            [
                self.config.oauth2_client_id,
                self.config.oauth2_client_secret,
                self.config.oauth2_token_url,
            ]
        ):
            raise ValueError(
                "oauth2_client_id, oauth2_client_secret, and oauth2_token_url "
                "are all required for oauth2 auth_type"
            )

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(
                self.config.oauth2_token_url,  # type: ignore[arg-type]
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.config.oauth2_client_id,
                    "client_secret": self.config.oauth2_client_secret,
                },
            )
            resp.raise_for_status()
            token_data = resp.json()
            return token_data["access_token"]

    async def submit(
        self, payload: SAHYOGSubmissionPayload
    ) -> SAHYOGSubmissionResponse:
        """POST payload to SAHYOG Portal API.

        Builds the Authorization header based on ``auth_type``:
          - ``api_key``  → ``Authorization: Bearer <api_key>``
          - ``oauth2``   → Obtain a token via client-credentials, then
                           ``Authorization: Bearer <access_token>``

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses (via ``raise_for_status``).
            httpx.TimeoutException: If the portal does not respond within
                ``timeout_seconds``.
            ValueError: If required oauth2 config fields are missing.

        Requirements: 12.1, 12.3
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if self.config.auth_type == "oauth2":
            token = await self._get_oauth2_token()
            headers["Authorization"] = f"Bearer {token}"
        elif self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.post(
                self.config.endpoint_url,
                json=payload.model_dump(),
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return SAHYOGSubmissionResponse(**data)
