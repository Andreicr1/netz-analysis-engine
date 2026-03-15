"""KYC Spider API client.

Imports only from stdlib + httpx. No sibling imports.
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


class KYCSpiderClient:
    """Thin wrapper around KYC Spider REST API v3."""

    def __init__(
        self,
        base_url: str = "https://platform.kycspider.com/api/rest/3.0.0",
        mandator: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.mandator = mandator or ""
        self.user = user or ""
        self.password = password or ""
        self._auth = (self.user, self.password) if self.user and self.password else None

    def screen_customer(
        self,
        *,
        reference: str,
        customer_type: str = "PERSON",
        first_name: str | None = None,
        last_name: str | None = None,
        organisation_name: str | None = None,
        date_of_birth: str | None = None,
        nationality: str | None = None,
        datasets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit a screening, wait for completion, and return results."""
        payload: dict[str, Any] = {
            "reference": reference,
            "customerType": customer_type,
            "mandator": self.mandator,
        }
        if customer_type == "PERSON":
            payload["firstName"] = first_name or ""
            payload["lastName"] = last_name or ""
            if date_of_birth:
                payload["dateOfBirth"] = date_of_birth
            if nationality:
                payload["nationality"] = nationality
        else:
            payload["organisationName"] = organisation_name or ""

        if datasets:
            payload["datasets"] = datasets

        url = f"{self.base_url}/checks"
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    url,
                    json=payload,
                    auth=self._auth,
                )
                resp.raise_for_status()
                data = resp.json()

            check_id = data.get("checkId") or data.get("id")
            check_results = data.get("checkResults", [])

            total_hits = sum(
                cr.get("hits", 0) or len(cr.get("matchIds", []))
                for cr in check_results
            )

            return {
                "check_id": check_id,
                "state": data.get("state", "COMPLETED"),
                "total_hits": total_hits,
                "check_results": check_results,
                "raw": data,
            }

        except Exception as exc:
            logger.error("kyc_spider_screen_failed", error=str(exc))
            raise
