import difflib
import pandas as pd
import streamlit as st
import db, pipeline, review, theme
from agents import llm, compliance
from agents.llm import live, MODEL
from config import BRANDS, PLATFORMS, LANGUAGES, FEEDBACK_TAGS

st.set_page_config(page_title="JA Assure AI Marketing Agent", layout="wide")
db.init()
st.markdown(theme.CSS, unsafe_allow_html=True)

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
    st.caption("Project 2 contract: a worker polls status='approved', posts, sets status='scheduled' + post_id.")
    rows = db.list_assets("approved") + db.list_assets("scheduled")
    if rows:
        st.dataframe(pd.DataFrame(rows)[["id", "brand", "platform", "language", "content", "status", "post_id"]],
                     use_container_width=True)
    else:
        st.info("No approved assets yet.")

with insights:
    reviewed = [a for a in db.list_assets() if a["status"] in ("approved", "rejected", "scheduled")]
    reviewed.sort(key=lambda a: a["reviewed_at"] or "")
    if reviewed:
        df = pd.DataFrame(reviewed)
        df["rejected"] = (df["status"] == "rejected").astype(int)
        df["edit_amount"] = [
            round(1 - difflib.SequenceMatcher(None, o or "", c or "").ratio(), 3)
            for o, c in zip(df["original_content"], df["content"])]
        df["batch"] = [i // 4 + 1 for i in range(len(df))]
        trend = df.groupby("batch")[["rejected", "edit_amount"]].mean()
        m1, m2, m3 = st.columns(3)
        m1.metric("Reviewed", len(df))
        m2.metric("Rejection Rate", f"{df['rejected'].mean():.0%}")
        m3.metric("Lessons Stored", len(db.all_lessons()))
        st.subheader("Is It Improving? (Per Batch Of 4 Reviews)")
        st.line_chart(trend)
    else:
        st.info("Review Some Assets To See The Learning Curve.")
    st.subheader("Lessons Learned Memory")
    ls = db.all_lessons()
    if ls:
        st.dataframe(pd.DataFrame(ls)[["id", "brand", "platform", "tag", "note", "bad_example"]],
                     use_container_width=True)
    st.subheader("Audit Log")
    st.dataframe(pd.DataFrame(db.audit()), use_container_width=True)
