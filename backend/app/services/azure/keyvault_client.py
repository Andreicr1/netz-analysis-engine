# DEPRECATED 2026-03-18: Key Vault replaced by platform env vars (Railway secrets, Milestone 2).
# Retained for rollback capability only.
# All azure imports are lazy to avoid breaking CI when azure SDK is not installed.
from __future__ import annotations

import warnings
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class KeyVaultHealth:
    ok: bool
    detail: str | None = None


def get_secret_client():
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    warnings.warn(
        "keyvault_client.get_secret_client is deprecated — use environment variables (Railway secrets)",
        DeprecationWarning,
        stacklevel=2,
    )
    if not settings.KEYVAULT_URL:
        raise ValueError("KEYVAULT_URL not configured")
    cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return SecretClient(vault_url=settings.KEYVAULT_URL, credential=cred)


def health_check_keyvault() -> KeyVaultHealth:
    warnings.warn(
        "keyvault_client.health_check_keyvault is deprecated — use environment variables",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        client = get_secret_client()
        # Do not leak values; just confirm we can list/get.
        it = client.list_properties_of_secrets()
        first = next(iter(it), None)
        if first is None:
            return KeyVaultHealth(ok=True, detail="no-secrets-visible")
        _ = client.get_secret(first.name)
        return KeyVaultHealth(ok=True)
    except Exception as e:
        return KeyVaultHealth(ok=False, detail=str(e))
