---
title: Shipment Reader
emoji: 📦
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
---

# Shipment Reader

OCR-powered shipment data extraction from PDF shipping labels.

## Features
- Extract tracking numbers from J&T Express and Shopee Express (SPX) labels
- Read SKU codes and quantities
- Split-view validation: results on left, PDF preview on right
- Download results as Excel spreadsheet
- Support for multi-page PDF files

## Supported Couriers
- **J&T Express** — JX, JP, JO, JA, JB, JD prefix
- **Shopee Express (SPX)** — SPXID prefix

## Tech Stack
- Python / Flask
- Tesseract OCR
- OpenCV for image preprocessing
