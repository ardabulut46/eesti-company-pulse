"""Synthetic source files with the real layouts, for tests and CI.

The values are invented; names are fictional company names (no natural persons). The fixture
contains two releases/snapshots of each source so that history rules can be exercised:

- register day 1 -> day 2: 10000002 goes into liquidation, 10000006 is deleted (disappears).
- EMTA release 2026-04-10 -> 2026-07-10: 10000001's 2026 Q1 turnover is revised,
  10000006 (deleted) is no longer published, Q2 2026 becomes available.
- One registry code has a leading zero (01234567) and must survive as text.
- Self-employed and non-resident rows exist and must be removed at conversion.

Run as a script to build a complete data directory for a dbt run:
    python tests/synthetic_sources.py /tmp/pulse-fixture
"""

from __future__ import annotations

import csv
import functools
import io
import sys
import threading
import zipfile
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RIK_BASIC_HEADER = [
    "nimi",
    "ariregistri_kood",
    "ettevotja_oiguslik_vorm",
    "ettevotja_oigusliku_vormi_alaliik",
    "kmkr_nr",
    "ettevotja_staatus",
    "ettevotja_staatus_tekstina",
    "ettevotja_esmakande_kpv",
    "ettevotja_aadress",
    "asukoht_ettevotja_aadressis",
    "asukoha_ehak_kood",
    "asukoha_ehak_tekstina",
    "indeks_ettevotja_aadressis",
    "ads_adr_id",
    "ads_ads_oid",
    "ads_normaliseeritud_taisaadress",
    "teabesysteemi_link",
]
STATUS = {"R": "Registrisse kantud", "L": "Likvideerimisel", "N": "Pankrotis"}
TALLINN = ("0596", "Pirita linnaosa, Tallinn, Harju maakond")
TARTU = ("8151", "Tartu linn, Tartu linn, Tartu maakond")
PARNU = ("0624", "Pärnu linn, Pärnu linn, Pärnu maakond")

EMTA_HEADER = (
    ["Data date", "Registry code", "Name", "Type", "County", "Activity", "Year"]
    + [f"State taxes {q} qtr" for q in ("I", "II", "III", "IV")]
    + [f"Labour taxes and payments {q} qtr" for q in ("I", "II", "III", "IV")]
    + [f"Turnover {q} qtr" for q in ("I", "II", "III", "IV")]
    + [f"Number of employees {q} qtr" for q in ("I", "II", "III", "IV")]
)

COMPANIES = {
    # code: (name, county text, activity, ehak)
    "10000001": ("Näidis Ehitus OÜ", "Harju ( Tallinn )", "CONSTRUCTION", TALLINN),
    "10000002": (
        "Proov Kaubandus AS",
        "Tartu ( Tartu linn )",
        "WHOLESALE AND RETAIL TRADE; REPAIR OF MOTOR VEHICLES AND MOTORCYCLES",
        TARTU,
    ),
    "10000003": (
        "Katse Tarkvara OÜ",
        "Harju ( Tallinn )",
        "INFORMATION AND COMMUNICATION",
        TALLINN,
    ),
    "10000004": ("Test Tehas OÜ", "Pärnu ( Pärnu linn )", "MANUFACTURING", PARNU),
    "10000006": ("Suletud Firma OÜ", "Harju ( Tallinn )", "CONSTRUCTION", TALLINN),
    "01234567": ("Nulliga Algav OÜ", "Harju ( Rae vald )", "TRANSPORTATION AND STORAGE", TALLINN),
}


def _csv_bytes(header, rows, delim, bom=False) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delim, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return (("﻿" if bom else "") + buf.getvalue()).encode("utf-8")


def _zip(name: str, payload: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, payload)
    return out.getvalue()


def rik_basic(day: int) -> bytes:
    rows = []
    for code, (name, _county, _act, (ehak, ehak_text)) in COMPANIES.items():
        status = "R"
        if code == "10000002" and day >= 2:
            status = "L"
        if code == "10000006" and day >= 2:
            continue  # deleted: absent from the file
        rows.append(
            [
                name,
                code,
                "Osaühing",
                "",
                f"EE{code}",
                status,
                STATUS[status],
                "01.02.2015",
                "",
                "Tee 1",
                ehak,
                ehak_text,
                "10111",
                "",
                "",
                f"Tee 1, {ehak_text}",
                f"https://ariregister.rik.ee/est/company/{code}",
            ]
        )
    rows.append(
        [
            "Mari Maasikas FIE",
            "30000001",
            "Füüsilisest isikust ettevõtja",
            "",
            "",
            "R",
            STATUS["R"],
            "01.01.2020",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    return _zip(
        "ettevotja_rekvisiidid__lihtandmed.csv", _csv_bytes(RIK_BASIC_HEADER, rows, ";", bom=True)
    )


def _emta_row(data_date, code, name, typ, county, activity, year, q_values):
    """q_values: list of 4 tuples (state, labour, turnover, employees) or None."""
    cols = {k: [] for k in ("s", "l", "t", "e")}
    for v in q_values:
        v = v or (None, None, None, None)
        for key, x in zip("slte", v, strict=True):
            cols[key].append("" if x is None else str(x))
    return [
        data_date,
        code,
        name,
        typ,
        county or "",
        activity or "",
        str(year),
        *cols["s"],
        *cols["l"],
        *cols["t"],
        *cols["e"],
    ]


def _company_quarters(code: str, year: int, n_quarters: int, release: int):
    base = int(code[-2:]) * 10 + (year - 2022) * 3
    out = []
    for q in range(1, 5):
        if q > n_quarters:
            out.append(None)
            continue
        turnover = base * 1000 + q * 100
        if code == "10000001" and year == 2026 and q == 1 and release == 2:
            turnover += 555  # revision in the second release
        employees = None if code == "01234567" and q == 2 else base
        out.append((base * 50, base * 30, turnover, employees))
    return out


def emta(release: int, history: bool) -> bytes:
    data_date = "10.04.2026" if release == 1 else "10.07.2026"
    years = (2022, 2023, 2024) if history else (2025, 2026)
    rows = []
    for code, (name, county, activity, _ehak) in COMPANIES.items():
        if code == "10000006" and release == 2:
            continue  # EMTA drops deleted legal persons
        for year in years:
            n = 4 if year < 2026 else (1 if release == 1 else 2)
            rows.append(
                _emta_row(
                    data_date,
                    code,
                    name,
                    "Company",
                    county,
                    activity,
                    year,
                    _company_quarters(code, year, n, release),
                )
            )
    rows.append(
        _emta_row(
            data_date,
            "EE0000000000000001",
            "Juhan Juurikas",
            "Self-employed person",
            "Harju ( Tallinn )",
            "CONSTRUCTION",
            years[0],
            [(1, 1, 1, 1)] * 4,
        )
    )
    rows.append(
        _emta_row(
            data_date,
            "QQ000001",
            "Foreign Ltd",
            "Non-resident",
            None,
            None,
            years[0],
            [(1, None, None, None)] * 4,
        )
    )
    rows.append(
        _emta_row(
            data_date,
            "80000001",
            "Näidis Selts MTÜ",
            "Non-profit association",
            "Harju ( Tallinn )",
            "OTHER SERVICE ACTIVITIES",
            years[0],
            [(5, 5, None, 1)] * 4,
        )
    )
    return _csv_bytes(EMTA_HEADER, rows, ",")


REPORT_HEADER = [
    "report_id",
    "taidetud_aruanne_report_id",
    "registrikood",
    "õiguslik vorm",
    "staatus",
    "aruandeaasta",
    "kas konsolideeritud?",
    "period_start",
    "period_end",
    "esitatud_kpv",
    "kas auditeeritud?",
    "valitud aruanne kategooria",
    "minimaalne kategooria andmete alusel",
    "auditi töövõtu liik",
    "audiitori otsuse tüüp",
    "modifikatsioon asjaolu rõhutamine",
    "modifikatsioon muu asjaolu",
    "modifikatsioon tegevuse jatkuvus",
    "Audiitorettevõtja (AEV)",
]


def _report_id(code: str, year: int) -> str:
    return f"{year}{code[-3:]}"


def reports_general() -> bytes:
    rows = []
    for code in ("10000001", "10000002", "10000003", "10000004", "10000006", "01234567"):
        for year in (2024, 2025):
            filled = f"9{_report_id(code, year)}" if code == "10000003" else ""
            status = "Kustutatud" if code == "10000006" else "Registrisse kantud"
            rows.append(
                [
                    _report_id(code, year),
                    filled,
                    code,
                    "OÜ",
                    status,
                    year,
                    "Ei",
                    f"01.01.{year}",
                    f"31.12.{year}",
                    f"30.06.{year + 1}",
                    "Ei",
                    "Mikroettevõtja",
                    "Mikroettevõtja",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
    return _zip("1.aruannete_yldandmed_kuni_31082026.csv", _csv_bytes(REPORT_HEADER, rows, ";"))


ELEMENT_HEADER = ["report_id", "tabel", "elemendi_label", "elemendi_nimetus", "vaartus"]


def elements(year: int) -> bytes:
    rows = []
    for code in ("10000001", "10000002", "10000003", "10000004", "01234567"):
        rid = _report_id(code, year)
        if code == "10000003":
            rid = f"9{rid}"  # elements live under the filled report id
        base = int(code[-2:]) * 10 + (year - 2022) * 3
        revenue = base * 4000
        rows += [
            [rid, "Kasumiaruanne skeem 1", "Müügitulu", "Revenue", f"{revenue}.0"],
            [
                rid,
                "Kasumiaruanne skeem 1",
                "Aruandeaasta kasum (kahjum)",
                "TotalAnnualPeriodProfitLoss",
                f"{base * 100}.0",
            ],
            [rid, "Lisa: Tööjõukulud", "Tööjõukulud", "LaborExpense", f"{base * 90}.0"],
            [
                rid,
                "Lisa: Tööjõukulud",
                "Töötajate keskmine arv taandatuna täistööajale",
                "AverageNumberOfEmployeesInFullTimeEquivalentUnits",
                f"{base}.5",
            ],
            [rid, "Bilanss", "Varad", "Assets", f"{base * 2000}.0"],
            [rid, "Bilanss", "Omakapital", "Equity", f"{base * 800}.0"],
            [rid, "PDF", "Müügitulu", "", str(revenue)],
        ]
        if code == "10000004":
            rows += [
                [rid, "Bilanss", "Lühiajalised kohustised", "CurrentLiabilities", "0"],
                [rid, "Bilanss", "Lühiajalised kohustised", "CurrentLiabilities", "99"],
            ]
    return _zip(
        f"4.{year}_aruannete_elemendid_kuni_31082026.csv", _csv_bytes(ELEMENT_HEADER, rows, ";")
    )


class Server:
    """Serves a directory over HTTP on a free local port."""

    def __init__(self, directory: Path):
        handler = functools.partial(_QuietHandler, directory=str(directory))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def build_data_dir(data_dir: Path) -> None:
    """Download two days of synthetic sources through the real downloader, then convert."""
    from pulse import convert, snapshots
    from pulse.config import Paths
    from pulse.sources import Resolved

    paths = Paths(data_dir)
    served = data_dir.parent / f"{data_dir.name}-served"
    served.mkdir(parents=True, exist_ok=True)
    days = {
        1: datetime(2026, 4, 11, 6, 0, tzinfo=UTC),
        2: datetime(2026, 7, 11, 6, 0, tzinfo=UTC),
    }
    with Server(served) as srv:
        for day, now in days.items():
            files = {
                "rik_basic": ("ettevotja_rekvisiidid__lihtandmed.csv.zip", rik_basic(day)),
                "emta_current": ("tasutud_maksud_kaesolev_aasta_eng.csv", emta(day, False)),
                "emta_history": ("tasutud_maksud_varasemad_aastad_eng.csv", emta(day, True)),
                "rik_reports_general": (
                    "1.aruannete_yldandmed_kuni_31082026_0.zip",
                    reports_general(),
                ),
                "rik_elements_2024": (
                    "4.2024_aruannete_elemendid_kuni_31082026_0.zip",
                    elements(2024),
                ),
                "rik_elements_2025": (
                    "4.2025_aruannete_elemendid_kuni_31082026_0.zip",
                    elements(2025),
                ),
            }
            for source, (filename, payload) in files.items():
                (served / filename).write_bytes(payload)
                cutoff = (
                    datetime(2026, 8, 31).date()
                    if source.startswith("rik_") and source != "rik_basic"
                    else None
                )
                snapshots.fetch(
                    Resolved(source, f"{srv.base_url}/{filename}", cutoff), paths, now=now
                )
    convert.convert_all(paths)


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve()
    build_data_dir(target)
    print(f"synthetic data directory ready: {target}")
