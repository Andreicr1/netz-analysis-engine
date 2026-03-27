"""Tests for data_providers.sec.iapd_xml_parser — IAPD XML Feed parser.

Covers:
  - parse_iapd_xml() — full parse of sample XML
  - _parse_fee_types() — Item 5E flag extraction
  - _parse_client_types() — Item 5D attribute extraction
  - _count_compliance_disclosures() — Item 11 Y-counting
  - _normalize_website() — URL normalization
  - Edge cases: empty Part1A, missing items, zero AUM
"""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

from data_providers.sec.iapd_xml_parser import (
    _count_compliance_disclosures,
    _normalize_website,
    _parse_client_types,
    _parse_fee_types,
    _parse_int_attr,
    parse_iapd_xml,
)

# ── Sample XML ────────────────────────────────────────────────────

SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<IAPDFirmSECReport GenOn="2026-03-24">
  <Firms>
    <Firm>
      <Info FirmCrdNb="137689" SECNb="801-73984" BusNm="ENDEAVOUR CAPITAL" LegalNm="ENDEAVOUR CAPITAL ADVISORS INC." UmbrRgstn="N"/>
      <MainAddr Strt1="410 GREENWICH AVE" City="GREENWICH" State="CT" Cntry="United States" PostlCd="06830" PhNb="203-618-0101"/>
      <Rgstn FirmType="Registered" St="APPROVED" Dt="2012-03-30"/>
      <Filing Dt="2025-03-28" FormVrsn="10/2021"/>
      <FormInfo>
        <Part1A>
          <Item1 Q1F5="0" Q1I="Y" Q1M="N" Q1P="LEI123">
            <WebAddrs>
              <WebAddr>HTTP://WWW.ENDCAP.COM</WebAddr>
            </WebAddrs>
          </Item1>
          <Item5A TtlEmp="8"/>
          <Item5D Q5DF1="3" Q5DF3="518254494"/>
          <Item5E Q5E1="Y" Q5E2="N" Q5E3="N" Q5E4="N" Q5E5="N" Q5E6="Y" Q5E7="N"/>
          <Item5F Q5F1="Y" Q5F2A="518254494" Q5F2B="0" Q5F2C="518254494" Q5F2D="3" Q5F2E="0" Q5F2F="3" Q5F3="0"/>
          <Item11 Q11="N"/>
          <Item11A Q11A1="N" Q11A2="N"/>
        </Part1A>
      </FormInfo>
    </Firm>
    <Firm>
      <Info FirmCrdNb="999999" SECNb="801-99999" BusNm="EMPTY FIRM" LegalNm="EMPTY FIRM LLC"/>
      <Filing Dt="2025-01-15"/>
      <FormInfo>
        <Part1A>
          <Item5F Q5F2A="0" Q5F2B="0" Q5F2C="0" Q5F2F="0"/>
        </Part1A>
      </FormInfo>
    </Firm>
    <Firm>
      <Info FirmCrdNb="555555" SECNb="801-55555" BusNm="MULTI CLIENT" LegalNm="MULTI CLIENT INC."/>
      <Filing Dt="2025-06-01"/>
      <FormInfo>
        <Part1A>
          <Item5D Q5DA1="10" Q5DA3="5000000" Q5DB1="5" Q5DB3="50000000" Q5DF1="2" Q5DF3="200000000"/>
          <Item5E Q5E1="Y" Q5E2="Y" Q5E3="N" Q5E4="Y" Q5E5="N" Q5E6="N" Q5E7="N"/>
          <Item5F Q5F2A="100000000" Q5F2B="50000000" Q5F2C="150000000" Q5F2F="17"/>
          <Item11 Q11="Y"/>
          <Item11A Q11A1="Y" Q11A2="N"/>
          <Item11B Q11B="Y"/>
        </Part1A>
      </FormInfo>
    </Firm>
  </Firms>
</IAPDFirmSECReport>
"""


# ── parse_iapd_xml() ─────────────────────────────────────────────


class TestParseIapdXml:
    def test_parses_full_sample(self, tmp_path):
        xml_file = tmp_path / "test_feed.xml"
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")

        results = parse_iapd_xml(str(xml_file))

        # Firm 2 (CRD 999999) has filing date → still included (has_data = True)
        assert len(results) == 3

        # Firm 1: Endeavour Capital
        firm1 = next(r for r in results if r["crd_number"] == "137689")
        assert firm1["aum_total"] == 518254494
        assert firm1["aum_discretionary"] == 518254494
        assert firm1["aum_non_discretionary"] is None  # 0 → None
        assert firm1["total_accounts"] == 3
        assert firm1["fee_types"] == ["pct_of_aum", "performance"]
        assert firm1["client_types"] == {
            "pooled_vehicles": {"count": 3, "aum": 518254494},
        }
        assert firm1["website"] == "http://WWW.ENDCAP.COM"
        assert firm1["compliance_disclosures"] == 0
        assert firm1["last_adv_filed_at"] == "2025-03-28"

    def test_multi_client_firm(self, tmp_path):
        xml_file = tmp_path / "test_feed.xml"
        xml_file.write_text(SAMPLE_XML, encoding="utf-8")

        results = parse_iapd_xml(str(xml_file))
        firm3 = next(r for r in results if r["crd_number"] == "555555")

        assert firm3["aum_total"] == 150000000
        assert firm3["aum_discretionary"] == 100000000
        assert firm3["aum_non_discretionary"] == 50000000
        assert firm3["total_accounts"] == 17
        assert firm3["fee_types"] == ["pct_of_aum", "hourly", "fixed"]
        assert "individuals" in firm3["client_types"]
        assert "hnw_individuals" in firm3["client_types"]
        assert "pooled_vehicles" in firm3["client_types"]
        assert firm3["client_types"]["individuals"]["count"] == 10
        assert firm3["client_types"]["individuals"]["aum"] == 5000000
        # Item 11: Q11=Y, Q11A1=Y, Q11A2=N, Q11B=Y → 3 Y's
        assert firm3["compliance_disclosures"] == 3

    def test_empty_xml(self, tmp_path):
        xml_file = tmp_path / "empty.xml"
        xml_file.write_text(
            '<?xml version="1.0"?><IAPDFirmSECReport><Firms></Firms></IAPDFirmSECReport>',
            encoding="utf-8",
        )
        results = parse_iapd_xml(str(xml_file))
        assert results == []


# ── _parse_fee_types() ────────────────────────────────────────────


class TestParseFeeTypes:
    def test_mixed_flags(self):
        elem = fromstring('<Item5E Q5E1="Y" Q5E2="N" Q5E3="N" Q5E4="N" Q5E5="N" Q5E6="Y" Q5E7="N"/>')
        assert _parse_fee_types(elem) == ["pct_of_aum", "performance"]

    def test_all_yes(self):
        elem = fromstring('<Item5E Q5E1="Y" Q5E2="Y" Q5E3="Y" Q5E4="Y" Q5E5="Y" Q5E6="Y" Q5E7="Y"/>')
        assert len(_parse_fee_types(elem)) == 7

    def test_all_no(self):
        elem = fromstring('<Item5E Q5E1="N" Q5E2="N" Q5E3="N" Q5E4="N" Q5E5="N" Q5E6="N" Q5E7="N"/>')
        assert _parse_fee_types(elem) == []

    def test_none_element(self):
        assert _parse_fee_types(None) == []


# ── _parse_client_types() ────────────────────────────────────────


class TestParseClientTypes:
    def test_single_client_type(self):
        elem = fromstring('<Item5D Q5DF1="3" Q5DF3="518254494"/>')
        result = _parse_client_types(elem)
        assert result == {"pooled_vehicles": {"count": 3, "aum": 518254494}}

    def test_zero_count_excluded(self):
        elem = fromstring('<Item5D Q5DA1="0" Q5DA3="0" Q5DF1="3" Q5DF3="100"/>')
        result = _parse_client_types(elem)
        assert "individuals" not in result
        assert "pooled_vehicles" in result

    def test_none_element(self):
        assert _parse_client_types(None) == {}

    def test_missing_aum_defaults_zero(self):
        elem = fromstring('<Item5D Q5DA1="5"/>')
        result = _parse_client_types(elem)
        assert result == {"individuals": {"count": 5, "aum": 0}}


# ── _count_compliance_disclosures() ──────────────────────────────


class TestCountComplianceDisclosures:
    def test_no_disclosures(self):
        part1a = fromstring("<Part1A><Item11 Q11='N'/><Item11A Q11A1='N' Q11A2='N'/></Part1A>")
        assert _count_compliance_disclosures(part1a) == 0

    def test_some_disclosures(self):
        part1a = fromstring("<Part1A><Item11 Q11='Y'/><Item11A Q11A1='Y' Q11A2='N'/></Part1A>")
        assert _count_compliance_disclosures(part1a) == 2

    def test_no_item11_returns_none(self):
        part1a = fromstring("<Part1A><Item5F Q5F2C='100'/></Part1A>")
        assert _count_compliance_disclosures(part1a) is None


# ── _normalize_website() ─────────────────────────────────────────


class TestNormalizeWebsite:
    def test_uppercase_http(self):
        assert _normalize_website("HTTP://WWW.ENDCAP.COM") == "http://WWW.ENDCAP.COM"

    def test_uppercase_https(self):
        assert _normalize_website("HTTPS://WWW.EXAMPLE.COM") == "https://WWW.EXAMPLE.COM"

    def test_no_scheme(self):
        assert _normalize_website("www.example.com") == "http://www.example.com"

    def test_trailing_slash(self):
        assert _normalize_website("http://example.com/") == "http://example.com"

    def test_none(self):
        assert _normalize_website(None) is None

    def test_empty(self):
        assert _normalize_website("") is None
        assert _normalize_website("  ") is None


# ── _parse_int_attr() ────────────────────────────────────────────


class TestParseIntAttr:
    def test_valid(self):
        elem = fromstring('<Item5F Q5F2C="518254494"/>')
        assert _parse_int_attr(elem, "Q5F2C") == 518254494

    def test_missing(self):
        elem = fromstring('<Item5F Q5F2C="518254494"/>')
        assert _parse_int_attr(elem, "Q5F2B") is None

    def test_empty(self):
        elem = fromstring('<Item5F Q5F2C=""/>')
        assert _parse_int_attr(elem, "Q5F2C") is None

    def test_non_numeric(self):
        elem = fromstring('<Item5F Q5F2C="abc"/>')
        assert _parse_int_attr(elem, "Q5F2C") is None
