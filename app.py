import difflib
import altair as alt
import pandas as pd
import streamlit as st
import db, pipeline, review, theme, vanta, worker
from agents import llm, compliance, publisher
from agents.llm import live, MODEL
from config import BRANDS, PLATFORMS, LANGUAGES, FEEDBACK_TAGS

st.set_page_config(page_title="JA Assure AI Marketing Agent", layout="wide")
db.init()
st.markdown(theme.CSS, unsafe_allow_html=True)

# --- animated background + intro splash -------------------------------------
st.session_state.setdefault("entered", False)

if not st.session_state["entered"]:
    if st.session_state.get("bg_on", True):
        vanta.render()                       # full strength, no scrim
    st.markdown(theme.splash(), unsafe_allow_html=True)
    _l, _mid, _r = st.columns([2, 1, 2])
    with _mid:
        if st.button("Enter", type="primary", key="enter-btn",
                     use_container_width=True):
            st.session_state["entered"] = True
            st.rerun()
    st.stop()                                # renders the splash and nothing else

# st.sidebar does not mount in Streamlit 1.63 (reproducible with no custom CSS),
# so these controls sit in a right-aligned row instead.
_sp, _tg, _rp = st.columns([6, 2, 2])
with _tg:
    bg_on = st.toggle("Animated background", value=True, key="bg_on")
with _rp:
    if st.button("Replay intro", type="tertiary"):
        st.session_state["entered"] = False
        st.rerun()
if bg_on:
    vanta.render()
    st.markdown(theme.main_overlay(), unsafe_allow_html=True)
# ---------------------------------------------------------------------------

if not live():
    mode = "MOCK (no GEMINI_API_KEY)"
elif llm.last_error:
    mode = "LIVE - last call FAILED, using mock"
elif llm.last_provider == "groq":
    mode = f"LIVE (Gemini chain exhausted -> Groq fallback: {llm.GROQ_MODEL})"
elif llm.last_model and llm.last_model != MODEL:
    mode = f"LIVE (fallback model: {llm.last_model})"
else:
    mode = f"LIVE ({MODEL})"
if llm.exhausted_models:
    mode += f" | exhausted: {', '.join(sorted(llm.exhausted_models))}"
st.markdown(
    theme.header("Research → Create → Comply → Review → Learn", mode,
                 ok=live() and not llm.last_error),
    unsafe_allow_html=True)

gen, rev, queue, insights = st.tabs(["Generate", "Review", "Approved queue", "Learning & Audit"])

with gen:
    c1, c2 = st.columns(2)
    brand = c1.selectbox("Brand", list(BRANDS))
    language = c2.selectbox("Language", LANGUAGES)
    platforms = st.multiselect("Platforms", list(PLATFORMS), default=["LinkedIn", "Instagram"])
    topic = st.text_input("Topic / idea", "Why jewellers need cover for stock in transit")
    use_research = st.checkbox("Use live research (needs TAVILY_API_KEY)")
    if st.button("Run pipeline", type="primary", disabled=not platforms):
        with st.spinner("Research -> content -> compliance..."):
            created, researched = pipeline.run(brand, platforms, language, topic, use_research)
        # Derive from the providers actually recorded on the assets: last_summary
        # only describes the final call, and a run makes several.
        provs = {prov for *_, prov in created}
        mocked = "mock" in provs
        if mocked:
            st.warning(llm.last_summary or "All providers failed - mock output")
        elif "groq" in provs:
            st.info(llm.last_summary or f"Gemini unavailable - answered by {llm.GROQ_MODEL}")
        elif llm.last_summary:
            st.info(llm.last_summary)
        blocked = sum(1 for *_, ok, _, _ in created if not ok)
        wrote_state = "mock" if mocked else ("done" if created else "waiting")
        st.markdown(theme.pipeline_steps([
            ("Researched" if researched else "Research skipped",
             "done" if researched else "waiting"),
            (f"Wrote {len(created)} variants", wrote_state),
            ("Compliance checked", wrote_state),
            (f"{len(created) - blocked} awaiting review", "waiting"),
        ]), unsafe_allow_html=True)
        for aid, p, v, ok, reasons, prov in created:
            tail = " [MOCK]" if prov == "mock" else ""
            if ok:
                st.write(f"#{aid} {p} variant {v}: passed compliance -> review{tail}")
            else:
                st.error(f"#{aid} {p} variant {v}: BLOCKED - {'; '.join(reasons)}{tail}")

with rev:
    show_blocked = st.toggle("Also show compliance-blocked assets")
    items = db.list_assets("pending") + (db.list_assets("blocked") if show_blocked else [])
    if not items:
        st.info("Nothing to review.")
    for a in items:
        # key=... stamps `st-key-jacard-<id>` on the container so CSS can style
        # the card while real widgets stay inside it.
        with st.container(key=f"jacard-{a['id']}"):
            if a["status"] == "blocked":
                st.markdown(theme.blocked_stamp(), unsafe_allow_html=True)
            st.markdown(theme.card_head(
                [f"#{a['id']}", a["brand"], a["platform"], a["language"],
                 f"Variant {a['variant']}"], a["status"],
                revised=bool(a["lessons_used"])), unsafe_allow_html=True)
            st.markdown(theme.avatar_row(
                a["brand"], BRANDS.get(a["brand"], {}).get("niche", ""),
                a["platform"]), unsafe_allow_html=True)

            is_mock = a["provider"] == "mock"
            if is_mock:
                st.markdown(theme.mock_banner(), unsafe_allow_html=True)

            rule_line, rule_ok, ai_line, ai_ok = compliance.split_reasons(a["compliance_reasons"])
            st.markdown(theme.compliance_boxes(rule_line, ai_line, rule_ok, ai_ok),
                        unsafe_allow_html=True)

            notes = [l["note"] or l["tag"] for l in db.get_lessons(a["brand"], limit=3)]
            st.markdown(theme.lessons_box(a["lessons_used"], notes), unsafe_allow_html=True)

            # A textarea can't carry underlines or tooltips, so blocked assets
            # get a read-only marked-up preview above the editable field.
            hits = compliance.hard_matches(a["content"]) if a["status"] == "blocked" else []
            if hits:
                st.markdown(theme.highlight(a["content"], hits), unsafe_allow_html=True)

            text = st.text_area("Content (edit before approving)", a["content"],
                                key=f"t{a['id']}", height=150)
            with st.expander(f"Image idea · {a['platform']}"):
                st.caption(a["image_idea"] or "None suggested")

            c1, c2, c3 = st.columns([1, 1, 2])
            # Heuristic suggestion, no LLM. index=None leaves it genuinely empty
            # rather than silently defaulting to the first tag in the list.
            suggested = review.suggest_tag(a)
            tag = c3.selectbox(
                "Reason tag", FEEDBACK_TAGS,
                index=FEEDBACK_TAGS.index(suggested) if suggested in FEEDBACK_TAGS else None,
                placeholder="Choose a reason", key=f"g{a['id']}")
            if suggested:
                c3.caption(f"(suggested) {suggested}")
            note = c3.text_input("Note", key=f"n{a['id']}")
            # Mock assets are template text, not model output: never approvable.
            if c1.button("Approve", key=f"a{a['id']}", type="primary",
                         disabled=a["status"] == "blocked" or is_mock,
                         help="Mock output cannot be approved" if is_mock else None):
                edited = text.strip() != a["content"].strip()
                db.review(a["id"], "approve", text, tag if edited else None, note)
                st.rerun()
            if c2.button("Reject", key=f"r{a['id']}"):
                if not tag:
                    st.warning("Pick a reason tag before rejecting.")
                else:
                    db.review(a["id"], "reject", text, tag, note)
                    st.rerun()

with queue:
    awaiting = db.list_assets("approved")
    in_flight = db.list_assets("posting")
    posted = db.list_assets("scheduled")
    failed = db.list_assets("failed")

    with st.container(key="section-queue"):
        st.markdown(theme.section_label("Approved queue"), unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:12px;color:{theme.MUTED};margin:-4px 0 14px 0;">'
            "Project 2 contract: a worker polls status='approved', posts, then sets "
            "status='scheduled' and writes back a post_id.</div>",
            unsafe_allow_html=True)

        pcol, bcol = st.columns([3, 1])
        with pcol:
            st.markdown(theme.provider_pill(publisher.active_provider()),
                        unsafe_allow_html=True)
        with bcol:
            if st.button("Run worker once", key="worker-once",
                         use_container_width=True):
                with st.spinner("Publishing approved assets..."):
                    counts = worker.run_once()
                st.success(" · ".join(f"{k.replace('_', ' ')}: {v}"
                                           for k, v in counts.items() if v) or "Nothing to post")
                st.rerun()

        platforms_covered = len({a["platform"] for a in awaiting + posted})
        q1, q2, q3 = st.columns(3)
        with q1:
            st.markdown(theme.soft_metric_card(
                "Awaiting post", str(len(awaiting)),
                "Ready for the worker" if awaiting else "Nothing queued",
                theme.ACCENT if awaiting else theme.MUTED), unsafe_allow_html=True)
        with q2:
            st.markdown(theme.soft_metric_card(
                "Posted", str(len(posted)),
                "Has post_id" if posted else "None posted yet",
                theme.GREEN if posted else theme.MUTED), unsafe_allow_html=True)
        with q3:
            st.markdown(theme.soft_metric_card(
                "Platforms", str(platforms_covered),
                ", ".join(sorted({a["platform"] for a in awaiting + posted})) or "—",
                theme.MUTED), unsafe_allow_html=True)

    if not (awaiting or in_flight or posted or failed):
        st.info("No approved assets yet.")
    else:
        # one markdown call per group: queue_card emits no widgets
        for label, group in (("Awaiting post", awaiting), ("Posting", in_flight),
                             ("Posted", posted), ("Failed", failed)):
            if not group:
                continue
            with st.container(key=f"section-queue-{label.split()[0].lower()}"):
                st.markdown(theme.section_label(f"{label} · {len(group)}"),
                            unsafe_allow_html=True)
                st.markdown("".join(theme.queue_card(a) for a in group),
                            unsafe_allow_html=True)

with insights:
    reviewed = [a for a in db.list_assets() if a["status"] in ("approved", "rejected", "scheduled")]
    reviewed.sort(key=lambda a: a.get("reviewed_at") or a.get("created_at") or "")

    batch_size = st.session_state.get("learning_batch_size", 5)
    all_ls = db.all_lessons()
    total_reviews = len(reviewed)

    batches_data = []
    if total_reviews > 0:
        total_batches = (total_reviews + batch_size - 1) // batch_size
        is_partial = (total_reviews % batch_size) != 0
        for b in range(1, total_batches + 1):
            s_idx = (b - 1) * batch_size
            e_idx = min(b * batch_size, total_reviews)
            b_slice = reviewed[s_idx:e_idx]
            b_count = len(b_slice)
            b_rej = sum(1 for a in b_slice if a["status"] == "rejected") / b_count
            b_edits = [
                round(1 - difflib.SequenceMatcher(None, o or "", c or "").ratio(), 3)
                for o, c in zip((a.get("original_content") or "" for a in b_slice),
                                (a.get("content") or "" for a in b_slice))
            ]
            b_edit_mean = sum(b_edits) / len(b_edits) if b_edits else 0.0
            b_lessons = sum(
                1 for a in b_slice
                if a["status"] == "rejected" or (a.get("original_content") or "").strip() != (a.get("content") or "").strip()
            )
            lbl = f"Batch {b} (partial)" if (b == total_batches and is_partial) else f"Batch {b}"
            batches_data.append({
                "batch_num": b,
                "label": lbl,
                "count": b_count,
                "rejection_rate": b_rej,
                "edit_amount": b_edit_mean,
                "lessons": b_lessons,
            })

    # 1. Overview
    with st.container(key="section-overview"):
        st.markdown(theme.section_label("Overview"), unsafe_allow_html=True)
        if total_reviews > 0:
            overall_rej = sum(1 for a in reviewed if a["status"] == "rejected") / total_reviews
            latest = batches_data[-1]
            has_prev = len(batches_data) >= 2
            prev = batches_data[-2] if has_prev else None

            rev_val = str(total_reviews)
            if has_prev:
                rev_diff = latest["count"] - prev["count"]
                if rev_diff == 0:
                    rev_trend = f"{latest['count']} in latest batch"
                elif rev_diff > 0:
                    rev_trend = f"+{rev_diff} vs prev batch"
                else:
                    rev_trend = f"{rev_diff} vs prev batch"
                rev_color = theme.ACCENT
            else:
                rev_trend = f"{latest['count']} in first batch"
                rev_color = theme.MUTED

            rej_val = f"{overall_rej:.0%}"
            if has_prev:
                rej_diff = latest["rejection_rate"] - prev["rejection_rate"]
                if rej_diff < 0:
                    rej_trend = f"↓ {abs(rej_diff):.0%} vs prev batch"
                    rej_color = theme.GREEN
                elif rej_diff > 0:
                    rej_trend = f"↑ {rej_diff:.0%} vs prev batch"
                    rej_color = theme.RED
                else:
                    rej_trend = "0% vs prev batch"
                    rej_color = theme.MUTED
            else:
                rej_trend = "First batch (baseline)"
                rej_color = theme.MUTED

            ls_val = str(len(all_ls))
            if has_prev:
                ls_diff = latest["lessons"] - prev["lessons"]
                if ls_diff < 0:
                    ls_trend = f"↓ {abs(ls_diff)} vs prev batch"
                    ls_color = theme.GREEN
                elif ls_diff > 0:
                    ls_trend = f"↑ {ls_diff} vs prev batch"
                    ls_color = theme.AMBER
                else:
                    ls_trend = "0 vs prev batch"
                    ls_color = theme.MUTED
            else:
                ls_trend = f"{latest['lessons']} from first batch"
                ls_color = theme.MUTED
        else:
            rev_val, rev_trend, rev_color = "0", "No reviews yet", theme.MUTED
            rej_val, rej_trend, rej_color = "0%", "—", theme.MUTED
            ls_val, ls_trend, ls_color = str(len(all_ls)), "—", theme.MUTED

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(theme.soft_metric_card("Reviewed", rev_val, rev_trend, rev_color),
                        unsafe_allow_html=True)
        with c2:
            st.markdown(theme.soft_metric_card("Rejection rate", rej_val, rej_trend, rej_color),
                        unsafe_allow_html=True)
        with c3:
            st.markdown(theme.soft_metric_card("Lessons stored", ls_val, ls_trend, ls_color),
                        unsafe_allow_html=True)

    # 2. Learning curve
    with st.container(key="section-curve"):
        st.markdown(theme.section_label("Learning curve"), unsafe_allow_html=True)
        col_exp, col_size = st.columns([3, 1])
        with col_exp:
            st.markdown(f'<div style="font-size:12px;color:{theme.MUTED};margin-top:14px;">'
                        f'Tracking rejection rate and human copy edit distance averaged across consecutive review batches over time.</div>',
                        unsafe_allow_html=True)
        with col_size:
            selected_size = st.slider("Batch size", min_value=3, max_value=10, value=batch_size, step=1, key="learning_batch_size")

        if total_reviews > 0:
            if selected_size != batch_size:
                b_size = selected_size
                t_batches = (total_reviews + b_size - 1) // b_size
                part = (total_reviews % b_size) != 0
                chart_rows = []
                for b in range(1, t_batches + 1):
                    s_idx = (b - 1) * b_size
                    e_idx = min(b * b_size, total_reviews)
                    b_slice = reviewed[s_idx:e_idx]
                    b_rej = sum(1 for a in b_slice if a["status"] == "rejected") / len(b_slice)
                    b_edits = [
                        round(1 - difflib.SequenceMatcher(None, o or "", c or "").ratio(), 3)
                        for o, c in zip((a.get("original_content") or "" for a in b_slice),
                                        (a.get("content") or "" for a in b_slice))
                    ]
                    b_edit_mean = sum(b_edits) / len(b_edits) if b_edits else 0.0
                    lbl = f"Batch {b} (partial)" if (b == t_batches and part) else f"Batch {b}"
                    chart_rows.append({"batch": lbl, "Rejection rate": b_rej, "Edit amount": b_edit_mean})
            else:
                chart_rows = [
                    {"batch": bd["label"], "Rejection rate": bd["rejection_rate"], "Edit amount": bd["edit_amount"]}
                    for bd in batches_data
                ]

            chart_df = pd.DataFrame(chart_rows)
            melted = chart_df.melt(
                id_vars=["batch"],
                value_vars=["Rejection rate", "Edit amount"],
                var_name="Series",
                value_name="Rate"
            )

            chart = alt.Chart(melted).mark_line(point=True, strokeWidth=2).encode(
                x=alt.X("batch:N", title="Batch", sort=None),
                y=alt.Y(
                    "Rate:Q",
                    scale=alt.Scale(domain=[0, 1], clamp=True),
                    axis=alt.Axis(format=".0%", tickCount=5, title=None)
                ),
                color=alt.Color(
                    "Series:N",
                    scale=alt.Scale(
                        domain=["Rejection rate", "Edit amount"],
                        range=[theme.RED, theme.GREEN]
                    ),
                    legend=alt.Legend(title=None, orient="top")
                ),
                tooltip=[
                    alt.Tooltip("batch:N", title="Batch"),
                    alt.Tooltip("Series:N", title="Series"),
                    alt.Tooltip("Rate:Q", title="Rate", format=".1%")
                ]
            ).properties(height=260)

            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Review some assets to see the learning curve.")

    # 3. Lessons
    with st.container(key="section-lessons"):
        st.markdown(theme.section_label("Lessons"), unsafe_allow_html=True)
        if all_ls:
            by_tag = {}
            for l in all_ls:
                tag = (l.get("tag") or "general").strip()
                by_tag.setdefault(tag, []).append(l)

            sorted_tags = sorted(by_tag.keys(), key=lambda t: len(by_tag[t]), reverse=True)
            for tag in sorted_tags:
                group = by_tag[tag]
                count = len(group)
                with st.expander(f"{tag} ({count})", expanded=False):
                    notes = []
                    seen_notes = set()
                    for l in group:
                        n = (l.get("note") or "").strip()
                        if n and n not in seen_notes:
                            seen_notes.add(n)
                            notes.append(n)

                    snippets = []
                    seen_bads = set()
                    for l in group:
                        be = (l.get("bad_example") or "").strip()
                        if be:
                            snip = (be[:117] + "...") if len(be) > 120 else be
                            if snip not in seen_bads:
                                seen_bads.add(snip)
                                snippets.append(snip)

                    if notes:
                        st.markdown(
                            f'<div style="font-size:11px;font-weight:600;letter-spacing:0.5px;'
                            f'color:{theme.ACCENT};margin-bottom:6px;">Notes</div>',
                            unsafe_allow_html=True
                        )
                        for n in notes:
                            st.markdown(f"- {n}")

                    if snippets:
                        st.markdown(
                            f'<div style="font-size:11px;font-weight:600;letter-spacing:0.5px;'
                            f'color:{theme.ACCENT};margin-top:10px;margin-bottom:6px;">Flagged Snippets</div>',
                            unsafe_allow_html=True
                        )
                        for snip in snippets:
                            st.markdown(
                                f'<div style="font-size:11px;font-family:monospace;background:{theme.INSET};'
                                f'border:1px solid {theme.CHIP_LINE};border-radius:6px;padding:6px 10px;'
                                f'margin-bottom:6px;color:{theme.BODY};white-space:pre-wrap;">"{theme._esc(snip)}"</div>',
                                unsafe_allow_html=True
                            )

                    if not notes and not snippets:
                        st.caption("No notes or examples recorded for this tag.")
        else:
            st.info("No lessons recorded yet.")

    # 4. Audit trail
    with st.container(key="section-audit"):
        st.markdown(theme.section_label("Audit trail"), unsafe_allow_html=True)
        broken = db.verify_chain()
        st.markdown(theme.audit_pill(broken), unsafe_allow_html=True)

        with st.expander("Show full log", expanded=False):
            show_chain = st.toggle("Show chain", value=False)
            entries = db.audit()
            cols = ["ts", "asset_id", "action", "actor", "detail"]
            if show_chain:
                cols.append("prev  hash")
            if entries:
                df_audit = pd.DataFrame(entries)
                if show_chain:
                    df_audit["prev  hash"] = [
                        f"{(r.get('prev_hash') or '')[:4]:<4}  {(r.get('hash') or '')[:4]:<4}"
                        for r in entries
                    ]
                st.dataframe(df_audit[[c for c in cols if c in df_audit.columns]],
                             hide_index=True, use_container_width=True)
            else:
                st.dataframe(pd.DataFrame(columns=cols), hide_index=True, use_container_width=True)


