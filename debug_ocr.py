"""
Debug script: OCR one page of a PDF and save results to file.
Usage: python debug_ocr.py --pdf your_file.pdf --page 1
"""
import argparse
import re
import sys
import io
import numpy as np

from pdf_splitter import split_pdf
from image_preprocessor import preprocess_image
from ocr_engine import run_ocr
from llm_parser import parse_ocr_text_rules
from config import TRACKING_NUMBER_PATTERN

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def main():
    parser = argparse.ArgumentParser(description="Debug OCR output for a single page")
    parser.add_argument("--pdf", required=True, help="Path to PDF")
    parser.add_argument("--page", type=int, default=1, help="Page number (1-indexed)")
    args = parser.parse_args()

    pages = split_pdf(args.pdf)

    if args.page < 1 or args.page > len(pages):
        print(f"ERROR: Page {args.page} out of range (1-{len(pages)})")
        sys.exit(1)

    page_img = pages[args.page - 1]
    original_np = np.array(page_img)
    preprocessed = preprocess_image(page_img)
    ocr = run_ocr(preprocessed, original_image=original_np)

    lines = []
    lines.append(f"Total pages: {len(pages)}")
    lines.append(f"Avg confidence: {ocr.avg_confidence:.1f}%")
    lines.append(f"Barcodes: {len(ocr.barcodes)}")

    if ocr.barcodes:
        lines.append("\n=== BARCODES ===")
        for i, bc in enumerate(ocr.barcodes, 1):
            is_tracking = bool(TRACKING_NUMBER_PATTERN.match(bc.upper()))
            label = "TRACKING" if is_tracking else "other"
            lines.append(f"  [{i}] {bc}  ({label})")

    lines.append("\n=== RAW OCR TEXT ===")
    lines.append(ocr.full_text)

    lines.append("\n=== TRACKING CANDIDATES ===")
    words = re.findall(r"[A-Za-z0-9]+", ocr.full_text)
    for word in words:
        cleaned = word.upper()
        if TRACKING_NUMBER_PATTERN.match(cleaned):
            lines.append(f"  > {cleaned}")

    lines.append("\n=== PARSER RESULT ===")
    result = parse_ocr_text_rules(ocr.full_text)
    lines.append(f"  Tracking: {result['tracking_number'] or '(none)'}")
    lines.append(f"  Items: {len(result['items'])}")
    for item in result["items"]:
        lines.append(f"    - {item['variant']} x{item['quantity']}")

    output = "\n".join(lines)

    # Save to file
    out_file = f"debug_page_{args.page}.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(output)

    # Print
    print(output)
    print(f"\nSaved to: {out_file}")


if __name__ == "__main__":
    main()
