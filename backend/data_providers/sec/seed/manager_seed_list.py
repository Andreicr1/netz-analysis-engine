"""Curated seed list of investment managers for initial database population.

Pre-researched CIK/CRD numbers covering equity, fixed income, alternatives,
hedge funds, and institutional investors — sufficient to validate the Manager
Screener across all filter dimensions.

Format: (firm_name, ticker_or_none, crd_or_none, notes)
"""
from __future__ import annotations

SEED_MANAGERS: list[tuple[str, str | None, str | None, str]] = [
    # ── Traditional Asset Managers — Equity & Multi-Asset ────────────
    ("BlackRock Inc", "BLK", "316793", "Largest AUM globally"),
    ("Vanguard Group", None, "105555", "Index funds, no ticker"),
    ("Fidelity Management Research", None, "316345", "FMR LLC"),
    ("T. Rowe Price", "TROW", "860028", "Active equity"),
    ("Capital Group", None, "5765", "American Funds"),
    ("Wellington Management", None, "106800", "Large private manager"),
    ("Dimensional Fund Advisors", None, "112580", "Factor investing"),
    ("Northern Trust", "NTRS", "128843", "Institutional"),
    ("State Street Global Advisors", None, "315066", "SSgA"),
    ("Invesco", "IVZ", "814986", "Multi-asset"),
    ("Franklin Templeton", "BEN", "38736", "Global equity/FI"),
    ("MFS Investment Management", None, "67759", "Active equity/FI"),
    ("Nuveen", None, "175359", "Fixed income + equity"),
    ("TIAA", None, "91578", "Institutional multi-asset"),
    ("Dodge & Cox", None, "30126", "Value equity"),
    ("Baird", None, "8012", "Mid-cap equity"),
    ("Artisan Partners", "APAM", "1377459", "Active equity"),
    ("Cohen & Steers", "CNS", "275119", "Real estate + infra"),
    ("Parnassus Investments", None, "278463", "ESG equity"),
    ("First Eagle Investment", None, "862375", "Value + alternatives"),

    # ── Fixed Income Specialists ────────────────────────────────────
    ("PIMCO", None, "1113197", "Fixed income leader"),
    ("Loomis Sayles", None, "60348", "FI + equity"),
    ("Western Asset Management", None, "106634", "FI specialist"),
    ("DoubleLine Capital", None, "1493881", "Mortgage/FI"),
    ("MetWest Asset Management", None, "860028", "FI"),
    ("Lord Abbett", None, "60349", "FI + equity"),

    # ── Large Alternatives / Private Credit / BDCs ──────────────────
    ("Blackstone Inc", "BX", "1393818", "Multi-strat alternatives"),
    ("Ares Management", "ARES", "1555280", "Private credit + equity"),
    ("KKR & Co", "KKR", "1404912", "PE + credit"),
    ("Apollo Global Management", "APO", "1411579", "PE + credit"),
    ("Carlyle Group", "CG", "1527590", "PE + credit"),
    ("Oaktree Capital Management", None, "316300", "Distressed + credit"),
    ("Blue Owl Capital", "OWL", "1823945", "BDC + real estate"),
    ("Golub Capital", None, "1476765", "BDC + private credit"),
    ("Ares Capital Corp", "ARCC", "1287750", "Largest BDC"),
    ("Blue Owl Capital Corp", "OBDC", "1655888", "BDC"),
    ("Prospect Capital", "PSEC", "1287286", "BDC"),
    ("FS Investment Corp", None, "1559849", "BDC"),
    ("Owl Rock Technology", None, "1747777", "BDC tech focus"),
    ("Sixth Street Partners", None, "1509671", "Credit"),
    ("HPS Investment Partners", None, "1637842", "Private credit"),

    # ── Hedge Funds (13F filers > $100M) ────────────────────────────
    ("Bridgewater Associates", None, "1350776", "Macro"),
    ("Renaissance Technologies", None, "1037389", "Quant"),
    ("Two Sigma Investments", None, "1484810", "Quant"),
    ("Citadel Advisors", None, "1423298", "Multi-strat"),
    ("Millennium Management", None, "1273931", "Multi-strat"),
    ("Point72 Asset Management", None, "1603466", "Multi-strat"),
    ("D.E. Shaw", None, "1009207", "Quant"),
    ("Elliott Investment Management", None, "1048268", "Activist"),
    ("Third Point", None, "1040273", "Event-driven"),
    ("Pershing Square", None, "1336528", "Activist/concentrated"),

    # ── Institutional Investors as 13F filers ───────────────────────
    ("Harvard Management Company", None, "1085682", "Endowment"),
    ("Yale Investments Office", None, "1104459", "Endowment"),
    ("Stanford Management Company", None, "1103804", "Endowment"),
    ("MIT Investment Management", None, "1341439", "Endowment"),
    ("Texas Teachers Retirement", None, "820027", "Pension"),
    ("CalPERS", None, "1364742", "Largest US pension"),
    ("CalSTRS", None, "1364743", "Pension"),
    ("New York State Common", None, "1025522", "Pension"),
    ("GIC Private Limited", None, "1424397", "Singapore sovereign"),
    ("Norges Bank Investment", None, "1095485", "Norway sovereign"),
]

# Institutional filer notes keywords — used by phase 5.
INSTITUTIONAL_KEYWORDS = ("endowment", "pension", "sovereign")
