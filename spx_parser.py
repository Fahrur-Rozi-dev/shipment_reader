"""
SPX Parser — Extracts shipment data from Shopee Express (SPX) shipping labels.

SPX Label Format:
  - Resi: SPXID + digits (17 chars), appears as "Resi:SPXID060123539222"
  - Items in table: # | Nama Produk | SKU | Variasi | Qty
  - SKU format: DSM-8cm-100pcs (same as J&T)
"""
import re
import logging

logger = logging.getLogger(__name__)

EMPTY_RESULT = {"tracking_number": "", "items": []}

# ── Tracking Number ───────────────────────────────────────────────────────
# SPX resi format: SPXID + 12 digits = 17 chars total
# Often appears as "Resi:SPXID060123539222" or just repeated in text
SPX_RESI_PATTERN = re.compile(r"SPX(?:ID|S)?\d{10,14}", re.IGNORECASE)

# Also check for "Resi:" label
RESI_LABEL_PATTERN = re.compile(
    r"[Rr]esi\s*[:\s]+([A-Z0-9]{10,20})",
    re.IGNORECASE
)

# ── Item Extraction ───────────────────────────────────────────────────────
# SKU code pattern (same as J&T: DSM-8cm-100pcs)
SKU_CODE_PATTERN = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+){1,})\b"
)

# Address prefixes to exclude
ADDRESS_PREFIXES = re.compile(
    r"^(Rt|Rw|RT|RW|km|KM|No|NO|Jl|JL|Gg|GG|Ds|DS|Kp|KP)[._]",
    re.IGNORECASE
)

# Qty pattern - look for Qty column value
QTY_PATTERN = re.compile(r"\bQty\b[:\s]*(\d+)", re.IGNORECASE)
QTY_TOTAL_PATTERN = re.compile(r"Qty\s+Total\s*[:\s]*(\d+)", re.IGNORECASE)

# Blacklist — words that look like SKUs but aren't
SKU_BLACKLIST = {
    "seller", "sku", "qty", "total", "product", "name", "order",
    "package", "weight", "ship", "estimated", "transit", "tokopedia",
    "shopee", "express", "cashless", "cod", "barang", "variasi",
    "in", "by", "the", "and", "for", "from", "with",
    "penerima", "pengirim", "perum", "jawa", "tengah", "barat", "timur",
    "rt", "rw", "km", "jl", "gg", "ds", "kp", "no",
    "desa", "kota", "kec", "kab", "kel",
    "home", "eco", "std", "cod",
    "tru", "tru-a", "by-65",  # SPX sorting codes
}


def _is_valid_sku(sku: str) -> bool:
    """Check if a candidate is likely a real SKU code."""
    if not any(c.isdigit() for c in sku):
        return False
    if len(sku) < 5:
        return False
    if ADDRESS_PREFIXES.match(sku):
        return False
    # Check word blacklist
    parts = re.split(r"[-_.]", sku.lower())
    if any(part in SKU_BLACKLIST for part in parts):
        return False
    # Skip sorting codes like TRU-A-05, BY-65
    if re.match(r"^[A-Z]{2,4}-[A-Z]-\d{1,2}$", sku):
        return False
    # Skip SPX resi numbers
    if sku.upper().startswith("SPX"):
        return False
    return True


def _find_qty_near_sku(sku: str, ocr_text: str) -> int:
    """Find qty number appearing near the SKU in text."""
    sku_pos = ocr_text.find(sku)
    if sku_pos >= 0:
        # Look at text after SKU (up to 50 chars for SPX table format)
        after_sku = ocr_text[sku_pos + len(sku):sku_pos + len(sku) + 50]
        qty_nearby = re.search(r"(?:^|\s)(\d{1,3})(?:\s|$|[,.])", after_sku)
        if qty_nearby:
            qty = int(qty_nearby.group(1))
            if 1 <= qty <= 999:
                return qty
    return 1


def parse_spx_text(ocr_text: str) -> dict:
    """
    Parse OCR text from an SPX (Shopee Express) shipping label.

    Returns:
        dict with 'tracking_number' and 'items' list
    """
    if not ocr_text or len(ocr_text.strip()) < 10:
        return EMPTY_RESULT

    result = {"tracking_number": "", "items": []}

    # ── Extract tracking number ───────────────────────────────────────
    # Strategy 1: Direct SPXID pattern match
    spx_matches = SPX_RESI_PATTERN.findall(ocr_text)
    if spx_matches:
        # Take the most common one (repeated many times on SPX labels)
        from collections import Counter
        counter = Counter(m.upper() for m in spx_matches)
        result["tracking_number"] = counter.most_common(1)[0][0]
        logger.info(f"SPX tracking found: {result['tracking_number']}")

    # Strategy 2: "Resi:" label
    if not result["tracking_number"]:
        resi_match = RESI_LABEL_PATTERN.search(ocr_text)
        if resi_match:
            candidate = resi_match.group(1).strip()
            if len(candidate) >= 10:
                result["tracking_number"] = candidate
                logger.info(f"SPX tracking via Resi label: {candidate}")

    # ── Extract items (SKU + Qty) ─────────────────────────────────────

    # Strategy 1: DSM split-SKU recovery
    # SPX labels often wrap SKU across lines:
    #   "DSM-8cm- 1 Cocok Untuk Produksi Siomay Dimsum 100pcs"
    # We need to find "DSM-Xcm-" and then look ahead for "\d+pcs"
    dsm_partial = re.search(
        r"(DSM[- ]?\d+\s*c?e?m)[- ]\s*",
        ocr_text, re.IGNORECASE
    )
    if dsm_partial:
        prefix = dsm_partial.group(1)  # e.g. "DSM-8cm"
        after_pos = dsm_partial.end()
        # Search ahead up to 150 chars for the pcs part
        ahead_text = ocr_text[after_pos:after_pos + 150]
        pcs_match = re.search(r"(\d+)\s*(?:p[cesCES]{2}|pcs|PCS)", ahead_text)
        if pcs_match:
            pcs_count = pcs_match.group(1)
            full_sku = f"{prefix}-{pcs_count}pcs"
            # Find qty: look for standalone digit right after "DSM-8cm-"
            qty_match = re.search(r"^\s*(\d{1,3})(?:\s|$)", ahead_text)
            qty = int(qty_match.group(1)) if qty_match else 1
            result["items"].append({"variant": full_sku, "quantity": max(qty, 1)})
            logger.info(f"SPX recovered split-SKU: '{full_sku}' x{qty}")

    # Strategy 2: Find complete SKU codes (DSM-8cm-100pcs in one piece)
    if not result["items"]:
        sku_candidates = SKU_CODE_PATTERN.findall(ocr_text)
        valid_skus = [sku for sku in sku_candidates if _is_valid_sku(sku)]

        if valid_skus:
            seen = set()
            for sku in valid_skus:
                if sku not in seen:
                    seen.add(sku)
                    qty = _find_qty_near_sku(sku, ocr_text)
                    result["items"].append({"variant": sku, "quantity": qty})

            logger.info(f"SPX items: {[(i['variant'], i['quantity']) for i in result['items']]}")

    # Fallback: if no items found, try Qty pattern alone
    if not result["items"]:
        qty_matches = QTY_PATTERN.findall(ocr_text)
        qty_total = QTY_TOTAL_PATTERN.search(ocr_text)
        if qty_matches:
            qty = int(qty_matches[0])
            if qty_total and int(qty_total.group(1)) == qty:
                pass  # Only total, no per-item
            result["items"].append({"variant": "-", "quantity": max(qty, 1)})

    return result
