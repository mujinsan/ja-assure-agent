"""Vanta TOPOLOGY background, rendered inside an st.iframe.

TOPOLOGY is the one Vanta effect built on p5.js rather than three.js, so p5
must load first. The iframe is decorative only: theme.py pins it behind the app
with pointer-events:none, so if either script 404s the page simply keeps the
plain dark theme.

The markup below is a fixed literal with nothing interpolated from users, the
database or model output, which is what st.iframe requires of an HTML src.
"""
import streamlit as st

P5 = "https://cdnjs.cloudflare.com/ajax/libs/p5.js/1.1.9/p5.min.js"
TOPOLOGY = "https://cdnjs.cloudflare.com/ajax/libs/vanta/0.5.24/vanta.topology.min.js"

BG = "#0a0a0c"       # near-black ground
LINE = 0xB9C6D8      # silver / blue-grey topology lines

_HTML = """
<div id="ja-vanta" style="position:fixed;inset:0;width:100vw;height:100vh;
     background:%(bg)s;"></div>
<script src="%(p5)s" onerror="window.__jaFail=1"></script>
<script src="%(topo)s" onerror="window.__jaFail=1"></script>
<script>
(function () {
  var reduce = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Either script missing, or the viewer asked for no motion: leave the plain
  // near-black div in place. That is the fallback.
  if (window.__jaFail || reduce
      || typeof VANTA === 'undefined' || !VANTA.TOPOLOGY) return;
  try {
    VANTA.TOPOLOGY({
      el: "#ja-vanta",
      mouseControls: true,
      touchControls: true,
      gyroControls: false,
      minHeight: 200.00,
      minWidth: 200.00,
      scale: 1.00,
      scaleMobile: 1.00,
      color: %(line)s,
      backgroundColor: %(bgint)s
    });
  } catch (e) { /* fallback: plain dark background */ }
})();
</script>
"""


def render(height=400):
    """Mount the background. CSS overrides the iframe box to fill the viewport.

    Uses st.iframe: st.components.v1.html is deprecated and was slated for
    removal after 2026-06-01.
    """
    st.iframe(
        _HTML % {"p5": P5, "topo": TOPOLOGY, "bg": BG,
                 "line": hex(LINE), "bgint": hex(int(BG[1:], 16))},
        height=height)
