# OCR Shipment Extraction MVP

Zero-budget system to extract shipment data (tracking numbers + items) from multi-page PDF files using OCR and free LLM.

## Tech Stack

| Component | Tool |
|-----------|------|
| PDF → Images | pdf2image + Poppler |
| Preprocessing | OpenCV |
| OCR | Tesseract |
| Text Parsing | Google Gemini Flash (free) |
| Language | Python 3.10+ |

## Prerequisites

### 1. Install Tesseract OCR
- Download from: https://github.com/UB-Mannheim/tesseract/wiki
- Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`

### 2. Install Poppler (required by pdf2image)
- Download from: https://github.com/oschwartz10612/poppler-windows/releases
- Extract and add `bin/` folder to your system PATH

### 3. Get a free Gemini API key
- Visit https://aistudio.google.com
- Create a free API key
- Copy `.env.example` to `.env` and paste your key:
  ```
  GEMINI_API_KEY=your_key_here
  ```

### 4. Install Python dependencies
```bash
pip install -r requirements.txt
```

## Usage

```bash
# Basic usage
python main.py --pdf input.pdf

# Custom output path
python main.py --pdf input.pdf --output results.json

# Verbose logging
python main.py --pdf input.pdf -v
```

## Output

### `shipments.json`
```json
{
  "shipments": [
    {
      "tracking_number": "JNT1234567890",
      "items": [
        {"variant": "Red T-Shirt Size L", "quantity": 2},
        {"variant": "Blue Cap", "quantity": 1}
      ],
      "page_range": [1, 2]
    }
  ],
  "stats": {
    "total_pages": 50,
    "total_shipments": 25,
    "total_items": 48,
    "pages_needing_review": 2
  }
}
```

### `manual_review.json`
Pages flagged due to low OCR confidence or missing tracking numbers.

## Architecture

```
PDF → pdf_splitter → image_preprocessor → ocr_engine → llm_parser → page_processor → shipments.json
                                                                                    → manual_review.json
```

Each page is processed **sequentially** with a stateful processor that:
- Detects new tracking numbers (strict validation)
- Inherits tracking across continuation pages
- Skips empty pages
- Flags ambiguous cases for human review

## Running Tests

```bash
python -m pytest tests/ -v
```
