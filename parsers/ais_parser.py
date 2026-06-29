# parsers/ais_parser.py
# Parses AIS (Annual Information Statement) Excel file.
# Sheets: Summary, Part A - TDS Summary, Part A2 Property,
#         Part C Tax Paid, Part E SFT

import pandas as pd


def _clean(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    s = str(val).replace(",", "").replace("₹", "").replace(" ", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_ais(file_obj) -> dict:
    """
    Parse AIS Excel file.
    Returns structured dict with TDS entries, tax paid, SFT flags, property.
    """
    xf = pd.ExcelFile(file_obj)
    sheets = xf.sheet_names

    data = {
        "pan": "",
        "name": "",
        "ay": "",
        "fy": "",
        "tds_entries": [],       # list of dicts per deductor
        "property_purchase": [], # list of property transactions
        "tax_paid": [],          # self-assessment / advance tax
        "sft_entries": [],       # high-value / SFT transactions
        "total_tds_ais": 0.0,
        "total_tax_paid_ais": 0.0,
        "total_fd_interest_ais": 0.0,   # inferred from bank TDS
        "total_mf_income_ais": 0.0,     # inferred from MF TDS
        "property_purchase_total": 0.0,
        "cash_deposit_total": 0.0,
        "time_deposit_total": 0.0,
    }

    # ── Summary ───────────────────────────────────────────────────────────
    if "Summary" in sheets:
        df_s = xf.parse("Summary")
        cols_s = list(df_s.columns)
        if "PAN" in cols_s and len(df_s) > 0:
            data["pan"]  = str(df_s["PAN"].iloc[0]).strip()
            data["name"] = str(df_s["Name"].iloc[0]).strip() if "Name" in cols_s else ""
            data["ay"]   = str(df_s["AY"].iloc[0]).strip()   if "AY"   in cols_s else ""
            data["fy"]   = str(df_s["FY"].iloc[0]).strip()   if "FY"   in cols_s else ""
        else:
            df2 = xf.parse("Summary", header=None)
            for _, row in df2.iterrows():
                key = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
                val = str(row.iloc[1]).strip() if len(row) > 1 and not pd.isna(row.iloc[1]) else ""
                if key == "PAN":    data["pan"]  = val
                elif key == "Name": data["name"] = val
                elif key == "AY":   data["ay"]   = val
                elif key == "FY":   data["fy"]   = val

    # ── Part A – TDS Summary ──────────────────────────────────────────────
    if "Part A - TDS Summary" in sheets:
        df = xf.parse("Part A - TDS Summary")
        # Columns: Deductor, TAN, Total Amount, TDS Deducted, TDS Deposited
        total_tds = 0.0
        for _, row in df.iterrows():
            deductor = str(row.get("Deductor", "")).strip()
            if not deductor or deductor.lower() in ["deductor", "nan"]:
                continue
            tan           = str(row.get("TAN", "")).strip()
            total_amount  = _clean(row.get("Total Amount"))
            tds_deducted  = _clean(row.get("TDS Deducted"))
            tds_deposited = _clean(row.get("TDS Deposited"))

            entry = {
                "deductor":      deductor,
                "tan":           tan,
                "total_amount":  total_amount,
                "tds_deducted":  tds_deducted,
                "tds_deposited": tds_deposited,
            }
            data["tds_entries"].append(entry)
            total_tds += tds_deducted

            # Classify the income source
            deductor_upper = deductor.upper()
            if "BANK" in deductor_upper:
                # Bank TDS is typically on FD interest (194A)
                data["total_fd_interest_ais"] += total_amount
            if "MUTUAL FUND" in deductor_upper or "MF" in deductor_upper:
                # MF TDS is on dividend / income (194K)
                data["total_mf_income_ais"] += total_amount

        data["total_tds_ais"] = total_tds

    # ── Part A2 – Property Transactions ──────────────────────────────────
    if "Part A2 Property" in sheets:
        df = xf.parse("Part A2 Property")
        prop_total = 0.0
        for _, row in df.iterrows():
            ack      = str(row.get("Ack No", "")).strip()
            if not ack or ack.lower() in ["ack no", "nan"]:
                continue
            pan_ded  = str(row.get("Deductor PAN", "")).strip()
            date     = row.get("Date", "")
            amount   = _clean(row.get("Transaction Amount"))
            tds      = _clean(row.get("TDS"))
            entry = {
                "ack_no":       ack,
                "deductor_pan": pan_ded,
                "date":         date,
                "amount":       amount,
                "tds":          tds,
            }
            data["property_purchase"].append(entry)
            prop_total += amount
        data["property_purchase_total"] = prop_total

    # ── Part C – Tax Paid ─────────────────────────────────────────────────
    if "Part C Tax Paid" in sheets:
        df = xf.parse("Part C Tax Paid")
        total_tax = 0.0
        for _, row in df.iterrows():
            bsr  = str(row.get("BSR Code", "")).strip()
            if not bsr or bsr.lower() in ["bsr code", "nan"]:
                continue
            date = row.get("Date", "")
            tax  = _clean(row.get("Total Tax"))
            data["tax_paid"].append({"bsr": bsr, "date": date, "amount": tax})
            total_tax += tax
        data["total_tax_paid_ais"] = total_tax

    # ── Part E – SFT (High-Value Transactions) ────────────────────────────
    if "Part E SFT" in sheets:
        df = xf.parse("Part E SFT")
        # Columns: Type, Bank, Amount
        cash_total = 0.0
        td_total   = 0.0
        for _, row in df.iterrows():
            txn_type = str(row.get("Type", "")).strip()
            if not txn_type or txn_type.lower() in ["type", "nan"]:
                continue
            bank   = str(row.get("Bank", "")).strip()
            amount = _clean(row.get("Amount"))
            entry  = {"type": txn_type, "bank": bank, "amount": amount}
            data["sft_entries"].append(entry)
            if "Cash deposit" in txn_type or "cash" in txn_type.lower():
                cash_total += amount
            if "Time Deposit" in txn_type or "FD" in txn_type.upper():
                td_total += amount
        data["cash_deposit_total"]  = cash_total
        data["time_deposit_total"]  = td_total

    return data
