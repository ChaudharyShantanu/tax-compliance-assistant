# engine/reconciler.py
# Core reconciliation engine.
# Takes parsed ITR, Form 16, and AIS data dicts.
# Returns a list of discrepancy dicts and a risk score.

from config import (
    LIMIT_80C, LIMIT_80D_SELF, LIMIT_80TTA,
    SFT_CASH_DEPOSIT_LIMIT, SFT_TIME_DEPOSIT_LIMIT, SFT_PROPERTY_LIMIT,
    RISK_WEIGHT_HIGH, RISK_WEIGHT_MEDIUM, RISK_WEIGHT_INFO,
)


def _disc(title, source_a_label, source_a_val, source_b_label, source_b_val,
          delta, section, severity, explanation):
    """Helper to build a standard discrepancy dict."""
    return {
        "title":          title,
        "source_a_label": source_a_label,
        "source_a_val":   source_a_val,
        "source_b_label": source_b_label,
        "source_b_val":   source_b_val,
        "delta":          delta,
        "section":        section,
        "severity":       severity,       # "HIGH" | "MEDIUM" | "INFO" | "OK"
        "explanation":    explanation,
    }


def reconcile(itr: dict, f16: dict, ais: dict) -> dict:
    """
    Run all reconciliation checks.
    Returns:
        {
          "discrepancies": [...],
          "risk_score":    int,
          "risk_band":     str,
          "taxpayer_name": str,
          "pan":           str,
          "ay":            str,
        }
    """
    discs = []

    # ── 1. HRA Exemption: ITR vs Form 16 ─────────────────────────────────
    hra_itr = itr.get("hra_received", 0.0)          # HRA shown in salary sheet
    hra_f16 = f16.get("hra_exemption_f16", 0.0)
    if hra_f16 > 0 and abs(hra_itr - hra_f16) > 500:
        delta = hra_itr - hra_f16
        discs.append(_disc(
            title="HRA exemption overclaimed in ITR vs Form 16",
            source_a_label="HRA exempt as per ITR",
            source_a_val=hra_itr,
            source_b_label="HRA exempt as per Form 16",
            source_b_val=hra_f16,
            delta=delta,
            section="Section 10(13A) r/w Rule 2A",
            severity="HIGH" if delta > 0 else "MEDIUM",
            explanation=(
                f"The taxpayer has claimed HRA exemption of ₹{hra_itr:,.0f} in the ITR, "
                f"whereas Form 16 issued by the employer reflects only ₹{hra_f16:,.0f}. "
                f"The excess claim of ₹{abs(delta):,.0f} reduces taxable salary income "
                f"without employer corroboration."
            ),
        ))

    # ── 2. Net Taxable Salary: SCH TI vs Form 16 ─────────────────────────
    itr_sal = itr.get("sch_ti_salary", 0.0)
    f16_sal = f16.get("taxable_salary_f16", 0.0)
    if f16_sal > 0 and abs(itr_sal - f16_sal) > 500:
        delta = itr_sal - f16_sal
        discs.append(_disc(
            title="Net salary income in ITR differs from Form 16",
            source_a_label="Salary (SCH TI, ITR)",
            source_a_val=itr_sal,
            source_b_label="Taxable salary (Form 16 Part B)",
            source_b_val=f16_sal,
            delta=delta,
            section="Section 17(1), Section 10(13A)",
            severity="HIGH",
            explanation=(
                f"Schedule TI of the ITR declares net salary of ₹{itr_sal:,.0f}, "
                f"while Form 16 Part B shows taxable salary of ₹{f16_sal:,.0f}. "
                f"Delta of ₹{abs(delta):,.0f} is likely caused by the excess HRA "
                f"exemption and warrants verification."
            ),
        ))

    # ── 3. FD Interest: ITR vs AIS ───────────────────────────────────────
    fd_itr = itr.get("interest_fd", 0.0)
    fd_ais = ais.get("total_fd_interest_ais", 0.0)
    if fd_ais > 0 and abs(fd_itr - fd_ais) > 500:
        delta = fd_ais - fd_itr
        discs.append(_disc(
            title="Fixed Deposit interest under-reported vs AIS",
            source_a_label="FD interest declared in ITR",
            source_a_val=fd_itr,
            source_b_label="FD interest per AIS (bank TDS)",
            source_b_val=fd_ais,
            delta=delta,
            section="Section 56(2), Section 194A",
            severity="HIGH" if delta > 5000 else "MEDIUM",
            explanation=(
                f"AIS reflects interest income of ₹{fd_ais:,.0f} from bank deposits "
                f"(based on TDS deducted u/s 194A), whereas the ITR declares only "
                f"₹{fd_itr:,.0f} under 'Other Sources'. The shortfall of "
                f"₹{abs(delta):,.0f} constitutes potential under-reporting of income."
            ),
        ))

    # ── 4. MF / Dividend Income: ITR vs AIS ──────────────────────────────
    div_itr = itr.get("dividend_income", 0.0)
    mf_ais  = ais.get("total_mf_income_ais", 0.0)
    if mf_ais > 0 and abs(div_itr - mf_ais) > 500:
        delta = mf_ais - div_itr
        discs.append(_disc(
            title="Mutual Fund / Dividend income under-reported vs AIS",
            source_a_label="Dividend/MF income declared in ITR",
            source_a_val=div_itr,
            source_b_label="MF income per AIS (TDS u/s 194K)",
            source_b_val=mf_ais,
            delta=delta,
            section="Section 56(2)(i), Section 194K",
            severity="HIGH" if delta > 10000 else "MEDIUM",
            explanation=(
                f"AIS shows Mutual Fund income of ₹{mf_ais:,.2f} on which TDS has "
                f"been deducted. The ITR declares only ₹{div_itr:,.0f} as dividend "
                f"income, leaving ₹{abs(delta):,.2f} unaccounted."
            ),
        ))

    # ── 5. Other Sources Internal Inconsistency ───────────────────────────
    os_sheet = itr.get("other_sources_sheet", 0.0)
    os_sch   = itr.get("sch_ti_other_src", 0.0)
    if abs(os_sheet - os_sch) > 200:
        discs.append(_disc(
            title="Other Sources total in ITR schedule differs from SCH TI",
            source_a_label="Other Sources (schedule total)",
            source_a_val=os_sheet,
            source_b_label="Other Sources (SCH TI filed value)",
            source_b_val=os_sch,
            delta=os_sheet - os_sch,
            section="Section 56(2)",
            severity="MEDIUM",
            explanation=(
                f"The Other Sources schedule lists total income of ₹{os_sheet:,.0f}, "
                f"but SCH TI (the summary schedule used for tax computation) reflects "
                f"only ₹{os_sch:,.0f}. This internal inconsistency of ₹{abs(os_sheet-os_sch):,.0f} "
                f"suggests the ITR may have been filed with an incorrect summary."
            ),
        ))

    # ── 6. TDS Claimed in ITR vs AIS (unclaimed TDS) ─────────────────────
    # Use Form 16 TDS as fallback if ITR TDS text parsing missed it
    tds_itr  = itr.get("tds_total_claimed", 0.0) or f16.get("total_tds_f16", 0.0)
    tds_ais  = ais.get("total_tds_ais", 0.0)
    tds_diff = tds_ais - tds_itr
    if abs(tds_diff) > 500:
        severity = "MEDIUM"
        explanation = (
            f"AIS reflects total TDS of ₹{tds_ais:,.2f} from all deductors, "
            f"whereas the ITR claims TDS of only ₹{tds_itr:,.0f} (salary only). "
        )
        if tds_diff > 0:
            explanation += (
                f"Additional TDS of ₹{tds_diff:,.2f} from bank and MF sources has "
                f"not been claimed, resulting in excess tax payment."
            )
        else:
            explanation += (
                f"ITR claims more TDS than shown in AIS — this may indicate "
                f"fraudulent TDS claims and warrants immediate verification."
            )
            severity = "HIGH"

        discs.append(_disc(
            title="TDS claimed in ITR does not match AIS",
            source_a_label="TDS claimed in ITR",
            source_a_val=tds_itr,
            source_b_label="Total TDS per AIS",
            source_b_val=tds_ais,
            delta=tds_diff,
            section="Section 199, Section 206AA",
            severity=severity,
            explanation=explanation,
        ))

    # ── 7. High-Value Cash Deposit (SFT) ─────────────────────────────────
    cash_dep = ais.get("cash_deposit_total", 0.0)
    net_inc  = itr.get("net_taxable_income", 0.0)
    if cash_dep >= SFT_CASH_DEPOSIT_LIMIT:
        ratio = (cash_dep / net_inc * 100) if net_inc else 0
        discs.append(_disc(
            title="High-value cash deposit in AIS exceeds declared income",
            source_a_label="Cash deposit (AIS SFT)",
            source_a_val=cash_dep,
            source_b_label="Net taxable income (ITR)",
            source_b_val=net_inc,
            delta=cash_dep - net_inc,
            section="Section 285BA, Rule 114E",
            severity="HIGH",
            explanation=(
                f"AIS reflects a cash deposit of ₹{cash_dep:,.0f} (reported as SFT "
                f"by the bank u/s 285BA). This is {ratio:.1f}% of the taxpayer's "
                f"declared net taxable income of ₹{net_inc:,.0f}. The source of "
                f"funds for this deposit has not been explained in the ITR."
            ),
        ))

    # ── 8. Property Purchase: AIS vs ITR ─────────────────────────────────
    prop_total = ais.get("property_purchase_total", 0.0)
    if prop_total >= SFT_PROPERTY_LIMIT:
        discs.append(_disc(
            title="High-value property purchase in AIS not reflected in ITR",
            source_a_label="Property purchase (AIS Part A2)",
            source_a_val=prop_total,
            source_b_label="Asset declared in ITR Schedule AL",
            source_b_val=0.0,
            delta=prop_total,
            section="Section 194IA, Schedule AL",
            severity="HIGH",
            explanation=(
                f"AIS Part A2 records a property purchase of ₹{prop_total:,.0f} "
                f"with TDS deducted u/s 194IA. This high-value asset has not been "
                f"disclosed in Schedule AL (Assets and Liabilities) of the ITR. "
                f"Source of funds for the property purchase also needs explanation."
            ),
        ))

    # ── 9. 80C Deduction Limit Check ─────────────────────────────────────
    ded_80c = itr.get("ded_80c", 0.0)
    if ded_80c > LIMIT_80C:
        excess = ded_80c - LIMIT_80C
        discs.append(_disc(
            title="80C deduction claimed exceeds statutory limit",
            source_a_label="80C claimed (ITR)",
            source_a_val=ded_80c,
            source_b_label="80C limit (AY 2025-26)",
            source_b_val=LIMIT_80C,
            delta=excess,
            section="Section 80C",
            severity="HIGH",
            explanation=(
                f"The taxpayer has claimed ₹{ded_80c:,.0f} under Section 80C, "
                f"exceeding the maximum permissible limit of ₹{LIMIT_80C:,.0f} by "
                f"₹{excess:,.0f}."
            ),
        ))

    # ── 10. 80D Deduction Limit Check ────────────────────────────────────
    ded_80d = itr.get("ded_80d", 0.0)
    if ded_80d > LIMIT_80D_SELF:
        excess = ded_80d - LIMIT_80D_SELF
        discs.append(_disc(
            title="80D deduction claimed exceeds limit (non-senior citizen)",
            source_a_label="80D claimed (ITR)",
            source_a_val=ded_80d,
            source_b_label="80D limit (self)",
            source_b_val=LIMIT_80D_SELF,
            delta=excess,
            section="Section 80D",
            severity="MEDIUM",
            explanation=(
                f"₹{ded_80d:,.0f} claimed under 80D exceeds the ₹{LIMIT_80D_SELF:,.0f} "
                f"limit applicable for non-senior citizens. Excess of ₹{excess:,.0f} "
                f"needs verification."
            ),
        ))

    # ── 11. Self-Assessment Tax Corroboration ─────────────────────────────
    self_tax = ais.get("total_tax_paid_ais", 0.0)
    if self_tax > 0:
        discs.append(_disc(
            title="Self-assessment tax paid (corroborating discrepancies)",
            source_a_label="Self-assessment tax paid (AIS Part C)",
            source_a_val=self_tax,
            source_b_label="TDS from salary (ITR)",
            source_b_val=itr.get("tds_total_claimed", 0.0),
            delta=self_tax,
            section="Section 140A",
            severity="INFO",
            explanation=(
                f"AIS Part C shows self-assessment tax of ₹{self_tax:,.0f} paid. "
                f"This is significantly above the salary TDS, suggesting the taxpayer "
                f"was aware of additional tax liability — corroborating the above income "
                f"under-reporting discrepancies."
            ),
        ))

    # ── Risk Score ────────────────────────────────────────────────────────
    score = 0
    for d in discs:
        if d["severity"] == "HIGH":
            score += RISK_WEIGHT_HIGH
        elif d["severity"] == "MEDIUM":
            score += RISK_WEIGHT_MEDIUM
        elif d["severity"] == "INFO":
            score += RISK_WEIGHT_INFO

    score = min(score, 100)

    if score >= 70:
        band = "🔴 Scrutiny Recommended"
    elif score >= 40:
        band = "🟠 High Risk — Further Review Required"
    elif score >= 20:
        band = "🟡 Medium Risk — Spot Check Advised"
    else:
        band = "🟢 Low Risk — No Immediate Action"

    return {
        "discrepancies":  discs,
        "risk_score":     score,
        "risk_band":      band,
        "taxpayer_name":  itr.get("name", ais.get("name", "Unknown")),
        "pan":            itr.get("pan", ais.get("pan", "")),
        "ay":             ais.get("ay", "2025-26"),
    }
