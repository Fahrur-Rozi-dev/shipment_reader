"""
Image Preprocessor — prepares page images for optimal OCR accuracy.

Pipeline:
  1. Convert to grayscale
  2. Gaussian blur (reduce noise)
  3. Adaptive thresholding (binarize)
  4. Optional deskew correction
"""
import logging
import numpy as np
import cv2
from PIL import Image

from config import (
    GAUSSIAN_KERNEL_SIZE,
    ADAPTIVE_THRESH_BLOCK_SIZE,
    ADAPTIVE_THRESH_C,
)

logger = logging.getLogger(__name__)


def preprocess_image(pil_image: Image.Image, deskew: bool = True) -> np.ndarray:
    """
    Apply the full preprocessing pipeline to a PIL Image.

    Args:
        pil_image: Input page image from pdf2image.
        deskew: Whether to attempt deskew correction.

    Returns:
        Preprocessed image as a numpy array (grayscale, binary).
    """
    # Convert PIL → OpenCV (BGR)
    img = np.array(pil_image)
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    else:
        gray = img

    # Step 1: Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(gray, GAUSSIAN_KERNEL_SIZE, 0)

    # Step 2: Adaptive threshold for binarization
    binary = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        ADAPTIVE_THRESH_BLOCK_SIZE,
        ADAPTIVE_THRESH_C,
    )

    # Step 3: Optional deskew
    if deskew:
        binary = _deskew(binary)

    logger.debug("Image preprocessed successfully")
    return binary


def _deskew(image: np.ndarray, max_angle: float = 5.0) -> np.ndarray:
    """
    Correct small rotations in the scanned image.

    Only corrects angles within ±max_angle degrees to avoid
    misinterpreting layout as skew.
    """
    coords = np.column_stack(np.where(image < 128))  # dark pixels

    if len(coords) < 100:
        # Too few dark pixels — likely a mostly-empty page
        return image

    try:
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]

        # Normalize angle
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        if abs(angle) > max_angle:
            return image  # Rotation too large, skip

        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            image,
            rotation_matrix,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        logger.debug(f"Deskewed by {angle:.2f}°")
        return rotated
    except Exception:
        # If deskew fails for any reason, return original
        return image
