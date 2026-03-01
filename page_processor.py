"""
Stateful Page Processor — the heart of the shipment extraction pipeline.

Maintains state across pages:
  - current_tracking_number
  - current_items
  - completed_shipments
  - manual_review queue

Decision logic per page:
  1. NEW valid tracking → save previous shipment, reset state
  2. No tracking → inherit previous, append items
  3. Empty page → skip
  4. NEEDS_REVIEW tracking → flag for manual review, do NOT auto-assign
"""
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from tracking_validator import (
    validate_tracking_number,
    ValidationStatus,
    ValidationResult,
)
from ocr_engine import OcrResult, get_word_confidence

logger = logging.getLogger(__name__)


@dataclass
class ManualReviewEntry:
    """A page flagged for manual review."""
    page_number: int
    reason: str
    ocr_text: str
    candidate_tracking: str = ""
    items: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "reason": self.reason,
            "candidate_tracking": self.candidate_tracking,
            "items": self.items,
            "ocr_text_preview": self.ocr_text[:300] if self.ocr_text else "",
        }


@dataclass
class Shipment:
    """A completed shipment with tracking number and items."""
    tracking_number: str
    items: List[Dict]
    page_range: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tracking_number": self.tracking_number,
            "items": self.items,
            "page_range": self.page_range,
        }


class PageProcessor:
    """
    Stateful processor that aggregates pages into shipments.

    Usage:
        processor = PageProcessor()
        for page_num, (llm_result, ocr_result) in enumerate(pages, 1):
            processor.process_page(page_num, llm_result, ocr_result)
        processor.finalize()
        shipments = processor.get_shipments()
        review = processor.get_manual_review()
    """

    def __init__(self):
        self._current_tracking: Optional[str] = None
        self._current_items: List[Dict] = []
        self._current_pages: List[int] = []
        self._shipments: List[Shipment] = []
        self._manual_review: List[ManualReviewEntry] = []
        self._page_count = 0

    def process_page(
        self,
        page_number: int,
        llm_result: dict,
        ocr_result: OcrResult,
    ) -> None:
        """
        Process a single page's extracted data.

        Args:
            page_number: 1-indexed page number.
            llm_result: Dict from llm_parser.parse_ocr_text().
            ocr_result: OcrResult from ocr_engine.run_ocr().
        """
        self._page_count += 1
        logger.info(f"── Processing page {page_number} ──")

        # ── Handle mostly-empty pages ─────────────────────────────────
        if ocr_result.is_mostly_empty and not llm_result.get("items"):
            logger.debug(f"Page {page_number}: mostly empty, skipping")
            if self._current_tracking:
                self._current_pages.append(page_number)
            return

        # ── Extract tracking number candidate from LLM output ─────────
        candidate_tracking = llm_result.get("tracking_number", "").strip()
        items = llm_result.get("items", [])

        # ── Validate tracking number ──────────────────────────────────
        if candidate_tracking:
            # Get OCR confidence for the tracking number
            tracking_confidence = self._get_tracking_confidence(
                candidate_tracking, ocr_result
            )

            validation = validate_tracking_number(
                candidate_tracking, tracking_confidence
            )

            if validation.status == ValidationStatus.VALID:
                self._handle_new_tracking(
                    page_number, validation.tracking_number, items
                )
                return

            elif validation.status == ValidationStatus.NEEDS_REVIEW:
                logger.warning(
                    f"Page {page_number}: tracking needs review — "
                    f"{validation.reason}"
                )
                self._manual_review.append(ManualReviewEntry(
                    page_number=page_number,
                    reason=validation.reason,
                    ocr_text=ocr_result.full_text,
                    candidate_tracking=validation.tracking_number,
                    items=items,
                ))
                # Do NOT auto-assign — inherit previous if available
                if self._current_tracking:
                    self._current_items.extend(items)
                    self._current_pages.append(page_number)
                return

            else:
                # INVALID — ignore the candidate
                logger.debug(
                    f"Page {page_number}: invalid tracking rejected — "
                    f"{validation.reason}"
                )

        # ── No valid tracking number → inherit ────────────────────────
        if self._current_tracking:
            logger.debug(
                f"Page {page_number}: inheriting tracking "
                f"'{self._current_tracking}'"
            )
            if items:
                self._current_items.extend(items)
            self._current_pages.append(page_number)
        else:
            # No current tracking and no valid new one
            if items:
                logger.warning(
                    f"Page {page_number}: items found but no tracking number!"
                )
                self._manual_review.append(ManualReviewEntry(
                    page_number=page_number,
                    reason="Items found but no tracking number available",
                    ocr_text=ocr_result.full_text,
                    items=items,
                ))
            else:
                logger.debug(f"Page {page_number}: no tracking, no items — skipping")

    def _handle_new_tracking(
        self,
        page_number: int,
        tracking_number: str,
        items: List[Dict],
    ) -> None:
        """Save previous shipment (if any) and start a new one."""
        # Save previous shipment
        if self._current_tracking and self._current_items:
            self._save_current_shipment()
        elif self._current_tracking and not self._current_items:
            logger.warning(
                f"Previous shipment '{self._current_tracking}' had no items"
            )
            self._save_current_shipment()

        # Start new shipment
        logger.info(f"Page {page_number}: NEW shipment → '{tracking_number}'")
        self._current_tracking = tracking_number
        self._current_items = list(items)
        self._current_pages = [page_number]

    def _save_current_shipment(self) -> None:
        """Save the current shipment to the completed list."""
        if self._current_tracking:
            shipment = Shipment(
                tracking_number=self._current_tracking,
                items=list(self._current_items),
                page_range=list(self._current_pages),
            )
            self._shipments.append(shipment)
            logger.info(
                f"Saved shipment '{self._current_tracking}' "
                f"with {len(self._current_items)} item(s) "
                f"(pages {self._current_pages})"
            )

    def _get_tracking_confidence(
        self,
        candidate: str,
        ocr_result: OcrResult,
    ) -> float:
        """
        Get OCR confidence for a tracking number candidate.

        Tries exact match first, then partial match by checking
        if any OCR word is contained in the candidate string.
        Falls back to overall page average.
        """
        # Try exact word confidence
        conf = get_word_confidence(ocr_result, candidate)
        if conf > 0:
            return conf

        # Try partial match: check if candidate chars appear as OCR words
        # This handles cases where OCR splits the tracking number
        for word, word_conf in ocr_result.word_confidences:
            if word.upper() in candidate.upper() and len(word) >= 4:
                return word_conf

        # Fallback to average confidence
        return ocr_result.avg_confidence

    def finalize(self) -> None:
        """
        Call after processing the last page.
        Saves any remaining shipment in progress.
        """
        if self._current_tracking:
            self._save_current_shipment()
            self._current_tracking = None
            self._current_items = []
            self._current_pages = []

        logger.info(
            f"Finalized: {len(self._shipments)} shipment(s), "
            f"{len(self._manual_review)} page(s) need review"
        )

    def get_shipments(self) -> List[dict]:
        """Return all completed shipments as a list of dicts."""
        return [s.to_dict() for s in self._shipments]

    def get_manual_review(self) -> List[dict]:
        """Return all pages flagged for manual review."""
        return [r.to_dict() for r in self._manual_review]

    def get_stats(self) -> dict:
        """Return processing statistics."""
        total_items = sum(len(s.items) for s in self._shipments)
        return {
            "total_pages": self._page_count,
            "total_shipments": len(self._shipments),
            "total_items": total_items,
            "pages_needing_review": len(self._manual_review),
        }
