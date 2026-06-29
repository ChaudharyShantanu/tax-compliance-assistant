# app.py — ITR Verification & Tax Compliance Assistant (v3)
# Run with: streamlit run app.py
#
# SCREEN FLOW:
#   Screen 0 — Case Dashboard   : AO selects or creates a case
#   Screen 1 — Case Workspace   : 4-tab investigation flow for the selected case
#     Tab 1 — Upload Documents
#     Tab 2 — Review & Validate Issues
#     Tab 3 — AI Investigation Report
#     Tab 4 — Draft Notice & Sign-off

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from io import BytesIO
import pandas as pd
from datetime import date

from parsers.itr_parser       import parse_itr
from parsers.form16_parser    import parse_form16
from parsers.ais_parser       import parse_ais
from engine.reconciler        import reconcile
from ai.sarvam_client         import generate_summary, refine_notice
from notice.notice_generator  import build_notice_docx, build_notice_pdf, PDF_AVAILABLE
from utils.din_generator      import generate_din, generate_dsc_block
from utils.case_manager       import (
    load_cases, add_case, update_case_status, delete_case,
    filter_cases, sort_cases,
    STATUS_META, STATUS_OPTIONS, AY_OPTIONS, ZONE_OPTIONS,
)


# ════════════════════════════════════════════════════════════════════════════
# Page config
# ════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="ITR Compliance Assistant",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main-title {
    font-size:1.6rem; font-weight:700; color:#1a1a2e;
    border-bottom:3px solid #c0392b; padding-bottom:8px; margin-bottom:2px;
}
.subtitle { font-size:0.85rem; color:#7f8c8d; margin-bottom:1rem; }

/* Case cards */
.case-card {
    border-radius:10px; padding:16px 18px; margin-bottom:12px;
    border:1px solid #e0e0e0; background:#fff;
    box-shadow:0 1px 4px rgba(0,0,0,0.07);
    transition: box-shadow 0.2s;
}
.case-card:hover { box-shadow:0 3px 10px rgba(0,0,0,0.12); }
.case-card-header { font-size:1rem; font-weight:700; color:#1a1a2e; margin-bottom:4px; }
.case-meta { font-size:0.8rem; color:#7f8c8d; margin-bottom:6px; }
.case-flag {
    font-size:0.8rem; background:#fff8e1; border-left:3px solid #f39c12;
    padding:5px 10px; border-radius:4px; margin-top:6px; color:#555;
}

/* Status badges */
.status-badge {
    display:inline-block; border-radius:20px; padding:3px 12px;
    font-size:0.75rem; font-weight:700; margin-bottom:6px;
}

/* Risk box */
.risk-box {
    border-radius:10px; padding:14px 20px;
    text-align:center; font-size:1rem; font-weight:700; margin-bottom:12px;
}
/* Discrepancy cards */
.disc-card {
    border-radius:8px; padding:14px 16px; margin-bottom:10px;
    border-left:5px solid #ccc;
}
.disc-HIGH   { background:#fff0f0; border-color:#e74c3c; }
.disc-MEDIUM { background:#fff8e1; border-color:#f39c12; }
.disc-INFO   { background:#eaf4fb; border-color:#2980b9; }
.disc-OK     { background:#eafaf1; border-color:#27ae60; }

/* Inline badges */
.badge {
    display:inline-block; border-radius:4px; padding:2px 9px;
    font-size:0.72rem; font-weight:700; margin-right:5px;
}
.badge-HIGH     { background:#e74c3c; color:#fff; }
.badge-MEDIUM   { background:#f39c12; color:#fff; }
.badge-INFO     { background:#2980b9; color:#fff; }
.badge-ACCEPTED { background:#27ae60; color:#fff; }
.badge-REJECTED { background:#95a5a6; color:#fff; }
.section-tag {
    background:#eaf0fb; color:#2c3e8c; border-radius:4px;
    padding:2px 8px; font-size:0.72rem;
}
/* DIN box */
.din-box {
    background:#f0f8ff; border:2px solid #2980b9; border-radius:8px;
    padding:14px 20px; font-family:monospace; font-size:0.88rem;
    margin-bottom:12px; line-height:1.7;
}
/* Stat tiles */
.stat-tile {
    background:#f8f9fa; border-radius:8px; padding:14px 18px;
    text-align:center; border-top:3px solid #ccc;
}
.stat-num  { font-size:1.8rem; font-weight:800; }
.stat-lbl  { font-size:0.78rem; color:#7f8c8d; margin-top:2px; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Session state
# ════════════════════════════════════════════════════════════════════════════
_defaults = {
    # Dashboard state
    "active_case":       None,   # the selected case dict
    "dashboard_view":    "list", # "list" | "add"
    # Investigation state (reset when a new case is opened)
    "itr_data":          None,
    "f16_data":          None,
    "ais_data":          None,
    "reconciliation":    None,
    "officer_name":      "The Assessing Officer",
    "ward_name":         "Ward 1(1), New Delhi",
    "disc_decisions":    {},
    "validated":         False,
    "ai_summary":        "",
    "ai_notice":         "",
    "ai_error":          None,
    "ai_called":         False,
    "notice_text":       "",
    "refinement_history":[],
    "din":               "",
    "dsc":               None,
    "signed_off":        False,
    "notice_editor_ver": 0,     # incremented on refinement to force widget reset
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ════════════════════════════════════════════════════════════════════════════
# Global header
# ════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="main-title">⚖️ ITR Verification & Tax Compliance Assistant</div>',
            unsafe_allow_html=True)
st.markdown('<div class="subtitle">Income Tax Department &nbsp;·&nbsp; Confidential — Official Use Only</div>',
            unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Helper: reset investigation state when opening a new case
# ════════════════════════════════════════════════════════════════════════════
def _reset_investigation():
    investigation_keys = [
        "itr_data", "f16_data", "ais_data", "reconciliation",
        "disc_decisions", "validated", "ai_summary", "ai_notice",
        "ai_error", "ai_called", "notice_text", "refinement_history",
        "din", "dsc", "signed_off",
    ]
    for k in investigation_keys:
        st.session_state[k] = _defaults[k]


# ════════════════════════════════════════════════════════════════════════════
# SCREEN 0 — CASE DASHBOARD
# Shown when no case is selected
# ════════════════════════════════════════════════════════════════════════════
if st.session_state.active_case is None:

    # ── Breadcrumb ────────────────────────────────────────────────────────
    st.caption("📋 Case Dashboard")
    st.divider()

    cases = load_cases()

    # ── Summary stat tiles ────────────────────────────────────────────────
    total     = len(cases)
    pending   = sum(1 for c in cases if c["status"] == "PENDING")
    inprog    = sum(1 for c in cases if c["status"] == "IN_PROGRESS")
    issued    = sum(1 for c in cases if c["status"] == "NOTICE_ISSUED")
    closed    = sum(1 for c in cases if c["status"] == "CLOSED")

    t1, t2, t3, t4, t5 = st.columns(5)
    tiles = [
        (t1, total,   "Total Cases",     "#7f8c8d"),
        (t2, pending, "Pending",         "#f39c12"),
        (t3, inprog,  "In Progress",     "#2980b9"),
        (t4, issued,  "Notice Issued",   "#e67e22"),
        (t5, closed,  "Closed",          "#27ae60"),
    ]
    for col, num, lbl, color in tiles:
        with col:
            st.markdown(
                f'<div class="stat-tile" style="border-top-color:{color};">'
                f'<div class="stat-num" style="color:{color};">{num}</div>'
                f'<div class="stat-lbl">{lbl}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Toolbar: filters + Add Case button ────────────────────────────────
    col_s, col_z, col_ay, col_st, col_add = st.columns([3, 2, 2, 2, 2])

    with col_s:
        search = st.text_input("🔍 Search name / PAN / issue",
                               placeholder="e.g. Rahul or ABCPE1234F",
                               label_visibility="collapsed")
    with col_z:
        zone_f = st.selectbox("Zone", ["All Zones"] + ZONE_OPTIONS,
                              label_visibility="collapsed")
    with col_ay:
        ay_f   = st.selectbox("AY", ["All AYs"] + AY_OPTIONS,
                              label_visibility="collapsed")
    with col_st:
        status_f = st.multiselect("Status", STATUS_OPTIONS,
                                  default=["PENDING", "IN_PROGRESS"],
                                  label_visibility="collapsed")
    with col_add:
        if st.button("➕ Add New Case", use_container_width=True, type="primary"):
            st.session_state.dashboard_view = "add"
            st.rerun()

    # ── Add New Case form ─────────────────────────────────────────────────
    if st.session_state.dashboard_view == "add":
        with st.expander("📝 New Case Details", expanded=True):
            f1, f2, f3 = st.columns(3)
            with f1:
                nc_name = st.text_input("Taxpayer Name *", placeholder="e.g. Ramesh Kumar")
                nc_pan  = st.text_input("PAN *", placeholder="e.g. ABCDE1234F",
                                        max_chars=10)
            with f2:
                nc_ay   = st.selectbox("Assessment Year *", AY_OPTIONS)
                nc_zone = st.selectbox("Zone *", ZONE_OPTIONS)
            with f3:
                nc_ward   = st.text_input("Ward / Circle *", placeholder="e.g. Ward 4(2), Mumbai")
                nc_source = st.text_input("Flag Source", placeholder="e.g. AIS / SFT")

            nc_reason = st.text_area("Reason for Flagging *",
                                     placeholder="e.g. Cash deposit Rs 15L > declared income",
                                     height=70)
            nc_notes  = st.text_area("Initial Notes", height=50)

            ca1, ca2 = st.columns(2)
            with ca1:
                if st.button("✅ Save Case", type="primary", use_container_width=True):
                    # Validate required fields
                    errors = []
                    if not nc_name.strip():   errors.append("Taxpayer Name")
                    if not nc_pan.strip():    errors.append("PAN")
                    if len(nc_pan.strip()) != 10: errors.append("PAN must be 10 characters")
                    if not nc_reason.strip(): errors.append("Flag Reason")
                    if not nc_ward.strip():   errors.append("Ward / Circle")

                    if errors:
                        st.error(f"Missing / invalid: {', '.join(errors)}")
                    else:
                        new_case = add_case(
                            taxpayer_name = nc_name,
                            pan           = nc_pan,
                            ay            = nc_ay,
                            zone          = nc_zone,
                            ward          = nc_ward,
                            flag_reason   = nc_reason,
                            flag_source   = nc_source,
                            notes         = nc_notes,
                        )
                        st.session_state.dashboard_view = "list"
                        st.success(f"Case {new_case['id']} created successfully.")
                        st.rerun()
            with ca2:
                if st.button("✖ Cancel", use_container_width=True):
                    st.session_state.dashboard_view = "list"
                    st.rerun()

    st.divider()

    # ── Case list ─────────────────────────────────────────────────────────
    filtered = filter_cases(cases, status_filter=status_f or None,
                            zone_filter=zone_f, ay_filter=ay_f,
                            search_text=search)
    filtered = sort_cases(filtered, sort_by="last_updated")

    if not filtered:
        st.info("No cases match the current filters.")
    else:
        st.markdown(f"**{len(filtered)} case(s)** — sorted by last updated")
        st.markdown("")

        for case in filtered:
            meta    = STATUS_META.get(case["status"],
                                      {"label": case["status"], "color": "#999"})
            bg_col  = "#fff"

            with st.container():
                # Card layout: info cols + action col
                ci1, ci2, ci3, ci4 = st.columns([4, 2, 2, 2])

                with ci1:
                    st.markdown(
                        f'<div class="case-card-header">{case["taxpayer_name"]}</div>'
                        f'<div class="case-meta">'
                        f'PAN: <b>{case["pan"]}</b> &nbsp;|&nbsp; '
                        f'AY: <b>{case["ay"]}</b> &nbsp;|&nbsp; '
                        f'ID: <b>{case["id"]}</b>'
                        f'</div>'
                        f'<div class="case-meta">'
                        f'Zone: {case.get("zone","")} &nbsp;|&nbsp; {case.get("ward","")}'
                        f'</div>'
                        f'<div class="case-flag">⚑ {case["flag_reason"][:120]}'
                        f'{"..." if len(case["flag_reason"]) > 120 else ""}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                with ci2:
                    st.markdown(
                        f'<div style="margin-top:8px">'
                        f'<span class="status-badge" '
                        f'style="background:{meta["color"]}22;color:{meta["color"]};'
                        f'border:1px solid {meta["color"]};">'
                        f'{meta["label"]}</span><br>'
                        f'<span style="font-size:0.75rem;color:#999;">'
                        f'Created: {case["created_on"]}<br>'
                        f'Updated: {case["last_updated"]}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                with ci3:
                    # Inline status update
                    new_status = st.selectbox(
                        "Status",
                        STATUS_OPTIONS,
                        index=STATUS_OPTIONS.index(case["status"]),
                        key=f"st_{case['id']}",
                        label_visibility="collapsed",
                    )
                    if new_status != case["status"]:
                        update_case_status(case["id"], new_status)
                        st.rerun()

                with ci4:
                    st.markdown('<div style="margin-top:4px"></div>', unsafe_allow_html=True)
                    if st.button("📂 Open Case", key=f"open_{case['id']}",
                                 type="primary", use_container_width=True):
                        _reset_investigation()
                        st.session_state.active_case  = case
                        st.session_state.officer_name = case.get("ward", "The Assessing Officer")
                        st.session_state.ward_name    = case.get("ward", "Ward 1(1), New Delhi")
                        st.rerun()

                    if st.button("🗑 Delete", key=f"del_{case['id']}",
                                 type="secondary", use_container_width=True):
                        delete_case(case["id"])
                        st.rerun()

            st.divider()

    st.stop()   # Don't render anything below when on dashboard


# ════════════════════════════════════════════════════════════════════════════
# SCREEN 1 — CASE WORKSPACE  (active case selected)
# ════════════════════════════════════════════════════════════════════════════
case = st.session_state.active_case

# ── Case header bar ───────────────────────────────────────────────────────
hc1, hc2 = st.columns([7, 2])
with hc1:
    meta = STATUS_META.get(case["status"], {"label": case["status"], "color": "#999"})
    st.markdown(
        f'<span style="font-size:0.95rem;font-weight:700;">{case["taxpayer_name"]}</span>'
        f'&nbsp; <span style="color:#888;font-size:0.85rem;">PAN: {case["pan"]} &nbsp;|&nbsp; '
        f'AY: {case["ay"]} &nbsp;|&nbsp; {case["id"]}</span>'
        f'&nbsp;&nbsp;<span class="status-badge" '
        f'style="background:{meta["color"]}22;color:{meta["color"]};'
        f'border:1px solid {meta["color"]};border-radius:20px;padding:2px 10px;'
        f'font-size:0.75rem;font-weight:700;">{meta["label"]}</span>',
        unsafe_allow_html=True,
    )
with hc2:
    if st.button("← Back to Dashboard", use_container_width=True):
        # Auto-update status to IN_PROGRESS when leaving a PENDING case
        if case["status"] == "PENDING":
            update_case_status(case["id"], "IN_PROGRESS")
        st.session_state.active_case = None
        st.rerun()

# Progress breadcrumb
recon = st.session_state.reconciliation
s1 = "✅" if recon                          else "⬜"
s2 = "✅" if st.session_state.validated     else "⬜"
s3 = "✅" if st.session_state.ai_called     else "⬜"
s4 = "✅" if st.session_state.signed_off    else "⬜"
st.caption(
    f"{s1} Upload & Parse &nbsp;›&nbsp; "
    f"{s2} Review Issues &nbsp;›&nbsp; "
    f"{s3} AI Report &nbsp;›&nbsp; "
    f"{s4} Sign-off"
)
st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📁 1 · Upload Documents",
    "🔍 2 · Review & Validate Issues",
    "🤖 3 · AI Investigation Report",
    "📝 4 · Draft Notice & Sign-off",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — Upload Documents
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Upload Taxpayer Documents")
    st.caption(
        "All parsing runs locally. Only structured discrepancy JSON "
        "(no raw documents) is sent to the AI API."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**ITR Extract** (Excel .xlsx)")
        itr_file = st.file_uploader("ITR", type=["xlsx"], key="up_itr",
                                    label_visibility="collapsed")
        if itr_file: st.success(f"✔ {itr_file.name}")
    with c2:
        st.markdown("**Form 16** (Excel .xlsx)")
        f16_file = st.file_uploader("F16", type=["xlsx"], key="up_f16",
                                    label_visibility="collapsed")
        if f16_file: st.success(f"✔ {f16_file.name}")
    with c3:
        st.markdown("**AIS / TIS** (Excel .xlsx)")
        ais_file = st.file_uploader("AIS", type=["xlsx"], key="up_ais",
                                    label_visibility="collapsed")
        if ais_file: st.success(f"✔ {ais_file.name}")

    st.divider()
    st.subheader("Officer Details")
    oc1, oc2 = st.columns(2)
    with oc1:
        officer_input = st.text_input("Assessing Officer Name",
                                      value=st.session_state.officer_name,
                                      placeholder="e.g. Sh. Rajesh Kumar, ITO")
    with oc2:
        ward_input = st.text_input("Ward / Circle",
                                   value=st.session_state.ward_name,
                                   placeholder="e.g. Ward 4(2), Mumbai")
    st.divider()

    all_uploaded = itr_file and f16_file and ais_file
    if not all_uploaded:
        st.info("Upload all three documents to proceed.")

    if st.button("🔍 Parse & Run Reconciliation", type="primary",
                 disabled=not all_uploaded, use_container_width=True):

        # Reset downstream state
        for k in ["disc_decisions", "validated", "ai_summary", "ai_notice",
                  "ai_error", "ai_called", "notice_text", "refinement_history",
                  "din", "dsc", "signed_off"]:
            st.session_state[k] = _defaults[k]

        with st.spinner("Parsing ITR..."):
            try:
                st.session_state.itr_data = parse_itr(BytesIO(itr_file.read()))
            except Exception as e:
                st.error(f"ITR parse error: {e}"); st.stop()

        with st.spinner("Parsing Form 16..."):
            try:
                st.session_state.f16_data = parse_form16(BytesIO(f16_file.read()))
            except Exception as e:
                st.error(f"Form 16 parse error: {e}"); st.stop()

        with st.spinner("Parsing AIS..."):
            try:
                st.session_state.ais_data = parse_ais(BytesIO(ais_file.read()))
            except Exception as e:
                st.error(f"AIS parse error: {e}"); st.stop()

        with st.spinner("Running reconciliation checks..."):
            recon = reconcile(
                st.session_state.itr_data,
                st.session_state.f16_data,
                st.session_state.ais_data,
            )
            st.session_state.reconciliation = recon
            st.session_state.officer_name   = officer_input
            st.session_state.ward_name      = ward_input

            # Initialise all decisions as ACCEPTED
            st.session_state.disc_decisions = {
                i: {
                    "status":             "ACCEPTED",
                    "edited_title":       d["title"],
                    "edited_explanation": d["explanation"],
                }
                for i, d in enumerate(recon["discrepancies"])
                if d["severity"] != "OK"
            }

        # Auto-update case status to IN_PROGRESS
        update_case_status(case["id"], "IN_PROGRESS")
        st.session_state.active_case["status"] = "IN_PROGRESS"

        st.success(
            f"✅ Parsed successfully. "
            f"Found {len(recon['discrepancies'])} discrepancies — "
            f"Risk Score: {recon['risk_score']}/100. "
            f"Go to Tab 2 to review each issue."
        )


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — Review & Validate Issues
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    if not st.session_state.reconciliation:
        st.info("Complete Tab 1 first.")
        st.stop()

    recon     = st.session_state.reconciliation
    decisions = st.session_state.disc_decisions

    # Risk score banner
    score = recon["risk_score"]
    if score >= 70:
        bg, br, tc = "#fdecea", "#e74c3c", "#922b21"
    elif score >= 40:
        bg, br, tc = "#fef9e7", "#f39c12", "#784212"
    else:
        bg, br, tc = "#eafaf1", "#27ae60", "#1e8449"

    st.markdown(
        f'<div class="risk-box" style="background:{bg};border:2px solid {br};color:{tc};">'
        f'Risk Score: <b>{score}/100</b> &nbsp;|&nbsp; {recon["risk_band"]}'
        f'</div>',
        unsafe_allow_html=True,
    )

    accepted_count = sum(1 for v in decisions.values() if v["status"] == "ACCEPTED")
    rejected_count = sum(1 for v in decisions.values() if v["status"] == "REJECTED")

    st.subheader("Review Each Discrepancy")
    st.caption(
        "Accept issues to include in the notice. "
        "Reject false positives. Edit title or explanation if needed."
    )
    st.markdown(
        f"**{accepted_count} accepted** &nbsp;|&nbsp; "
        f"**{rejected_count} rejected** &nbsp;|&nbsp; "
        f"**{len(decisions)} total**"
    )
    st.divider()

    for i, disc in enumerate(recon["discrepancies"]):
        if disc["severity"] == "OK":
            continue

        dec    = decisions.get(i, {"status": "ACCEPTED",
                                    "edited_title": disc["title"],
                                    "edited_explanation": disc["explanation"]})
        sev    = disc["severity"]
        is_acc = dec["status"] == "ACCEPTED"

        status_badge = (
            '<span class="badge badge-ACCEPTED">✔ ACCEPTED</span>'
            if is_acc else
            '<span class="badge badge-REJECTED">✖ REJECTED</span>'
        )
        st.markdown(
            f'<div class="disc-card disc-{sev}">'
            f'<span class="badge badge-{sev}">{sev}</span>'
            f'<span class="section-tag">{disc["section"]}</span>'
            f'&nbsp;&nbsp;{status_badge}'
            f'<br><b style="font-size:0.95rem">{dec["edited_title"]}</b>'
            f'<div style="font-size:0.82rem;color:#555;margin-top:6px;">'
            f'📋 {disc["source_a_label"]}: <b>₹{disc["source_a_val"]:,.0f}</b>'
            f'&nbsp;&nbsp;📋 {disc["source_b_label"]}: <b>₹{disc["source_b_val"]:,.0f}</b>'
            f'&nbsp;&nbsp;⚡ Delta: <b>₹{abs(disc["delta"]):,.0f}</b>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        with st.expander(f"▼ Actions & Edit — Issue #{i+1}"):
            col_a, col_r = st.columns(2)
            with col_a:
                if st.button("✔ Accept", key=f"acc_{i}",
                             type="primary" if not is_acc else "secondary",
                             use_container_width=True):
                    decisions[i]["status"] = "ACCEPTED"
                    st.session_state.disc_decisions = decisions
                    st.rerun()
            with col_r:
                if st.button("✖ Reject (False Positive)", key=f"rej_{i}",
                             type="secondary", use_container_width=True):
                    decisions[i]["status"] = "REJECTED"
                    st.session_state.disc_decisions = decisions
                    st.rerun()

            st.markdown("**Edit title** *(optional)*")
            new_title = st.text_input("Title", value=dec["edited_title"],
                                      key=f"ttl_{i}", label_visibility="collapsed")
            st.markdown("**Edit explanation / evidence request** *(optional)*")
            new_exp   = st.text_area("Explanation", value=dec["edited_explanation"],
                                     key=f"exp_{i}", height=90,
                                     label_visibility="collapsed")
            if st.button(f"💾 Save edits", key=f"save_{i}"):
                decisions[i]["edited_title"]       = new_title
                decisions[i]["edited_explanation"] = new_exp
                st.session_state.disc_decisions    = decisions
                st.success("Saved.")

    st.divider()

    accepted_preview = [
        recon["discrepancies"][i] | {
            "title":       decisions[i]["edited_title"],
            "explanation": decisions[i]["edited_explanation"],
        }
        for i in decisions if decisions[i]["status"] == "ACCEPTED"
    ]

    if not accepted_preview:
        st.warning("No discrepancies accepted. Accept at least one to continue.")
    else:
        st.info(f"**{len(accepted_preview)} issue(s) accepted.** Click below when ready.")
        if st.button("➡ Proceed to AI Investigation Report",
                     type="primary", use_container_width=True):
            st.session_state.validated   = True
            st.session_state.ai_called   = False
            st.session_state.notice_text = ""
            st.success("Validated. Go to Tab 3.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — AI Investigation Report  (API Call 1 — once only)
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    if not st.session_state.validated:
        st.info("Complete Tab 2 first.")
        st.stop()

    recon     = st.session_state.reconciliation
    decisions = st.session_state.disc_decisions

    accepted_discs = [
        recon["discrepancies"][i] | {
            "title":       decisions[i]["edited_title"],
            "explanation": decisions[i]["edited_explanation"],
        }
        for i in decisions if decisions[i]["status"] == "ACCEPTED"
    ]

    # API Call 1 — cached in session state, not repeated
    if not st.session_state.ai_called:
        with st.spinner("Generating AI report via Sarvam AI… (one call only)"):
            result = generate_summary(
                accepted_discs = accepted_discs,
                taxpayer_name  = recon["taxpayer_name"],
                pan            = recon["pan"],
                ay             = recon["ay"],
            )
        st.session_state.ai_summary  = result.get("executive_summary", "")
        st.session_state.ai_notice   = result.get("draft_notice", "")
        st.session_state.notice_text = result.get("draft_notice", "")
        st.session_state.ai_error    = result.get("error")
        st.session_state.ai_called   = True

    if st.session_state.ai_error:
        st.warning(f"⚠️ AI API: {st.session_state.ai_error}")
        st.caption("The discrepancy table below is fully accurate regardless.")

    # Executive summary
    st.subheader("Executive Summary")
    if st.session_state.ai_summary:
        st.info(st.session_state.ai_summary)
    else:
        titles = [d["title"] for d in accepted_discs if d["severity"] == "HIGH"]
        st.info(
            f"Analysis of {recon['taxpayer_name']} (PAN: {recon['pan']}) for "
            f"AY {recon['ay']} — Risk score: {recon['risk_score']}/100. "
            f"{len(accepted_discs)} issue(s) accepted: "
            + ("; ".join(titles[:3]) or "See table below.")
        )

    st.divider()

    # Accepted issues table
    st.subheader(f"Accepted Issues — {len(accepted_discs)}")
    rows = []
    for j, d in enumerate(accepted_discs, 1):
        rows.append({
            "#":             j,
            "Issue":         d["title"],
            "Source A (₹)":  f"{d['source_a_val']:,.0f}",
            "Source B (₹)":  f"{d['source_b_val']:,.0f}",
            "Delta (₹)":     f"{abs(d['delta']):,.0f}",
            "Section":       d["section"],
            "Severity":      d["severity"],
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Rejected issues
    rejected = [recon["discrepancies"][i] for i in decisions
                if decisions[i]["status"] == "REJECTED"]
    if rejected:
        st.divider()
        st.subheader(f"Rejected (False Positives) — {len(rejected)}")
        for d in rejected:
            st.markdown(
                f'<div class="disc-card disc-OK">'
                f'<span class="badge badge-REJECTED">REJECTED</span> '
                f'{d["title"]} &nbsp;<span class="section-tag">{d["section"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.divider()
    st.info("Go to **Tab 4** to review the notice, request AI refinements, and download the signed PDF.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — Draft Notice & Sign-off
# ════════════════════════════════════════════════════════════════════════════
with tab4:
    if not st.session_state.ai_called:
        st.info("Complete Tabs 1–3 first.")
        st.stop()

    recon = st.session_state.reconciliation

    # Notice metadata
    st.subheader("Notice Details")
    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        officer = st.text_input("Assessing Officer",
                                value=st.session_state.officer_name)
    with nc2:
        ward = st.text_input("Ward / Circle",
                             value=st.session_state.ward_name)
    with nc3:
        ref_no = st.text_input(
            "Reference Number",
            value=f"ITO/{recon['ay'].replace('-','_')}/{recon['pan']}/142(1)"
        )
    st.divider()

    # Build fallback notice if AI returned nothing
    if not st.session_state.notice_text:
        decisions     = st.session_state.disc_decisions
        accepted_discs = [
            recon["discrepancies"][i] | {
                "title":       decisions[i]["edited_title"],
                "explanation": decisions[i]["edited_explanation"],
            }
            for i in decisions if decisions[i]["status"] == "ACCEPTED"
        ]
        pts = []
        for j, d in enumerate(accepted_discs, 1):
            pts.append(
                f"{j}. {d['title']} ({d['section']})\n"
                f"   {d['source_a_label']}: ₹{d['source_a_val']:,.0f} | "
                f"{d['source_b_label']}: ₹{d['source_b_val']:,.0f} | "
                f"Delta: ₹{abs(d['delta']):,.0f}\n"
                f"   {d['explanation']}\n"
                f"   Please furnish supporting documents within 15 days."
            )
        st.session_state.notice_text = (
            f"In connection with the assessment of {recon['taxpayer_name']}, "
            f"PAN {recon['pan']}, AY {recon['ay']}, you are called upon to explain "
            f"the following discrepancies under Section 142(1) of the Income Tax "
            f"Act, 1961:\n\n" + "\n\n".join(pts)
            + "\n\nYou are required to comply within 15 days of receipt of this notice."
        )

    # Editable notice
    st.subheader("Draft Notice — Section 142(1)")
    st.caption("Review and edit directly. Use the AI refinement box below for assisted changes.")
    # The key includes notice_editor_ver — when it increments after a refinement,
    # Streamlit destroys the old widget and creates a fresh one with the new value.
    # This prevents the old widget value from overwriting the refined notice on rerun.
    editor_key = f"notice_editor_{st.session_state.notice_editor_ver}"
    edited = st.text_area(
        "Notice body",
        value=st.session_state.notice_text,
        height=420,
        key=editor_key,
        label_visibility="collapsed",
    )
    # Only sync manual edits back to session state (not after AI refinement rerun)
    if edited != st.session_state.notice_text:
        st.session_state.notice_text = edited

    # AI Refinement loop
    st.divider()
    st.subheader("🔄 Request AI Refinement")
    st.caption("One small API call per refinement request — only sent when you click Refine.")

    feedback_input = st.text_area(
        "Your feedback",
        placeholder='e.g. "Remove issue 2. Add a request for ITR acknowledgement for issue 3."',
        height=80,
        key="ao_feedback",
    )
    if st.button("✨ Refine Notice with AI", type="primary", use_container_width=True):
        if not feedback_input.strip():
            st.warning("Please type your feedback first.")
        else:
            with st.spinner("Refining… (one compact API call)"):
                result = refine_notice(
                    current_notice = st.session_state.notice_text,
                    ao_feedback    = feedback_input,
                    taxpayer_name  = recon["taxpayer_name"],
                    pan            = recon["pan"],
                    ay             = recon["ay"],
                )
            if result.get("error"):
                st.error(f"Refinement error: {result['error']}")
            else:
                st.session_state.refinement_history.append({
                    "feedback": feedback_input,
                    "notice":   st.session_state.notice_text,
                })
                st.session_state.notice_text    = result["draft_notice"]
                st.session_state.notice_editor_ver += 1   # forces widget to redraw with new text
                st.success("Notice refined. Review the updated text above.")
                st.rerun()

    if st.session_state.refinement_history:
        with st.expander(
            f"📜 Revision history ({len(st.session_state.refinement_history)} revision(s))"
        ):
            for rev_i, rev in enumerate(reversed(st.session_state.refinement_history), 1):
                st.markdown(f"**Rev {len(st.session_state.refinement_history)-rev_i+1}** — _{rev['feedback']}_")
                st.text_area(f"Draft #{rev_i}", value=rev["notice"],
                             height=100, disabled=True, key=f"hist_{rev_i}")

    st.divider()

    # DIN + DSC Sign-off
    st.subheader("🔏 Approve & Generate DIN / DSC")
    st.caption("Assigns a Document Identification Number and applies a simulated Digital Signature.")

    if not st.session_state.signed_off:
        if st.button("✅ Approve Notice & Generate DIN + DSC",
                     type="primary", use_container_width=True):
            din = generate_din(pan=recon["pan"], ay=recon["ay"])
            dsc = generate_dsc_block(officer_name=officer, ward=ward, pan=recon["pan"])
            st.session_state.din        = din
            st.session_state.dsc        = dsc
            st.session_state.signed_off = True
            # Update case status
            update_case_status(case["id"], "NOTICE_ISSUED",
                               notes=f"Notice approved. DIN: {din}")
            st.session_state.active_case["status"] = "NOTICE_ISSUED"
            st.rerun()
    else:
        din = st.session_state.din
        dsc = st.session_state.dsc
        st.markdown(
            f'<div class="din-box">'
            f'<b>DIN:</b> {din}<br>'
            f'<b>Signed by:</b> {dsc["signed_by"]} &nbsp;|&nbsp; '
            f'<b>Date & Time:</b> {dsc["signed_on"]}<br>'
            f'<b>Cert. Serial:</b> {dsc["cert_serial"]} &nbsp;|&nbsp; '
            f'<b>Valid Until:</b> {dsc["valid_until"]}<br>'
            f'<small style="color:#666;">{dsc["note"]}</small>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.success("✅ Approved. DIN assigned. Case status updated to Notice Issued.")

        if st.button("🔄 Revoke Sign-off (make further edits)", type="secondary"):
            st.session_state.signed_off = False
            st.session_state.din        = ""
            st.session_state.dsc        = None
            update_case_status(case["id"], "IN_PROGRESS")
            st.session_state.active_case["status"] = "IN_PROGRESS"
            st.rerun()

    st.divider()

    # Downloads
    st.subheader("⬇️ Download Final Notice")
    _din = st.session_state.din if st.session_state.signed_off else ""
    _dsc = st.session_state.dsc if st.session_state.signed_off else None

    if not st.session_state.signed_off:
        st.info("Approve the notice above to embed DIN and DSC in the downloaded files.")

    dl1, dl2 = st.columns(2)

    with dl1:
        try:
            docx_buf = build_notice_docx(
                notice_text       = st.session_state.notice_text,
                taxpayer_name     = recon["taxpayer_name"],
                pan               = recon["pan"],
                ay                = recon["ay"],
                assessing_officer = officer,
                ward              = ward,
                ref_no            = ref_no,
                din               = _din,
                dsc               = _dsc,
            )
            st.download_button(
                label     = "📄 Download DOCX",
                data      = docx_buf,
                file_name = f"Notice_142_1_{recon['pan']}_{recon['ay']}.docx",
                mime      = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"DOCX error: {e}")

    with dl2:
        if PDF_AVAILABLE:
            try:
                pdf_buf = build_notice_pdf(
                    notice_text       = st.session_state.notice_text,
                    taxpayer_name     = recon["taxpayer_name"],
                    pan               = recon["pan"],
                    ay                = recon["ay"],
                    assessing_officer = officer,
                    ward              = ward,
                    ref_no            = ref_no,
                    din               = _din,
                    dsc               = _dsc,
                )
                st.download_button(
                    label     = "📕 Download PDF",
                    data      = pdf_buf,
                    file_name = f"Notice_142_1_{recon['pan']}_{recon['ay']}.pdf",
                    mime      = "application/pdf",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"PDF error: {e}")
        else:
            st.warning("PDF export unavailable. Run: `pip install reportlab`")

    st.divider()

    # Case notes
    st.subheader("📌 Case Notes")
    new_notes = st.text_area(
        "Add observations (saved to case file)",
        value=case.get("notes", ""),
        placeholder="e.g. Taxpayer contacted. Cash deposit source appears undisclosed...",
        height=100,
        key="case_notes",
    )
    if st.button("💾 Save Notes", type="secondary"):
        update_case_status(case["id"], case["status"], notes=new_notes)
        st.session_state.active_case["notes"] = new_notes
        st.success("Notes saved.")
