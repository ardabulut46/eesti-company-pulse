"""Eesti Company Pulse - Streamlit app over the serving database (data/serving/pulse.duckdb).

Run:  streamlit run app/streamlit_app.py
The app only reads marts. It never opens the warehouse, so it cannot block `pulse build`.
Legal entities only: self-employed persons and non-residents are removed before modelling.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA_DIR = Path(os.environ.get("PULSE_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
SERVING = DATA_DIR / "serving" / "pulse.duckdb"

# Reference categorical palette (validated: adjacent CVD dE >= 9.1). Slots used in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
POSITIVE, NEGATIVE, NEUTRAL = "#2a78d6", "#e34948", "#9a9a95"  # diverging poles + gray
REGIONS = ["Tallinn", "Harju (excl. Tallinn)", "Tartu city", "Rest of Estonia"]
REGION_COLORS = dict(zip(REGIONS, SERIES, strict=False))

METRICS = {
    "Employees": ("employees", "employees_matched_current_yoy", "employees_matched_previous_yoy"),
    "Turnover": ("turnover", "turnover_matched_current_yoy", "turnover_matched_previous_yoy"),
    "Labour taxes": (
        "labour_taxes",
        "labour_taxes_matched_current_yoy",
        "labour_taxes_matched_previous_yoy",
    ),
}

st.set_page_config(page_title="Eesti Company Pulse", layout="wide")


@st.cache_resource
def connection(mtime: float) -> duckdb.DuckDBPyConnection:  # mtime busts the cache on publish
    return duckdb.connect(str(SERVING), read_only=True)


def q(sql: str, params: list | None = None) -> pd.DataFrame:
    return connection(SERVING.stat().st_mtime).execute(sql, params or []).df()


def yq_label(yq: int) -> str:
    return f"{yq // 10} Q{yq % 10}"


def style(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=48, b=8),
        # Lines: one tooltip for every series at the hovered x. Bars set "closest" themselves.
        hovermode=fig.layout.hovermode or "x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0, title=None),
        font=dict(size=13),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(
        gridcolor="rgba(128,128,128,0.18)", zeroline=True, zerolinecolor="rgba(128,128,128,0.5)"
    )
    fig.update_traces(selector=dict(type="scatter"), line=dict(width=2), marker=dict(size=8))
    return fig


def table_view(df: pd.DataFrame, label: str = "Table view") -> None:
    with st.expander(label):
        st.dataframe(df, hide_index=True, use_container_width=True)


if not SERVING.exists():
    st.error(f"Serving database not found at {SERVING}. Run `pulse run` (or `pulse build`).")
    st.stop()

snap = q(
    "select max(retrieved_at) as t, max(publisher_last_modified_at) as p "
    "from marts.mart_pipeline_snapshots"
)
st.title("Eesti Company Pulse")
st.caption(
    "Estonian companies (EMTA type *Company*) from EMTA quarterly tax data and e-Business "
    f"Register open data. Newest snapshot taken {snap.t[0]:%Y-%m-%d %H:%M} UTC. "
    "Descriptive only: no causal claims, no investment advice."
)

pulse_tab, fundamentals_tab, consistency_tab, company_tab, quality_tab = st.tabs(
    [
        "Pulse",
        "Annual fundamentals",
        "EMTA vs annual reports",
        "Company lookup",
        "Data quality & pipeline",
    ]
)

# --------------------------------------------------------------------------------------- Pulse
with pulse_tab:
    quarters = q("select distinct year_quarter from marts.mart_sector_region_quarter order by 1")
    yqs = quarters.year_quarter.tolist()
    c1, c2, c3 = st.columns([1, 1, 2])
    metric_name = c1.selectbox("Metric", list(METRICS), index=0)
    latest = c2.selectbox("Quarter", yqs[::-1], format_func=yq_label)
    regions = c3.multiselect("Regions", REGIONS, default=REGIONS)
    total_col, cur_col, prev_col = METRICS[metric_name]
    region_filter = regions or REGIONS

    base = q(
        f"""
        select year_quarter, region_group, section_code, section_name,
               sum({total_col}) as total, sum({cur_col}) as cur, sum({prev_col}) as prev,
               sum(n_companies_reporting) as n_companies,
               sum(n_matched_yoy_employees) as n_matched,
               sum(turnover_of_employers) as t_emp, sum(employees_of_employers) as e_emp
        from marts.mart_sector_region_quarter
        where region_group in (select unnest(?::varchar[]))
        group by all
        """,
        [region_filter],
    )

    def growth(df: pd.DataFrame) -> float | None:
        prev = df.prev.sum()
        return None if not prev else df.cur.sum() / prev - 1

    now = base[base.year_quarter == latest]
    k1, k2, k3, k4 = st.columns(4)
    unit = "" if metric_name == "Employees" else " EUR"
    k1.metric(f"{metric_name}, {yq_label(latest)}", f"{now.total.sum():,.0f}{unit}")
    g = growth(now)
    k2.metric(
        "Year-on-year, same companies",
        "n/a" if g is None else f"{g:+.1%}",
        help="Matched panel: only companies with a value in both quarters.",
    )
    k3.metric("Companies reporting", f"{now.n_companies.sum():,.0f}")
    tpe = now.t_emp.sum() / now.e_emp.sum() if now.e_emp.sum() else None
    k4.metric(
        "Turnover per employee (quarter)",
        "n/a" if tpe is None else f"{tpe:,.0f} EUR",
        help="Companies with employees > 0 and known turnover.",
    )

    by_region = base.groupby(["year_quarter", "region_group"], as_index=False)[
        ["cur", "prev"]
    ].sum()
    by_region = by_region[by_region.prev > 0]
    by_region["yoy"] = by_region.cur / by_region.prev - 1
    by_region["quarter"] = by_region.year_quarter.map(yq_label)
    left, right = st.columns(2)
    with left:
        fig = px.line(
            by_region,
            x="quarter",
            y="yoy",
            color="region_group",
            markers=True,
            color_discrete_map=REGION_COLORS,
            category_orders={"region_group": REGIONS},
            title=f"{metric_name}: year-on-year change, same companies",
            labels={"yoy": "", "quarter": "", "region_group": "Region"},
        )
        fig.update_yaxes(tickformat="+.0%")
        fig.update_traces(hovertemplate="%{y:+.1%}")
        st.plotly_chart(style(fig), use_container_width=True)
        table_view(by_region[["quarter", "region_group", "cur", "prev", "yoy"]])

    with right:
        sectors = now.groupby(["section_code", "section_name"], as_index=False)[
            ["cur", "prev", "total"]
        ].sum()
        sectors = sectors[(sectors.prev > 0) & (sectors.section_code != "?")]
        sectors["yoy"] = sectors.cur / sectors.prev - 1
        sectors = sectors.sort_values("yoy")
        fig = go.Figure(
            go.Bar(
                x=sectors.yoy,
                y=sectors.section_name,
                orientation="h",
                marker_color=[POSITIVE if v >= 0 else NEGATIVE for v in sectors.yoy],
                customdata=sectors.total,
                hovertemplate="%{y}: %{x:+.1%}<br>total %{customdata:,.0f}<extra></extra>",
            )
        )
        fig.update_layout(
            title=f"{metric_name} by sector, {yq_label(latest)} vs a year earlier",
            hovermode="closest",
        )
        fig.update_xaxes(tickformat="+.0%")
        st.plotly_chart(style(fig, height=520), use_container_width=True)
        table_view(sectors[["section_code", "section_name", "total", "cur", "prev", "yoy"]])

    tpe_region = now.groupby("region_group", as_index=False)[["t_emp", "e_emp"]].sum()
    tpe_region = tpe_region[tpe_region.e_emp > 0]
    tpe_region["turnover_per_employee"] = tpe_region.t_emp / tpe_region.e_emp
    tpe_region = tpe_region.sort_values("turnover_per_employee")
    fig = px.bar(
        tpe_region,
        x="turnover_per_employee",
        y="region_group",
        orientation="h",
        color="region_group",
        color_discrete_map=REGION_COLORS,
        title=f"Quarterly turnover per employee, {yq_label(latest)} (EUR)",
        labels={"turnover_per_employee": "", "region_group": ""},
    )
    fig.update_layout(showlegend=False, hovermode="closest")
    fig.update_traces(hovertemplate="%{y}: %{x:,.0f} EUR<extra></extra>")
    st.plotly_chart(style(fig, height=260), use_container_width=True)
    st.caption(
        "EMTA turnover = VAT-declared supply incl. reverse-charge purchases, shifted one month "
        "(Q1 = December-February). Employees = employment-register entries on the last day of "
        "the quarter. Sector and county are those published with the first stored release "
        "after each quarter; for quarters before our first snapshot this is today's value."
    )

# ------------------------------------------------------------------------------ Fundamentals
with fundamentals_tab:
    fy = q(
        "select * from marts.mart_sector_fundamentals_year where section_code <> '?' "
        "order by fiscal_year, section_code"
    )
    years = sorted(fy.fiscal_year.unique())
    year = st.select_slider("Fiscal year", years, value=years[-2] if len(years) > 1 else years[-1])
    st.caption(
        "The newest fiscal year is incomplete: reports are filed until mid-year. "
        "Sectors with fewer than 20 reports are left out of the charts (see the table)."
    )
    all_sectors = fy[fy.fiscal_year == year]
    one = all_sectors[all_sectors.n_reports >= 20].sort_values("revenue_per_fte")
    left, right = st.columns(2)
    with left:
        fig = px.bar(
            one,
            x="revenue_per_fte",
            y="section_name",
            orientation="h",
            title=f"Revenue per FTE employee, {year} (EUR)",
            labels={"revenue_per_fte": "", "section_name": ""},
            color_discrete_sequence=[SERIES[0]],
        )
        fig.update_layout(hovermode="closest")
        fig.update_traces(hovertemplate="%{y}: %{x:,.0f} EUR<extra></extra>")
        st.plotly_chart(style(fig, height=520), use_container_width=True)
    with right:
        one2 = one.sort_values("net_margin_median")
        fig = go.Figure(
            go.Bar(
                x=one2.net_margin_median,
                y=one2.section_name,
                orientation="h",
                marker_color=[POSITIVE if v >= 0 else NEGATIVE for v in one2.net_margin_median],
                hovertemplate="%{y}: %{x:.1%}<extra></extra>",
            )
        )
        fig.update_layout(title=f"Median net margin, {year}", hovermode="closest")
        fig.update_xaxes(tickformat=".0%")
        st.plotly_chart(style(fig, height=520), use_container_width=True)
    table_view(
        all_sectors[
            [
                "section_code",
                "section_name",
                "n_reports",
                "revenue_total",
                "revenue_median",
                "fte_total",
                "revenue_per_fte",
                "labour_expense_share_of_revenue",
                "net_margin_median",
                "share_loss_making",
                "equity_ratio_median",
            ]
        ]
    )

# ------------------------------------------------------------------------------- Consistency
with consistency_tab:
    st.markdown(
        "Same companies, same calendar year, two sources. The ratios are **not expected to be "
        "1**: EMTA turnover includes reverse-charge purchases and is shifted by one month; "
        "labour taxes are cash paid, labour expense is accrued gross cost; headcount at "
        "quarter end is not full-time equivalents."
    )
    cmp = q(
        """
        select fiscal_year,
               count(*) as companies,
               median(turnover_to_revenue_ratio) filter (where ar_revenue > 0
                   and emta_turnover_4q > 0) as turnover_to_revenue,
               avg(case when abs(turnover_to_revenue_ratio - 1) <= 0.25 then 1.0 else 0.0 end)
                   filter (where ar_revenue > 0 and emta_turnover_4q > 0)
                   as share_turnover_within_25pct,
               median(labour_taxes_to_expense_ratio) filter (where ar_labour_expense > 0
                   and emta_labour_taxes_4q > 0) as labour_taxes_to_expense,
               median(employees_to_fte_ratio) filter (where ar_fte_employees > 0
                   and emta_avg_employees > 0) as headcount_to_fte
        from marts.mart_emta_vs_annual_report
        group by 1 order by 1
        """
    )
    long = cmp.melt(
        id_vars="fiscal_year",
        value_vars=["turnover_to_revenue", "labour_taxes_to_expense", "headcount_to_fte"],
        var_name="ratio",
        value_name="median",
    )
    fig = px.line(
        long,
        x="fiscal_year",
        y="median",
        color="ratio",
        markers=True,
        color_discrete_sequence=SERIES,
        title="Median ratio EMTA / annual report",
        labels={"median": "", "fiscal_year": ""},
    )
    fig.update_xaxes(dtick=1)
    fig.update_traces(hovertemplate="%{y:.2f}")
    st.plotly_chart(style(fig), use_container_width=True)
    table_view(cmp)

    ratios = q(
        """select turnover_to_revenue_ratio as r from marts.mart_emta_vs_annual_report
           where fiscal_year = (select max(fiscal_year) - 1 from marts.mart_emta_vs_annual_report)
             and ar_revenue > 0 and emta_turnover_4q > 0
             and turnover_to_revenue_ratio between 0 and 3"""
    )
    fig = px.histogram(
        ratios,
        x="r",
        nbins=60,
        color_discrete_sequence=[SERIES[0]],
        title="Distribution of EMTA turnover / annual revenue (ratios 0-3)",
        labels={"r": "ratio"},
    )
    fig.update_layout(bargap=0.08, hovermode="closest")
    st.plotly_chart(style(fig, height=300), use_container_width=True)

# ---------------------------------------------------------------------------- Company lookup
with company_tab:
    term = st.text_input("Registry code or company name (legal entities only)")
    if term:
        found = q(
            """select registry_code, company_name, legal_form, status_name, section_code,
                      region_group, is_in_register_now
               from marts.dim_company
               where registry_code = ? or company_name ilike '%' || ? || '%'
               order by is_in_register_now desc, company_name limit 50""",
            [term.strip(), term.strip()],
        )
        if found.empty:
            st.info("No match.")
        else:
            code = st.selectbox(
                "Company",
                found.registry_code,
                format_func=lambda c: f"{c} - {found.set_index('registry_code').company_name[c]}",
            )
            qtr = q(
                """select year_quarter, employees, turnover, labour_taxes, state_taxes,
                              is_in_latest_release, section_code, region_group
                       from marts.fct_company_quarter where registry_code = ?
                       order by year_quarter""",
                [code],
            )
            qtr["quarter"] = qtr.year_quarter.map(yq_label)
            left, right = st.columns(2)
            for col, (field, title) in zip(
                (left, right),
                [
                    ("employees", "Employees at quarter end"),
                    ("turnover", "Quarterly turnover (EUR)"),
                ],
                strict=True,
            ):
                fig = px.line(
                    qtr,
                    x="quarter",
                    y=field,
                    markers=True,
                    title=title,
                    color_discrete_sequence=[SERIES[0]],
                    labels={field: "", "quarter": ""},
                )
                col.plotly_chart(style(fig, height=300), use_container_width=True)
            table_view(qtr.drop(columns="year_quarter"), "Quarterly values")
            st.subheader("Register history (SCD Type 2)")
            st.dataframe(
                q(
                    """select version_number, valid_from, valid_to, is_present,
                                     company_name, legal_form, status_name, ehak_name
                              from marts.dim_company_history where registry_code = ?
                              order by version_number""",
                    [code],
                ),
                hide_index=True,
                use_container_width=True,
            )
            st.subheader("Annual reports")
            st.dataframe(
                q(
                    """select fiscal_year, revenue, net_profit, labour_expense,
                                     fte_employees, total_assets, equity, n_conflicting_elements
                              from marts.fct_annual_fundamentals where registry_code = ?
                              order by fiscal_year""",
                    [code],
                ),
                hide_index=True,
                use_container_width=True,
            )

# ------------------------------------------------------------------------------ Data quality
with quality_tab:
    st.subheader("Every rule that removes, nulls, or flags data")
    dq = q("select * from marts.mart_data_quality")
    dq["share"] = dq.affected / dq.out_of
    st.dataframe(
        dq,
        hide_index=True,
        use_container_width=True,
        column_config={"share": st.column_config.NumberColumn(format="percent")},
    )
    left, right = st.columns(2)
    with left:
        st.subheader("EMTA companies vs register")
        st.dataframe(
            q("""select match_reason, count(*) as companies,
                                 count(*) filter (where last_reporting_year_quarter =
                                     (select max(last_reporting_year_quarter)
                                      from marts.mart_join_coverage)) as reporting_in_newest_quarter
                          from marts.mart_join_coverage group by 1 order by 2 desc"""),
            hide_index=True,
            use_container_width=True,
        )
    with right:
        st.subheader("EMTA revisions between releases")
        rev = q("select * from marts.mart_emta_revisions_summary")
        if rev.empty:
            st.info("No revisions yet: needs two stored EMTA releases (next release ~10 Oct).")
        else:
            st.dataframe(rev, hide_index=True, use_container_width=True)
    st.subheader("Stored snapshots")
    st.dataframe(
        q("""select source, snapshot_id, retrieved_at, publisher_last_modified_at,
                             cutoff_date, size_bytes, rows_total, rows_kept, rows_dropped,
                             left(sha256, 12) as sha256
                      from marts.mart_pipeline_snapshots order by source, snapshot_id"""),
        hide_index=True,
        use_container_width=True,
    )
