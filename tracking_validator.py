"""
Tracking Number Validator — strict rule-based validation engine.

Rules:
  - Uppercase only (A-Z, 0-9)
  - Length between 10 and 18 characters
  - OCR confidence must meet threshold
  - NEVER accepts low-confidence tracking numbers

Returns a ValidationResult with status: VALID, NEEDS_REVIEW, or INVALID.
"""
import logging
from dataclasses import dataclass
from enum import Enum

from config import (
    TRACKING_NUMBER_PATTERN,
    TRACKING_MIN_LENGTH,
    TRACKING_MAX_LENGTH,
    TRACKING_CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    """Possible tracking number validation outcomes."""
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    INVALID = "invalid"


@dataclass
class ValidationResult:
    """Result of tracking number validation."""
    status: ValidationStatus
    tracking_number: str
    confidence: float
    reason: str


def validate_tracking_number(
    candidate: str,
    ocr_confidence: float,
) -> ValidationResult:
    """
    Validate a tracking number candidate against strict rules.

    Args:
        candidate: The raw tracking number string from LLM output.
        ocr_confidence: OCR confidence for this word/region (0-100).

    Returns:
        ValidationResult indicating VALID, NEEDS_REVIEW, or INVALID.
    """
    if not candidate or not candidate.strip():
        return ValidationResult(
            status=ValidationStatus.INVALID,
            tracking_number="",
            confidence=0.0,
            reason="Empty tracking number",
        )

    # Normalize: strip whitespace, uppercase
    cleaned = candidate.strip().upper()

    # ── Length check ──────────────────────────────────────────────────
    if len(cleaned) < TRACKING_MIN_LENGTH:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            tracking_number=cleaned,
            confidence=ocr_confidence,
            reason=f"Too short ({len(cleaned)} chars, min {TRACKING_MIN_LENGTH})",
        )

    if len(cleaned) > TRACKING_MAX_LENGTH:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            tracking_number=cleaned,
            confidence=ocr_confidence,
            reason=f"Too long ({len(cleaned)} chars, max {TRACKING_MAX_LENGTH})",
        )

    # ── Regex check (A-Z, 0-9 only) ──────────────────────────────────
    if not TRACKING_NUMBER_PATTERN.match(cleaned):
        return ValidationResult(
            status=ValidationStatus.INVALID,
            tracking_number=cleaned,
            confidence=ocr_confidence,
            reason="Contains invalid characters (must be A-Z, 0-9 only)",
        )

    # ── OCR confidence check ──────────────────────────────────────────
    if ocr_confidence < TRACKING_CONFIDENCE_THRESHOLD:
        logger.warning(
            f"Tracking '{cleaned}' has low OCR confidence: "
            f"{ocr_confidence:.1f}% (threshold: {TRACKING_CONFIDENCE_THRESHOLD}%)"
        )
        return ValidationResult(
            status=ValidationStatus.NEEDS_REVIEW,
            tracking_number=cleaned,
            confidence=ocr_confidence,
            reason=(
                f"Low OCR confidence ({ocr_confidence:.1f}%, "
                f"threshold {TRACKING_CONFIDENCE_THRESHOLD}%)"
            ),
        )

    # ── All checks passed ─────────────────────────────────────────────
    logger.info(f"Tracking '{cleaned}' validated (confidence: {ocr_confidence:.1f}%)")
    return ValidationResult(
        status=ValidationStatus.VALID,
        tracking_number=cleaned,
        confidence=ocr_confidence,
        reason="All checks passed",
    )
