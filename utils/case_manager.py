# utils/case_manager.py
# Manages the local case queue for the AO dashboard.
#
# Cases are stored in a JSON file: data/cases.json
# Each case has:
#   id, taxpayer_name, pan, ay, zone, ward, flag_reason,
#   flag_source, status, created_on, last_updated
#
# Statuses: PENDING | IN_PROGRESS | NOTICE_ISSUED | CLOSED

import json
import uuid
from datetime import date, datetime
from pathlib import Path

# ── Storage path ──────────────────────────────────────────────────────────
_BASE_DIR  = Path(__file__).resolve().parent.parent
DATA_DIR   = _BASE_DIR / "data"
CASES_FILE = DATA_DIR / "cases.json"

# ── Seed cases shown on first run ─────────────────────────────────────────
_SEED_CASES = [
    {
        "id":            "CASE-2025-001",
        "taxpayer_name": "Rahul Sharma",
        "pan":           "ABCPE1234F",
        "ay":            "2025-26",
        "zone":          "Delhi",
        "ward":          "Ward 1(1), New Delhi",
        "flag_reason":   "Cash deposit ₹12,00,000 > declared income; property purchase ₹30,05,000 unaccounted",
        "flag_source":   "SFT / AIS",
        "status":        "PENDING",
        "created_on":    "2025-06-01",
        "last_updated":  "2025-06-01",
        "notes":         "",
    },
    {
        "id":            "CASE-2025-002",
        "taxpayer_name": "Priya Menon",
        "pan":           "BKZPM5678G",
        "ay":            "2025-26",
        "zone":          "Mumbai",
        "ward":          "Ward 14(3), Mumbai",
        "flag_reason":   "Foreign remittance ₹18,00,000 not declared in ITR; TDS mismatch ₹45,000",
        "flag_source":   "AIS / Form 26AS",
        "status":        "PENDING",
        "created_on":    "2025-06-03",
        "last_updated":  "2025-06-03",
        "notes":         "",
    },
    {
        "id":            "CASE-2025-003",
        "taxpayer_name": "Anil Kapoor Enterprises",
        "pan":           "CRTAE9012H",
        "ay":            "2025-26",
        "zone":          "Bangalore",
        "ward":          "Ward 2(2), Bengaluru",
        "flag_reason":   "Business turnover in AIS ₹85L vs ITR ₹42L; 80C excess claim",
        "flag_source":   "AIS / ITR",
        "status":        "IN_PROGRESS",
        "created_on":    "2025-05-28",
        "last_updated":  "2025-06-10",
        "notes":         "Documents partially received.",
    },
    {
        "id":            "CASE-2025-004",
        "taxpayer_name": "Sunita Verma",
        "pan":           "DMPVS3456J",
        "ay":            "2025-26",
        "zone":          "Delhi",
        "ward":          "Ward 6(4), New Delhi",
        "flag_reason":   "High-value FD ₹25L; dividend income ₹3.2L not declared",
        "flag_source":   "AIS",
        "status":        "NOTICE_ISSUED",
        "created_on":    "2025-05-15",
        "last_updated":  "2025-06-18",
        "notes":         "Notice issued on 18-Jun-2025. Awaiting reply.",
    },
    {
        "id":            "CASE-2025-005",
        "taxpayer_name": "Mohammed Irfan",
        "pan":           "EHKMI7890K",
        "ay":            "2025-26",
        "zone":          "Hyderabad",
        "ward":          "Ward 5(1), Hyderabad",
        "flag_reason":   "Capital gains ₹22L on share sale not declared; TDS u/s 194K mismatch",
        "flag_source":   "AIS / Form 26AS",
        "status":        "PENDING",
        "created_on":    "2025-06-05",
        "last_updated":  "2025-06-05",
        "notes":         "",
    },
]

# ── Status config ─────────────────────────────────────────────────────────
STATUS_OPTIONS = ["PENDING", "IN_PROGRESS", "NOTICE_ISSUED", "CLOSED"]

STATUS_META = {
    "PENDING":       {"label": "🟡 Pending",        "color": "#f39c12"},
    "IN_PROGRESS":   {"label": "🔵 In Progress",    "color": "#2980b9"},
    "NOTICE_ISSUED": {"label": "🟠 Notice Issued",  "color": "#e67e22"},
    "CLOSED":        {"label": "🟢 Closed",         "color": "#27ae60"},
}

AY_OPTIONS = ["2025-26", "2024-25", "2023-24", "2022-23"]
ZONE_OPTIONS = [
    "Delhi", "Mumbai", "Bangalore", "Hyderabad", "Chennai",
    "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
]


# ── File I/O ──────────────────────────────────────────────────────────────

def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_cases() -> list:
    """Load all cases from cases.json. Seeds with sample data on first run."""
    _ensure_data_dir()
    if not CASES_FILE.exists():
        _save_cases(_SEED_CASES)
        return list(_SEED_CASES)
    try:
        with open(CASES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return list(_SEED_CASES)


def _save_cases(cases: list):
    _ensure_data_dir()
    with open(CASES_FILE, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)


# ── CRUD operations ───────────────────────────────────────────────────────

def add_case(taxpayer_name: str, pan: str, ay: str, zone: str,
             ward: str, flag_reason: str, flag_source: str,
             notes: str = "") -> dict:
    """Create a new case and append to the queue."""
    cases   = load_cases()
    today   = date.today().isoformat()
    # Generate sequential ID based on year and count
    year    = date.today().year
    count   = sum(1 for c in cases if c["id"].startswith(f"CASE-{year}")) + 1
    case_id = f"CASE-{year}-{count:03d}"

    new_case = {
        "id":            case_id,
        "taxpayer_name": taxpayer_name.strip().title(),
        "pan":           pan.strip().upper(),
        "ay":            ay,
        "zone":          zone,
        "ward":          ward.strip(),
        "flag_reason":   flag_reason.strip(),
        "flag_source":   flag_source.strip(),
        "status":        "PENDING",
        "created_on":    today,
        "last_updated":  today,
        "notes":         notes.strip(),
    }
    cases.append(new_case)
    _save_cases(cases)
    return new_case


def update_case_status(case_id: str, new_status: str, notes: str = None):
    """Update the status (and optionally notes) of a case."""
    cases = load_cases()
    for c in cases:
        if c["id"] == case_id:
            c["status"]       = new_status
            c["last_updated"] = date.today().isoformat()
            if notes is not None:
                c["notes"] = notes
            break
    _save_cases(cases)


def delete_case(case_id: str):
    """Remove a case from the queue."""
    cases = load_cases()
    cases = [c for c in cases if c["id"] != case_id]
    _save_cases(cases)


def get_case(case_id: str) -> dict | None:
    """Fetch a single case by ID."""
    for c in load_cases():
        if c["id"] == case_id:
            return c
    return None


# ── Filter / sort helpers ─────────────────────────────────────────────────

def filter_cases(cases: list,
                 status_filter: list = None,
                 zone_filter: str    = None,
                 ay_filter: str      = None,
                 search_text: str    = "") -> list:
    """Filter and search the case list."""
    result = cases
    if status_filter:
        result = [c for c in result if c["status"] in status_filter]
    if zone_filter and zone_filter != "All Zones":
        result = [c for c in result if c.get("zone") == zone_filter]
    if ay_filter and ay_filter != "All AYs":
        result = [c for c in result if c.get("ay") == ay_filter]
    if search_text.strip():
        q = search_text.strip().lower()
        result = [
            c for c in result
            if q in c["taxpayer_name"].lower()
            or q in c["pan"].lower()
            or q in c.get("flag_reason", "").lower()
        ]
    return result


def sort_cases(cases: list, sort_by: str = "created_on") -> list:
    """Sort cases. sort_by: created_on | last_updated | taxpayer_name | status"""
    reverse = sort_by in ("created_on", "last_updated")
    return sorted(cases, key=lambda c: c.get(sort_by, ""), reverse=reverse)
