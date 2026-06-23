"""
Streamlit UI — EU AI Act audit tool (internal consulting tool).

Run:
    streamlit run app.py

Workflow during a client session:
    1. Enter the client/company name.
    2. For each AI system the client uses, enter a name + plain-language description
       (Dutch / French / English / Spanish all work).
    3. The tool classifies it, asks follow-up questions if uncertain, and lists
       obligations + gaps.
    4. Export a branded PDF report.
"""
import streamlit as st

import config
from graph import audit_system
from report import generate_report



st.set_page_config(page_title="EU AI Act Audit — KRS Solutions", page_icon="⚖️", layout="wide")

if "systems" not in st.session_state:
    st.session_state.systems = []      # completed AuditState dicts
if "pending" not in st.session_state:
    st.session_state.pending = None    # a low-confidence result awaiting clarification

st.title("⚖️ EU AI Act — Compliance Audit")
st.caption(f"{config.COMPANY_NAME} · internal diagnostic tool · model: {config.LLM_MODEL}")

with st.expander("🎨 Colour legend", expanded=True):
    st.markdown(
        "**Risk tiers** &nbsp; "
        "🔴 Prohibited (stop now) &nbsp;·&nbsp; "
        "🟠 High-risk (Annex I / III — allowed with obligations) &nbsp;·&nbsp; "
        "🔵 Limited (transparency only) &nbsp;·&nbsp; "
        "🟢 Minimal (no obligations) &nbsp;·&nbsp; "
        "🟣 GPAI (foundation-model flag, added on top)"
    )
    st.markdown(
        "**Obligation status** &nbsp; "
        "⚠️ Likely gap &nbsp;·&nbsp; "
        "✅ Likely in place &nbsp;·&nbsp; "
        "❓ Confirm with client"
    )

client_name = st.text_input("Client / company name", placeholder="e.g. Acme NV")

st.divider()
st.subheader("Add an AI system")

with st.form("add_system", clear_on_submit=True):
    name = st.text_input("System name", placeholder="e.g. HireFast CV screener")
    desc = st.text_area(
        "Describe it in plain language (NL / FR / EN / ES)",
        placeholder="What does it do? Who is affected? What decisions does it influence?",
        height=120,
    )
    components = st.text_area(
        "Components / architecture (optional, one per line)",
        placeholder="- Web portal (recruiter uploads CVs)\n- AI Agent (GPT-4o)\n"
                    "- Ranking model (fine-tuned on past hires)\n- Email integration (auto rejection)",
        height=120,
    )
    submitted = st.form_submit_button("Classify")

if submitted and not (name and desc):
    st.warning("Please fill in both the system name and a description before classifying.")
elif submitted:
    try:
        with st.spinner("Reasoning over the EU AI Act..."):
            result = audit_system(name, desc, components=components)
        if result.get("needs_review") and result.get("follow_up_questions"):
            st.session_state.pending = result
        else:
            st.session_state.systems.append(result)
            st.success(f"Classified **{name}** as {result.get('tier')}"
                       f"{' + GPAI' if result.get('is_gpai') else ''}.")
    except Exception as e:  # noqa: BLE001
        st.error(f"Classification failed: {e}")
        st.info("If this mentions 'credit balance', top up API credits at "
                "console.anthropic.com → Plans & Billing.")

# --- Clarification loop -------------------------------------------------------
if st.session_state.pending:
    p = st.session_state.pending
    st.warning(f"Classification of **{p['system_name']}** is uncertain. "
               "Answer these to refine it:")
    with st.form("clarify"):
        answers = {}
        for q in p.get("follow_up_questions", []):
            answers[q] = st.text_input(q)
        col1, col2 = st.columns(2)
        refine = col1.form_submit_button("Re-classify with answers")
        accept = col2.form_submit_button("Accept as 'Needs legal review'")
    if refine:
        with st.spinner("Re-classifying..."):
            result = audit_system(p["system_name"], p["description"],
                                  components=p.get("components", ""), clarifications=answers)
        st.session_state.systems.append(result)
        st.session_state.pending = None
        st.rerun()
    if accept:
        st.session_state.systems.append(p)
        st.session_state.pending = None
        st.rerun()

# --- Results ------------------------------------------------------------------
st.divider()
st.subheader(f"Audited systems ({len(st.session_state.systems)})")

TIER_BADGE = {
    "PROHIBITED": "🔴", "ANNEX_I": "🟠", "ANNEX_III": "🟠",
    "LIMITED": "🔵", "MINIMAL": "🟢", "GPAI": "🟣",
}
STATUS_BADGE = {
    "likely_gap": "⚠️ likely gap",
    "likely_in_place": "✅ likely in place",
    "needs_confirmation": "❓ confirm",
}

for i, s in enumerate(st.session_state.systems):
    badge = TIER_BADGE.get(s.get("tier", ""), "⚪")
    gpai = " + 🟣 GPAI" if s.get("is_gpai") else ""
    with st.expander(f"{badge} {s.get('system_name')} — {s.get('tier')}{gpai} "
                     f"({s.get('confidence', '?')} confidence)"):
        if s.get("annex_category"):
            st.markdown(f"**Category:** {s['annex_category']}")
        st.markdown(f"**Rationale:** {s.get('rationale', '')}")
        if s.get("is_gpai"):
            st.markdown(f"**🟣 Also a GPAI provider:** {s.get('gpai_rationale', '')}")
        if s.get("triggering_articles"):
            st.markdown("**Triggering provisions:** " + ", ".join(s["triggering_articles"]))
        if s.get("obligations"):
            st.markdown("**Obligations & gaps:**")
            st.table([
                {"Obligation": o.get("obligation"),
                 "Deadline": o.get("deadline"),
                 "Gap check": o.get("gap_question"),
                 "Assessment": o.get("reasoning"),
                 "Status": STATUS_BADGE.get(o.get("status"), "❓ confirm")}
                for o in s["obligations"]
            ])
        if st.button("Remove", key=f"rm_{i}"):
            st.session_state.systems.pop(i)
            st.rerun()

# --- Export -------------------------------------------------------------------
st.divider()
if st.session_state.systems and client_name:
    if st.button("📄 Generate PDF report", type="primary"):
        path = generate_report(client_name, st.session_state.systems)
        st.success(f"Report saved to {path}")
        with open(path, "rb") as f:
            st.download_button("⬇️ Download report", f, file_name=path.name,
                               mime="application/pdf")
elif not client_name:
    st.info("Enter a client name to enable PDF export.")
