"""
OCR Engine — runs Tesseract OCR + barcode detection.

Combines:
  1. Tesseract OCR for text with per-word confidence
  2. pyzbar for barcode/QR code reading (more reliable for tracking numbers)

Dual-pass approach:
  - Barcode reading on the ORIGINAL image (not preprocessed) for best results
  - Tesseract OCR on the PREPROCESSED image for best text recognition
"""
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

import numpy as np
import cv2
import pytesseract

from config import TESSERACT_CMD, OCR_CONFIDENCE_THRESHOLD

try:
    from pyzbar.pyzbar import decode as decode_barcodes
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    """Result of OCR + barcode detection on a single page."""
    full_text: str
    avg_confidence: float
    word_confidences: List[Tuple[str, float]] = field(default_factory=list)
    barcodes: List[str] = field(default_factory=list)
    is_low_confidence: bool = False
    is_mostly_empty: bool = False


def run_ocr(
    image: np.ndarray,
    original_image: Optional[np.ndarray] = None,
    min_text_length: int = 10,
) -> OcrResult:
    """
    Run Tesseract OCR + barcode detection.

    Args:
        image: Preprocessed grayscale/binary image for OCR.
        original_image: Original (non-preprocessed) image for barcode reading.
                        If None, uses the preprocessed image for barcodes too.
        min_text_length: If OCR text is shorter than this, page is "mostly empty".

    Returns:
        OcrResult with full text, confidences, barcodes, and quality flags.
    """
    # ── Barcode detection (on ORIGINAL for best results) ──────────────
    barcode_source = original_image if original_image is not None else image
    barcodes = _detect_barcodes(barcode_source)

    # Also try on preprocessed if original didn't find any
    if not barcodes and original_image is not None:
        barcodes = _detect_barcodes(image)

    # Also try with different thresholding for barcodes
    if not barcodes and original_image is not None:
        barcodes = _detect_barcodes_enhanced(original_image)

    if barcodes:
        logger.info(f"Found {len(barcodes)} barcode(s): {barcodes}")

    # ── Tesseract OCR (on preprocessed image) ─────────────────────────
    try:
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",
        )
    except Exception as e:
        logger.error(f"Tesseract OCR failed: {e}")
        return OcrResult(
            full_text="",
            avg_confidence=0.0,
            barcodes=barcodes,
            is_low_confidence=True,
            is_mostly_empty=True,
        )

    word_confidences = []
    words = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if text:
            conf = float(data["conf"][i])
            if conf >= 0:
                word_confidences.append((text, conf))
                words.append(text)

    full_text = " ".join(words)

    # Append barcode data to OCR text with high confidence
    if barcodes:
        barcode_text = "\n".join(f"[BARCODE] {bc}" for bc in barcodes)
        full_text = full_text + "\n" + barcode_text
        for bc in barcodes:
            word_confidences.append((bc, 99.0))

    if word_confidences:
        avg_conf = sum(c for _, c in word_confidences) / len(word_confidences)
    else:
        avg_conf = 0.0

    is_empty = len(full_text.strip()) < min_text_length
    is_low = avg_conf < OCR_CONFIDENCE_THRESHOLD

    return OcrResult(
        full_text=full_text,
        avg_confidence=avg_conf,
        word_confidences=word_confidences,
        barcodes=barcodes,
        is_low_confidence=is_low,
        is_mostly_empty=is_empty,
    )


def _detect_barcodes(image: np.ndarray) -> List[str]:
    """Detect and decode barcodes/QR codes from the image."""
    if not HAS_PYZBAR:
        return []

    try:
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        results = decode_barcodes(gray)

        decoded = []
        for result in results:
            text = result.data.decode("utf-8", errors="replace").strip()
            if text and len(text) >= 8:
                decoded.append(text)
                logger.debug(f"Barcode [{result.type}]: '{text}'")

        return decoded

    except Exception as e:
        logger.warning(f"Barcode detection failed: {e}")
        return []


def _detect_barcodes_enhanced(image: np.ndarray) -> List[str]:
    """
    Enhanced barcode detection with multiple image processing attempts.
    Tries different thresholding and scaling to read difficult barcodes.
    """
    if not HAS_PYZBAR:
        return []

    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        # Attempt 1: Binary threshold (Otsu)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        results = decode_barcodes(binary)
        if results:
            return [r.data.decode("utf-8", errors="replace").strip()
                    for r in results if len(r.data) >= 8]

        # Attempt 2: Inverted binary
        results = decode_barcodes(255 - binary)
        if results:
            return [r.data.decode("utf-8", errors="replace").strip()
                    for r in results if len(r.data) >= 8]

        # Attempt 3: Sharpened image
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(gray, -1, kernel)
        results = decode_barcodes(sharpened)
        if results:
            return [r.data.decode("utf-8", errors="replace").strip()
                    for r in results if len(r.data) >= 8]

        return []

    except Exception as e:
        logger.debug(f"Enhanced barcode detection failed: {e}")
        return []


def get_word_confidence(ocr_result: OcrResult, target_word: str) -> float:
    """
    Find the OCR confidence for a specific word.
    Returns 99.0 if the word was from a barcode.
    """
    target_upper = target_word.upper()
    for bc in ocr_result.barcodes:
        if bc.upper() == target_upper:
            return 99.0

    confidences = [
        conf
        for word, conf in ocr_result.word_confidences
        if word.upper() == target_upper
    ]
    return max(confidences) if confidences else 0.0
