#!/bin/bash
echo "Installing dependencies..."
pip install -r requirements.txt
echo ""
echo "Make sure tesseract and poppler are installed:"
echo "  Ubuntu/Debian: sudo apt-get install tesseract-ocr poppler-utils"
echo "  macOS: brew install tesseract poppler"
echo ""
echo "Starting OCR server at http://localhost:5000 ..."
python3 app.py
