from app.services.providers.csv_import_adapter import CsvImportAdapter
from app.services.providers.protocol import InstrumentDataProvider, RawInstrumentData
from app.services.providers.tiingo_instrument_provider import TiingoInstrumentProvider
from app.services.providers.yahoo_finance_provider import YahooFinanceProvider

__all__ = [
    "CsvImportAdapter",
    "InstrumentDataProvider",
    "RawInstrumentData",
    "TiingoInstrumentProvider",
    "YahooFinanceProvider",
    "get_instrument_provider",
]


def get_instrument_provider() -> InstrumentDataProvider:
    """Factory — returns FEFundInfo when enabled, Tiingo otherwise.

    Tiingo is the production default for NAV ingestion across the global
    catalog (~5.5k instruments). Yahoo Finance is retained only as a
    legacy import symbol until PR-C removes the module entirely.
    """
    from app.core.config.settings import settings

    if settings.feature_fefundinfo_enabled:
        from app.services.providers.fefundinfo_client import (
            FEFundInfoClient,
            FEFundInfoTokenManager,
        )
        from app.services.providers.fefundinfo_provider import FEFundInfoProvider

        token_mgr = FEFundInfoTokenManager(
            client_id=settings.fefundinfo_client_id,
            client_secret=settings.fefundinfo_client_secret,
            token_url=settings.fefundinfo_token_url,
        )
        client = FEFundInfoClient(
            token_manager=token_mgr,
            subscription_key=settings.fefundinfo_subscription_key,
        )
        return FEFundInfoProvider(client)
    return TiingoInstrumentProvider()
