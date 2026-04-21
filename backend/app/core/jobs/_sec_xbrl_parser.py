from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import ijson


@dataclass(frozen=True, slots=True)
class XbrlFact:
    cik: int
    taxonomy: str
    concept: str
    unit: str
    period_end: date
    period_start: date | None
    val: Decimal | None
    val_text: str | None
    accn: str
    fy: int | None
    fp: str | None
    form: str
    filed: date


def iter_facts_from_file(path: Path) -> Iterator[XbrlFact]:
    """Parse SEC CompanyFacts JSON efficiently using ijson."""
    with open(path, "rb") as f:
        parser = ijson.parse(f)
        cik: int | None = None
        obs: dict[str, Any] = {}
        in_obs = False
        taxonomy: str | None = None
        concept: str | None = None
        unit: str | None = None

        for prefix, event, value in parser:
            if prefix == "cik" and event == "number":
                cik = value
                continue
            
            if prefix.startswith("facts."):
                parts = prefix.split(".")
                
                # Check if we are inside the array of observations
                # e.g., facts.us-gaap.AccountsPayable.units.USD.item
                if len(parts) >= 6 and parts[3] == "units":
                    if parts[5] == "item":
                        if event == "start_map":
                            in_obs = True
                            obs.clear()
                            taxonomy = parts[1]
                            concept = parts[2]
                            unit = parts[4]
                        elif event == "end_map":
                            in_obs = False
                            
                            # Parse observation fields
                            val = obs.get("val")
                            val_num = None
                            val_text = None
                            if val is not None:
                                if isinstance(val, (int, float, Decimal)):
                                    val_num = Decimal(str(val))
                                else:
                                    val_text = str(val)
                            
                            start_date = None
                            if "start" in obs:
                                start_date = datetime.strptime(obs["start"], "%Y-%m-%d").date()
                            
                            end_date = datetime.strptime(obs["end"], "%Y-%m-%d").date()
                            filed_date = datetime.strptime(obs["filed"], "%Y-%m-%d").date()
                            
                            if cik is not None and taxonomy is not None and concept is not None and unit is not None:
                                yield XbrlFact(
                                    cik=cik,
                                    taxonomy=taxonomy,
                                    concept=concept,
                                    unit=unit,
                                    period_end=end_date,
                                    period_start=start_date,
                                    val=val_num,
                                    val_text=val_text,
                                    accn=obs["accn"],
                                    fy=obs.get("fy"),
                                    fp=obs.get("fp"),
                                    form=obs["form"],
                                    filed=filed_date
                                )
                        elif in_obs and len(parts) == 7:
                            field = parts[6]
                            obs[field] = value
