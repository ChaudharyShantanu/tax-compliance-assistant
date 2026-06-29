# parsers/itr_parser.py
# Parses ITR Excel file with the sheet structure seen in the portal extract.
# Sheets handled: Part A-General Details, Salary, House Property,
#                 Other Sources, Deductions, TDS and Bank details, SCH TI

import pandas as pd
from io import BytesIO


def _clean(val):
    """Strip commas, ₹ symbols, spaces from a cell value and return float."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    s = str(val).replace(",", "").replace("₹", "").replace(" ", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _sheet_to_dict(xf, sheet_name):
    """Read a two-column (label, value) sheet into a flat dict."""
    try:
        df = xf.parse(sheet_name, header=None)
    except Exception:
        return {}
    result = {}
    for _, row in df.iterrows():
        key = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
        val = row.iloc[1] if len(row) > 1 else None
        if key:
            result[key] = val
    return result


def parse_itr(file_obj) -> dict:
    """
    Parse ITR Excel file.
    Accepts a file-like object (BytesIO or path string).
    Returns a structured dict of all key fields.
    """
    xf = pd.ExcelFile(file_obj)
    sheets = xf.sheet_names

    data = {}

    # ── Part A – General Details ──────────────────────────────────────────
    if "Part A- General Details" in sheets:
        gd = _sheet_to_dict(xf, "Part A- General Details")
        data["pan"]                = str(gd.get("PAN", "")).strip()
        data["first_name"]         = str(gd.get("First Name", "")).strip()
        data["last_name"]          = str(gd.get("Last Name", "")).strip()
        data["name"]               = f"{data['first_name']} {data['last_name']}".strip()
        data["dob"]                = gd.get("Date of Birth", "")
        data["mobile"]             = str(gd.get("Mobile Number", "")).strip()
        data["email"]              = str(gd.get("Email Address", "")).strip()
        data["residential_status"] = str(gd.get("Residential Status", "Resident")).strip()
        data["filing_status"]      = str(gd.get("Filing Status", "")).strip()
        data["new_regime"]         = str(gd.get("New Tax Regime?", "No")).strip()

    # ── Salary ────────────────────────────────────────────────────────────
    if "Salary" in sheets:
        sd = _sheet_to_dict(xf, "Salary")
        data["employer_name"]      = str(sd.get("Name of Employer", "")).strip()
        data["gross_salary"]       = _clean(sd.get("Gross Salary (Total)"))
        data["basic_salary"]       = _clean(sd.get("Basic Salary"))
        data["hra_received"]       = _clean(sd.get("House Rent Allowance (HRA)"))
        data["std_deduction_16ia"] = _clean(sd.get("Standard Deduction (u/s 16ia)"))
        data["hra_exemption_itr"]  = _clean(sd.get("House Rent Allowance (HRA)"))  # proxy

    # ── House Property ────────────────────────────────────────────────────
    if "House Property" in sheets:
        hp = _sheet_to_dict(xf, "House Property")
        data["hp_type"]            = str(hp.get("Type of Property", "")).strip()
        data["annual_rent"]        = _clean(hp.get("Annual Rent Received"))
        data["municipal_tax"]      = _clean(hp.get("Municipal Taxes Paid"))
        data["hp_std_deduction"]   = _clean(hp.get("Standard Deduction (30%)"))
        data["housing_loan_int"]   = _clean(hp.get("Interest on Housing Loan"))
        data["net_hp_income"]      = _clean(hp.get("Net Income from HP"))

    # ── Other Sources ─────────────────────────────────────────────────────
    if "Other Sources" in sheets:
        try:
            df_os = xf.parse("Other Sources")
            # Expect columns: Source, Amount
            rows = {}
            for _, row in df_os.iterrows():
                src = str(row.iloc[0]).strip()
                amt = _clean(row.iloc[1]) if len(row) > 1 else 0.0
                rows[src] = amt
            data["interest_sb"]         = rows.get("Interest from Savings Bank", 0.0)
            data["interest_fd"]         = rows.get("Interest from Fixed Deposits", 0.0)
            data["dividend_income"]     = rows.get("Dividend Income from Indian Cos", 0.0)
            data["other_sources_sheet"] = rows.get("Total Other Sources",
                                          data["interest_sb"] + data["interest_fd"] + data["dividend_income"])
        except Exception:
            data["interest_sb"] = data["interest_fd"] = data["dividend_income"] = 0.0
            data["other_sources_sheet"] = 0.0

    # ── Deductions ────────────────────────────────────────────────────────
    if "Deductions" in sheets:
        try:
            df_ded = xf.parse("Deductions")
            ded_map = {}
            for _, row in df_ded.iterrows():
                sec = str(row.iloc[0]).strip()
                amt = _clean(row.iloc[1]) if len(row) > 1 else 0.0
                ded_map[sec] = amt
            data["ded_80c"]   = ded_map.get("80C (PPF/LIC/ELSS)", 0.0)
            data["ded_80d"]   = ded_map.get("80D (Health Insurance)", 0.0)
            data["ded_80tta"] = ded_map.get("80TTA (Savings Interest)", 0.0)
            data["total_deductions"] = sum(ded_map.values()) if ded_map else 0.0
        except Exception:
            data["ded_80c"] = data["ded_80d"] = data["ded_80tta"] = 0.0
            data["total_deductions"] = 0.0

    # ── TDS & Bank Details ────────────────────────────────────────────────
    if "TDS and Bank details" in sheets:
        try:
            df_tds = xf.parse("TDS and Bank details", header=None)
            raw = " ".join(df_tds.astype(str).values.flatten())
            import re
            tans   = re.findall(r'TAN:\s*([A-Z]{4}\d{5}[A-Z])', raw)
            amounts = re.findall(r'Tax Deducted:\s*([\d,]+)', raw)
            data["salary_tan"]     = tans[0] if tans else ""
            data["tds_from_salary"] = _clean(amounts[0]) if amounts else 0.0
        except Exception:
            data["salary_tan"] = ""
            data["tds_from_salary"] = 0.0

    # ── SCH TI (Schedule Total Income — the filed numbers) ───────────────
    if "SCH TI" in sheets:
        try:
            df_ti = xf.parse("SCH TI")
            ti_map = {}
            for _, row in df_ti.iterrows():
                desc = str(row.iloc[1]).strip() if len(row) > 1 else ""
                amt  = _clean(row.iloc[2]) if len(row) > 2 else 0.0
                ti_map[desc] = amt
            data["sch_ti_salary"]       = ti_map.get("Salaries (Net of Standard Deduction)", 0.0)
            data["sch_ti_house_prop"]   = ti_map.get("Income from House Property", 0.0)
            data["sch_ti_other_src"]    = ti_map.get("Income from Other Sources", 0.0)
            data["gross_total_income"]  = ti_map.get("Gross Total Income (Sum of 1 to 4)", 0.0)
            data["total_vi_a_ded"]      = abs(ti_map.get("Deductions under Chapter VI-A", 0.0))
            data["net_taxable_income"]  = ti_map.get("Net Taxable Income (Rounded off)", 0.0)
        except Exception:
            data["sch_ti_salary"] = data["sch_ti_house_prop"] = 0.0
            data["sch_ti_other_src"] = data["gross_total_income"] = 0.0
            data["total_vi_a_ded"] = data["net_taxable_income"] = 0.0

    # ── Derived fields ────────────────────────────────────────────────────
    data["tds_total_claimed"] = data.get("tds_from_salary", 0.0)

    return data
