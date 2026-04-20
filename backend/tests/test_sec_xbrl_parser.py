from datetime import date
from decimal import Decimal
from pathlib import Path

from app.core.jobs._sec_xbrl_parser import iter_facts_from_file

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "xbrl"


def test_parser_valid_file_aar():
    """Test parsing a valid file with both numeric and non-numeric facts, and restatements."""
    file_path = FIXTURE_DIR / "CIK0000001750.json"
    facts = list(iter_facts_from_file(file_path))
    
    assert len(facts) == 4
    
    # Non-numeric fact
    fact_name = [f for f in facts if f.concept == "EntityRegistrantName"][0]
    assert fact_name.cik == 1750
    assert fact_name.taxonomy == "dei"
    assert fact_name.unit == "pure"
    assert fact_name.val is None
    assert fact_name.val_text == "AAR CORP."
    assert fact_name.period_end == date(2010, 5, 31)
    
    # Numeric fact with restatement
    ap_facts = [f for f in facts if f.concept == "AccountsPayable"]
    assert len(ap_facts) == 3
    
    # 10-Q
    ap_q1 = [f for f in ap_facts if f.form == "10-Q"][0]
    assert ap_q1.val == Decimal("114906000")
    assert ap_q1.unit == "USD"
    assert ap_q1.period_end == date(2010, 5, 31)
    assert ap_q1.fy == 2011
    assert ap_q1.fp == "Q1"
    
    # 10-K and 10-K/A
    ap_10k = [f for f in ap_facts if f.form == "10-K"][0]
    ap_10ka = [f for f in ap_facts if f.form == "10-K/A"][0]
    assert ap_10k.val == Decimal("120000000")
    assert ap_10ka.val == Decimal("121000000")
    assert ap_10k.accn != ap_10ka.accn


def test_parser_valid_file_aapl():
    """Test parsing a file with period_start and non-USD units."""
    file_path = FIXTURE_DIR / "CIK0000320193.json"
    facts = list(iter_facts_from_file(file_path))
    
    assert len(facts) == 2
    
    net_income = [f for f in facts if f.concept == "NetIncomeLoss"][0]
    assert net_income.cik == 320193
    assert net_income.period_start == date(2020, 9, 27)
    assert net_income.period_end == date(2021, 9, 25)
    assert net_income.val == Decimal("94680000000")
    assert net_income.unit == "USD"
    
    shares = [f for f in facts if f.concept == "CommonStockSharesOutstanding"][0]
    assert shares.unit == "shares"
    assert shares.val == Decimal("16406397000")
    assert shares.period_start is None


def test_parser_malformed_file():
    """Test parsing a malformed JSON file."""
    file_path = FIXTURE_DIR / "CIK0000000000_malformed.json"
    import ijson
    try:
        list(iter_facts_from_file(file_path))
    except ijson.JSONError:
        pass  # Expected to fail
