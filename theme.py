"""Visual theme for ProdSched Nexus (frontend only).

This module changes how the app LOOKS. It never changes how it WORKS:
no scheduling, simulation, disruption, database or analytics code lives here.

What it provides:
- inject_theme()      : the app-wide CSS (navy, white and soft teal)
- sidebar_brand()     : logo and product name at the top of the sidebar
- sidebar_status()    : the small "Workshop status" panel in the sidebar
- hero()              : the home (Dashboard) banner with a live mini timeline
- style_figure()      : restyles any Plotly figure (colours, fonts, spacing)
- themed_chart()      : drop-in replacement for st.plotly_chart(fig, ...)
"""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any, Iterable, Sequence

import streamlit as st

# -----------------------------------------------------------------------------
# Design tokens
# -----------------------------------------------------------------------------
NAVY_950 = "#0A1A31"   # sidebar background
NAVY_900 = "#0F2442"   # hero background
INK = "#12294A"        # headings and main text
BODY = "#3A4B66"       # paragraph text
MUTED = "#6A7891"      # secondary text
TEAL = "#14A394"       # soft teal highlight
TEAL_DEEP = "#0C7F74"  # buttons (keeps white text readable)
TEAL_SOFT = "#E4F5F2"  # teal tint backgrounds
PAGE = "#F3F6F9"       # page background
LINE = "#E2E8F0"       # borders
GOOD = "#1F8A5B"
WARN = "#B7791F"
BAD = "#C2414B"

FONT = "'Manrope', 'Segoe UI', system-ui, -apple-system, sans-serif"
FONT_PLAIN = "Manrope, Segoe UI, system-ui, -apple-system, sans-serif"

# Calm, distinguishable job colours (navy and teal family first)
JOB_COLOURS = ("#1F4E8C", "#14A394", "#6C7FC4", "#3A8FC7", "#D2A043", "#7B5EA7", "#2F6F73", "#8A99B3")

# Old chart colours (from analytics.py and app.py) -> new theme colours.
# Charts are recoloured when shown; analytics.py itself is not modified.
COLOR_REMAP = {
    # Job palette
    "#2563EB": JOB_COLOURS[0],
    "#0284C7": TEAL,
    "#4F46E5": JOB_COLOURS[2],
    "#0D9488": "#3A8FC7",
    "#D97706": JOB_COLOURS[4],
    # Plotly default fallback palette (used for extra jobs)
    "#636EFA": "#1F4E8C", "#EF553B": "#C2414B", "#00CC96": TEAL, "#AB63FA": "#7B5EA7",
    "#FFA15A": "#D2A043", "#19D3F3": "#3A8FC7", "#FF6692": "#C2697B", "#B6E880": "#7FB38A",
    "#FF97FF": "#B08AC4", "#FECB52": "#D9B45A",
    # Urgent jobs and breakdowns
    "#DC2626": BAD,
    "#EF4444": "#E07A7F",
    "#B91C1C": "#A3333C",
    # Busy / idle / waiting
    "#94A3B8": "#C5CFDB",
    "#F59E0B": "#E3B04B",
    "#7C3AED": JOB_COLOURS[2],
    "#4B5563": "#8A99B3",
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


# -----------------------------------------------------------------------------
# CSS
# -----------------------------------------------------------------------------
_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

:root {{
  --ps-navy-950: {NAVY_950}; --ps-navy-900: {NAVY_900};
  --ps-ink: {INK}; --ps-body: {BODY}; --ps-muted: {MUTED};
  --ps-teal: {TEAL}; --ps-teal-deep: {TEAL_DEEP}; --ps-teal-soft: {TEAL_SOFT};
  --ps-page: {PAGE}; --ps-line: {LINE};
  --ps-good: {GOOD}; --ps-warn: {WARN}; --ps-bad: {BAD};
  --ps-font: {FONT};
  --ps-radius: 14px;
  --ps-shadow: 0 1px 2px rgba(10, 26, 49, 0.04), 0 6px 20px rgba(10, 26, 49, 0.06);
}}

/* ---------- Base ---------- */
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp li, .stApp td, .stApp th,
.stApp [data-testid="stMarkdownContainer"] {{
  font-family: var(--ps-font);
}}
.stApp {{ background: var(--ps-page); color: var(--ps-ink); }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{
  padding-top: 1.6rem !important; padding-bottom: 3rem !important;
  padding-left: 2.4rem !important; padding-right: 2.4rem !important;
  max-width: 1360px;
}}
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 {{ color: var(--ps-ink); letter-spacing: -0.01em; }}
.stApp p, .stApp li {{ color: var(--ps-body); }}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, var(--ps-navy-950) 0%, #0E2341 100%);
  border-right: none;
}}
[data-testid="stSidebar"] * {{ color: #DCE5F0; }}
[data-testid="stSidebar"] hr {{ border-top: 1px solid rgba(255,255,255,0.10) !important; }}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{
  color: #8FA3BD !important; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.02em;
  margin-top: 0.4rem;
}}

/* Sidebar radio menus look like navigation items */
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 0.2rem; display: flex; flex-direction: column; align-items: stretch; width: 100%; }}
[data-testid="stSidebar"] [data-testid="stRadio"], [data-testid="stSidebar"] [data-testid="stRadio"] > div {{ width: 100%; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  width: 100%; box-sizing: border-box; margin: 0 !important; padding: 0.55rem 0.8rem; border-radius: 10px;
  border: 1px solid transparent; cursor: pointer; transition: background 0.15s ease;
}}
/* hide the radio dot (works for older and newer Streamlit layouts) */
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child:not(:has([data-testid="stMarkdownContainer"])),
[data-testid="stSidebar"] [role="radiogroup"] label > div > div:first-child:not([data-testid="stMarkdownContainer"]) {{ display: none !important; }}
[data-testid="stSidebar"] [role="radiogroup"] label p {{
  color: #C8D4E3 !important; font-size: 0.93rem; font-weight: 600;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: rgba(255,255,255,0.06); }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked),
[data-testid="stSidebar"] [role="radiogroup"] label[data-selected="true"] {{
  background: rgba(20, 163, 148, 0.16); border-color: rgba(20, 163, 148, 0.45);
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p,
[data-testid="stSidebar"] [role="radiogroup"] label[data-selected="true"] p {{ color: #FFFFFF !important; }}

/* Sidebar buttons */
[data-testid="stSidebar"] .stButton button {{
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.16);
  border-radius: 10px; box-shadow: none;
}}
[data-testid="stSidebar"] .stButton button:hover {{ background: rgba(255,255,255,0.12); border-color: var(--ps-teal); }}
[data-testid="stSidebar"] .stButton button p {{ color: #FFFFFF !important; font-weight: 600; }}

.ps-brand {{ display: flex; align-items: center; gap: 0.75rem; padding: 0.2rem 0 0.4rem; }}
.ps-brand img {{ width: 44px; height: 44px; border-radius: 11px; box-shadow: 0 4px 14px rgba(0,0,0,0.35); }}
.ps-brand-name {{ font-size: 1.12rem; font-weight: 800; color: #FFFFFF !important; letter-spacing: -0.01em; line-height: 1.15; }}
.ps-brand-sub {{ font-size: 0.78rem; color: #8FA3BD !important; margin-top: 2px; }}

.ps-side-card {{
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.10);
  border-radius: 12px; padding: 0.8rem 0.9rem; margin: 0.2rem 0 0.7rem;
}}
.ps-side-title {{ font-size: 0.78rem; font-weight: 700; color: #8FA3BD !important; margin-bottom: 0.45rem; }}
.ps-side-row {{ display: flex; justify-content: space-between; align-items: center; padding: 0.2rem 0; font-size: 0.86rem; }}
.ps-side-row span {{ color: #AFC0D4 !important; }}
.ps-side-row b {{ color: #FFFFFF !important; font-variant-numeric: tabular-nums; }}
.ps-side-row b.ps-up {{ color: #F4A7AC !important; }}
.ps-pill {{ display: inline-block; padding: 0.12rem 0.55rem; border-radius: 999px; font-size: 0.74rem; font-weight: 700; }}
.ps-pill.ok  {{ background: rgba(20,163,148,0.22); color: #7FE3D6 !important; }}
.ps-pill.bad {{ background: rgba(194,65,75,0.25); color: #FFB8BD !important; }}

/* ---------- Home hero ---------- */
.ps-hero {{
  position: relative; overflow: hidden;
  display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 2rem;
  background: radial-gradient(120% 140% at 100% 0%, rgba(20,163,148,0.22) 0%, rgba(20,163,148,0) 55%), var(--ps-navy-900);
  border-radius: 20px; padding: 1.8rem 2rem; margin: 0 0 1.4rem;
  box-shadow: 0 12px 32px rgba(10, 26, 49, 0.18);
}}
.ps-hero-kicker {{ color: #7FE3D6; font-size: 0.85rem; font-weight: 700; margin-bottom: 0.45rem; }}
.ps-hero h1 {{ color: #FFFFFF !important; font-size: 2.05rem; font-weight: 800; line-height: 1.15; margin: 0 0 0.5rem; padding: 0; }}
.ps-hero p {{ color: #B9C7D9 !important; font-size: 1rem; margin: 0 0 1.3rem; max-width: 46ch; line-height: 1.55; }}
.ps-hero-stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.6rem; }}
.ps-hero-stat {{ background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10); border-radius: 12px; padding: 0.7rem 0.8rem; }}
.ps-hero-stat b {{ display: block; color: #FFFFFF; font-size: 1.35rem; font-weight: 800; font-variant-numeric: tabular-nums; line-height: 1.2; }}
.ps-hero-stat b small {{ font-size: 0.8rem; font-weight: 600; color: #9FB2C9; margin-left: 0.2rem; }}
.ps-hero-stat span {{ color: #9FB2C9; font-size: 0.78rem; font-weight: 600; }}
.ps-hero-stat.ok b {{ color: #7FE3D6; }}
.ps-hero-stat.bad b {{ color: #FFB8BD; }}

.ps-plan {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.10); border-radius: 14px; padding: 1rem 1.1rem 0.9rem; align-self: center; }}
.ps-plan-title {{ display: flex; justify-content: space-between; color: #DCE5F0; font-size: 0.85rem; font-weight: 700; margin-bottom: 0.75rem; }}
.ps-plan-title span {{ color: #8FA3BD; font-weight: 600; }}
.ps-plan-row {{ display: grid; grid-template-columns: 84px 1fr; align-items: center; gap: 0.7rem; margin-bottom: 0.55rem; }}
.ps-plan-row label {{ color: #AFC0D4; font-size: 0.8rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.ps-plan-track {{ position: relative; height: 20px; background: rgba(255,255,255,0.05); border-radius: 6px; }}
.ps-plan-bar {{ position: absolute; top: 2px; bottom: 2px; border-radius: 5px; }}
.ps-plan-bar.down {{ background: repeating-linear-gradient(45deg, rgba(224,122,127,0.85) 0 4px, rgba(224,122,127,0.35) 4px 8px); }}
.ps-plan-axis {{ display: flex; justify-content: space-between; margin-left: calc(84px + 0.7rem); color: #7F93AC; font-size: 0.72rem; font-variant-numeric: tabular-nums; }}

@keyframes ps-grow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
.ps-plan-bar {{ transform-origin: left center; animation: ps-grow 0.6s ease-out both; }}
@media (prefers-reduced-motion: reduce) {{ .ps-plan-bar {{ animation: none; }} }}

/* ---------- Existing page header ---------- */
.nexus-page-header {{ margin: 0 0 1.3rem; padding: 0; border: none; }}
.nexus-page-title {{ font-size: 1.75rem !important; font-weight: 800 !important; color: var(--ps-ink) !important; letter-spacing: -0.015em; margin: 0 !important; padding: 0 !important; line-height: 1.2; }}
.nexus-page-title::after {{ content: ""; display: block; width: 44px; height: 4px; border-radius: 4px; background: var(--ps-teal); margin-top: 0.6rem; }}
.nexus-page-subtitle {{ font-size: 0.98rem !important; color: var(--ps-muted) !important; margin-top: 0.55rem !important; max-width: 75ch; line-height: 1.5; }}

/* ---------- Cards ---------- */
.nexus-card, .nexus-kpi-card {{
  background: #FFFFFF !important; border: 1px solid var(--ps-line) !important;
  border-radius: var(--ps-radius) !important; box-shadow: var(--ps-shadow) !important;
}}
.nexus-card {{ padding: 1rem 1.2rem; margin-bottom: 0.85rem; }}
.nexus-kpi-card {{ padding: 1rem 1.1rem !important; margin-bottom: 0.9rem; min-height: 112px; }}
.nexus-kpi-label {{ font-size: 0.82rem !important; font-weight: 700 !important; color: var(--ps-muted) !important; text-transform: none !important; letter-spacing: 0 !important; margin-bottom: 0.35rem !important; }}
.nexus-kpi-val {{ font-size: 1.7rem !important; font-weight: 800 !important; line-height: 1.15 !important; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }}
.nexus-kpi-sub {{ font-size: 0.8rem !important; color: var(--ps-muted) !important; margin-top: 0.3rem !important; }}

/* Badges */
.nexus-badge {{ padding: 0.18rem 0.6rem !important; border-radius: 999px !important; font-size: 0.74rem !important; font-weight: 700 !important; }}
.badge-success {{ background: #E6F4EC !important; color: var(--ps-good) !important; border: 1px solid #BFE2CE !important; }}
.badge-warning {{ background: #FBF1E0 !important; color: var(--ps-warn) !important; border: 1px solid #F0D7AA !important; }}
.badge-danger  {{ background: #FBE9EA !important; color: var(--ps-bad) !important; border: 1px solid #F1C4C8 !important; }}
.badge-info    {{ background: var(--ps-teal-soft) !important; color: var(--ps-teal-deep) !important; border: 1px solid #B9E4DD !important; }}
.badge-neutral {{ background: #F1F4F8 !important; color: var(--ps-muted) !important; border: 1px solid var(--ps-line) !important; }}

/* Callout */
.nexus-callout {{
  background: var(--ps-teal-soft) !important; border: 1px solid #C6E9E3 !important;
  border-left: 4px solid var(--ps-teal) !important; border-radius: 12px !important;
  padding: 0.85rem 1.1rem !important; color: var(--ps-ink) !important; font-size: 0.92rem !important;
}}

/* Section headers */
.nexus-section-header {{
  font-size: 1.12rem !important; font-weight: 800 !important; color: var(--ps-ink) !important;
  margin: 1.5rem 0 0.75rem !important;
  display: flex !important; align-items: center; gap: 0.6rem !important;
}}
.nexus-section-header::before {{
  content: ""; width: 4px; height: 1.05em; border-radius: 4px; background: var(--ps-teal); display: inline-block;
}}

/* ---------- Charts, tables, forms ---------- */
[data-testid="stPlotlyChart"] {{
  background: #FFFFFF; border: 1px solid var(--ps-line); border-radius: var(--ps-radius);
  box-shadow: var(--ps-shadow); padding: 0.6rem 0.6rem 0.2rem; overflow: hidden;
}}
[data-testid="stDataFrame"] {{
  border: 1px solid var(--ps-line); border-radius: var(--ps-radius); box-shadow: var(--ps-shadow);
  overflow: hidden; background: #FFFFFF;
}}
[data-testid="stTable"] {{ border-radius: var(--ps-radius); overflow: hidden; box-shadow: var(--ps-shadow); border: 1px solid var(--ps-line); background: #FFFFFF; }}
[data-testid="stTable"] table {{ border-collapse: collapse; width: 100%; }}
[data-testid="stTable"] th {{ background: #F4F7FA !important; color: var(--ps-ink) !important; font-weight: 700 !important; font-size: 0.85rem; border-bottom: 1px solid var(--ps-line) !important; }}
[data-testid="stTable"] td {{ color: var(--ps-body) !important; font-size: 0.88rem; border-bottom: 1px solid #EEF2F6 !important; }}

[data-testid="stForm"] {{
  background: #FFFFFF; border: 1px solid var(--ps-line) !important; border-radius: 16px !important;
  box-shadow: var(--ps-shadow); padding: 1.3rem 1.4rem !important;
}}
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{
  border-radius: 10px !important; border-color: #D6DEE8 !important; background: #FFFFFF !important;
}}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {{
  border-color: var(--ps-teal) !important; box-shadow: 0 0 0 3px rgba(20,163,148,0.15) !important;
}}
.stApp [data-testid="stWidgetLabel"] p {{ font-weight: 600; color: var(--ps-ink); font-size: 0.88rem; }}

/* Buttons */
.stButton button, .stDownloadButton button, .stFormSubmitButton button {{
  border-radius: 10px !important; font-weight: 700 !important; min-height: 2.6rem;
  transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}}
.stApp button[kind="primary"], .stApp button[kind="primaryFormSubmit"],
.stApp [data-testid="stBaseButton-primary"], .stApp [data-testid="stBaseButton-primaryFormSubmit"] {{
  background: var(--ps-teal-deep) !important; border: 1px solid var(--ps-teal-deep) !important;
  color: #FFFFFF !important; box-shadow: 0 4px 14px rgba(12,127,116,0.25) !important;
}}
.stApp button[kind="primary"]:hover, .stApp button[kind="primaryFormSubmit"]:hover,
.stApp [data-testid="stBaseButton-primary"]:hover, .stApp [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
  background: #0A6C63 !important; border-color: #0A6C63 !important;
}}
.stApp button[kind="primary"] p, .stApp button[kind="primaryFormSubmit"] p {{ color: #FFFFFF !important; }}
.stApp .main button[kind="secondary"], .stApp .main .stDownloadButton button,
.stApp [data-testid="stMain"] button[kind="secondary"], .stApp [data-testid="stMain"] .stDownloadButton button {{
  background: #FFFFFF !important; border: 1px solid #CFD9E4 !important; color: var(--ps-ink) !important;
}}
.stApp [data-testid="stMain"] button[kind="secondary"]:hover, .stApp [data-testid="stMain"] .stDownloadButton button:hover {{
  border-color: var(--ps-teal) !important; color: var(--ps-teal-deep) !important;
}}

/* Tabs as a segmented control (old and new Streamlit markup) */
[data-testid="stMain"] [role="tablist"], .stTabs [data-baseweb="tab-list"] {{
  gap: 0.25rem; background: #E7EDF3; padding: 0.3rem; border-radius: 12px;
  width: fit-content; max-width: 100%; overflow-x: auto; border: none !important;
}}
[data-testid="stMain"] [role="tab"], .stTabs [data-baseweb="tab"] {{
  border-radius: 9px !important; padding: 0.45rem 1rem !important; height: auto; background: transparent; border: none !important;
}}
[data-testid="stMain"] [role="tab"] p, .stTabs [data-baseweb="tab"] p {{ font-weight: 700; color: var(--ps-muted); font-size: 0.9rem; }}
[data-testid="stMain"] [role="tab"][aria-selected="true"], .stTabs [aria-selected="true"] {{
  background: #FFFFFF !important; box-shadow: 0 1px 3px rgba(10,26,49,0.10);
}}
[data-testid="stMain"] [role="tab"][aria-selected="true"] p, .stTabs [aria-selected="true"] p {{ color: var(--ps-ink) !important; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"],
[data-testid="stMain"] [data-testid="stTabsHighlight"], [data-testid="stMain"] [role="tablist"] + div[aria-hidden="true"] {{ display: none !important; }}
[data-testid="stMain"] [role="tablist"] > div:not([role="tab"]) {{ display: none !important; }}

/* Expanders and alerts */
[data-testid="stExpander"] details {{ background: #FFFFFF; border: 1px solid var(--ps-line) !important; border-radius: 12px !important; box-shadow: var(--ps-shadow); }}
[data-testid="stExpander"] summary p {{ font-weight: 700; color: var(--ps-ink); }}
[data-testid="stAlert"] > div {{ border-radius: 12px; }}

/* ---------- Responsive ---------- */
@media (max-width: 1100px) {{
  .ps-hero {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 760px) {{
  .block-container {{ padding-left: 1rem !important; padding-right: 1rem !important; }}
  .ps-hero {{ padding: 1.3rem 1.2rem; border-radius: 16px; }}
  .ps-hero h1 {{ font-size: 1.6rem; }}
  .ps-hero-stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .nexus-page-title {{ font-size: 1.45rem !important; }}
}}
</style>
"""


def inject_theme() -> None:
    """Add the app-wide CSS. Call once near the top of app.py."""
    st.markdown(_CSS, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Sidebar pieces
# -----------------------------------------------------------------------------
def _logo_data_uri(path: Path) -> str | None:
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def sidebar_brand(logo_path: Path, subtitle: str) -> None:
    uri = _logo_data_uri(logo_path)
    logo = f'<img src="{uri}" alt="ProdSched Nexus logo"/>' if uri else ""
    st.markdown(
        f'<div class="ps-brand">{logo}<div><div class="ps-brand-name">ProdSched Nexus</div>'
        f'<div class="ps-brand-sub">{_esc(subtitle)}</div></div></div>',
        unsafe_allow_html=True,
    )


def sidebar_status(base_mk: int, rev_mk: int, active_disruptions: int) -> None:
    state = (
        f'<span class="ps-pill bad">{active_disruptions} Disruption(s)</span>'
        if active_disruptions > 0
        else '<span class="ps-pill ok">Nominal</span>'
    )
    revised = (
        f'<div class="ps-side-row"><span>Revised Makespan</span><b class="ps-up">{rev_mk} min</b></div>'
        if active_disruptions > 0
        else ""
    )
    st.markdown(
        f"""
        <div class="ps-side-card">
          <div class="ps-side-title">Workshop Status</div>
          <div class="ps-side-row"><span>Baseline Makespan</span><b>{base_mk} min</b></div>
          <div class="ps-side-row"><span>Active State</span>{state}</div>
          {revised}
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Home hero
# -----------------------------------------------------------------------------
def hero(
    title: str,
    subtitle: str,
    schedule: Any,
    machines: Sequence[Any],
    jobs_count: int,
    active_disruptions: int,
) -> None:
    """Dashboard banner: headline, four live numbers and a mini timeline of the current plan."""
    total = int(getattr(schedule, "makespan_min", 0) or 0)
    status_cls = "bad" if active_disruptions else "ok"
    status_txt = f"{active_disruptions} active" if active_disruptions else "On plan"

    stats = (
        f'<div class="ps-hero-stat"><b>{total}<small>min</small></b><span>Production time</span></div>'
        f'<div class="ps-hero-stat"><b>{jobs_count}</b><span>Jobs</span></div>'
        f'<div class="ps-hero-stat"><b>{len(machines)}</b><span>Machines</span></div>'
        f'<div class="ps-hero-stat {status_cls}"><b>{_esc(status_txt)}</b><span>Disruptions</span></div>'
    )

    plan_html = ""
    ops = tuple(getattr(schedule, "operations", ()) or ())
    if total > 0 and ops:
        job_ids = sorted({op.job_id for op in ops})
        colours = {jid: JOB_COLOURS[i % len(JOB_COLOURS)] for i, jid in enumerate(job_ids)}
        rows = []
        for m in list(machines)[:6]:
            bars = []
            for dt in getattr(schedule, "downtimes", ()) or ():
                if dt.machine_id == m.machine_id:
                    left, width = 100 * dt.start_min / total, 100 * dt.duration_min / total
                    bars.append(f'<div class="ps-plan-bar down" style="left:{left:.2f}%;width:{width:.2f}%"></div>')
            for op in ops:
                if op.machine_id == m.machine_id:
                    left, width = 100 * op.start_min / total, 100 * op.duration_min / total
                    colour = BAD if getattr(op, "is_urgent", False) else colours[op.job_id]
                    bars.append(
                        f'<div class="ps-plan-bar" title="{_esc(op.job_id)}: minute {op.start_min} to {op.end_min}" '
                        f'style="left:{left:.2f}%;width:{max(width - 0.4, 0.6):.2f}%;background:{colour}"></div>'
                    )
            rows.append(
                f'<div class="ps-plan-row"><label>{_esc(m.name)}</label>'
                f'<div class="ps-plan-track">{"".join(bars)}</div></div>'
            )
        plan_html = (
            '<div class="ps-plan"><div class="ps-plan-title">Current plan<span>each bar is one job step</span></div>'
            + "".join(rows)
            + f'<div class="ps-plan-axis"><span>0</span><span>{total // 2}</span><span>{total} min</span></div></div>'
        )

    st.markdown(
        f"""
        <section class="ps-hero">
          <div>
            <div class="ps-hero-kicker">Workshop Production Planner</div>
            <h1>{_esc(title)}</h1>
            <p>{_esc(subtitle)}</p>
            <div class="ps-hero-stats">{stats}</div>
          </div>
          {plan_html}
        </section>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Plotly styling
# -----------------------------------------------------------------------------
def _remap(value: Any) -> Any:
    """Map one colour (or a list of colours) to the theme palette."""
    if isinstance(value, str):
        return COLOR_REMAP.get(value.upper(), value)
    if isinstance(value, (list, tuple)) or hasattr(value, "tolist"):
        items: Iterable[Any] = value.tolist() if hasattr(value, "tolist") else value
        return [COLOR_REMAP.get(v.upper(), v) if isinstance(v, str) else v for v in items]
    return value


def style_figure(fig: Any) -> Any:
    """Recolour and restyle a Plotly figure. Data and values are not changed."""
    for trace in fig.data:
        marker = getattr(trace, "marker", None)
        if marker is not None:
            if marker.color is not None:
                marker.color = _remap(marker.color)
            line = getattr(marker, "line", None)
            if line is not None and line.color is not None:
                line.color = _remap(line.color)
            pattern = getattr(marker, "pattern", None)
            if pattern is not None and getattr(pattern, "shape", None):
                pattern.fgcolor = "#A3333C"
                pattern.solidity = 0.3
        tline = getattr(trace, "line", None)
        if tline is not None and getattr(tline, "color", None) is not None:
            tline.color = _remap(tline.color)
        textfont = getattr(trace, "textfont", None)
        if textfont is not None:
            textfont.family = FONT_PLAIN

    fig.update_layout(
        font=dict(family=FONT_PLAIN, color=INK, size=12),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        hoverlabel=dict(bgcolor=NAVY_900, bordercolor=NAVY_900, font=dict(family=FONT_PLAIN, color="#FFFFFF", size=12)),
        legend=dict(font=dict(family=FONT_PLAIN, size=12, color=BODY), bgcolor="rgba(0,0,0,0)"),
    )
    if fig.layout.title and fig.layout.title.text:
        fig.update_layout(title_font=dict(family=FONT_PLAIN, size=15, color=INK))
        # A legend placed above the plot collides with the title in narrow columns:
        # move it below the plot instead.
        legend_y = fig.layout.legend.y
        if legend_y is not None and legend_y >= 1 and fig.layout.showlegend is not False:
            bottom = (fig.layout.margin.b or 35) + 40
            fig.update_layout(
                legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0),
                margin=dict(b=bottom),
                height=(fig.layout.height or 300) + 30,
            )
    try:
        fig.update_layout(barcornerradius=5)
    except (ValueError, TypeError):
        pass  # older Plotly versions without rounded bars
    fig.update_xaxes(gridcolor="#EEF2F6", linecolor=LINE, zerolinecolor=LINE,
                     tickfont=dict(family=FONT_PLAIN, color=MUTED, size=11),
                     title_font=dict(family=FONT_PLAIN, color=MUTED, size=12))
    fig.update_yaxes(gridcolor="#EEF2F6", linecolor=LINE, zerolinecolor=LINE,
                     tickfont=dict(family=FONT_PLAIN, color=INK, size=12),
                     title_font=dict(family=FONT_PLAIN, color=MUTED, size=12))
    for ann in fig.layout.annotations or ():
        ann.font = dict(family=FONT_PLAIN, size=13, color=INK)
    return fig


def themed_chart(fig: Any, **kwargs: Any) -> None:
    """Show a Plotly figure with the theme applied. Same arguments as st.plotly_chart."""
    kwargs.setdefault("config", {"displaylogo": False})
    st.plotly_chart(style_figure(fig), **kwargs)
