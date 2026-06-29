# ai/sarvam_client.py
#
# TWO focused API calls — never more than 2 per case session:
#
#   generate_summary()  — called ONCE after AO validates discrepancies
#   refine_notice()     — called ONLY when AO clicks Refine
#
# Key Sarvam API settings:
#   - Model: sarvam-30b
#   - reasoning_effort: null  (disables thinking mode → content not empty)
#   - max_tokens: 4096

import json
import re
import requests
from config import (
    SARVAM_API_KEY, SARVAM_ENDPOINT, SARVAM_MODEL,
    NOTICE_MAX_TOKENS, REFINE_MAX_TOKENS,
    API_TEMPERATURE,
)


# ── Internal helpers ──────────────────────────────────────────────────────

def _safe_str(val) -> str:
    """Convert any value to string safely — handles None, int, list, etc."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return str(val)


def _call_api(prompt: str, max_tokens: int) -> dict:
    """
    Single POST to Sarvam AI.
    Returns {content, raw_response, error}.
    """
    if not SARVAM_API_KEY or SARVAM_API_KEY == "YOUR_SARVAM_API_KEY_HERE":
        return {"content": "", "raw_response": {}, "error": "API key not configured in config.py"}

    try:
        payload = {
            "model":            SARVAM_MODEL,
            "messages":         [{"role": "user", "content": prompt}],
            "max_tokens":       max_tokens,
            "temperature":      API_TEMPERATURE,
            "reasoning_effort": None,   # disables thinking mode → content not empty
        }

        resp = requests.post(
            SARVAM_ENDPOINT,
            headers={
                "Authorization": f"Bearer {SARVAM_API_KEY}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()

        content = ""

        if "choices" in data and isinstance(data["choices"], list) and data["choices"]:
            first   = data["choices"][0]
            message = first.get("message") if isinstance(first, dict) else None
            if isinstance(message, dict):
                raw_content = message.get("content")
                content     = _safe_str(raw_content)
                if not content.strip():
                    finish_reason = _safe_str(first.get("finish_reason", ""))
                    reasoning     = _safe_str(message.get("reasoning_content", ""))
                    if reasoning:
                        return {
                            "content": "", "raw_response": data,
                            "error": (
                                f"Sarvam returned only reasoning_content "
                                f"(finish_reason={finish_reason}). "
                                f"reasoning_effort=None may not have been applied."
                            ),
                        }
        elif "content" in data:
            items = data["content"]
            if isinstance(items, list):
                parts = [
                    _safe_str(i.get("text"))
                    for i in items
                    if isinstance(i, dict) and i.get("type") == "text"
                ]
                content = " ".join(parts)
            else:
                content = _safe_str(items)
        elif "text" in data:
            content = _safe_str(data["text"])
        elif "output" in data:
            content = _safe_str(data["output"])
        elif "response" in data:
            content = _safe_str(data["response"])

        return {"content": content.strip(), "raw_response": data, "error": None}

    except requests.exceptions.Timeout:
        return {
            "content": "", "raw_response": {},
            "error": "API request timed out (90s). Please retry.",
        }
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = e.response.text[:400]
        except Exception:
            pass
        return {"content": "", "raw_response": {}, "error": f"HTTP {e.response.status_code}: {body}"}
    except Exception as e:
        return {"content": "", "raw_response": {}, "error": str(e)}


def _extract_json(text: str) -> dict | None:
    """Robustly extract a JSON object from model output."""
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    try:
        return json.loads(stripped.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    try:
        normalized = re.sub(r"(?<!\w)'([^']*)'(?!\w)", r'"\1"', text)
        match2 = re.search(r"\{[\s\S]*\}", normalized)
        if match2:
            return json.loads(match2.group())
    except (json.JSONDecodeError, re.error, ValueError):
        pass
    return None


def _clean_notice_text(text: str) -> str:
    """
    Strip prompt scaffolding and XML tags that may leak into notice output.
    Called on both input (before sending) and output (after receiving).
    """
    if not text:
        return ""

    # Remove XML/HTML tags the model might echo or add
    text = re.sub(r"<current_notice>\s*", "", text)
    text = re.sub(r"\s*</current_notice>", "", text)
    text = re.sub(r"<ao_feedback>\s*", "", text)
    text = re.sub(r"\s*</ao_feedback>", "", text)
    text = re.sub(r"<[^>]+>", "", text)   # any remaining tags

    # Remove severity labels like [HIGH], [MEDIUM], [INFO] — not for legal notices
    text = re.sub(r"\[(HIGH|MEDIUM|INFO|LOW|OK)\]\s*", "", text)

    # Remove everything from known prompt section headers onwards
    cutoff_markers = [
        "ASSESSING OFFICER FEEDBACK:",
        "AO FEEDBACK:",
        "TASK:",
        "CURRENT NOTICE DRAFT:",
        "Instructions:",
        "You are a senior Indian Income Tax Officer",
        "The Assessing Officer has requested",
    ]
    for marker in cutoff_markers:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]

    return text.strip()


def _format_notice_points(text: str) -> str:
    """
    Ensure each numbered point in the notice is on its own line.
    Handles cases where the model writes all points inline in one paragraph.
    """
    # Split inline numbered points onto separate lines
    text = re.sub(r'\s+(\d+[.)]\s)', lambda m: '\n\n' + m.group(1), text)

    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def _renumber_notice_points(text: str) -> str:
    """
    Renumber all numbered points in the notice sequentially (1, 2, 3...).
    Fixes gaps left when the model removes a point without renumbering.

    Strategy:
    - Split the notice into blocks separated by blank lines
    - Identify blocks that start with a number (the numbered points)
    - Reassign numbers 1, 2, 3... in order
    - Preserve the introductory paragraph and closing line (non-numbered)
    """
    if not text:
        return text

    # Split into blocks on blank lines
    blocks = re.split(r'\n\s*\n', text.strip())

    intro_blocks  = []   # paragraphs before the first numbered point
    point_blocks  = []   # the numbered points themselves
    closing_block = []   # lines after the last numbered point (compliance deadline etc.)

    found_first_point = False
    last_point_idx    = -1

    # First pass — identify which blocks are numbered points
    for i, block in enumerate(blocks):
        stripped = block.strip()
        if re.match(r'^\d+[.)]', stripped):
            found_first_point = True
            last_point_idx    = i

    # Second pass — categorise blocks
    for i, block in enumerate(blocks):
        stripped = block.strip()
        if not found_first_point:
            # No numbered points found at all — return as-is
            return text
        if i < last_point_idx and not re.match(r'^\d+[.)]', stripped) and not point_blocks:
            intro_blocks.append(block.strip())
        elif re.match(r'^\d+[.)]', stripped):
            # Strip the old number and renumber later
            without_num = re.sub(r'^\d+[.)]\s*', '', stripped)
            point_blocks.append(without_num)
        elif i > last_point_idx:
            closing_block.append(block.strip())

    # Renumber points sequentially
    renumbered = [f"{j}. {pt}" for j, pt in enumerate(point_blocks, 1)]

    # Reassemble
    parts = []
    if intro_blocks:
        parts.append('\n\n'.join(intro_blocks))
    parts.extend(renumbered)
    if closing_block:
        parts.append('\n\n'.join(closing_block))

    return '\n\n'.join(parts).strip()


def _build_local_summary(accepted_discs: list, taxpayer_name: str,
                          pan: str, ay: str) -> dict:
    """
    Build executive summary and Section 142(1) notice body from local data.
    Zero API cost. Used as fallback when API is unavailable.
    """
    high   = [d for d in accepted_discs if d.get("severity") == "HIGH"]
    medium = [d for d in accepted_discs if d.get("severity") == "MEDIUM"]
    info   = [d for d in accepted_discs if d.get("severity") == "INFO"]

    summary_parts = [
        f"Scrutiny analysis of {taxpayer_name} (PAN: {pan}, AY: {ay}) identified "
        f"{len(accepted_discs)} discrepanc{'y' if len(accepted_discs) == 1 else 'ies'} "
        f"across ITR, Form 16, and AIS."
    ]
    if high:
        titles = "; ".join(d["title"] for d in high[:3])
        summary_parts.append(
            f"{len(high)} high-severity issue(s): {titles}"
            + (" and others." if len(high) > 3 else ".")
        )
    if medium:
        summary_parts.append(f"{len(medium)} medium-severity issue(s) also noted.")
    if info:
        summary_parts.append(f"{len(info)} informational flag(s) corroborate the above.")
    summary_parts.append(
        "Scrutiny notice under Section 142(1) of the Income Tax Act, 1961 is warranted."
    )
    summary = " ".join(summary_parts)

    pts = []
    for j, d in enumerate(accepted_discs, 1):
        explanation = _safe_str(d.get("explanation") or d.get("edited_explanation"))
        pts.append(
            f"{j}. {d['title']}\n"
            f"   Relevant provision: {d['section']}\n"
            f"   As per records, {d['source_a_label']} is "
            f"Rs {d['source_a_val']:,.0f} whereas {d['source_b_label']} "
            f"reflects Rs {d['source_b_val']:,.0f} — a difference of "
            f"Rs {abs(d['delta']):,.0f}. {explanation}\n"
            f"   You are requested to explain this discrepancy and furnish "
            f"supporting documentary evidence."
        )

    notice = (
        f"In connection with the assessment proceedings in the case of "
        f"{taxpayer_name} (PAN: {pan}) for Assessment Year {ay}, the following "
        f"discrepancies have been identified. You are hereby called upon under "
        f"Section 142(1) of the Income Tax Act, 1961 to furnish explanation and "
        f"supporting documents for each point below:\n\n"
        + "\n\n".join(pts)
        + "\n\nYou are required to comply within 15 days of receipt of this notice. "
        "Non-compliance may attract penalty under Section 272A of the "
        "Income Tax Act, 1961."
    )

    return {"executive_summary": summary, "draft_notice": notice}


# ── Public API ────────────────────────────────────────────────────────────

def generate_summary(accepted_discs: list, taxpayer_name: str,
                     pan: str, ay: str) -> dict:
    """
    API Call 1 — called ONCE after AO accepts/rejects discrepancies.
    Returns: {executive_summary, draft_notice, error}
    Falls back to local generation gracefully on any failure.
    """
    if not accepted_discs:
        return {
            "executive_summary": "No discrepancies accepted for notice generation.",
            "draft_notice":      "",
            "error":             None,
        }

    if not SARVAM_API_KEY or SARVAM_API_KEY == "YOUR_SARVAM_API_KEY_HERE":
        local = _build_local_summary(accepted_discs, taxpayer_name, pan, ay)
        return {
            "executive_summary": local["executive_summary"],
            "draft_notice":      local["draft_notice"],
            "error":             None,
        }

    # Build compact disc list — NO severity labels, clean title only
    disc_lines = "\n".join(
        f"{i}. {d['title']} | Delta: Rs {abs(d['delta']):,.0f} | Section: {d['section']}"
        for i, d in enumerate(accepted_discs, 1)
    )

    prompt = f"""You are a senior Indian Income Tax Officer drafting a legal scrutiny notice.

CASE DETAILS:
Taxpayer: {taxpayer_name}
PAN: {pan}
Assessment Year: {ay}

DISCREPANCIES IDENTIFIED ({len(accepted_discs)} issues):
{disc_lines}

YOUR TASKS:

TASK 1 — EXECUTIVE SUMMARY:
Write exactly 4 to 6 sentences summarising the key compliance issues found.
Be concise, factual, and use professional language.

TASK 2 — NOTICE BODY (Section 142(1)):
Draft the body of a formal Income Tax scrutiny notice.

STRICT FORMATTING RULES — follow exactly:
- Start with one introductory paragraph explaining why the notice is issued.
- Then list each discrepancy as a SEPARATE NUMBERED POINT.
- Each numbered point MUST be on its own line, separated by a blank line.
- Each point format:
  [point number]. [Description of discrepancy and amount involved, citing the Section]
  You are requested to [specific document/explanation required].
- Do NOT write all points in a single paragraph.
- Do NOT use inline numbering like "1. issue 2. issue 3. issue" on one line.
- End with: "You are required to comply within 15 days of receipt of this notice."

EXAMPLE of correct format:
1. The salary income declared in the ITR is Rs X,XXX less than shown in Form 16 under Section 17(1). You are requested to furnish a reconciliation statement and the original Form 16 for the financial year.

2. Interest income from Fixed Deposits amounting to Rs X,XXX as reflected in the AIS has not been declared under Section 56(2). You are requested to furnish Form 16A and bank statements showing interest credited.

Return ONLY valid JSON with exactly these two keys — no preamble, no markdown:
{{"executive_summary": "your summary here", "draft_notice": "your notice body here"}}"""

    result = _call_api(prompt, NOTICE_MAX_TOKENS)

    if result["error"]:
        local = _build_local_summary(accepted_discs, taxpayer_name, pan, ay)
        return {
            "executive_summary": local["executive_summary"],
            "draft_notice":      local["draft_notice"],
            "error":             f"API unavailable: {result['error']}",
        }

    content = result["content"]

    if not content:
        local = _build_local_summary(accepted_discs, taxpayer_name, pan, ay)
        return {
            "executive_summary": local["executive_summary"],
            "draft_notice":      local["draft_notice"],
            "error":             "API returned empty response — local draft generated.",
        }

    parsed = _extract_json(content)
    if parsed and "executive_summary" in parsed and "draft_notice" in parsed:
        summary = _clean_notice_text(_safe_str(parsed.get("executive_summary")))
        notice  = _clean_notice_text(_safe_str(parsed.get("draft_notice")))
        notice  = _format_notice_points(notice)
        notice  = _renumber_notice_points(notice)
        return {
            "executive_summary": summary,
            "draft_notice":      notice,
            "error":             None,
        }

    if len(content) > 150:
        local = _build_local_summary(accepted_discs, taxpayer_name, pan, ay)
        notice = _clean_notice_text(content)
        notice = _format_notice_points(notice)
        return {
            "executive_summary": local["executive_summary"],
            "draft_notice":      notice,
            "error":             None,
        }

    local = _build_local_summary(accepted_discs, taxpayer_name, pan, ay)
    return {
        "executive_summary": local["executive_summary"],
        "draft_notice":      local["draft_notice"],
        "error":             "Could not use AI response — local draft generated.",
    }


def refine_notice(current_notice: str, ao_feedback: str,
                  taxpayer_name: str, pan: str, ay: str) -> dict:
    """
    API Call 2 — called ONLY when AO provides explicit refinement feedback.
    Sends ONLY current notice + feedback. Returns: {draft_notice, error}
    """
    if not ao_feedback.strip():
        return {"draft_notice": current_notice, "error": "No feedback provided."}

    if not SARVAM_API_KEY or SARVAM_API_KEY == "YOUR_SARVAM_API_KEY_HERE":
        return {
            "draft_notice": current_notice,
            "error":        "API key not configured — notice unchanged.",
        }

    # Clean any leaked prompt/tag text from the current notice before sending
    clean_notice = _clean_notice_text(current_notice)

    prompt = f"""You are a senior Indian Income Tax Officer editing a legal scrutiny notice.

Taxpayer: {taxpayer_name} | PAN: {pan} | AY: {ay}

Below is the current notice draft enclosed in triple backticks:
```
{clean_notice}
```

The Assessing Officer wants these changes:
"{ao_feedback}"

Edit the notice applying ONLY the requested changes. Then return the complete revised notice.

STRICT RULES:
- Each numbered point MUST be on its own separate line with a blank line between points.
- Do NOT collapse multiple points into one paragraph.
- Renumber points sequentially (1, 2, 3...) if any point was removed.
- Remove severity labels like [HIGH] or [INFO] if present — these are internal only.
- Remove any XML tags like <current_notice> if present.
- Keep all formal legal language.
- Return ONLY the revised notice body text — no explanation, no preamble, no tags."""

    result = _call_api(prompt, REFINE_MAX_TOKENS)

    if result["error"]:
        return {"draft_notice": current_notice, "error": result["error"]}

    refined = _safe_str(result["content"])

    # Strip markdown fences
    refined = re.sub(r"^```(?:json|text)?\s*", "", refined, flags=re.IGNORECASE)
    refined = re.sub(r"\s*```$", "", refined.strip()).strip()

    # Strip any leaked prompt/tag text from the response
    refined = _clean_notice_text(refined)

    # Ensure points are on separate lines, then renumber sequentially
    refined = _format_notice_points(refined)
    refined = _renumber_notice_points(refined)

    if not refined:
        return {"draft_notice": current_notice, "error": "Empty response — notice unchanged."}

    if len(refined) < 100:
        return {
            "draft_notice": current_notice,
            "error": f"Unusable AI response (too short) — notice unchanged.",
        }

    return {"draft_notice": refined, "error": None}
