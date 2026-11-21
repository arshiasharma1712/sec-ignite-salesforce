"""Pure-Python helpers for the dashboard: filtering, sorting, paging, HTML and CSS.

Nothing here imports Streamlit, so all of it can be unit-tested. app.py just
calls these functions and displays what they return.

Input is the pipeline result dict (see dev_only/pipeline_stub.py for the contract).
"""

import csv
import html
import io
import os
import re
import tempfile
import hashlib
import urllib.request

PRIORITIES = ["Critical", "High", "Medium", "Low"]
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}
STATUS_ASSIGNED = "Assigned"
STATUS_REVIEW = "Manager Review"
STATUS_HANDLED = "Handled"  # a manager dealt with it outside the system

SORT_OPTIONS = [
    "Priority (Critical first)",
    "Score (high to low)",
    "Score (low to high)",
    "Lead ID",
    "Company (A-Z)",
]

# --------------------------------------------------------------------------
# Theme. Palette: royal blue #022AC0, sky blue #90D0FE, turquoise #04E1CB, green #2E844A,
# purple #A76CF1; warm accents (used sparingly): yellow #F4D500 and pink #FA5D91.
# Light mode = white base with bubbly rounded cards. Dark mode is designed separately.
# The user picks light/dark with the toggle on the screen (the OS setting is ignored).
# --------------------------------------------------------------------------

ROYAL = "#022AC0"
SKY = "#90D0FE"
TURQUOISE = "#04E1CB"
GREEN = "#2E844A"
PURPLE = "#A76CF1"
YELLOW = "#F4D500"
PINK = "#FA5D91"

_FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
NAVY = "#032D60"  # header bar

_LIGHT = {
    "font": _FONT_STACK,
    "bg": "#F3F3F3", "page_bg": "#F3F3F3",
    "card": "#FFFFFF", "card2": "#F3F6F9",
    "text": "#181818", "strong": NAVY, "muted": "#555555",
    "border": "#C9C9C9", "border_strong": "#747474", "track": "#D9DFE5", "hover": "#EEF5FD",
    "accent": "#066AFE", "accent2": "#0B4FB8", "focus": "#0550C4",
    "teal": TURQUOISE, "green": GREEN, "sky": SKY, "purple": PURPLE, "yellow": YELLOW, "pink": PINK,
    "pink_solid": "#C23863",
    "review": SKY,
    "ok_bg": "#E1F2E6", "ok_text": "#14522C",
    "warn_bg": "#FFF0CD", "warn_text": "#684100", "warn_line": "#DD7A01",
    "critical": "#BA0517", "crit_bg": "#FCE6E8", "crit_text": "#870B17",
    "high": "#DD7A01", "high_bg": "#FFF0CD", "high_text": "#684100",
    "medium": "#1B96FF", "medium_bg": "#DCEEFF", "medium_text": "#003F83",
    "low": GREEN, "lowb_bg": "#E1F2E6", "lowb_text": "#14522C",
    "low_bg": "#DCEEFF", "on_low": "#003F83",
    "chip_bg": "#DCEEFF", "chip_text": "#003F83",
    "page_text": "#181818", "page_muted": "#555555",
    "hero_bg": NAVY, "hero_title": "#FFFFFF", "hero_sub": "#D9E9FA",
    "pill_bg": "#FFFFFF", "pill_text": NAVY,
    "btn_bg": "#FFFFFF", "btn_text": "#014486", "btn_border": "#747474",
    "primary_bg": "#066AFE", "primary_text": "#FFFFFF",
    "tab_text": "#181818", "tab_sel_bg": "transparent", "tab_sel_text": "#014486",
    "shadow": "0 1px 3px rgba(3,45,96,.10)",
}
_DARK = {
    "font": _FONT_STACK,
    "bg": "#0F1A2E", "page_bg": "#0F1A2E",
    "card": "#192840", "card2": "#14233A",
    "text": "#F3F6FB", "strong": "#FFFFFF", "muted": "#C9D4E5",
    "border": "#34476A", "border_strong": "#8396B3", "track": "#3A4C6E", "hover": "#213557",
    "accent": "#78B9F6", "accent2": "#A4D8FF", "focus": "#A4D8FF",
    "teal": TURQUOISE, "green": "#3BA755", "sky": SKY, "purple": PURPLE, "yellow": YELLOW, "pink": PINK,
    "pink_solid": "#C23863",
    "review": SKY,
    "ok_bg": "#1B563A", "ok_text": "#FFFFFF",
    "warn_bg": "#59421A", "warn_text": "#FFFFFF", "warn_line": "#FFB75D",
    "critical": "#FF8A94", "crit_bg": "#61222D", "crit_text": "#FFFFFF",
    "high": "#FFB75D", "high_bg": "#59421A", "high_text": "#FFFFFF",
    "medium": "#78B9F6", "medium_bg": "#254F7A", "medium_text": "#FFFFFF",
    "low": "#5FD08A", "lowb_bg": "#1B563A", "lowb_text": "#FFFFFF",
    "low_bg": "#254F7A", "on_low": "#FFFFFF",
    "chip_bg": "#254F7A", "chip_text": "#FFFFFF",
    "page_text": "#F3F6FB", "page_muted": "#C9D4E5",
    "hero_bg": NAVY, "hero_title": "#FFFFFF", "hero_sub": "#D9E9FA",
    "pill_bg": "#78B9F6", "pill_text": NAVY,
    "btn_bg": "#192840", "btn_text": "#F3F6FB", "btn_border": "#8396B3",
    "primary_bg": "#78B9F6", "primary_text": NAVY,
    "tab_text": "#F3F6FB", "tab_sel_bg": "transparent", "tab_sel_text": "#78B9F6",
    "shadow": "0 1px 3px rgba(0,0,0,.45)",
}


def _vars(palette):
    return "".join(f"--{name.replace('_', '-')}:{value};" for name, value in palette.items())


# --------------------------------------------------------------------------
# Settings (the ☰ menu): text size, high contrast, reduced motion and table density. Each one is a small override on top of the theme.
# --------------------------------------------------------------------------

TEXT_SIZES = {"Normal": 100, "Large": 112.5, "Extra large": 125}  # percent of the normal text size
DENSITIES = ["Comfortable", "Compact"]

_HC_LIGHT = {"text": "#000000", "page_text": "#000000", "strong": "#00137F", "muted": "#1F2A44",
             "page_muted": "#1F2A44", "border": "#5B6B8C", "border_strong": "#16284F", "track": "#C9D6EA",
             "tab_text": "#000000"}
_HC_DARK = {"text": "#FFFFFF", "page_text": "#FFFFFF", "strong": "#FFFFFF", "muted": "#FFFFFF",
            "page_muted": "#FFFFFF", "border": "rgba(255,255,255,.55)", "border_strong": "#FFFFFF",
            "card": "#000000", "card2": "#000000", "track": "rgba(255,255,255,.22)", "tab_text": "#FFFFFF"}
_COMPACT_CSS = (".tbl td{padding:5px 12px !important;} .tbl th{padding:8px 12px !important;}"
                " .panel{padding:12px 18px !important;} .kpi{padding:11px 16px 10px !important;}")
_NO_MOTION_CSS = "*, *::before, *::after{transition:none !important;animation:none !important;scroll-behavior:auto !important;}"


def build_css(mode="light", text_size="Normal", high_contrast=False, reduce_motion=False, compact=False):
    """CSS for the whole app. mode is 'light' (default) or 'dark'; the rest are the Settings options."""
    palette = _DARK if mode == "dark" else _LIGHT
    css = _FONT + f":root{{{_vars(palette)}}}"
    if high_contrast:
        css += f":root{{{_vars(_HC_DARK if mode == 'dark' else _HC_LIGHT)}}}"
    css += f"html{{font-size:{TEXT_SIZES.get(text_size, 100)}% !important;}}"
    css += _BASE_CSS
    if compact:
        css += _COMPACT_CSS
    if reduce_motion:
        css += _NO_MOTION_CSS
    return "<style>" + css + "</style>"


def settings_css_for_page():
    """The same options as attribute rules, for the browser prototype (it switches them with data-* attributes)."""
    out = "".join(f'html[data-size="{name}"]{{font-size:{pct}%;}}' for name, pct in TEXT_SIZES.items() if pct != 100)
    out += f'html[data-hc="1"][data-theme="light"]{{{_vars(_HC_LIGHT)}}}html[data-hc="1"][data-theme="dark"]{{{_vars(_HC_DARK)}}}'
    out += ('html[data-density="compact"] .tbl td{padding:5px 12px;}html[data-density="compact"] .tbl th{padding:8px 12px;}'
            'html[data-density="compact"] .panel{padding:12px 18px;}html[data-density="compact"] .kpi{padding:11px 16px 10px;}')
    out += f'html[data-motion="1"] *, html[data-motion="1"] *::before, html[data-motion="1"] *::after{{transition:none !important;animation:none !important;}}'
    return out


_FONT = ""  # system font stack: nothing is downloaded

_BASE_CSS = """
html, body{background:var(--bg) !important;color:var(--page-text);font-family:var(--font);}
.stApp{background:var(--page-bg) !important;color:var(--page-text);font-family:var(--font);}
[data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stMain"]{background:transparent !important;}
.stApp *{font-family:var(--font);}
.block-container{padding-top:1.2rem; max-width:1500px;}
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] p, label, label p, label span{color:var(--page-text);}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p{color:var(--page-muted) !important;}
footer{visibility:hidden;}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px;}

/* header: slim global bar on top, record-style page header below it */
.gbar{display:flex;align-items:center;gap:10px;background:var(--hero-bg);color:var(--hero-title);padding:9px 20px;
  border-radius:8px 8px 0 0;font-size:.85rem;font-weight:700;position:relative;}
.gbar::after{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;
  background:linear-gradient(90deg,var(--purple) 0 25%,var(--pink) 25% 50%,var(--yellow) 50% 75%,var(--teal) 75% 100%);}
.gbar .sep{opacity:.5;font-weight:400;} .gbar .sub{font-weight:400;color:var(--hero-sub);}
.hero{display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:var(--card);border:1px solid var(--border);
  border-top:0;border-radius:0 0 8px 8px;padding:16px 22px;margin-bottom:16px;box-shadow:var(--shadow);}
.hero .tile{flex:none;display:grid;place-items:center;width:44px;height:44px;border-radius:8px;background:var(--accent);}
.hero .tile svg{width:24px;height:24px;}
.hero .eyebrow{font-size:.74rem;font-weight:600;color:var(--muted);margin-bottom:1px;}
.hero h1{margin:0;font-size:1.5rem;font-weight:700;color:var(--strong);letter-spacing:-.01em;line-height:1.2;}
.hero p{margin:3px 0 0;font-size:.9rem;color:var(--muted);}
.hero .pill{margin-left:auto;background:var(--chip-bg);color:var(--chip-text);padding:5px 12px;border-radius:999px;
  font-size:.78rem;font-weight:700;}
.listhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:2px 0 6px;}
.listhead b{font-size:1.1rem;color:var(--strong);}
.listhead span{font-size:.84rem;color:var(--muted);}

/* native widgets */
.stButton button, .stDownloadButton button, [data-testid="stPopover"] > button{border-radius:6px;font-weight:700;
  min-height:40px;padding:.4rem 1rem;background:var(--btn-bg);border:1px solid var(--btn-border);box-shadow:none;}
.stButton button p, .stDownloadButton button p, [data-testid="stPopover"] > button p,
[data-testid="stPopover"] > button span{color:var(--btn-text) !important;font-weight:700;}
.stButton button[kind="primary"], .stButton button[data-testid="stBaseButton-primary"]{
  background:var(--primary-bg);border-color:var(--primary-bg);}
.stButton button[kind="primary"] p, .stButton button[data-testid="stBaseButton-primary"] p{color:var(--primary-text) !important;}
.stButton button:hover, .stDownloadButton button:hover, [data-testid="stPopover"] > button:hover{
  border-color:var(--accent);box-shadow:0 1px 4px rgba(3,45,96,.18);}
.stButton button[kind="primary"]:hover{background:var(--accent2);border-color:var(--accent2);}
.stButton button:disabled{opacity:.5;box-shadow:none;}
[data-testid="stPopoverBody"], div[data-baseweb="popover"] > div{background:var(--card) !important;border-radius:8px;}
[data-testid="stPopoverBody"] label p, [data-testid="stPopoverBody"] label span,
[data-testid="stPopoverBody"] [data-testid="stWidgetLabel"] p, [data-testid="stPopoverBody"] p,
[data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"], [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] p{
  color:var(--text) !important;}
[data-testid="stPopoverBody"] .stButton button[kind="primary"] p{color:var(--primary-text) !important;}
div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="base-input"]{
  background:var(--card) !important;border-color:var(--border-strong) !important;border-radius:6px;}
div[data-baseweb="input"] input, div[data-baseweb="select"] input{color:var(--text) !important;-webkit-text-fill-color:var(--text);}
div[data-baseweb="input"] input::placeholder{color:var(--muted) !important;-webkit-text-fill-color:var(--muted);opacity:.8;}
div[data-baseweb="select"] span, div[data-baseweb="select"] div{color:var(--text);}
span[data-baseweb="tag"]{background:var(--chip-bg) !important;border-radius:999px;}
span[data-baseweb="tag"], span[data-baseweb="tag"] *{color:var(--chip-text) !important;font-weight:700;}
div[data-baseweb="popover"] ul, div[data-baseweb="popover"] li, div[data-baseweb="menu"]{
  background:var(--card) !important;color:var(--text) !important;}
div[data-baseweb="popover"] li:hover{background:var(--hover) !important;}
[data-testid="stSlider"] [data-testid="stTickBarMin"], [data-testid="stSlider"] [data-testid="stTickBarMax"]{color:var(--page-text);}
div[data-baseweb="tab-list"]{gap:4px;border-bottom:1px solid var(--border);}
button[data-baseweb="tab"]{border-radius:0;padding:10px 16px;background:transparent;border-bottom:3px solid transparent;}
button[data-baseweb="tab"] p{color:var(--tab-text);font-weight:600;font-size:.95rem;}
button[data-baseweb="tab"][aria-selected="true"]{border-bottom-color:var(--accent);}
button[data-baseweb="tab"][aria-selected="true"] p{color:var(--tab-sel-text);}
button[data-baseweb="tab"]:hover{background:var(--hover);}
div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"]{display:none;}
[data-testid="stExpander"]{background:var(--card);border:1px solid var(--border);border-radius:8px;}
[data-testid="stExpander"] *{color:var(--text);}
.stAlert{border-radius:8px;}

/* KPI cards: flat, with a colored left edge and one soft circle for personality */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:16px;margin:8px 0 18px;}
.kpi{--tone:var(--accent);position:relative;background:var(--card);color:var(--text);
  border:1px solid var(--border);border-left:4px solid var(--tone);border-radius:8px;padding:16px 18px 15px;box-shadow:var(--shadow);}
.kpi .bg{position:absolute;inset:0;overflow:hidden;border-radius:inherit;pointer-events:none;}
.kpi .bg{display:none;}
.kpi.blue{--tone:var(--accent);} .kpi.sky{--tone:var(--sky);} .kpi.teal{--tone:var(--teal);}
.kpi.green{--tone:var(--green);} .kpi.yellow{--tone:var(--yellow);} .kpi.pink, .kpi.critical{--tone:var(--pink);}
.kpi.purple, .kpi.logo{--tone:var(--purple);}
.kpi .label{position:relative;font-size:.82rem;font-weight:600;color:var(--muted);}
.kpi .value{position:relative;font-size:1.9rem;font-weight:700;color:var(--strong);line-height:1.15;margin-top:5px;letter-spacing:-.01em;}
.kpi .sub{position:relative;font-size:.78rem;color:var(--muted);margin-top:2px;}
[class*="st-key-kpi_"] button{min-height:0;padding:.2rem .9rem;font-size:.78rem;margin-top:-10px;}
[class*="st-key-kpi_"] button p{font-size:.78rem;}

/* hover / tap explanations (pure CSS; tap works on iPad and iPhone) */
[data-tip]{position:relative;cursor:help;outline:none;}
[data-tip]:hover::after, [data-tip]:focus::after{content:attr(data-tip);position:absolute;z-index:60;left:0;top:calc(100% + 6px);
  width:max-content;max-width:min(280px,80vw);background:var(--strong);color:var(--card);font-size:.8rem;font-weight:500;
  line-height:1.4;padding:8px 12px;border-radius:6px;box-shadow:0 6px 20px rgba(3,45,96,.3);text-transform:none;
  letter-spacing:0;white-space:normal;text-align:left;pointer-events:none;}
.tbl th:nth-last-child(-n+2)[data-tip]:hover::after, .tbl th:nth-last-child(-n+2)[data-tip]:focus::after{left:auto;right:0;}
.panel h3[data-tip], .tbl th[data-tip], .bar-row .name[data-tip]{text-decoration:underline dotted;
  text-decoration-color:var(--border-strong);text-underline-offset:4px;}

/* panels + bars */
.panel{background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:20px 24px;
  margin-bottom:16px;box-shadow:var(--shadow);}
.panel h3{margin:0 0 2px;font-size:1.05rem;font-weight:700;color:var(--strong);}
.panel .hint{font-size:.8rem;color:var(--muted);margin:0 0 12px;}
.bar-row{display:grid;grid-template-columns:165px 1fr 110px;gap:12px;align-items:center;margin:10px 0;font-size:.85rem;color:var(--text);}
.bar-row .name{color:var(--text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.bar-row .num{color:var(--muted);text-align:right;font-variant-numeric:tabular-nums;font-weight:600;}
.track{background:var(--track);height:10px;border-radius:99px;overflow:hidden;display:flex;}
.fill{height:100%;}
.fill:only-child{border-radius:99px;}
.fill.critical{background:var(--critical);} .fill.high{background:var(--high);}
.fill.medium{background:var(--medium);} .fill.low{background:var(--low);}
.fill.teal{background:var(--teal);} .fill.yellow{background:var(--yellow);}
.fill.orange{background:var(--pink);} .fill.review{background:var(--review);opacity:.7;} .fill.blue{background:var(--accent);}
.legend{display:flex;gap:14px;font-size:.76rem;color:var(--muted);margin-top:6px;flex-wrap:wrap;font-weight:600;}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;}

/* badges (always carry their text, so color is never the only signal) */
.badge{display:inline-block;padding:3px 9px;border-radius:4px;font-size:.72rem;font-weight:700;
  letter-spacing:.01em;white-space:nowrap;}
.b-critical{background:var(--crit-bg);color:var(--crit-text);}
.b-high{background:var(--high-bg);color:var(--high-text);}
.b-medium{background:var(--medium-bg);color:var(--medium-text);}
.b-low{background:var(--lowb-bg);color:var(--lowb-text);}
.s-assigned{background:var(--ok-bg);color:var(--ok-text);}
.s-review{background:var(--warn-bg);color:var(--warn-text);}
.tag{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.72rem;font-weight:700;
  background:var(--low-bg);color:var(--on-low);}
.vip{display:inline-block;margin-left:6px;padding:0 7px;border-radius:4px;font-size:.64rem;font-weight:800;
  background:var(--purple);color:#FFFFFF;}
.dflt{display:inline-block;margin-left:6px;padding:0 7px;border-radius:4px;font-size:.62rem;font-weight:800;
  background:var(--pink-solid);color:#FFFFFF;cursor:help;}
.st-key-edit_off button{background:var(--btn-bg) !important;border:1px solid var(--accent) !important;}
.st-key-edit_off button p{color:var(--accent2) !important;font-weight:700;}
.st-key-edit_on button{background:var(--accent2) !important;border:1px solid var(--accent2) !important;}
.st-key-edit_on button p{color:#FFFFFF !important;font-weight:700;}
.dflt-star{color:var(--pink-solid);font-weight:800;margin-left:2px;cursor:help;}
.live{display:inline-block;font-size:.78rem;color:var(--muted);}
.live b{color:var(--accent2);}

/* tables */
.tbl-wrap{background:var(--card);border:1px solid var(--border);border-radius:8px;max-height:640px;overflow:auto;
  -webkit-overflow-scrolling:touch;box-shadow:var(--shadow);}
.tbl{width:100%;border-collapse:collapse;font-size:.84rem;}
.tbl th{position:sticky;top:0;z-index:1;background:var(--card2);color:var(--muted);text-align:left;
  font-size:.78rem;font-weight:600;padding:12px 14px;
  border-bottom:1px solid var(--border);}
.tbl td{padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);vertical-align:middle;}
.tbl tr:last-child td{border-bottom:none;}
.tbl tbody tr:hover td{background:var(--hover);}
.tbl tr.row-critical td:first-child{box-shadow:inset 4px 0 0 var(--critical);}
.tbl .id{font-weight:700;color:var(--strong);white-space:nowrap;}
.tbl .dim{color:var(--muted);}
.tbl .reason{color:var(--muted);max-width:340px;}
.mini{display:flex;align-items:center;gap:8px;min-width:110px;}
.mini .track{flex:1;height:8px;} .mini b{min-width:30px;text-align:right;color:var(--strong);}
.load{min-width:190px;}
.load .top{display:flex;justify-content:space-between;font-size:.76rem;margin-bottom:3px;color:var(--text);font-weight:600;}
.load .top b{color:var(--strong);}
.empty{background:var(--card);border:1px dashed var(--border-strong);border-radius:8px;
  padding:42px 20px;text-align:center;color:var(--muted);}
.empty h2{color:var(--strong);margin:0 0 6px;font-size:1.2rem;font-weight:700;}
.notice{background:var(--card);border:1px solid var(--border);border-left:4px solid var(--accent);color:var(--text);
  border-radius:6px;padding:9px 16px;margin:6px 0 12px;font-size:.84rem;}
.notice b{color:var(--strong);}
.pager{font-weight:600;color:var(--page-text);text-align:center;padding-top:6px;font-size:.88rem;}
.filter-hint{color:var(--page-muted);font-size:.8rem;margin:4px 0 -4px;}
.s-handled{background:var(--card2);color:var(--muted);border:1px solid var(--border-strong);}
.notice.good{border-left-color:var(--green);}
.alert-low{background:var(--card);color:var(--text);border:1px solid var(--border);border-left:4px solid var(--warn-line);
  border-radius:6px;padding:12px 18px;margin:6px 0 14px;font-size:.86rem;}
.alert-low h4{margin:0 0 6px;font-size:.95rem;font-weight:700;color:var(--text);}
.alert-low .al{display:flex;justify-content:space-between;gap:12px;padding:4px 0;flex-wrap:wrap;}
.alert-low .dim{opacity:.8;}

/* "Why this rep?" */
.why-box{background:var(--card2);border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin:8px 0 14px;}
.why-box h4{margin:0 0 8px;font-size:.95rem;color:var(--strong);font-weight:700;}
.step{display:flex;gap:10px;padding:5px 0;font-size:.85rem;}
.step .n{flex:none;width:22px;height:22px;border-radius:50%;background:var(--accent2);color:#FFFFFF;font-weight:700;
  font-size:.75rem;display:flex;align-items:center;justify-content:center;margin-top:1px;}
.step .d{color:var(--muted);margin-top:1px;}
.step code{background:var(--card);padding:0 6px;border-radius:4px;border:1px solid var(--border);}
.calc div{display:flex;justify-content:space-between;padding:3px 0;font-size:.86rem;border-bottom:1px dashed var(--border);}
.calc .tot{font-weight:700;color:var(--strong);border-bottom:none;}
.cand{padding:8px 0;border-top:1px solid var(--border);font-size:.86rem;color:var(--text);}
.cand .ms{display:flex;gap:5px;margin-top:3px;flex-wrap:wrap;}
.cand .rk{color:var(--muted);font-weight:700;margin-right:2px;}
.m{font-size:.7rem;font-weight:700;padding:1px 8px;border-radius:4px;}
.m.ok{background:var(--ok-bg);color:var(--ok-text);}
.m.any{background:var(--card);color:var(--muted);border:1px solid var(--border-strong);}
.m.no{background:var(--crit-bg);color:var(--crit-text);}

/* tabs: a styled radio so a KPI card can jump to a tab; selected tab gets the underline */
.st-key-tab div[role="radiogroup"]{gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--border);}
.st-key-tab label[data-baseweb="radio"]{border-radius:0;padding:10px 16px;margin:0;cursor:pointer;background:transparent;
  border-bottom:3px solid transparent;}
.st-key-tab label[data-baseweb="radio"] > div:first-child{display:none;}
.st-key-tab label[data-baseweb="radio"] p{color:var(--tab-text);font-weight:600;font-size:.95rem;}
.st-key-tab label[data-baseweb="radio"]:hover{background:var(--hover);}
.st-key-tab label[data-baseweb="radio"]:has(input:checked){border-bottom-color:var(--accent);}
.st-key-tab label[data-baseweb="radio"]:has(input:checked) p{color:var(--tab-sel-text);font-weight:600;}

/* different screens: projector / tablet / phone */
@media (max-width:1100px){
  .hero{padding:14px 18px;} .hero h1{font-size:1.35rem;}
  .bar-row{grid-template-columns:112px 1fr 80px;}
  .kpi .value{font-size:1.7rem;}
}
@media (max-width:760px){
  .block-container{padding-left:.8rem;padding-right:.8rem;}
  .hero{padding:14px 16px;} .hero h1{font-size:1.2rem;} .hero p{font-size:.85rem;}
  .hero .pill{white-space:normal;margin-left:0;} .gbar{padding:8px 14px;}
  .bar-row{grid-template-columns:96px 1fr 70px;gap:8px;font-size:.78rem;}
  .panel{padding:14px 16px;} .kpi{padding:12px 14px;}
  .kpi .value{font-size:1.5rem;}
  .tbl{min-width:720px;font-size:.78rem;} .tbl th, .tbl td{padding:8px 10px;}
  .tbl td:first-child, .tbl th:first-child{position:sticky;left:0;background:var(--card);z-index:1;}
  .tbl th:first-child{background:var(--card2);z-index:2;}
  .st-key-tab label[data-baseweb="radio"]{padding:9px 12px;}
}
"""

# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------


def esc(value):
    """HTML-escape a value (also stops Streamlit reading $ as maths)."""
    return html.escape("" if value is None else str(value)).replace("$", "&#36;")


def fmt_int(number):
    return f"{int(number):,}"


def fmt_pct(part, whole):
    return "0%" if not whole else f"{100 * part / whole:.0f}%"


def fmt_seconds(seconds):
    if seconds is None:
        return "-"
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.2f} s"


def _natural(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(text))]


def unique_values(rows, field):
    return sorted({row.get(field) for row in rows if row.get(field)})



# --------------------------------------------------------------------------
# Hover / tap explanations. tip("Critical") returns the attributes to put on an element.
# --------------------------------------------------------------------------

TIPS = {
    "Critical": "Most urgent. Score of 85 or more, or any VIP referral. Goes to a Senior rep first, then a Manager. Never to a Junior.",
    "High": "Score 60 to 84. Important leads that should be handled soon.",
    "Medium": "Score 40 to 59. Follow up in the normal flow.",
    "Low": "Score 0 to 39. Lowest urgency.",
    "Assigned": "A matching rep with free capacity was found and now owns this lead.",
    "Manager Review": "No rep could take this lead (no match, reps full, or unclear data), so a manager has to decide who handles it.",
    "Handled": "A manager marked this lead as dealt with outside the system. It no longer counts as waiting for review.",
    "VIP": "VIP referral. Always Critical with a score of 100, no matter the company size, activity or industry.",
    "DEFAULT": "A missing value on this lead was defaulted by a manager (a default under Manager edits, or a fix on this one lead). Values marked * were not in the data.",
    "Junior": "Handles high volume (about 40 to 50 leads). Can never be given Critical leads.",
    "Senior": "Mid volume (about 20 to 25 leads). First choice for Critical leads.",
    "Manager": "Low volume (about 5 to 10 leads). Takes Critical leads only when every matching Senior is full.",
    "No matching rep": "No rep covers this lead's exact region, language and industry (for Critical leads, no Senior or Manager does).",
    "At max capacity": "Matching reps exist, but every one has reached their maximum number of leads.",
    "Includes missing/unclear data": "The lead's region, language or industry was blank or unreadable, so it can't be matched strictly.",
    "Reps running low": "Groups of identical reps (same level, region, language and industry) that are 90% full or more. Add reps or rebalance before Critical leads start overflowing.",
    "Total leads": "Every lead that was cleaned, scored and routed in this run.",
    "Assigned leads": "Leads that were given to a rep.",
    "Assignment rate": "Assigned leads divided by total leads. Higher means fewer leads waiting on a manager.",
    "Critical leads": "Leads scoring 85 or more, or flagged VIP. The most urgent ones.",
    "Rep utilization": "How full the team is: slots used divided by total slots. Each rep has a maximum number of leads.",
    "Processing time": "How long cleaning, scoring and routing took. It doesn't include drawing the page.",
    "Total slots": "The most leads all reps together can hold. Each rep has a maximum.",
    "Used": "Slots already filled by assigned leads.",
    "Remaining": "Open slots: total slots minus used slots.",
    "Reps at max": "Reps who can't take any more leads.",
    "Priority mix": "How many leads fall in each priority tier.",
    "Assignment by priority": "For each tier, how many leads got a rep (teal) and how many went to Manager Review (light blue).",
    "Why leads reach Manager Review": "The reasons leads couldn't be given to a rep.",
    "Capacity by seniority": "How full each rep level is: slots used out of total slots.",
    "col:Priority": "Urgency tier worked out from the score: Critical, High, Medium or Low.",
    "col:Lead": "The lead's ID. A purple VIP tag means a VIP referral.",
    "col:Company": "The prospective customer's company name.",
    "col:Region": "Where the lead is. Reps only get leads from their own region.",
    "col:Industry": "The lead's industry. Reps only get leads in their area of expertise.",
    "col:Score": "Points from company size, recent activity and industry. VIPs are always 100.",
    "col:Status": "Assigned to a rep, or waiting in Manager Review.",
    "col:Rep": "The rep who owns this lead. Hover a rep's name to see why they were chosen.",
    "col:Reason": "Why the lead was assigned or sent to Manager Review.",
    "rcol:Rep": "The rep's ID.",
    "rcol:Name": "The rep's name.",
    "rcol:Level": "Junior, Senior or Manager. The level decides which leads a rep can take.",
    "rcol:Region": "The region this rep covers.",
    "rcol:Language": "The language this rep works in.",
    "rcol:Industry": "The industry this rep specializes in. Unknown means no lead can be matched to them.",
    "rcol:Load": "Leads assigned out of the most this rep can hold. Teal is comfortable, yellow is getting full, pink is at the limit.",
    "help:search": "Finds rows where any column contains what you type.",
    "help:priority": "Show only the tiers you pick. Pick none to see all.",
    "help:status": "Show only assigned leads or only Manager Review leads.",
    "help:sort": "Changes the order of the list.",
    "help:rows": "How many rows to show per page.",
    "help:reason": "Show only leads sent to review for the reasons you pick.",
    "help:level": "Show only reps of the levels you pick.",
    "help:slider": "Hides reps who are less full than this percentage.",
    "help:Run Pipeline": "Clean, score and route the full 50,000-lead file to test speed and capacity limits.",
    "help:Reset": "Clear the results and put every rep back at zero leads. Your manager defaults stay.",
    "help:Dark": "Switch between light and dark mode.",
    "help:lead": "Pick a lead from the rows on this page to see how it was routed.",
}


def tip(key, text=None):
    """Attributes that make an element show an explanation on hover (computer) or tap (iPad / iPhone)."""
    message = text if text is not None else TIPS.get(key)
    return f' data-tip="{esc(message)}" tabindex="0"' if message else ""


def help_text(key):
    """Plain text for a Streamlit widget's help= argument (shows a small ? icon)."""
    return TIPS.get(f"help:{key}")


# --------------------------------------------------------------------------
# Manager-set defaults for blank values
# --------------------------------------------------------------------------
# The manager can say "when a lead has no Region, use Europe". We fill those blanks in a
# temporary copy of the leads CSV *before* the pipeline runs, so this works with any
# pipeline and the original CSV is never touched.

NO_DEFAULT = "(no default)"
ACTIVITY_CHOICES = ["Requested Live Demo", "Contact Sales", "Attended Webinar",
                    "Downloaded Whitepaper", "Visited Pricing Page", "Other"]
# key, CSV column, label shown to the manager, allowed choices (None = free text)
DEFAULT_FIELDS = [
    ("region", "Region", "Region", ["North America", "Europe", "Asia-Pacific"]),
    ("language", "Language", "Language", ["English", "Spanish", "German"]),
    ("industry", "Industry_Vertical", "Industry",
     ["Technology", "Healthcare", "Finance", "Manufacturing", "Retail"]),
    ("size", "Company_Size", "Company size (employees)", None),
    ("activity", "Recent_Activity", "Recent activity", ACTIVITY_CHOICES),
    ("company", "Company_Name", "Company name", None),
]
_FIELD_BY_KEY = {key: (col, label) for key, col, label, _ in DEFAULT_FIELDS}
_MISSING = {"", "none", "null", "nan", "n/a", "na", "unknown"}


def is_missing(key, value):
    """Blank-like cell? 'NA' is a real region alias (North America), so it only counts as blank elsewhere."""
    text = str(value if value is not None else "").strip().lower()
    if key == "region" and text == "na":
        return False
    return text in _MISSING


def clean_defaults(values):
    """values: {key: raw input}. Returns (defaults_dict, error_messages). Blank / '(no default)' are dropped."""
    defaults, errors = {}, []
    for key, raw in (values or {}).items():
        text = str(raw if raw is not None else "").strip()
        if not text or text == NO_DEFAULT:
            continue
        if key == "size":
            if not text.isdigit():
                errors.append("Company size must be a whole number, like 250.")
                continue
            text = str(int(text))
        defaults[key] = text
    return defaults, errors


def describe_defaults(defaults):
    return " · ".join(f"{_FIELD_BY_KEY[k][1]} = {v}" for k, v in (defaults or {}).items() if k in _FIELD_BY_KEY)


def write_filled_csv(src_path, defaults):
    """Copy a leads CSV to a temp file with blank values replaced by the defaults.

    Returns (temp_path, filled, counts): filled = {lead_id: [labels]}, counts = {label: n}.
    The caller deletes temp_path. If there are no defaults the original path is returned untouched.
    """
    active = {k: v for k, v in (defaults or {}).items() if k in _FIELD_BY_KEY and str(v).strip()}
    if not active:
        return src_path, {}, {}
    filled, counts = {}, {}
    handle, temp_path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(handle, "w", newline="", encoding="utf-8") as out, \
            open(src_path, newline="", encoding="utf-8-sig") as src:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(out, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            lead_id = (row.get("Lead_ID") or "").strip()
            for key, value in active.items():
                column, label = _FIELD_BY_KEY[key]
                if column in row and is_missing(key, row.get(column)):
                    row[column] = value
                    filled.setdefault(lead_id, []).append(label)
                    counts[label] = counts.get(label, 0) + 1
            writer.writerow(row)
    return temp_path, filled, counts


SKILL_KEYS = ("region", "language", "industry")


def unreadable_patches(leads, defaults):
    """After a first run: leads whose region / language / industry the cleaner could not read (marked 'Unknown')
    for a field that has a manager default. Returns {lead_id: {csv column: default}} and {lead_id: [labels]}."""
    patches, labels = {}, {}
    for lead in leads:
        for key in SKILL_KEYS:
            value = (defaults or {}).get(key)
            if value and str(value).strip() and lead.get(key) in (None, "", "Unknown"):
                column, label = _FIELD_BY_KEY[key]
                patches.setdefault(str(lead.get("lead_id")).strip(), {})[column] = value
                labels.setdefault(str(lead.get("lead_id")).strip(), []).append(label)
    return patches, labels


def write_patched_csv(src_path, patches):
    """Copy a leads CSV to a temp file, replacing the given cells: patches = {lead_id: {column: value}}."""
    handle, temp_path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(handle, "w", newline="", encoding="utf-8") as out, \
            open(src_path, newline="", encoding="utf-8-sig") as src:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(out, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            row.update({c: v for c, v in patches.get((row.get("Lead_ID") or "").strip(), {}).items() if c in row})
            writer.writerow(row)
    return temp_path


def notice_html(defaults, counts=None):
    """Strip shown under the controls while defaults are active."""
    if not defaults:
        return ""
    text = f"✎ Manager defaults active: <b>{esc(describe_defaults(defaults))}</b>"
    if counts is not None:
        total = sum(counts.values())
        detail = ", ".join(f"{esc(label)} {fmt_int(n)}" for label, n in counts.items())
        text += (f" &nbsp;·&nbsp; filled {fmt_int(total)} blank value{'s' if total != 1 else ''}"
                 + (f" ({detail})" if detail else ""))
    return f'<div class="notice">{text}</div>'


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------


def review_category(reason):
    """Bucket a Manager Review reason, tolerating different wording from teammates."""
    text = (reason or "").lower()
    if "capacity" in text or "full" in text:
        return "At max capacity"
    if any(word in text for word in ("missing", "unknown", "unrecogn", "ambiguous", "invalid")):
        return "Includes missing/unclear data"
    return "No matching rep"


def is_waiting(lead):
    """Waiting for a manager (not assigned and not already handled)."""
    return lead.get("assignment_status") not in (STATUS_ASSIGNED, STATUS_HANDLED)


def compute_kpis(results):
    leads = results.get("leads", [])
    reps = results.get("reps", [])
    metrics = results.get("metrics", {})
    total = len(leads)
    assigned = sum(1 for lead in leads if lead.get("assignment_status") == STATUS_ASSIGNED)
    critical = [lead for lead in leads if lead.get("priority") == "Critical"]
    critical_assigned = sum(1 for lead in critical if lead.get("assignment_status") == STATUS_ASSIGNED)
    cap_total = sum(max(rep.get("max_capacity", 0), 0) for rep in reps)
    cap_used = sum(rep.get("current_capacity", 0) for rep in reps)
    return {
        "total": total,
        "assigned": assigned,
        "review": sum(1 for lead in leads if is_waiting(lead)),
        "handled": sum(1 for lead in leads if lead.get("assignment_status") == STATUS_HANDLED),
        "rate": (assigned / total) if total else 0.0,
        "critical": len(critical),
        "critical_assigned": critical_assigned,
        "elapsed": metrics.get("elapsed_seconds"),
        "cap_total": cap_total,
        "cap_used": cap_used,
        "utilization": (cap_used / cap_total) if cap_total else 0.0,
        "reps_full": sum(1 for rep in reps if rep.get("max_capacity", 0) > 0
                         and rep.get("current_capacity", 0) >= rep["max_capacity"]),
    }


def priority_breakdown(leads):
    """{priority: (assigned, review)} in Critical-to-Low order."""
    table = {name: [0, 0] for name in PRIORITIES}
    for lead in leads:
        name = lead.get("priority")
        if name in table and lead.get("assignment_status") != STATUS_HANDLED:
            table[name][0 if lead.get("assignment_status") == STATUS_ASSIGNED else 1] += 1
    return {name: tuple(pair) for name, pair in table.items()}


def review_breakdown(leads):
    counts = {}
    for lead in leads:
        if is_waiting(lead):
            category = review_category(lead.get("reason"))
            counts[category] = counts.get(category, 0) + 1
    return counts


def seniority_utilization(reps):
    """{seniority: (used, max)}."""
    table = {}
    for rep in reps:
        used, cap = table.get(rep.get("seniority"), (0, 0))
        table[rep.get("seniority")] = (used + rep.get("current_capacity", 0),
                                       cap + max(rep.get("max_capacity", 0), 0))
    return table


# --------------------------------------------------------------------------
# Filter / sort / page
# --------------------------------------------------------------------------


LEAD_COLUMNS = [("lead_id", "Lead ID"), ("company", "Company"), ("region", "Region"),
                ("language", "Language"), ("industry", "Industry"), ("rep", "Rep"), ("reason", "Reason")]
REP_COLUMNS = [("rep_id", "Rep ID"), ("name", "Name"), ("region", "Region"),
               ("language", "Language"), ("industry", "Industry")]


def _cell(row, field):
    """Text of one column. 'rep' covers both the rep ID and the rep name."""
    if field == "rep":
        return f"{row.get('rep_id', '')} {row.get('rep_name', '')}"
    if field == "reason":
        return reason_text(row)
    return str(row.get(field, "") or "")


def matches_columns(row, columns):
    """True if every non-empty column filter is found (case-insensitive, 'contains') in that column."""
    for field, word in (columns or {}).items():
        word = (word or "").strip().lower()
        if word and word not in _cell(row, field).lower():
            return False
    return True


def filter_leads(leads, search="", priorities=(), statuses=(), columns=None):
    """search = any column; columns = {field: word} typed per column, all must match."""
    needle = (search or "").strip().lower()
    out = []
    for lead in leads:
        if priorities and lead.get("priority") not in priorities:
            continue
        if statuses and lead.get("assignment_status") not in statuses:
            continue
        if not matches_columns(lead, columns):
            continue
        if needle:
            blob = " ".join(_cell(lead, k) for k in
                            ("lead_id", "company", "region", "language", "industry", "rep", "reason")).lower()
            if needle not in blob:
                continue
        out.append(lead)
    return out


def sort_leads(leads, how="Priority (Critical first)"):
    if how == "Score (high to low)":
        return sorted(leads, key=lambda r: -r.get("score", 0))
    if how == "Score (low to high)":
        return sorted(leads, key=lambda r: r.get("score", 0))
    if how == "Lead ID":
        return sorted(leads, key=lambda r: _natural(r.get("lead_id")))
    if how == "Company (A-Z)":
        return sorted(leads, key=lambda r: str(r.get("company", "")).lower())
    return sorted(leads, key=lambda r: (PRIORITY_RANK.get(r.get("priority"), 9), -r.get("score", 0)))


def paginate(rows, page, page_size):
    """Return (rows_on_page, page_used, total_pages). Page is clamped to a valid number."""
    total_pages = max(1, -(-len(rows) // page_size))
    page = min(max(int(page), 1), total_pages)
    start = (page - 1) * page_size
    return rows[start:start + page_size], page, total_pages


def filter_reps(reps, search="", seniorities=(), min_util=0, columns=None):
    needle = (search or "").strip().lower()
    out = []
    for rep in reps:
        if seniorities and rep.get("seniority") not in seniorities:
            continue
        if min_util and rep_utilization(rep) * 100 < min_util:
            continue
        if not matches_columns(rep, columns):
            continue
        if needle and needle not in " ".join(_cell(rep, k) for k in
                                             ("rep_id", "name", "region", "language", "industry", "seniority")).lower():
            continue
        out.append(rep)
    return out


def rep_utilization(rep):
    cap = rep.get("max_capacity", 0)
    return (rep.get("current_capacity", 0) / cap) if cap > 0 else 0.0


def sort_reps(reps, how="Most utilized"):
    if how == "Least utilized":
        return sorted(reps, key=lambda r: (rep_utilization(r), _natural(r.get("rep_id"))))
    if how == "Rep ID":
        return sorted(reps, key=lambda r: _natural(r.get("rep_id")))
    return sorted(reps, key=lambda r: (-rep_utilization(r), _natural(r.get("rep_id"))))


def to_csv_bytes(rows, fields):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(dict(r, reason=reason_text(r)) if "reason" in fields else r for r in rows)
    return buffer.getvalue().encode("utf-8")


# --------------------------------------------------------------------------
# HTML builders (kept on one line each: Streamlit's markdown breaks on indents)
# --------------------------------------------------------------------------


_FUNNEL_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" '
               'stroke-linejoin="round" aria-hidden="true"><path d="M3 5h18l-7 8v6l-4-2v-4z"/></svg>')
_EMPTY_SVG = ('<svg viewBox="0 0 120 80" width="120" height="80" aria-hidden="true" style="margin-bottom:8px">'
              '<rect x="12" y="10" width="96" height="14" rx="4" fill="#DCEEFF" stroke="#8396B3"/>'
              '<rect x="12" y="30" width="96" height="14" rx="4" fill="#FFF0CD" stroke="#8396B3"/>'
              '<rect x="12" y="50" width="96" height="14" rx="4" fill="#E1F2E6" stroke="#8396B3"/>'
              '<circle cx="24" cy="17" r="3" fill="#BA0517"/><circle cx="24" cy="37" r="3" fill="#DD7A01"/>'
              '<circle cx="24" cy="57" r="3" fill="#2E844A"/></svg>')


def hero_html(dataset_label=None, pipeline_name=""):
    pill = (f'<span class="pill">{esc(dataset_label)} · {esc(pipeline_name)}</span>'
            if dataset_label else '<span class="pill">Run a dataset</span>')
    return ('<div class="gbar">Lead Operations<span class="sep">|</span><span class="sub">Sales workspace</span></div>'
            f'<div class="hero"><span class="tile">{_FUNNEL_SVG}</span><div>'
            '<div class="eyebrow">Sales operations / Lead management</div>'
            '<h1>Lead Prioritization Dashboard</h1>'
            f'<p>The right lead, to the right rep, at the right time.</p></div>{pill}</div>')


def list_header_html(title, shown, total, sort_label):
    """The list-view line above a table: name, item count and how it is sorted."""
    items = f"{fmt_int(total)} items" if shown == total else f"{fmt_int(shown)} of {fmt_int(total)} items"
    return f'<div class="listhead"><b>{esc(title)}</b><span>{items} · Sorted by {esc(sort_label)}</span></div>'


def empty_html():
    return (f'<div class="empty">{_EMPTY_SVG}<h2>No results yet</h2>'
            '<div>Press <b>Run Pipeline</b> to see the prioritized queue.</div></div>')


def kpi_card(label, value, sub="", tone="", tip_key=None):
    return (f'<div class="kpi {tone}"{tip(tip_key or label)}><span class="bg"></span><div class="label">{esc(label)}</div>'
            f'<div class="value">{esc(value)}</div><div class="sub">{esc(sub)}</div></div>')


def kpi_specs(kpis):
    """The overview cards as data: label, value, sub text, tone, tooltip key and what a click does.

    action = (tab, filters): jump to that tab and pre-fill these filters. None = not clickable.
    """
    waiting_note = "need a human decision"
    if kpis.get("handled"):
        waiting_note += f' · {fmt_int(kpis["handled"])} handled'
    return [
        ("Total leads", fmt_int(kpis["total"]), "processed", "blue", "Total leads", ("Lead Queue", {})),
        ("Assigned", fmt_int(kpis["assigned"]), f'{fmt_pct(kpis["assigned"], kpis["total"])} of leads', "green",
         "Assigned leads", ("Lead Queue", {"q_status": [STATUS_ASSIGNED]})),
        ("Manager Review", fmt_int(kpis["review"]), waiting_note, "yellow", "Manager Review", ("Manager Review", {})),
        ("Assignment rate", f'{kpis["rate"] * 100:.1f}%', "assigned / total", "teal", "Assignment rate", None),
        ("Critical leads", fmt_int(kpis["critical"]), f'{fmt_int(kpis["critical_assigned"])} assigned', "pink",
         "Critical leads", ("Lead Queue", {"q_priority": ["Critical"]})),
        ("Rep utilization", f'{kpis["utilization"] * 100:.0f}%',
         f'{fmt_int(kpis["cap_used"])} / {fmt_int(kpis["cap_total"])} slots · {kpis["reps_full"]} reps full', "purple",
         "Rep utilization", ("Rep Capacity", {})),
        ("Processing time", fmt_seconds(kpis["elapsed"]), "", "sky", "Processing time", None),
    ]


def kpi_cards_html(kpis):
    """All overview cards in one grid (used by the offline preview)."""
    cards = [kpi_card(label, value, sub, tone, key) for label, value, sub, tone, key, _ in kpi_specs(kpis)]
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def priority_badge(priority):
    return f'<span class="badge b-{esc(str(priority).lower())}"{tip(str(priority))}>{esc(priority)}</span>'


def status_badge(status):
    css = {STATUS_ASSIGNED: "s-assigned", STATUS_HANDLED: "s-handled"}.get(status, "s-review")
    return f'<span class="badge {css}"{tip(str(status))}>{esc(status)}</span>'


def _bar_row(name, parts, right, tip_key=None):
    """parts = [(percent_of_track, css_class), ...]"""
    fills = "".join(f'<div class="fill {css}" style="width:{pct:.2f}%"></div>' for pct, css in parts)
    return (f'<div class="bar-row"><div class="name"{tip(tip_key or name)}>{esc(name)}</div>'
            f'<div class="track">{fills}</div><div class="num">{esc(right)}</div></div>')


def panel_html(title, hint, body):
    return f'<div class="panel"><h3{tip(title)}>{esc(title)}</h3><p class="hint">{esc(hint)}</p>{body}</div>'


def priority_mix_html(leads):
    counts = {name: sum(pair) for name, pair in priority_breakdown(leads).items()}
    total = sum(counts.values()) or 1
    rows = "".join(_bar_row(name, [(100 * n / total, name.lower())], f"{fmt_int(n)} · {fmt_pct(n, total)}")
                   for name, n in counts.items())
    return panel_html("Priority mix", "How the queue splits across tiers", rows)


def assignment_by_priority_html(leads):
    breakdown = priority_breakdown(leads)
    rows = ""
    for name, (assigned, review) in breakdown.items():
        total = (assigned + review) or 1
        rows += _bar_row(name, [(100 * assigned / total, "teal"), (100 * review / total, "review")],
                         f"{fmt_int(assigned)} / {fmt_int(assigned + review)}")
    legend = ('<div class="legend"><span><i class="dot" style="background:var(--teal)"></i>Assigned</span>'
              '<span><i class="dot" style="background:var(--review);opacity:.7"></i>Manager Review</span></div>')
    return panel_html("Assignment by priority", "Are the important leads getting reps?", rows + legend)


def review_reasons_html(leads):
    counts = review_breakdown(leads)
    if not counts:
        return panel_html("Why leads reach Manager Review", "Nothing is waiting on a manager.", "")
    top = max(counts.values())
    rows = "".join(_bar_row(name, [(100 * n / top, "yellow")], fmt_int(n))
                   for name, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    return panel_html("Why leads reach Manager Review", "Skill gaps, full reps, or data that could not be matched", rows)


def seniority_load_html(reps):
    table = seniority_utilization(reps)
    order = [s for s in ("Junior", "Senior", "Manager") if s in table] + \
            [s for s in table if s not in ("Junior", "Senior", "Manager")]
    rows = ""
    for level in order:
        used, cap = table[level]
        pct = 100 * used / cap if cap else 0
        rows += _bar_row(level, [(pct, _load_tone(pct / 100))], f"{fmt_int(used)} / {fmt_int(cap)}")
    return panel_html("Capacity by seniority", "Used slots out of total slots", rows)


def _load_tone(fraction):
    if fraction >= 1:
        return "orange"
    if fraction >= 0.7:
        return "yellow"
    return "teal"


def leads_table_html(rows, show_status=True, show_reason=True):
    if not rows:
        return '<div class="empty"><h2>No leads match these filters</h2><div>Try clearing a filter.</div></div>'
    head = ["Priority", "Lead", "Company", "Region", "Industry", "Score"]
    if show_status:
        head.append("Status")
    head.append("Rep")
    if show_reason:
        head.append("Reason")
    body = []
    for lead in rows:
        score = int(lead.get("score", 0))
        cls = "row-critical" if lead.get("priority") == "Critical" else ""
        vip = f'<span class="vip"{tip("VIP")}>VIP</span>' if lead.get("vip") else ""
        filled = list(lead.get("defaults_applied") or []) + [f.capitalize() + " (this lead)" for f in (lead.get("overrides") or {})]
        if filled:
            vip += (f'<span class="dflt"{tip("DEFAULT", "Defaulted by a manager, not in the data: " + ", ".join(filled))}>DEFAULTED</span>')
        if lead.get("rep_id"):
            rep = (f'<span{tip("why", why_short(lead))}><span class="id">{esc(lead.get("rep_id"))}</span> '
                   f'<span class="dim">{esc(lead.get("rep_name"))}</span></span>')
        else:
            rep = '<span class="dim">-</span>'
        cells = [
            f'<td>{priority_badge(lead.get("priority"))}</td>',
            f'<td class="id">{esc(lead.get("lead_id"))}{vip}</td>',
            f'<td>{esc(lead.get("company"))}</td>',
            f'<td>{field_text(lead, "region")}</td>',
            f'<td>{field_text(lead, "industry")}</td>',
            f'<td><div class="mini"><b>{score}</b><div class="track"><div class="fill blue" '
            f'style="width:{min(score, 100)}%"></div></div></div></td>',
        ]
        if show_status:
            cells.append(f'<td>{status_badge(lead.get("assignment_status"))}</td>')
        cells.append(f"<td>{rep}</td>")
        if show_reason:
            cells.append(f'<td class="reason">{esc(reason_text(lead))}</td>')
        body.append(f'<tr class="{cls}">{"".join(cells)}</tr>')
    header = "".join(f'<th{tip("col:" + h)}>{h}</th>' for h in head)
    return f'<div class="tbl-wrap"><table class="tbl"><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def reps_table_html(reps):
    if not reps:
        return '<div class="empty"><h2>No reps match these filters</h2><div>Try clearing a filter.</div></div>'
    body = []
    for rep in reps:
        cap, used = rep.get("max_capacity", 0), rep.get("current_capacity", 0)
        frac = rep_utilization(rep)
        pct = min(frac, 1) * 100
        load = (f'<div class="load"><div class="top"><span><b>{used}</b> / {cap}</span>'
                f'<span>{frac * 100:.0f}%</span></div><div class="track">'
                f'<div class="fill {_load_tone(frac)}" style="width:{pct:.1f}%"></div></div></div>')
        body.append(
            f'<tr><td class="id">{esc(rep.get("rep_id"))}</td><td>{esc(rep.get("name"))}</td>'
            f'<td><span class="tag"{tip(str(rep.get("seniority")))}>{esc(rep.get("seniority"))}</span></td>'
            f'<td>{esc(rep.get("region"))}</td><td>{esc(rep.get("language"))}</td>'
            f'<td>{esc(rep.get("industry"))}</td><td>{load}</td></tr>')
    header = "".join(f'<th{tip("rcol:" + key)}>{h}</th>' for key, h in
                     [("Rep", "Rep"), ("Name", "Name"), ("Level", "Level"), ("Region", "Region"),
                      ("Language", "Language"), ("Industry", "Industry"), ("Load", "Load (assigned / max)")])
    return f'<div class="tbl-wrap"><table class="tbl"><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


# --------------------------------------------------------------------------
# Capacity alerts
# --------------------------------------------------------------------------


def low_groups(reps, threshold=0.9):
    """Groups of identical reps (level + region + language + industry) that are `threshold` full or more."""
    groups = {}
    for rep in reps:
        if rep.get("max_capacity", 0) <= 0 or "Unknown" in (rep.get("region"), rep.get("language"), rep.get("industry")):
            continue
        key = (rep.get("seniority"), rep.get("region"), rep.get("language"), rep.get("industry"))
        group = groups.setdefault(key, {"seniority": key[0], "region": key[1], "language": key[2],
                                        "industry": key[3], "used": 0, "cap": 0, "n": 0})
        group["used"] += rep.get("current_capacity", 0)
        group["cap"] += rep["max_capacity"]
        group["n"] += 1
    low = [g for g in groups.values() if g["used"] / g["cap"] >= threshold]
    return sorted(low, key=lambda g: (-g["used"] / g["cap"], -g["cap"]))


def low_banner_html(reps, limit=5):
    groups = low_groups(reps)
    if not groups:
        return f'<div class="notice good"{tip("Reps running low")}>✓ No group of reps is 90% full or more.</div>'
    rows = "".join(
        f'<div class="al"><span><b>{esc(g["seniority"])}</b> reps for {esc(g["region"])} / {esc(g["language"])} / '
        f'{esc(g["industry"])} are at <b>{g["used"] / g["cap"] * 100:.0f}%</b></span>'
        f'<span class="dim">{fmt_int(g["used"])} of {fmt_int(g["cap"])} slots · {g["n"]} rep{"s" if g["n"] != 1 else ""}</span></div>'
        for g in groups[:limit])
    more = (f'<div class="dim" style="padding-top:6px;font-size:.8rem">+ {fmt_int(len(groups) - limit)} more groups</div>'
            if len(groups) > limit else "")
    return (f'<div class="alert-low"{tip("Reps running low")}><h4>⚠ Reps running low ({fmt_int(len(groups))} '
            f'group{"s" if len(groups) != 1 else ""} at 90%+)</h4>{rows}{more}</div>')


# --------------------------------------------------------------------------
# Score breakdown and "Why this rep?"
# --------------------------------------------------------------------------

ACTIVITY_PTS = {"requested live demo": 35, "contact sales": 35, "attended webinar": 25,
                "downloaded whitepaper": 15, "visited pricing page": 5}
INDUSTRY_PTS = {"Technology": 15, "Healthcare": 10, "Finance": 10}


def score_breakdown(lead):
    """(lines, total): a plain-English copy of the scoring cheat sheet applied to one lead."""
    if lead.get("vip"):
        return [("VIP referral (overrides scoring)", 100)], 100
    size = lead.get("company_size")
    lines = [("Company size missing (standard fallback)" if size is None else f"Company size {fmt_int(size)} employees",
              20 if size is None else 50 if size >= 1000 else 30 if size >= 100 else 0)]
    activity = " ".join(str(lead.get("activity") or "").lower().split())
    lines.append((f'Recent activity: {lead.get("activity") or "none recorded"}', ACTIVITY_PTS.get(activity, 0)))
    lines.append((f'Industry: {lead.get("industry")}', INDUSTRY_PTS.get(lead.get("industry"), 0)))
    return lines, sum(points for _, points in lines)


def score_html(lead):
    lines, total = score_breakdown(lead)
    rows = "".join(f'<div><span>{esc(text)}</span><span>{points:+d}</span></div>' for text, points in lines)
    return (f'<div class="why-box calc"><h4>How the score was worked out</h4>{rows}'
            f'<div class="tot"><span>Total score → {esc(lead.get("priority"))}</span><span>{total}</span></div>'
            '<div style="font-size:.76rem;color:var(--muted);padding-top:6px">Critical 85+ · High 60–84 · '
            'Medium 40–59 · Low 0–39. VIP referrals are always Critical.</div></div>')


def _rule(lead):
    if lead.get("priority") == "Critical":
        return "Critical leads go to a Senior first, then a Manager, never a Junior."
    return "Other leads try a Junior first, then a Senior, then a Manager."


def _step_text(step):
    level, n, free = step
    if n == 0:
        return f"{level}: no rep covers this region, language and industry"
    plural = "" if n == 1 else "s"
    if free == 0:
        return f"{level}: {n} matching rep{plural}, all at maximum capacity"
    return f"{level}: {n} matching rep{plural}, {free} with room"


def unreadable_fields(lead):
    """Which of region / language / industry were blank or unreadable (the pipeline marks them 'Unknown')."""
    return [name for name in ("region", "language", "industry") if lead.get(name) in (None, "", "Unknown")]


def _name_list(names):
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def field_text(lead, field):
    """A value for a table cell. Values a manager filled in for this one lead get an asterisk."""
    text = esc(lead.get(field))
    if field in (lead.get("overrides") or {}) or field.capitalize() in (lead.get("defaults_applied") or []):
        return f'{text}<span class="dflt-star"{tip("DEFAULT", "Defaulted by a manager, not in the original data")}>*</span>'
    return text


def reason_text(lead):
    """Reason column text. Generic 'missing data' reasons name the exact fields, e.g. 'Region and industry missing or unreadable'."""
    reason = lead.get("reason") or ""
    if review_category(reason) == "Includes missing/unclear data" and not lead.get("rep_id"):
        names = unreadable_fields(lead)
        if not names and lead.get("overrides"):
            text = _name_list(list(lead["overrides"]))
            return f"{text[0].upper()}{text[1:]} filled in by a manager, needs a rep"
        if names:
            text = _name_list(names)
            return f"{text[0].upper()}{text[1:]} missing or unreadable"
    return reason


def unreadable_sentence(lead):
    """e.g. 'The region and industry were blank or unreadable, so ...'"""
    if lead.get("overrides") and not unreadable_fields(lead):
        return (f"A manager filled in the missing {_name_list(list(lead['overrides']))} by hand (marked *). "
                "Choose a rep below to finish routing this lead.")
    names = unreadable_fields(lead) or ["region, language or industry"]
    verb = "was" if len(names) == 1 else "were"
    return (f"The {_name_list(names)} {verb} blank or unreadable, so this lead couldn't be matched to a rep safely.")


def why_short(lead):
    """One or two sentences for the hover on a rep's name."""
    manual = lead.get("manual")
    if manual == "assigned":
        return "A manager assigned this lead by hand, overriding the automatic routing."
    if manual == "handled":
        return "A manager marked this lead as handled."
    trace = lead.get("trace")
    if not trace:  # the team's pipeline may not send a trace: explain from the result alone
        return (f'Matched on region ({lead.get("region")}), language ({lead.get("language")}) and industry '
                f'({lead.get("industry")}). {_rule(lead)} Result: {lead.get("reason") or lead.get("assignment_status")}.')
    if trace.get("unknown"):
        return unreadable_sentence(lead)
    pick = trace.get("pick")
    if lead.get("assignment_status") == STATUS_ASSIGNED and pick:
        return (f'Matched {lead.get("region")} · {lead.get("language")} · {lead.get("industry")}. {_rule(lead)} '
                f'Chosen: a {pick["lv"]}, rep #{pick["pos"]} of {pick["n"]} identical reps by round-robin, with '
                f'{pick["load"]} of {pick["max"]} slots used before this lead.')
    steps = "; ".join(_step_text(step) for step in trace.get("steps", [])) or "no levels"
    return f"{_rule(lead)} Tried: {steps}. Nobody could take it, so a manager decides."


def why_html(lead):
    """The explanation box. Waiting leads: why they need a manager. Assigned leads: why this rep."""
    trace = lead.get("trace")
    waiting = is_waiting(lead)
    steps = []
    if not trace:
        if waiting and unreadable_fields(lead) and lead.get("reason", "").lower().startswith(("missing", "unrecog")):
            steps.append(("Stopped before matching", esc(unreadable_sentence(lead))))
        else:
            steps.append(("Matched on skills", f'Region {esc(lead.get("region"))}, language {esc(lead.get("language"))}, '
                          f'industry {esc(lead.get("industry"))}. {esc(_rule(lead))}'))
            steps.append(("Result", esc(lead.get("reason") or lead.get("assignment_status"))))
    elif trace.get("unknown"):
        steps.append(("Stopped before matching", esc(unreadable_sentence(lead))))
    else:
        steps.append(("Chose which levels may take it", f'{esc(_rule(lead))} Order tried: '
                      f'<b>{esc(" → ".join(trace.get("levels", [])))}</b>.'))
        steps.append(("Checked each level", "<br>".join(esc(_step_text(step)) for step in trace.get("steps", []))))
        pick = trace.get("pick")
        if pick:
            skipped = (f' (skipped {pick["skipped"]} full rep{"s" if pick["skipped"] != 1 else ""} first)'
                       if pick.get("skipped") else "")
            steps.append(("Picked a rep by round-robin",
                          f'Matching {esc(pick["lv"])} reps are taken in turns so no one gets everything. This lead went to '
                          f'rep <b>#{pick["pos"]} of {pick["n"]}</b>{skipped}, who had {pick["load"]} of {pick["max"]} slots used.'))
        else:
            original = (lead.get("auto") or {}).get("reason") or lead.get("reason")
            steps.append(("No rep could take it", f'{esc(original)}. It was sent to Manager Review.'))
    title = "Why this lead needs a manager" if (waiting or (lead.get("auto") and not (trace or {}).get("pick"))) else "Why this rep? How the lead was routed"
    rows = "".join(f'<div class="step"><span class="n">{n}</span><div><b>{head}</b><div class="d">{body}</div></div></div>'
                   for n, (head, body) in enumerate(steps, 1))
    return f'<div class="why-box"><h4>{title}</h4>{rows}</div>'


# --------------------------------------------------------------------------
# Manager actions: assign a waiting lead to a rep, or mark it handled
# --------------------------------------------------------------------------
# These change the in-memory results only (the CSV files are never touched), so a
# fresh run or Reset puts everything back to the pipeline's own answer.


def candidate_reps(reps, lead, loose=True):
    """Every rep with room who may take this lead, most to least qualified:
    [(rep, [(skill, 'ok'|'any'|'no')], misses)].

    Order: fewest skill mismatches first, then the preferred level (Junior before Senior before Manager,
    but Senior before Manager for Critical leads), then the least busy rep. loose=False keeps only perfect matches.
    """
    order = ["Senior", "Manager"] if lead.get("priority") == "Critical" else ["Junior", "Senior", "Manager"]
    out = []
    for rep in reps:
        if rep.get("current_capacity", 0) >= rep.get("max_capacity", 0) or rep.get("seniority") not in order:
            continue
        marks = []
        for name, wanted, have in (("Region", lead.get("region"), rep.get("region")),
                                   ("Language", lead.get("language"), rep.get("language")),
                                   ("Industry", lead.get("industry"), rep.get("industry"))):
            marks.append((name, "any" if wanted == "Unknown" else "ok" if wanted == have else "no"))
        misses = sum(1 for _, state in marks if state == "no")
        if misses and not loose:
            continue
        out.append((rep, marks, misses))
    out.sort(key=lambda c: (c[2], order.index(c[0]["seniority"]), rep_utilization(c[0]), _natural(c[0]["rep_id"])))
    return out


def candidate_html(rep, marks, rank=None):
    chips = "".join(f'<span class="m {state}">{esc(name)} {"✓" if state == "ok" else "any" if state == "any" else "✗"}</span>'
                    for name, state in marks)
    number = f'<span class="rk">{rank}.</span> ' if rank else ""
    return (f'<div class="cand">{number}<b>{esc(rep.get("rep_id"))}</b> {esc(rep.get("name"))} '
            f'<span class="tag"{tip(str(rep.get("seniority")))}>{esc(rep.get("seniority"))}</span> · '
            f'{rep.get("current_capacity", 0)} / {rep.get("max_capacity", 0)} slots<div class="ms">{chips}</div></div>')


def assign_manually(lead, rep):
    """Give a waiting lead to a rep (only if the rep still has room). Returns True if it worked."""
    if rep.get("current_capacity", 0) >= rep.get("max_capacity", 0):
        return False
    if "auto" not in lead:
        lead["auto"] = {"status": lead.get("assignment_status"), "reason": lead.get("reason")}
    rep["current_capacity"] = rep.get("current_capacity", 0) + 1
    lead.update(manual="assigned", rep_id=rep["rep_id"], rep_name=rep.get("name"), rep_seniority=rep.get("seniority"),
                assignment_status=STATUS_ASSIGNED, reason="Manually assigned by a manager")
    return True


def mark_handled(lead):
    if "auto" not in lead:
        lead["auto"] = {"status": lead.get("assignment_status"), "reason": lead.get("reason")}
    lead.update(manual="handled", assignment_status=STATUS_HANDLED, reason="Marked as handled by a manager")


def undo_manual(reps, lead):
    """Put a hand-edited lead back to what the pipeline decided."""
    if not lead.get("manual"):
        return
    if lead["manual"] == "assigned":
        for rep in reps:
            if rep.get("rep_id") == lead.get("rep_id") and rep.get("current_capacity", 0) > 0:
                rep["current_capacity"] -= 1
                break
        lead.update(rep_id="", rep_name="", rep_seniority="")
    lead.update(assignment_status=lead["auto"]["status"], reason=lead["auto"]["reason"])
    del lead["manual"]


def search_candidates(candidates, query):
    """Keep the candidates whose rep ID or name contains what the manager typed (case-insensitive)."""
    needle = (query or "").strip().lower()
    if not needle:
        return candidates
    return [c for c in candidates if needle in f'{c[0].get("rep_id", "")} {c[0].get("name", "")}'.lower()]


# --------------------------------------------------------------------------
# Fix one lead's missing value, and keep manager work when the CSV changes
# --------------------------------------------------------------------------


def set_override(lead, field, value):
    """Fill a missing region / language / industry on ONE lead. Other leads and the defaults are untouched."""
    if "auto" not in lead:
        lead["auto"] = {"status": lead.get("assignment_status"), "reason": lead.get("reason")}
    lead.setdefault("overrides", {})[field] = value
    lead.setdefault("original_values", {}).setdefault(field, lead.get(field))
    lead[field] = value


def clear_overrides(lead):
    for field, old in (lead.get("original_values") or {}).items():
        lead[field] = old
    lead.pop("overrides", None)
    lead.pop("original_values", None)


def save_manager_work(leads):
    """Everything a manager did by hand, keyed by lead ID, so it survives a re-run."""
    saved = {}
    for lead in leads:
        if lead.get("manual") or lead.get("overrides"):
            saved[lead.get("lead_id")] = {k: lead.get(k) for k in ("manual", "rep_id", "overrides")}
    return saved


def reapply_manager_work(results, saved):
    """Put saved manager work back on freshly routed results. Skips anything that no longer applies:
    a lead that is gone, a value the CSV now has, or a rep that is full. Returns how many edits were kept."""
    by_id = {lead.get("lead_id"): lead for lead in results.get("leads", [])}
    reps = {rep.get("rep_id"): rep for rep in results.get("reps", [])}
    kept = 0
    for lead_id, work in (saved or {}).items():
        lead = by_id.get(lead_id)
        if not lead or not is_waiting(lead):
            continue
        for field, value in (work.get("overrides") or {}).items():
            if lead.get(field) in (None, "", "Unknown"):
                set_override(lead, field, value)
                kept += 1
        if work.get("manual") == "handled":
            mark_handled(lead)
            kept += 1
        elif work.get("manual") == "assigned" and work.get("rep_id") in reps and assign_manually(lead, reps[work["rep_id"]]):
            kept += 1
    return kept


def find_data_dir(here):
    """Where the real CSVs live: $LEAD_DATA_DIR, then <dashboard>/data, then <repo root>/data."""
    import os
    from pathlib import Path
    options = [os.environ.get("LEAD_DATA_DIR"), Path(here) / "data", Path(here).parent / "data"]
    for option in options:
        if option and (Path(option) / "leads_scale.csv").exists():
            return Path(option)
    return Path(here) / "data"  # nothing found: the app shows a plain "file not found" message


def file_signature(paths):
    """(modified-time, size) for each file; changes whenever someone saves the CSV."""
    out = []
    for path in paths:
        try:
            stat = os.stat(path)
            out.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


# --------------------------------------------------------------------------
# Live link: a Google Sheet (or any CSV link) that anyone can edit
# --------------------------------------------------------------------------


def sheet_csv_url(url):
    """Turn a normal Google Sheets link into its CSV download link. Any other link is used as it is."""
    text = (url or "").strip()
    match = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", text)
    if not match:
        return text
    gid = re.search(r"[#&?]gid=(\d+)", text)
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv&gid={gid.group(1) if gid else 0}"


def download_csv(url, dest, must_have):
    """Download a CSV link to dest and return a fingerprint of its contents (changes when anyone edits the sheet).

    must_have: a column name that has to be in the header (catches a login page or the wrong tab).
    Raises ValueError with a plain-English message if the link doesn't give back the CSV.
    """
    link = sheet_csv_url(url)
    if not link.lower().startswith(("http://", "https://")):
        raise ValueError("That doesn't look like a web link. Paste the Google Sheet or CSV link.")
    try:
        with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": "lead-dashboard"}), timeout=20) as reply:
            data = reply.read()
    except Exception as error:
        raise ValueError(f"Couldn't reach the link ({error}). Check the internet connection and that the sheet is shared "
                         "as 'Anyone with the link can view'.") from error
    first_line = data[:2000].decode("utf-8", errors="ignore").splitlines()[0:1]
    header = (first_line[0] if first_line else "").lower().replace(" ", "_")
    if must_have not in header:
        raise ValueError(f"The link didn't return the expected table (no {must_have} column). "
                         "Is it the right tab, and is sharing set to 'Anyone with the link can view'?")
    with open(dest, "wb") as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Edit mode: type a new value into a missing or defaulted cell
# --------------------------------------------------------------------------


def editable_fields(lead):
    """Region / language / industry cells a manager may change: still Unknown, or filled in by a default or fix."""
    return [key for key in SKILL_KEYS
            if lead.get(key) in (None, "", "Unknown") or key in (lead.get("overrides") or {})
            or key.capitalize() in (lead.get("defaults_applied") or [])]


def changed_cells(leads, records):
    """leads and records line up row by row. Returns [(lead, field, new value)] for allowed cells that really changed."""
    out = []
    for lead, record in zip(leads, records):
        for key in editable_fields(lead):
            new = record.get(key.capitalize())
            if new not in (None, "", "Unknown") and new != lead.get(key):
                out.append((lead, key, new))
    return out


def edit_value(reps, lead, field, value):
    """Manager types a new value. If the lead already had a rep, that rep is freed and the lead goes back to
    Manager Review, because the old match was based on the old value."""
    if lead.get("manual"):
        undo_manual(reps, lead)
    if lead.get("rep_id"):
        for rep in reps:
            if rep.get("rep_id") == lead["rep_id"] and rep.get("current_capacity", 0) > 0:
                rep["current_capacity"] -= 1
                break
        if "auto" not in lead:
            lead["auto"] = {"status": lead.get("assignment_status"), "reason": lead.get("reason")}
        lead.update(rep_id="", rep_name="", rep_seniority="", assignment_status=STATUS_REVIEW,
                    reason="Value changed by a manager, needs a rep")
    set_override(lead, field, value)