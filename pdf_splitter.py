"""
PDF Splitter — converts a multi-page PDF into a list of PIL Images.

Uses PyMuPDF (fitz) — no external binary (Poppler) needed.
Pages are returned IN ORDER, which is critical for stateful processing.
"""
import logging
from pathlib import Path
from typing import List

import fitz  # PyMuPDF
from PIL import Image

from config import PDF_DPI

logger = logging.getLogger(__name__)


def split_pdf(pdf_path: str, dpi: int = PDF_DPI) -> List[Image.Image]:
    """
    Convert every page of the PDF to a PIL Image.

    Args:
        pdf_path: Path to the input PDF file.
        dpi: Resolution for rendering (higher = better OCR, slower).

    Returns:
        Ordered list of PIL Image objects, one per page.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        RuntimeError: If PyMuPDF fails.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info(f"Splitting PDF: {pdf_path}  (DPI={dpi})")

    try:
        doc = fitz.open(str(pdf_path))
        images = []
        zoom = dpi / 72  # 72 is the default PDF resolution
        matrix = fitz.Matrix(zoom, zoom)

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matrix)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)

        doc.close()
    except Exception as e:
        raise RuntimeError(f"Failed to split PDF: {e}") from e

    logger.info(f"Split into {len(images)} page(s)")
    return images
