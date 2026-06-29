# utils/din_generator.py
# Generates a simulated DIN (Document Identification Number) and
# DSC (Digital Signature Certificate) stamp for the final notice.
#
# In production, DIN is assigned by ITBA (Income Tax Business Application).
# Here we simulate it with a deterministic, realistic format.
#
# DIN format used by IT Dept: ITBA/AST/S/142(1)/YYYY-YY/XXXXXXXXXX(1)
# e.g.  ITBA/AST/S/142(1)/2025-26/10012345678(1)

import hashlib
import random
from datetime import date, datetime
from config import DIN_PREFIX


def generate_din(pan: str, ay: str, notice_section: str = "142(1)") -> str:
    """
    Generate a simulated DIN for the notice.
    Deterministic for the same PAN + AY combination (same case = same DIN).
    Format: ITBA/AST/S/142(1)/2025-26/10XXXXXXXXXX(1)
    """
    # Create a deterministic seed from PAN + AY so re-generating gives same DIN
    seed = hashlib.md5(f"{pan}{ay}".encode()).hexdigest()
    numeric_part = int(seed[:10], 16) % 10_000_000_000   # 10-digit number
    ay_clean = ay.strip()
    return f"{DIN_PREFIX}/S/{notice_section}/{ay_clean}/{10_000_000_000 + numeric_part}(1)"


def generate_dsc_block(officer_name: str, ward: str, pan: str) -> dict:
    """
    Generate a simulated DSC metadata block.
    In production this would be a real cryptographic signature via the
    ITBA DSC module. Here we produce a realistic placeholder.
    """
    now = datetime.now()
    # Deterministic cert serial for same officer+PAN
    seed  = hashlib.sha256(f"{officer_name}{pan}".encode()).hexdigest()
    serial = seed[:16].upper()

    return {
        "signed_by":    officer_name,
        "designation":  "Income Tax Officer / Assessing Officer",
        "ward":         ward,
        "signed_on":    now.strftime("%d/%m/%Y %H:%M:%S"),
        "cert_serial":  f"DSC-{serial}",
        "valid_until":  f"31/03/{now.year + 1}",
        "note":         "This is a system-generated document. DSC applied via ITBA.",
    }


def format_dsc_stamp_text(dsc: dict) -> str:
    """Return DSC block as formatted text for embedding in notice."""
    return (
        f"\n{'─' * 60}\n"
        f"DIGITALLY SIGNED\n"
        f"Signed by  : {dsc['signed_by']}\n"
        f"Designation: {dsc['designation']}\n"
        f"Ward/Circle: {dsc['ward']}\n"
        f"Date & Time: {dsc['signed_on']}\n"
        f"Cert Serial: {dsc['cert_serial']}\n"
        f"Valid Until: {dsc['valid_until']}\n"
        f"{dsc['note']}\n"
        f"{'─' * 60}\n"
    )
