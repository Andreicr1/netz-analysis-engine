"""One-shot script to run instrument NAV ingestion via Tiingo."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.domains.wealth.workers.instrument_ingestion import run_instrument_ingestion  # noqa: E402


async def main() -> None:
    result = await run_instrument_ingestion()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
