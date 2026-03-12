"""
LLM Parser — extracts shipment data from OCR text.

Two modes:
  1. RULE-BASED (default, no API needed):
     - Context-aware tracking number detection
     - Known courier prefix matching
     - Blacklist for order numbers
     - Pattern matching for items

  2. AI-ENHANCED (optional, needs OpenRouter API key):
     - Sends OCR text to OpenRouter LLM
     - Fallback to rule-based if API fails
"""
import json
import re
import time
import logging
import urllib.request
import urllib.error

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    LLM_MAX_RETRIES,
    LLM_RETRY_DELAY_BASE,
    LLM_TEMPERATURE,
    LLM_SYSTEM_PROMPT,
    TRACKING_NUMBER_PATTERN,
)

logger = logging.getLogger(__name__)

EMPTY_RESULT = {"tracking_number": "", "items": []}
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ═══════════════════════════════════════════════════════════════════════════
# KNOWN COURIER PREFIXES (Indonesian + International)
# Based on actual resi format research
#
# KEY FORMATS:
#   J&T Express  : JX, JP, JO, JA, JB, JD, J + digits (12-13 chars)
#   Shopee Express: SPXID + digits (17 chars total)
#   JNE          : CGK, BDO, SUB, MES, PLM, PKU, PDG, SRG, ORI + digits
#                  Also PLMAA, TLKC, etc. (3-5 letters + digits, 15 chars)
#   SiCepat      : Pure 12-digit numbers (002xxx, 003xxx, 004xxx, 000xxx)
#   Anteraja     : 10 + digits (14 chars), or ANT prefix
#   Lion Parcel  : LP + digits
#   ID Express   : IDE + digits
# ═══════════════════════════════════════════════════════════════════════════
COURIER_PREFIXES = [
    # ── Shopee Express / SPX (17 chars) ───────────────────────────────
    "SPXID",   # e.g. SPXID042116879123
    "SPX",
    "SPXS",

    # ── J&T Express (12-13 chars) ─────────────────────────────────────
    "JX",      # e.g. JX0428252887 (utama)
    "JP",      # e.g. JP5034350637
    "JO",      # e.g. JO1234567890
    "JA",      # e.g. JA1234567890
    "JB",      # e.g. JB0033526964
    "JD",      # e.g. JD0393631234
    "JT",      # e.g. JTE1234567890
    "JNT",

    # ── JNE (13-15 chars, starts with city/hub code) ──────────────────
    "PLMAA", "TLKC", "CGKC", "BDOC", "SUBC",  # 5-char hub codes
    "JNE",
    "CGK",     # Jakarta
    "BDO",     # Bandung
    "SUB",     # Surabaya
    "MES",     # Medan
    "PLM",     # Palembang
    "PKU",     # Pekanbaru
    "PDG",     # Padang
    "SRG",     # Semarang
    "SOC",     # Solo
    "JOG",     # Jogja
    "DPS",     # Bali/Denpasar
    "UPG",     # Makassar/Ujung Pandang
    "BPN",     # Balikpapan
    "MDC",     # Manado
    "BTH",     # Batam
    "ORI",     # Origin

    # ── SiCepat (pure 12-digit, starts with 00x) ─────────────────────
    "SCP", "SICEPAT",
    # Note: SiCepat is mostly digits like 004312059123 — handled separately

    # ── Anteraja ──────────────────────────────────────────────────────
    "ANT", "ANTE",
    # Note: Anteraja can be 10 + 12 digits = 14 chars

    # ── ID Express ────────────────────────────────────────────────────
    "IDE", "IDEX",

    # ── Ninja Van / Ninja Xpress ──────────────────────────────────────
    "NJVN", "NV", "NINJA",

    # ── Lion Parcel ───────────────────────────────────────────────────
    "LP", "LION",

    # ── SAP Express ───────────────────────────────────────────────────
    "SAP",

    # ── Rex Express ───────────────────────────────────────────────────
    "REX",

    # ── Pos Indonesia ─────────────────────────────────────────────────
    "POS",

    # ── Grab Express ──────────────────────────────────────────────────
    "GRAB",

    # ── TikTok / Tokopedia Logistics ──────────────────────────────────
    "TKLP", "TKP",

    # ── GoSend ────────────────────────────────────────────────────────
    "GS",

    # ── Wahana ────────────────────────────────────────────────────────
    "WAH", "WHN", "AGT",

    # ── TIKI ──────────────────────────────────────────────────────────
    "TIKI", "TK",

    # ── Paxel ─────────────────────────────────────────────────────────
    "PXL", "PAXEL",

    # ── DHL ───────────────────────────────────────────────────────────
    "DHL",

    # ── FedEx ─────────────────────────────────────────────────────────
    "FEDEX",

    # ── International ─────────────────────────────────────────────────
    "EMS", "RM", "CP", "LY", "RR",
]

# Sort by length descending so longer prefixes match first
COURIER_PREFIXES.sort(key=len, reverse=True)

# ── Digit-only resi patterns (SiCepat, JNE numeric, Anteraja) ─────────
# These couriers use pure-digit tracking numbers with specific formats
DIGIT_RESI_PATTERNS = [
    # SiCepat: 12 digits starting with 00x (002, 003, 004, 000)
    re.compile(r"^00[0-4]\d{9}$"),
    # Anteraja: starts with 10, 14 digits total
    re.compile(r"^10\d{12}$"),
    # JNE numeric: 15 digits (some JNE resi are all numbers)
    re.compile(r"^\d{15}$"),
]

# ═══════════════════════════════════════════════════════════════════════════
# CONTEXT CLUES — text near a tracking number vs order number
# ═══════════════════════════════════════════════════════════════════════════

# Words that appear NEAR a resi/tracking number
RESI_CONTEXT_WORDS = [
    "resi", "no resi", "no. resi", "nomor resi",
    "tracking", "tracking no", "tracking number",
    "awb", "no awb", "airway bill",
    "pengiriman", "no pengiriman",
    "barcode", "shipment",
    "[barcode]",  # injected by our barcode reader
    "jet.co.id", "j&t", "jnt",  # courier website/name near resi
]

# Words that appear NEAR an order number (NOT resi)
ORDER_CONTEXT_WORDS = [
    "pesanan", "no pesanan", "no. pesanan", "nomor pesanan",
    "order", "order id", "order no", "order number",
    "tt order", "tt order id",  # Tokopedia TT Order Id
    "invoice", "inv", "no invoice",
    "transaksi", "no transaksi",
    "pembelian", "no pembelian",
    "package id",  # Tokopedia Package ID
]

# ═══════════════════════════════════════════════════════════════════════════
# PATTERNS TO EXCLUDE (these look alphanumeric but are NOT resi numbers)
# ═══════════════════════════════════════════════════════════════════════════

# Marketplace order number patterns
ORDER_PATTERNS = [
    # Shopee order: starts with date digits, e.g. "241231ABCDEF1234"
    re.compile(r"^\d{6}[A-Z0-9]{6,12}$"),
    # Tokopedia INV format
    re.compile(r"^INV\d+$", re.IGNORECASE),
    # Common date-based IDs
    re.compile(r"^20\d{10,16}$"),  # Starts with year like 2024...
]

# Phone number patterns (NOT tracking numbers!)
PHONE_PATTERNS = [
    re.compile(r"^62\d{8,13}$"),     # +62 Indonesia (without +)
    re.compile(r"^08\d{8,13}$"),     # 08xx local format
    re.compile(r"^0\d{9,12}$"),      # 0xxx landline
    re.compile(r"^62[Ss]\d{7,12}$"), # OCR misread: 62s... (s instead of 8)
]

# Pure digit strings that are too long (Order IDs, Package IDs)
LONG_DIGIT_PATTERN = re.compile(r"^\d{16,}$")  # 16+ digits = not a resi


# ═══════════════════════════════════════════════════════════════════════════
# RULE-BASED PARSER
# ═══════════════════════════════════════════════════════════════════════════

def parse_ocr_text_rules(ocr_text: str) -> dict:
    """
    Extract tracking number and items using context-aware rules.
    No API call needed.
    """
    if not ocr_text or not ocr_text.strip():
        return EMPTY_RESULT.copy()

    result = EMPTY_RESULT.copy()
    text_upper = ocr_text.upper()

    # ── Step 1: Find ALL alphanumeric candidates ──────────────────────
    words = re.findall(r"[A-Za-z0-9]+", ocr_text)
    candidates = []

    for word in words:
        cleaned = word.upper().strip()
        if TRACKING_NUMBER_PATTERN.match(cleaned):
            # Check it's not an excluded pattern (order number)
            if _is_order_number(cleaned):
                logger.debug(f"Excluded order number pattern: {cleaned}")
                continue
            candidates.append(cleaned)

    if not candidates:
        logger.debug("No tracking number candidates found")
        result["items"] = _extract_items_rules(ocr_text)
        return result

    # ── Step 2: Score each candidate ──────────────────────────────────
    scored = []
    for candidate in candidates:
        score = _score_tracking_candidate(candidate, ocr_text)
        scored.append((candidate, score))
        logger.debug(f"Candidate '{candidate}' → score {score}")

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    best_candidate, best_score = scored[0]

    # Only accept if score is positive (has at least some evidence)
    if best_score > 0:
        result["tracking_number"] = best_candidate
        logger.info(
            f"Rule-based: selected '{best_candidate}' (score={best_score}, "
            f"{len(candidates)} candidates)"
        )
    else:
        # All candidates have score 0 or negative — ambiguous
        # Still pick it if there's a known prefix match
        for candidate, score in scored:
            if _has_courier_prefix(candidate):
                result["tracking_number"] = candidate
                logger.info(f"Rule-based: selected '{candidate}' via prefix match")
                break

    # ── Step 3: Extract items ─────────────────────────────────────────
    result["items"] = _extract_items_rules(ocr_text)

    return result


def _score_tracking_candidate(candidate: str, full_text: str) -> int:
    """
    Score how likely a candidate is to be a resi/tracking number.

    Higher score = more likely to be a resi number.
    Negative score = likely an order number.
    """
    score = 0
    text_lower = full_text.lower()

    # ── Courier prefix bonus (+100) ───────────────────────────────────
    if _has_courier_prefix(candidate):
        score += 100

    # ── Digit-only resi pattern bonus (+80) ───────────────────────────
    # SiCepat, Anteraja, JNE numeric have pure-digit resi numbers
    if _is_digit_resi(candidate):
        score += 80

    # ── Length bonus (prefer 12-16 char range, typical for resi) ──────
    length = len(candidate)
    if 12 <= length <= 16:
        score += 20
    elif 10 <= length <= 18:
        score += 10

    # ── Context: near "resi" words (+50 each) ─────────────────────────
    candidate_pos = text_lower.find(candidate.lower())
    if candidate_pos >= 0:
        # Look at surrounding text (200 chars before and after)
        context_start = max(0, candidate_pos - 200)
        context_end = min(len(text_lower), candidate_pos + len(candidate) + 200)
        context = text_lower[context_start:context_end]

        for resi_word in RESI_CONTEXT_WORDS:
            if resi_word in context:
                score += 50
                logger.debug(f"  +50 context match: '{resi_word}'")
                break  # One context bonus is enough

        # ── Context: near "pesanan/order" words (-80 each) ────────────
        for order_word in ORDER_CONTEXT_WORDS:
            if order_word in context:
                score -= 80
                logger.debug(f"  -80 order context: '{order_word}'")
                break

    # ── Has mixed letters+digits (+15, typical for resi) ──────────────
    has_letters = any(c.isalpha() for c in candidate)
    has_digits = any(c.isdigit() for c in candidate)
    if has_letters and has_digits:
        score += 15

    # ── All digits & not a known digit resi (-20) ─────────────────────
    if candidate.isdigit() and not _is_digit_resi(candidate):
        score -= 20

    return score


def _has_courier_prefix(candidate: str) -> bool:
    """Check if candidate starts with a known courier prefix."""
    upper = candidate.upper()
    for prefix in COURIER_PREFIXES:
        if upper.startswith(prefix):
            return True
    return False


def _is_digit_resi(candidate: str) -> bool:
    """Check if a pure-digit candidate matches known digit-only resi patterns."""
    if not candidate.isdigit():
        return False
    for pattern in DIGIT_RESI_PATTERNS:
        if pattern.match(candidate):
            return True
    return False


def _is_order_number(candidate: str) -> bool:
    """Check if candidate matches known order/phone/excluded patterns."""
    # Order number patterns
    for pattern in ORDER_PATTERNS:
        if pattern.match(candidate):
            return True
    # Phone number patterns
    for pattern in PHONE_PATTERNS:
        if pattern.match(candidate):
            return True
    # Long pure digit strings (Order ID, Package ID)
    if LONG_DIGIT_PATTERN.match(candidate):
        return True
    return False


# ── Item extraction ───────────────────────────────────────────────────────

# J&T label: "Jumlah : 1pcs, Barang : 8 cm, Putih"
# OCR often misreads "pcs" as "pes", "pce", "pss", etc.
# Variant is typically short (e.g. "8 cm, Putih", "Default", "XL, Hitam")
# Stop before keywords that indicate end of variant section
JNT_BARANG_PATTERN = re.compile(
    r"[Jj]umlah\s*[:\s]+(\d+)\s*(?:p[cesCES]{2}|pcs|PCS)?\s*[,.]?\s*"
    r"[Bb]arang\s*[:\s]+(.+?)(?=\s+(?:Order|PERUM|KAPASAN|Product|SKU|Qty|In\s+transit|\d{10,}|[A-Z]{5,}\s+[A-Z]{5,})|\n|$)",
    re.IGNORECASE
)

# SKU-like code pattern: alphanumeric with dashes/dots (e.g. DSM-8cm-100pcs, ABC-XL-RED)
# Must contain at least one dash or dot, AND at least one digit
SKU_CODE_PATTERN = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+){1,})\b"
)

# Address component patterns (NOT SKUs!)
# Rt.04, Rw.026, km.1, No.A6, Jl.Raya, Gg.3
ADDRESS_PREFIXES = re.compile(
    r"^(Rt|Rw|RT|RW|km|KM|No|NO|Jl|JL|Gg|GG|Ds|DS|Kp|KP)[._]",
    re.IGNORECASE
)

def _is_valid_sku(sku: str) -> bool:
    """Check if a candidate is likely a real SKU code."""
    # Must have at least one digit (DSM-8cm-100pcs has digits, WATES-NGA doesn't)
    if not any(c.isdigit() for c in sku):
        return False
    # Must be at least 5 chars (short codes like km.1 are addresses)
    if len(sku) < 5:
        return False
    # Skip address components (Rt.04, Rw.026, km.1, etc.)
    if ADDRESS_PREFIXES.match(sku):
        return False
    # Check word blacklist (check each part separated by -._)
    parts = re.split(r"[-_.]", sku.lower())
    if any(part in SKU_BLACKLIST for part in parts):
        return False
    # Skip sorting codes like 550-NGA23A-89A
    if re.match(r"^\d{3}-[A-Z]{3}", sku):
        return False
    # Skip short sorting codes like b2-I7, A3-K9 (all segments ≤ 2 chars)
    if all(len(p) <= 2 for p in parts):
        return False
    # Skip 2-part codes that look like sorting codes (e.g. B2-17, C1-A5)
    if len(parts) == 2 and len(sku) <= 6:
        return False
    # Skip patterns that look like "word.digits" (e.g. pos.6815atas, post.17611)
    if re.match(r"^[a-zA-Z]{2,}\.[0-9]+[a-zA-Z]*$", sku):
        return False
    # Skip NO/No/n0/N0 + digits (OCR of "No.16" etc, e.g. NO15C.c, n0.16)
    if re.match(r"^[Nn][Oo0]\d", sku) or re.match(r"^[Nn][Oo0][._]", sku):
        return False
    # Skip codes with single-char dot segments (e.g. NO15C.c, ref.A)
    if re.search(r"\.[a-zA-Z]$", sku) and len(sku.split(".")[-1]) <= 2:
        return False
    # Skip if first part is a common Indonesian word (not a brand code)
    first_part = parts[0] if parts else ""
    if len(first_part) >= 3 and first_part.isalpha() and first_part not in ("dsm", "kd"):
        # Check if it looks like a regular word rather than a code
        if not any(c.isdigit() for c in first_part) and first_part in _COMMON_WORDS:
            return False
    return True

# Common Indonesian words that OCR might combine with numbers
_COMMON_WORDS = {
    "pos", "pesanan", "pesan", "atas", "bawah", "dari", "untuk", "yang",
    "kirim", "terima", "paket", "barang", "nomor", "alamat", "nama",
    "berat", "batas", "tanggal", "estimasi", "pengiriman", "penerima",
    "pengirim", "produk", "total", "harga", "biaya", "ongkir",
    "cod", "home", "eco", "std", "reg", "yes", "oke",
    "hub", "via", "ref", "info", "note", "add", "new",
}

# Variasi / Variant field 
VARIASI_PATTERN = re.compile(
    r"[Vv]aria(?:si|nt)\s*[:\s]+(.+?)(?:\n|Qty|$)",
    re.IGNORECASE
)

# Qty with a number (matches "Qty 1", "Qty: 2", "Qty Total: 1")
QTY_PATTERN = re.compile(r"\bQty\b[:\s]*(\d+)", re.IGNORECASE)
QTY_TOTAL_PATTERN = re.compile(r"Qty\s+Total\s*[:\s]*(\d+)", re.IGNORECASE)

# Words to EXCLUDE from SKU matching (these look like SKU codes but aren't)
SKU_BLACKLIST = {
    "seller", "sku", "qty", "total", "product", "name", "order",
    "package", "weight", "ship", "estimated", "transit", "tokopedia",
    "shopee", "express", "cashless", "cod", "barang",
    "in", "by", "the", "and", "for", "from", "with",
    "penerima", "pengirim", "perum", "jawa",
    # Address words
    "rt", "rw", "km", "jl", "gg", "ds", "kp", "no",
    "desa", "kota", "kec", "kab", "kel",
    # Common false positives from OCR
    "pos", "pesanan", "pesan", "atas", "bawah",
    "kirim", "terima", "paket", "nomor", "alamat",
    "berat", "batas", "estimasi", "pengiriman",
    "produk", "harga", "biaya", "ongkir",
}

# Legacy patterns (generic labels)
ITEM_QTY_PATTERNS = [
    re.compile(r"(\d+)\s*[xX]\s+(.+?)(?:\n|$)", re.MULTILINE),
    re.compile(r"(.+?)\s*[xX]\s*(\d+)(?:\n|$)", re.MULTILINE),
]


def _extract_items_rules(ocr_text: str) -> list:
    """
    Extract items from OCR text using multiple strategies optimized
    for Indonesian e-commerce shipping labels (Tokopedia, Shopee, J&T, JNE).
    
    Priority:
      1. SKU code pattern   (finds DSM-8cm-100pcs style codes — most reliable)
      2. J&T Barang format  (fallback: free-form variant text from label)
      3. Variasi field
      4. Legacy regex
    """
    items = []

    # Get all Qty values for pairing later
    qty_matches = QTY_PATTERN.findall(ocr_text)
    qty_total_match = QTY_TOTAL_PATTERN.search(ocr_text)

    # ── Strategy 1: Find SKU-like codes (DSM-8cm-100pcs, etc.) ────────
    sku_candidates = SKU_CODE_PATTERN.findall(ocr_text)
    if sku_candidates:
        valid_skus = [sku for sku in sku_candidates if _is_valid_sku(sku)]

        if valid_skus:
            for sku in valid_skus:
                qty = _find_qty_near_sku(sku, ocr_text, qty_matches, qty_total_match)
                items.append({"variant": sku, "quantity": max(qty, 1)})

            if items:
                logger.info(f"Extracted {len(items)} item(s) via SKU codes: "
                           f"{[(i['variant'], i['quantity']) for i in items]}")
                return items

    # ── Strategy 2: J&T "Barang" format (fallback) ────────────────────
    jnt_match = JNT_BARANG_PATTERN.search(ocr_text)
    if jnt_match:
        qty = int(jnt_match.group(1))
        variant = jnt_match.group(2).strip().rstrip(",. ")
        if variant and len(variant) >= 2:
            items.append({"variant": variant, "quantity": max(qty, 1)})
            logger.info(f"Extracted item via J&T Barang: '{variant}' x{qty}")
            return items

    # ── Strategy 3: Variasi field ─────────────────────────────────────
    variasi_match = VARIASI_PATTERN.search(ocr_text)
    if variasi_match:
        variant = variasi_match.group(1).strip().rstrip(",. ")
        qty = 1
        per_item_qty = _get_per_item_qty(qty_matches, qty_total_match)
        if per_item_qty:
            qty = per_item_qty[0]
        if variant and len(variant) >= 2:
            items.append({"variant": variant, "quantity": max(qty, 1)})
            logger.info(f"Extracted item via Variasi: '{variant}' x{qty}")
            return items

    # ── Strategy 4: Legacy regex patterns ─────────────────────────────
    seen = set()
    for pattern in ITEM_QTY_PATTERNS:
        for match in pattern.finditer(ocr_text):
            groups = match.groups()
            if groups[0].strip().isdigit():
                qty_str, variant = groups[0], groups[1]
            else:
                variant, qty_str = groups[0], groups[1]

            variant = variant.strip()
            if not variant or len(variant) < 2:
                continue

            try:
                qty = int(qty_str)
            except ValueError:
                qty = 1

            key = variant.lower()
            if key not in seen:
                seen.add(key)
                items.append({"variant": variant, "quantity": max(qty, 1)})

    if items:
        logger.info(f"Extracted {len(items)} item(s) via legacy patterns")

    return items


def _find_qty_near_sku(sku: str, ocr_text: str, qty_matches: list, qty_total_match) -> int:
    """
    Find the quantity for a given SKU by looking at the text near it.

    Strategy:
      1. Look for a standalone number (1-3 digits) within 30 chars after the SKU
      2. Fall back to Qty keyword matches
    """
    # Find the SKU in the text
    sku_pos = ocr_text.find(sku)
    if sku_pos >= 0:
        # Look at text right after the SKU (up to 30 chars)
        after_sku = ocr_text[sku_pos + len(sku):sku_pos + len(sku) + 30]
        # Find a standalone number (1-3 digits, not part of a larger number)
        qty_nearby = re.search(r"(?:^|\s)(\d{1,3})(?:\s|$|[,.])", after_sku)
        if qty_nearby:
            qty = int(qty_nearby.group(1))
            if 1 <= qty <= 999:
                logger.debug(f"Found qty {qty} near SKU '{sku}'")
                return qty

    # Fall back to Qty keyword matches
    per_item_qty = _get_per_item_qty(qty_matches, qty_total_match)
    if per_item_qty:
        return per_item_qty[0]

    return 1


def _get_per_item_qty(qty_matches: list, qty_total_match) -> list:
    """Extract per-item quantities, excluding Qty Total."""
    if not qty_matches:
        return []

    qtys = [int(q) for q in qty_matches]

    # Remove Qty Total value if present
    if qty_total_match:
        total_val = int(qty_total_match.group(1))
        # Remove last occurrence of total_val (Qty Total usually appears last)
        for i in range(len(qtys) - 1, -1, -1):
            if qtys[i] == total_val:
                qtys.pop(i)
                break

    return qtys


# ═══════════════════════════════════════════════════════════════════════════
# AI-ENHANCED PARSER (optional)
# ═══════════════════════════════════════════════════════════════════════════

def parse_ocr_text_ai(ocr_text: str) -> dict:
    """Send OCR text to OpenRouter LLM. Falls back to rule-based on failure."""
    if not ocr_text or not ocr_text.strip():
        return EMPTY_RESULT.copy()

    if not OPENROUTER_API_KEY:
        return parse_ocr_text_rules(ocr_text)

    prompt = (
        f"Extract the tracking number and items from this OCR text:\n\n"
        f"---\n{ocr_text}\n---"
    )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": LLM_TEMPERATURE,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "ShipExtract OCR",
    }

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                OPENROUTER_URL, data=data, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                response_body = json.loads(resp.read().decode("utf-8"))

            choices = response_body.get("choices", [])
            if not choices:
                continue

            content = choices[0].get("message", {}).get("content", "")
            if not content:
                continue

            parsed = json.loads(content)
            result = _validate_and_clean(parsed)

            logger.info(
                f"AI extracted: tracking='{result['tracking_number']}', "
                f"items={len(result['items'])}"
            )
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON from LLM (attempt {attempt}): {e}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.warning(f"HTTP {e.code} from OpenRouter (attempt {attempt}): {body}")
        except Exception as e:
            logger.warning(f"LLM call failed (attempt {attempt}): {e}")

        if attempt < LLM_MAX_RETRIES:
            delay = LLM_RETRY_DELAY_BASE ** attempt
            logger.info(f"Retrying in {delay}s...")
            time.sleep(delay)

    logger.warning("AI failed, falling back to rule-based parser")
    return parse_ocr_text_rules(ocr_text)


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def parse_ocr_text(ocr_text: str) -> dict:
    """Main entry point. Uses AI if key available, otherwise rule-based."""
    if OPENROUTER_API_KEY:
        return parse_ocr_text_ai(ocr_text)
    else:
        return parse_ocr_text_rules(ocr_text)


def _validate_and_clean(parsed: dict) -> dict:
    """Validate and sanitize LLM output."""
    result = EMPTY_RESULT.copy()

    raw_tracking = parsed.get("tracking_number", "")
    if isinstance(raw_tracking, str):
        result["tracking_number"] = raw_tracking.strip()

    raw_items = parsed.get("items", [])
    if isinstance(raw_items, list):
        clean_items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            variant = item.get("variant", "")
            quantity = item.get("quantity", 0)
            if not isinstance(variant, str) or not variant.strip():
                continue
            try:
                quantity = int(quantity)
            except (ValueError, TypeError):
                quantity = 0
            if quantity < 0:
                quantity = 0
            clean_items.append({"variant": variant.strip(), "quantity": quantity})
        result["items"] = clean_items

    return result
