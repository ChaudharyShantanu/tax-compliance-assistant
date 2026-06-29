# config.py — API keys and rule thresholds

SARVAM_API_KEY  = "Add_your_apiKey_here"
SARVAM_ENDPOINT = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_MODEL = "sarvam-30b"

# ── API cost controls ─────────────────────────────────────────────────────
# Thinking mode is ON by default in Sarvam models.
# With low max_tokens, ALL tokens get consumed by internal reasoning,
# leaving empty content in the response. Two fixes applied:
#   1. max_tokens set high enough to accommodate reasoning + output
#   2. reasoning_effort=None passed to DISABLE thinking mode entirely
#      (thinking mode is unnecessary for structured JSON generation)
#
# API call budget per case:
#   Call 1 — generate_summary() : once after AO validates discrepancies
#   Call 2 — refine_notice()    : only when AO clicks Refine
NOTICE_MAX_TOKENS  = 4096   # generous — covers reasoning headroom + full output
REFINE_MAX_TOKENS  = 4096   # same for refinement
SUMMARY_MAX_TOKENS = 4096   # kept for import compatibility (merged into NOTICE)
API_TEMPERATURE    = 0.2    # low = deterministic output

# ── Deduction limits (AY 2025-26, Old Regime) ────────────────────────────
LIMIT_80C        = 150000
LIMIT_80D_SELF   = 25000
LIMIT_80D_SENIOR = 50000
LIMIT_80TTA      = 10000
LIMIT_80TTB      = 50000   # senior citizens

# ── SFT / High-value thresholds ───────────────────────────────────────────
SFT_CASH_DEPOSIT_LIMIT = 1000000   # Rs 10L cash deposit triggers SFT
SFT_TIME_DEPOSIT_LIMIT = 1000000   # Rs 10L fixed deposit
SFT_PROPERTY_LIMIT     = 3000000   # Rs 30L property purchase

# ── Risk weights ──────────────────────────────────────────────────────────
RISK_WEIGHT_HIGH   = 15
RISK_WEIGHT_MEDIUM = 5
RISK_WEIGHT_INFO   = 1

# ── DIN config ────────────────────────────────────────────────────────────
DIN_PREFIX = "ITBA/AST"   # standard ITBA DIN prefix
