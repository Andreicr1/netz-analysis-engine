import argparse
import asyncio
import logging
import sys

from app.core.jobs.sec_xbrl_facts_ingestion import ingest_sec_xbrl_facts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest SEC XBRL Company Facts bulk JSON into TimescaleDB.")
    parser.add_argument("--cik", type=str, action="append", help="Specific CIKs to ingest (can be repeated)")
    parser.add_argument("--limit", type=int, help="Maximum number of files to process")
    parser.add_argument("--dry-run", action="store_true", help="Parse and count, but do not insert into DB")
    
    args = parser.parse_args()
    
    result = await ingest_sec_xbrl_facts(
        ciks=args.cik,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
        
    print("\nIngestion Summary:")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
