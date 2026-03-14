from __future__ import annotations

from dataclasses import dataclass

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from app.core.config import settings


@dataclass(frozen=True)
class KeyVaultHealth:
    ok: bool
    detail: str | None = None


def get_secret_client() -> SecretClient:
    if not settings.KEYVAULT_URL:
        raise ValueError("KEYVAULT_URL not configured")
    cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return SecretClient(vault_url=settings.KEYVAULT_URL, credential=cred)


def health_check_keyvault() -> KeyVaultHealth:
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

