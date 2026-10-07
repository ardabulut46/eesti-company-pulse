import pytest

from pulse.sources import DiscoveryError, family_of, parse_emta_page, parse_rik_page

RIK_HTML = """
<a href="/sites/default/files/1.aruannete_yldandmed_kuni_31072026_0.zip">old</a>
<a href="/sites/default/files/1.aruannete_yldandmed_kuni_31082026_0.zip">new</a>
<a href="/sites/default/files/4.2024_aruannete_elemendid_kuni_31082026_0.zip">2024</a>
<a href="/sites/default/files/4.2025_aruannete_elemendid_kuni_31082026.zip">2025</a>
<a href="/sites/default/files/13_11_lihtandmed.parquet_1.zip">stale parquet</a>
"""


def test_rik_page_picks_newest_cutoff_and_all_element_years():
    found = {r.source: r for r in parse_rik_page(RIK_HTML)}
    general = found["rik_reports_general"]
    assert general.url.endswith("kuni_31082026_0.zip")
    assert general.url.startswith("https://avaandmed.ariregister.rik.ee/")
    assert general.cutoff_date.isoformat() == "2026-08-31"
    assert set(found) == {"rik_reports_general", "rik_elements_2024", "rik_elements_2025"}


def test_rik_page_without_links_fails_loudly():
    with pytest.raises(DiscoveryError):
        parse_rik_page("<html>page redesigned</html>")


def test_emta_page():
    html = (
        '<a href="https://ncfailid.emta.ee/s/abc/download/tasutud_maksud_kaesolev_aasta_eng.csv">'
        '<a href="https://ncfailid.emta.ee/s/def/download/tasutud_maksud_varasemad_aastad_eng.csv">'
        '<a href="https://ncfailid.emta.ee/s/xyz/download/tasutud_maksud_kaesolev_aasta_eng.xlsx">'
    )
    found = {r.source: r.url for r in parse_emta_page(html)}
    assert found["emta_current"].endswith("/abc/download/tasutud_maksud_kaesolev_aasta_eng.csv")
    assert found["emta_history"].endswith("/def/download/tasutud_maksud_varasemad_aastad_eng.csv")


def test_emta_page_missing_link():
    with pytest.raises(DiscoveryError):
        parse_emta_page("<a href='x.xlsx'>")


def test_source_families():
    assert family_of("rik_elements_2019").family == "rik_elements"
    assert family_of("emta_history").family == "emta"
    assert family_of("rik_basic").fmt.delim == ";"
