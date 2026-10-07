"""Source catalogue and URL discovery.

RIK embeds the cut-off date in annual-report file names (`..._kuni_31082026_0.zip`) and EMTA
serves files through share links, so download URLs are resolved from the publishers' pages on
every run instead of being hard-coded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin

import requests

RIK_PAGE = "https://avaandmed.ariregister.rik.ee/en/downloading-open-data"
EMTA_PAGE = (
    "https://www.emta.ee/en/business-client/board-news-and-contact/"
    "news-press-information-statistics/statistics-and-open-data"
)
RIK_BASIC_URL = (
    "https://avaandmed.ariregister.rik.ee/sites/default/files/avaandmed/"
    "ettevotja_rekvisiidid__lihtandmed.csv.zip"
)
USER_AGENT = "eesti-company-pulse/0.1 (open-data project)"

# Rows removed while converting raw -> Parquet (privacy and project scope).
# The raw file keeps them because it must stay byte-identical to what was downloaded.


@dataclass(frozen=True)
class CsvFormat:
    delim: str
    # SQL predicate that selects rows to KEEP; rows failing it are counted, not stored.
    keep_predicate: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    family: str  # emta, rik_basic, rik_reports_general, rik_elements
    fmt: CsvFormat
    schedule: str  # human-readable cadence of the publisher
    freshness_warn_days: int
    freshness_error_days: int


FAMILIES: dict[str, SourceSpec] = {
    "rik_basic": SourceSpec(
        "rik_basic",
        CsvFormat(";", "ettevotja_oiguslik_vorm IS DISTINCT FROM 'Füüsilisest isikust ettevõtja'"),
        "daily",
        2,
        4,
    ),
    "emta": SourceSpec(
        "emta",
        CsvFormat(",", "\"Type\" NOT IN ('Self-employed person', 'Non-resident')"),
        "quarterly, 10th of the month after the quarter",
        100,
        120,
    ),
    "rik_reports_general": SourceSpec("rik_reports_general", CsvFormat(";"), "monthly", 40, 70),
    "rik_elements": SourceSpec("rik_elements", CsvFormat(";"), "monthly", 40, 70),
}


def family_of(source: str) -> SourceSpec:
    if source.startswith("rik_elements_"):
        return FAMILIES["rik_elements"]
    if source.startswith("emta_"):
        return FAMILIES["emta"]
    return FAMILIES[source]


@dataclass(frozen=True)
class Resolved:
    source: str
    url: str
    cutoff_date: date | None = None


_REPORTS_RE = re.compile(r'href="([^"]*/1\.aruannete_yldandmed_kuni_(\d{8})(?:_\d+)?\.zip)"')
_ELEMENTS_RE = re.compile(
    r'href="([^"]*/4\.(\d{4})_aruannete_elemendid_kuni_(\d{8})(?:_\d+)?\.zip)"'
)
_EMTA_RE = {
    "emta_current": re.compile(r'href="([^"]+/tasutud_maksud_kaesolev_aasta_eng\.csv)"'),
    "emta_history": re.compile(r'href="([^"]+/tasutud_maksud_varasemad_aastad_eng\.csv)"'),
}


class DiscoveryError(RuntimeError):
    """A publisher page no longer contains a link we depend on."""


def _ddmmyyyy(s: str) -> date:
    return date(int(s[4:]), int(s[2:4]), int(s[:2]))


def parse_rik_page(html: str, base_url: str = RIK_PAGE) -> list[Resolved]:
    out: list[Resolved] = []
    reports = [(_ddmmyyyy(c), urljoin(base_url, u)) for u, c in _REPORTS_RE.findall(html)]
    if not reports:
        raise DiscoveryError("annual-report general file link not found on RIK page")
    cutoff, url = max(reports)
    out.append(Resolved("rik_reports_general", url, cutoff))

    latest_by_year: dict[int, tuple[date, str]] = {}
    for u, year, c in _ELEMENTS_RE.findall(html):
        cand = (_ddmmyyyy(c), urljoin(base_url, u))
        if int(year) not in latest_by_year or cand > latest_by_year[int(year)]:
            latest_by_year[int(year)] = cand
    if not latest_by_year:
        raise DiscoveryError("annual-report element file links not found on RIK page")
    for year in sorted(latest_by_year):
        cutoff, url = latest_by_year[year]
        out.append(Resolved(f"rik_elements_{year}", url, cutoff))
    return out


def parse_emta_page(html: str) -> list[Resolved]:
    out = []
    for source, pattern in _EMTA_RE.items():
        m = pattern.search(html)
        if not m:
            raise DiscoveryError(f"{source} link not found on EMTA page")
        out.append(Resolved(source, m.group(1)))
    return out


def _get(url: str, session: requests.Session) -> str:
    r = session.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.text


def discover(
    families: set[str] | None = None,
    element_years: set[int] | None = None,
    session: requests.Session | None = None,
) -> list[Resolved]:
    """Resolve today's download URLs. `families` limits which publishers are contacted."""
    session = session or requests.Session()
    families = families or set(FAMILIES)
    out: list[Resolved] = []
    if "rik_basic" in families:
        out.append(Resolved("rik_basic", RIK_BASIC_URL))
    if "emta" in families:
        out.extend(parse_emta_page(_get(EMTA_PAGE, session)))
    if families & {"rik_reports_general", "rik_elements"}:
        for r in parse_rik_page(_get(RIK_PAGE, session)):
            fam = family_of(r.source).family
            if fam not in families:
                continue
            if fam == "rik_elements" and element_years is not None:
                if int(r.source.rsplit("_", 1)[1]) not in element_years:
                    continue
            out.append(r)
    return out
