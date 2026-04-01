"""One-shot script to run global risk metrics for all active instruments."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.domains.wealth.workers.risk_calc import run_global_risk_metrics  # noqa: E402


async def main() -> None:
    result = await run_global_risk_metrics()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
