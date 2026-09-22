"""Prism dark theme: global CSS plus small HTML builders for the review card.

Streamlit widgets cannot live inside an st.markdown() string, so a card is built
in two layers: static chrome from the builders below, and real widgets styled by
CSS that targets Streamlit's own DOM. st.container(key="x") stamps a
`st-key-x` class on its element, which is the supported hook for scoping styles
to a container that holds live widgets.
"""
import html

BG = "#0a0a0c"
PANEL = "#141418"
INSET = "#0f0f12"
LINE = "#2e2e36"
LINE_SOFT = "#26262e"
CHIP_LINE = "#33333c"
BTN_LINE = "#3a3a44"
SILVER_LINE = "#5f6a7a"
HEAD = "#f2f2f5"
BODY = "#d4d4da"
MUTED = "#8d8d96"
ACCENT = "#b9c6d8"
PRIMARY = "#d4dbe6"
GREEN = "#9FE1CB"
DOT = "#5DCAA5"

# status -> (background, foreground, label)
STATUS = {
    "pending":   ("#412402", "#FAC775", "Pending"),
    "blocked":   ("#3d1414", "#F5A3A3", "Blocked"),
    "approved":  ("#10301f", "#9FE1CB", "Approved"),
    "rejected":  ("#2b2b33", "#b9b9c2", "Rejected"),
    "scheduled": ("#12243a", "#a8c8f0", "Scheduled"),
}

RED = "#F5534E"          # reserved: compliance and security signals only
SERIF = "'Instrument Serif', Georgia, 'Times New Roman', serif"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap');

/* ---- editorial serif: display only, never body/labels/buttons ---- */
.ja-title, .stApp h1, .stApp h2, .stApp h3,
[data-testid="stMetricValue"] {{
  font-family:{SERIF}; font-weight:400; letter-spacing:.2px;
}}
.stApp h2, .stApp h3 {{ color:{HEAD}; }}
[data-testid="stMetricValue"] {{ font-size:2rem !important; }}
/* metric labels stay sans */
[data-testid="stMetricLabel"] {{ font-family:inherit; }}

/* ---- BLOCKED rubber stamp ---- */
.ja-stamp {{
  position:absolute; top:12px; right:18px; z-index:5; pointer-events:none;
  font-family:{SERIF}; font-size:20px; font-weight:700; letter-spacing:3px;
  color:{RED}; border:2.5px solid {RED}; border-radius:5px;
  padding:1px 12px 3px; opacity:.82;
  /* uneven ink: two soft blotches so the fill isn't flat */
  background:
    radial-gradient(ellipse at 22% 34%, rgba(245,83,78,.13) 0 34%, transparent 36%),
    radial-gradient(ellipse at 74% 66%, rgba(245,83,78,.09) 0 28%, transparent 30%);
  transform:rotate(-8deg);
  animation:ja-stamp-in 350ms cubic-bezier(.2,1.45,.35,1) both;
}}
@keyframes ja-stamp-in {{
  0%   {{ transform:rotate(-8deg) scale(1.6); opacity:0; }}
  55%  {{ transform:rotate(-8deg) scale(.93); opacity:.95; }}
  78%  {{ transform:rotate(-8deg) scale(1.05); opacity:.74; }}
  100% {{ transform:rotate(-8deg) scale(1); opacity:.82; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .ja-stamp {{ animation:none; transform:rotate(-8deg) scale(1); opacity:.82; }}
}}

/* ---- offending phrase: red wavy underline, rule name on hover ---- */
.ja-hit {{
  text-decoration:underline wavy {RED};
  text-decoration-thickness:1.5px;
  text-underline-offset:3px;
  cursor:help;
}}

html, body {{ background:{BG}; }}

/* ---- pin vanta background iframe behind the whole app ---- */
iframe[title="streamlit.components.v1.html"],
[data-testid="stCustomComponentV1"],
[data-testid="stCustomComponentV1"] > iframe {{
  position: fixed !important;
  inset: 0 !important;
  top: 0 !important;
  left: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  z-index: 0 !important;
  pointer-events: none !important;
  border: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
}}

/* ---- transparent containers & content z-index ---- */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stHeader"],
.main,
.block-container {{
  background: transparent !important;
}}

[data-testid="stAppViewContainer"] > .main,
.block-container,
[data-testid="stHeader"] {{
  position: relative;
  z-index: 1;
}}

/* ---- dark overlay for main app ---- */
.ja-main-overlay {{
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(10, 10, 12, 0.73);
  z-index: 0;
  pointer-events: none;
}}

.block-container {{ padding-top:2.2rem; max-width:1100px; }}

/* ---- tabs: quiet labels, silver underline on the active one ---- */
.stTabs [data-baseweb="tab-list"] {{
  gap:18px; border-bottom:1px solid {LINE_SOFT}; background:transparent;
}}
.stTabs [data-baseweb="tab"] {{
  background:transparent; color:{MUTED}; font-size:13px;
  padding:0 0 8px 0; height:auto;
}}
.stTabs [aria-selected="true"] {{
  color:{HEAD}; border-bottom:1.5px solid {ACCENT};
}}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display:none; }}

/* ---- the review card: a real container holding real widgets ---- */
[class*="st-key-jacard-"] {{
  background:{PANEL}; border:1px solid {LINE}; border-radius:12px;
  padding:14px 16px; margin-bottom:14px;
  position:relative;   /* anchors the BLOCKED stamp */
}}

/* ---- text area: flat inset, silver focus ring ---- */
.stTextArea textarea {{
  background:{INSET} !important; color:{BODY} !important;
  border:1px solid {CHIP_LINE} !important; border-radius:8px;
  font-size:13px; line-height:1.6;
}}
.stTextArea textarea:focus {{ border-color:{ACCENT} !important; box-shadow:none !important; }}
.stTextArea label, .stSelectbox label, .stTextInput label, .stMultiSelect label {{
  color:{MUTED} !important; font-size:11px !important;
}}

/* ---- buttons: outlined secondary, light silver primary ---- */
.stButton > button {{
  background:transparent; color:{BODY};
  border:1px solid {BTN_LINE}; border-radius:8px;
  font-size:12px; padding:6px 16px; min-height:0;
}}
.stButton > button:hover {{ border-color:{ACCENT}; color:{HEAD}; background:transparent; }}
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {{
  background:{PRIMARY}; color:{BG}; border:1px solid {PRIMARY}; font-weight:500;
}}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {{
  background:#e4e9f1; color:{BG}; border-color:#e4e9f1;
}}
.stButton > button:disabled {{ opacity:.4; }}

/* ---- inputs and selects ---- */
.stSelectbox [data-baseweb="select"] > div, .stMultiSelect [data-baseweb="select"] > div,
.stTextInput input {{
  background:{INSET} !important; border-color:{CHIP_LINE} !important;
  color:{BODY} !important; font-size:13px;
}}

/* ---- inline "Show prompt" style expanders ---- */
[data-testid="stExpander"] details {{
  background:transparent; border:1px solid {CHIP_LINE}; border-radius:8px;
}}
[data-testid="stExpander"] summary {{ font-size:12px; color:{MUTED}; }}
[data-testid="stExpander"] summary:hover {{ color:{ACCENT}; }}

/* ---- dataframes ---- */
[data-testid="stDataFrame"] {{ border:1px solid {LINE}; border-radius:10px; }}

/* ---- alerts: flatten Streamlit's saturated blocks ---- */
[data-testid="stAlert"] {{
  background:{INSET}; border:1px solid {CHIP_LINE}; border-radius:8px;
  color:{BODY}; font-size:12px;
}}

/* ---- hide Streamlit deploy button & main menu ---- */
#MainMenu,
[data-testid="stMainMenu"],
[data-testid="stAppDeployButton"],
.stDeployButton,
[data-testid="stToolbarActions"],
header [data-testid="stHeaderActionElements"] {{
  display: none !important;
  visibility: hidden !important;
}}

/* ---- section containers & scroll-driven entry animations ---- */
[class*="st-key-section-"] {{
  margin-bottom: 2.2rem;
}}

@media (prefers-reduced-motion: no-preference) {{
  @supports ((animation-timeline: view()) and (animation-range: entry)) {{
    @keyframes section-fade-rise {{
      from {{
        opacity: 0;
        transform: translateY(20px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}
    [class*="st-key-section-"] {{
      animation: section-fade-rise 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
      animation-timeline: view();
      animation-range: entry 0% cover 25%;
    }}
  }}
}}

/* ---- soft metric cards fallback/native styling ---- */
[data-testid="stMetric"] {{
  background: {PANEL};
  border: 1px solid {LINE};
  border-radius: 12px;
  padding: 14px 18px;
}}
</style>
"""


def _esc(s):
    return html.escape(str(s or ""))


def header(subtitle, mode_text, ok=True):
    """Title block with the live/mode pill on the right."""
    dot = DOT if ok else "#F5A3A3"
    return f"""
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">
  <div>
    <div class="ja-title" style="font-size:38px;line-height:1.15;color:{HEAD};">JA Assure · AI marketing agent</div>
    <div style="font-size:12px;color:{MUTED};margin-top:2px;">{_esc(subtitle)}</div>
  </div>
  <div style="font-size:11px;padding:4px 10px;border-radius:999px;border:1px solid {BTN_LINE};
              color:{ACCENT};white-space:nowrap;">
    <span style="color:{dot};">●</span> {_esc(mode_text)}
  </div>
</div>
"""


AMBER = "#FAC775"

# state -> (colour, mark, suffix)
STEP_STATE = {
    "done":    (GREEN, "✓", ""),
    "waiting": (ACCENT, "◷", ""),
    "mock":    (AMBER, "!", " (mock)"),
}


def pipeline_steps(steps):
    """steps: list of (label, state) where state is done | waiting | mock.

    A mock step goes amber and says so: a green tick over mock output claims
    work the model never did.
    """
    out = []
    for label, state in steps:
        colour, mark, suffix = STEP_STATE.get(state, STEP_STATE["waiting"])
        border = colour if state == "mock" else LINE
        out.append(
            f'<span style="padding:4px 10px;border-radius:999px;background:{PANEL};'
            f'border:1px solid {border};color:{colour};">'
            f'{mark} {_esc(label)}{suffix}</span>')
    return ('<div style="display:flex;gap:6px;margin-top:14px;font-size:11px;'
            f'flex-wrap:wrap;">{"".join(out)}</div>')


def mock_banner():
    """Loud in-card warning that this asset is template text, not model output."""
    return (f'<div style="margin-top:10px;border:1px solid {AMBER};border-radius:8px;'
            f'padding:6px 10px;font-size:12px;color:{AMBER};background:#2a1c05;">'
            f'! MOCK - do not approve</div>')


def card_head(meta, status, revised=False):
    """Meta chips on the left, optional Revised badge, status badge on the right."""
    chips = "".join(
        f'<span style="padding:2px 8px;border:1px solid {CHIP_LINE};border-radius:6px;">'
        f'{_esc(m)}</span>' for m in meta)
    if revised:
        # silver outline, deliberately quieter than the status pill
        chips += (f'<span style="padding:2px 8px;border:1px solid {SILVER_LINE};'
                  f'border-radius:6px;color:{ACCENT};">Revised ✓</span>')
    bg, fg, label = STATUS.get(status, ("#2b2b33", BODY, status))
    return f"""
<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
  <div style="display:flex;gap:6px;font-size:11px;color:{MUTED};flex-wrap:wrap;">{chips}</div>
  <span style="font-size:11px;padding:3px 10px;border-radius:999px;background:{bg};color:{fg};">
    {_esc(label)}</span>
</div>
"""


def blocked_stamp():
    """Rotated rubber stamp, positioned against the card container."""
    return '<div class="ja-stamp">BLOCKED</div>'


def highlight(text, spans):
    """Post text with rule-layer hits wavy-underlined and titled.

    spans: [(start, end, rule_name)] from compliance.hard_matches(), which
    guarantees they are sorted and non-overlapping.
    """
    out, cursor = [], 0
    for start, end, rule in spans:
        out.append(_esc(text[cursor:start]))
        out.append(f'<span class="ja-hit" title="{_esc(rule)}">'
                   f'{_esc(text[start:end])}</span>')
        cursor = end
    out.append(_esc(text[cursor:]))
    return (f'<div style="font-size:13px;line-height:1.7;color:{BODY};margin-top:10px;'
            f'white-space:pre-wrap;">{"".join(out)}</div>')


def avatar_row(brand, niche, platform):
    """Platform-styled author row: initials disc, brand, niche - Promoted."""
    words = str(brand).split()
    # "Jaguar Transit" -> JT, "DoctorShield" -> DS (internal capitals), "Jade" -> J
    caps = [c for c in str(brand) if c.isupper()]
    initials = ("".join(w[0] for w in words[:2]) if len(words) > 1
                else "".join(caps[:2]) or str(brand)[:1]).upper()
    return f"""
<div style="display:flex;gap:10px;align-items:center;margin-top:12px;">
  <div style="width:32px;height:32px;border-radius:50%;background:{LINE_SOFT};display:flex;
              align-items:center;justify-content:center;font-size:12px;color:{ACCENT};">
    {_esc(initials)}</div>
  <div>
    <div style="font-size:13px;color:{HEAD};">{_esc(brand)}</div>
    <div style="font-size:11px;color:{MUTED};">{_esc(niche)} · Promoted on {_esc(platform)}</div>
  </div>
</div>
"""


def compliance_boxes(rule_line, ai_line, rule_ok=True, ai_ok=True):
    """Two-box breakdown: deterministic rule layer beside the LLM rubric layer."""
    def box(title, line, ok):
        colour = GREEN if ok else "#F5A3A3"
        mark = "✓" if ok else "✕"
        return (f'<div style="background:{INSET};border-radius:8px;padding:8px 10px;">'
                f'<div style="color:{MUTED};font-size:11px;">{title}</div>'
                f'<div style="color:{colour};margin-top:2px;">{mark} {_esc(line)}</div></div>')
    return ('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));'
            'gap:8px;margin-top:12px;font-size:12px;">'
            + box("Rule layer", rule_line, rule_ok)
            + box("AI layer", ai_line, ai_ok) + '</div>')


def lessons_box(count, notes):
    """Silver-bordered memory box. notes: list of short strings."""
    body = " · ".join(_esc(n) for n in notes) if notes else "No lessons recorded yet"
    return f"""
<div style="margin-top:10px;border:1px solid {SILVER_LINE};border-radius:8px;
            padding:8px 10px;font-size:12px;">
  <div style="color:{ACCENT};">◈ Lessons applied from past feedback · {int(count)}</div>
  <div style="color:{MUTED};margin-top:4px;line-height:1.5;">{body}</div>
</div>
"""


def post_body(text):
    return (f'<div style="font-size:13px;line-height:1.6;color:{BODY};margin-top:10px;'
            f'white-space:pre-wrap;">{_esc(text)}</div>')


def audit_pill(broken_id=None):
    if broken_id is None:
        return (f'<span style="display:inline-block;font-size:11px;padding:3px 10px;'
                f'border-radius:999px;background:#10301f;border:1px solid #1b4d31;color:{GREEN};">'
                f'<span style="color:{DOT};">●</span> Audit chain verified</span>')
    return (f'<span style="display:inline-block;font-size:11px;padding:3px 10px;'
            f'border-radius:999px;background:#3d1414;border:1px solid {RED};color:#F5A3A3;">'
            f'<span style="color:{RED};">●</span> Tampering detected at entry #{int(broken_id)}</span>')


def section_label(text):
    """Small uppercase section label with muted styling."""
    return (f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;'
            f'letter-spacing:1px;color:{MUTED};margin-bottom:12px;">{_esc(text)}</div>')


def soft_metric_card(label, value, trend_text=None, trend_color=None):
    """Soft card for overview metrics with trend indicator."""
    trend_html = ""
    if trend_text:
        color = trend_color or MUTED
        trend_html = f'<div style="font-size:11px;color:{color};margin-top:6px;">{_esc(trend_text)}</div>'
    return f"""
<div style="background:{PANEL};border:1px solid {LINE};border-radius:12px;padding:14px 18px;">
  <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;color:{MUTED};font-weight:500;">{_esc(label)}</div>
  <div style="font-family:{SERIF};font-size:32px;line-height:1.15;color:{HEAD};margin:6px 0 2px 0;">{_esc(value)}</div>
  {trend_html}
</div>
"""


