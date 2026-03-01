"""
Central configuration for the OCR Shipment Extraction pipeline.
"""
import os
import re
import platform
from dotenv import load_dotenv

load_dotenv()

# ── Tesseract ──────────────────────────────────────────────────────────────
# Auto-detect: Linux (Railway/Docker) vs Windows
_default_tesseract = (
    "/usr/bin/tesseract" if platform.system() != "Windows"
    else r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
TESSERACT_CMD = os.getenv("TESSERACT_CMD", _default_tesseract)

# ── PDF Splitting ──────────────────────────────────────────────────────────
PDF_DPI = 300  # Resolution for page-to-image conversion

# ── Image Preprocessing ───────────────────────────────────────────────────
GAUSSIAN_KERNEL_SIZE = (5, 5)
ADAPTIVE_THRESH_BLOCK_SIZE = 11
ADAPTIVE_THRESH_C = 2

# ── OCR Confidence ─────────────────────────────────────────────────────────
OCR_CONFIDENCE_THRESHOLD = 60  # Minimum average word confidence (0-100)
TRACKING_CONFIDENCE_THRESHOLD = 70  # Stricter for tracking numbers

# ── Tracking Number Validation ─────────────────────────────────────────────
TRACKING_NUMBER_PATTERN = re.compile(r"^[A-Z0-9]{10,18}$")
TRACKING_MIN_LENGTH = 10
TRACKING_MAX_LENGTH = 18

# ── LLM (OpenRouter) ──────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "google/gemini-2.0-flash-exp:free",  # Best free model for JSON extraction
)
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY_BASE = 2  # seconds (exponential backoff)
LLM_TEMPERATURE = 0.0  # Deterministic output

# ── Output ─────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_FILE = "shipments.json"
MANUAL_REVIEW_FILE = "manual_review.json"

# ── System Prompt for LLM ─────────────────────────────────────────────────
LLM_SYSTEM_PROMPT = """\
You are a precise data extraction assistant. You will receive raw OCR text 
from a shipment label page. Your task is to extract:

1. tracking_number: The shipment tracking number found on the page.
   - It is typically a prominent alphanumeric code (10-18 characters, uppercase).
   - If you cannot find a clear tracking number, return an EMPTY string "".
   - NEVER guess or fabricate a tracking number.

2. items: A list of product items found on the page.
   - Each item has a "variant" (product description/name) and "quantity" (integer).
   - If no items are found, return an empty list [].
   - NEVER guess missing data.

Return ONLY valid JSON in this exact format:
{
  "tracking_number": "",
  "items": [
    {"variant": "", "quantity": 0}
  ]
}

Rules:
- Output MUST be valid JSON, nothing else.
- Do NOT add any explanation, comments, or markdown.
- If unsure about any value, omit it or use empty string / 0.
- tracking_number must contain ONLY uppercase letters A-Z and digits 0-9.
"""
