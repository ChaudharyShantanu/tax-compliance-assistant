# parsers/form16_parser.py
# Parses Form 16 Excel file.
# Sheet structure: single sheet (Sheet1) with Part A TDS table at top,
# followed by Part B salary computation below.

import pandas as pd
import re


def _clean(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    s = str(val).replace(",", "").replace("₹", "").replace(" ", "").strip()
    # Handle negative in parentheses like (150000)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_form16(file_obj) -> dict:
    """
    Parse Form 16 Excel file.
    Returns a structured dict with Part A (TDS) and Part B (salary) fields.
    """
    xf = pd.ExcelFile(file_obj)
    sheet = xf.sheet_names[0]   # typically Sheet1

    df = xf.parse(sheet, header=None)

    data = {
        "tds_quarters": [],
        "gross_salary_f16": 0.0,
        "hra_exemption_f16": 0.0,
        "salary_after_hra": 0.0,
        "std_deduction_f16": 0.0,
        "taxable_salary_f16": 0.0,
        "other_income_f16": 0.0,
        "gross_total_f16": 0.0,
        "total_tds_f16": 0.0,
        "total_tds_deposited_f16": 0.0,
    }

    # ── Part A: TDS quarterly table ───────────────────────────────────────
    # Rows with Quarter (Q1–Q4) contain: Quarter, Receipt, Amount, TDS deducted, TDS deposited
    quarter_rows = []
    total_row = None

    for _, row in df.iterrows():
        first = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
        if first in ["Q1", "Q2", "Q3", "Q4"]:
            quarter_rows.append({
                "quarter":      first,
                "receipt_no":   str(row.iloc[1]).strip() if len(row) > 1 else "",
                "amount":       _clean(row.iloc[2]) if len(row) > 2 else 0.0,
                "tds_deducted": _clean(row.iloc[3]) if len(row) > 3 else 0.0,
                "tds_deposited":_clean(row.iloc[4]) if len(row) > 4 else 0.0,
            })
        elif first.lower() == "total":
            total_row = row

    data["tds_quarters"] = quarter_rows

    if total_row is not None:
        data["gross_salary_f16"]      = _clean(total_row.iloc[2]) if len(total_row) > 2 else 0.0
        data["total_tds_f16"]         = _clean(total_row.iloc[3]) if len(total_row) > 3 else 0.0
        data["total_tds_deposited_f16"] = _clean(total_row.iloc[4]) if len(total_row) > 4 else 0.0
    elif quarter_rows:
        data["gross_salary_f16"]      = sum(r["amount"] for r in quarter_rows)
        data["total_tds_f16"]         = sum(r["tds_deducted"] for r in quarter_rows)
        data["total_tds_deposited_f16"] = sum(r["tds_deposited"] for r in quarter_rows)

    # ── Part B: Salary computation rows ──────────────────────────────────
    # We look for specific row labels in column 0 or 1
    raw_text = df.astype(str).values

    for row in raw_text:
        joined = " | ".join(str(c) for c in row)

        # Gross salary total
        if "Total Gross Salary" in joined or "Total amount of salary received" in joined:
            for cell in row[1:]:
                v = _clean(cell)
                if v > 0:
                    if "Total Gross Salary" in joined:
                        data["gross_salary_f16"] = data["gross_salary_f16"] or v
                    else:
                        data["salary_after_hra"] = v
                    break

        # HRA exemption
        if "House rent allowance" in joined or "hra" in joined.lower():
            for cell in row[1:]:
                v = abs(_clean(cell))
                if v > 0:
                    data["hra_exemption_f16"] = v
                    break

        # Standard deduction
        if "Standard deduction" in joined and "16(ia)" in joined.lower():
            for cell in row[1:]:
                v = abs(_clean(cell))
                if v > 0:
                    data["std_deduction_f16"] = v
                    break

        # Income chargeable under Salaries (taxable salary)
        if 'Income chargeable under the head "Salaries"' in joined or \
           "Income chargeable under the head" in joined:
            for cell in row[1:]:
                v = abs(_clean(cell))
                if v > 0:
                    data["taxable_salary_f16"] = v
                    break

        # Other income (savings interest)
        if "other income reported" in joined.lower() or "Savings Interest" in joined:
            for cell in row[1:]:
                v = abs(_clean(cell))
                if v > 0:
                    data["other_income_f16"] = v
                    break

        # Gross Total Income in Form 16
        if "Gross Total Income" in joined and "6+8" in joined:
            for cell in row[1:]:
                v = abs(_clean(cell))
                if v > 0:
                    data["gross_total_f16"] = v
                    break

    return data
