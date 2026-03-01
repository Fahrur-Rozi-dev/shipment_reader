"""
Main Pipeline — CLI orchestrator for the OCR Shipment Extraction system.

Usage:
    python main.py --pdf input.pdf --output shipments.json
    python main.py --pdf input.pdf  (defaults to shipments.json)

Steps:
  1. Split PDF into page images
  2. For each page sequentially:
     a. Preprocess image (OpenCV)
     b. Run OCR (Tesseract)
     c. Parse OCR text via LLM (Gemini Flash)
     d. Update stateful processor
  3. Finalize and save results
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

from pdf_splitter import split_pdf
from image_preprocessor import preprocess_image
from ocr_engine import run_ocr
from llm_parser import parse_ocr_text
from page_processor import PageProcessor
from config import DEFAULT_OUTPUT_FILE, MANUAL_REVIEW_FILE

# ── Logging setup ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_pipeline(pdf_path: str, output_path: str, review_path: str) -> dict:
    """
    Execute the full extraction pipeline.

    Args:
        pdf_path: Path to the input PDF.
        output_path: Path for the shipments JSON output.
        review_path: Path for the manual review JSON output.

    Returns:
        Statistics dict.
    """
    start_time = time.time()

    # ── Step 1: Split PDF ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 1: Splitting PDF into page images")
    logger.info("=" * 60)
    pages = split_pdf(pdf_path)
    total_pages = len(pages)
    logger.info(f"Total pages: {total_pages}")

    # ── Step 2: Process pages sequentially ────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 2: Processing pages sequentially")
    logger.info("=" * 60)

    processor = PageProcessor()

    for page_num, page_image in enumerate(pages, start=1):
        logger.info(f"─── Page {page_num}/{total_pages} ───")

        # 2a. Preprocess
        preprocessed = preprocess_image(page_image)

        # 2b. OCR
        ocr_result = run_ocr(preprocessed)

        if ocr_result.is_mostly_empty:
            logger.info(f"Page {page_num}: mostly empty, minimal processing")
            # Still process through the state machine (it handles empty pages)
            llm_result = {"tracking_number": "", "items": []}
        else:
            # 2c. LLM parsing
            llm_result = parse_ocr_text(ocr_result.full_text)

        # 2d. State update
        processor.process_page(page_num, llm_result, ocr_result)

    # ── Step 3: Finalize ──────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STEP 3: Finalizing")
    logger.info("=" * 60)

    processor.finalize()

    # ── Save outputs ──────────────────────────────────────────────────
    shipments = processor.get_shipments()
    manual_review = processor.get_manual_review()
    stats = processor.get_stats()

    # Write shipments
    output_file = Path(output_path)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {"shipments": shipments, "stats": stats},
            f,
            indent=2,
            ensure_ascii=False,
        )
    logger.info(f"Shipments saved to: {output_file}")

    # Write manual review (if any)
    if manual_review:
        review_file = Path(review_path)
        with open(review_file, "w", encoding="utf-8") as f:
            json.dump(manual_review, f, indent=2, ensure_ascii=False)
        logger.info(f"Manual review saved to: {review_file}")
    else:
        logger.info("No pages require manual review ✓")

    # ── Print summary ─────────────────────────────────────────────────
    elapsed = time.time() - start_time
    _print_summary(stats, elapsed)

    return stats


def _print_summary(stats: dict, elapsed: float) -> None:
    """Print a human-readable summary of the pipeline results."""
    print("\n" + "=" * 60)
    print("  EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"  Pages processed:       {stats['total_pages']}")
    print(f"  Shipments extracted:   {stats['total_shipments']}")
    print(f"  Total items found:     {stats['total_items']}")
    print(f"  Pages needing review:  {stats['pages_needing_review']}")
    print(f"  Time elapsed:          {elapsed:.1f}s")
    print("=" * 60)

    if stats["pages_needing_review"] > 0:
        print(
            f"\n  ⚠ {stats['pages_needing_review']} page(s) flagged "
            f"for manual review. Check {MANUAL_REVIEW_FILE}"
        )

    if stats["total_shipments"] == 0:
        print(
            "\n  ⚠ No shipments extracted! The PDF may not contain "
            "recognizable shipment labels."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Extract shipment data from multi-page PDF files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example:
  python main.py --pdf labels.pdf
  python main.py --pdf labels.pdf --output results.json
        """,
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to the input PDF file",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--review",
        default=MANUAL_REVIEW_FILE,
        help=f"Manual review JSON file path (default: {MANUAL_REVIEW_FILE})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        run_pipeline(args.pdf, args.output, args.review)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
