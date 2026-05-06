import os
import io
import sys
import tempfile
import base64
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import pytesseract
from pytesseract import Output
from pdf2image import convert_from_bytes
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# ─────────────────────────────────────────────────────────────────
#  WINDOWS PATH CONFIGURATION  ← Edit these two lines
# ─────────────────────────────────────────────────────────────────

TESSERACT_PATH = r"C:\Users\Rusan\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
POPPLER_PATH   = r"C:\poppler\Library\bin"

# ─────────────────────────────────────────────────────────────────

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    if os.path.isfile(TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    else:
        print(f"[WARN] Tesseract not found at: {TESSERACT_PATH}")
    if not os.path.isdir(POPPLER_PATH):
        print(f"[WARN] Poppler not found at: {POPPLER_PATH}")

UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "ocr_uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

OCR_DPI = 300  # Higher = better accuracy, slower


def get_poppler_path():
    if IS_WINDOWS and os.path.isdir(POPPLER_PATH):
        return POPPLER_PATH
    return None


# ─────────────────────────────────────────────────────────────────
#  CORE: Build a searchable PDF page that LOOKS identical to original
#
#  Strategy:
#    1. Render original page as high-res image (background)
#    2. OCR → get per-word bounding boxes
#    3. Draw image as full-page background in ReportLab
#    4. Overlay each word as invisible text (font size 0, transparent)
#       at the EXACT position Tesseract detected it
#    Result: visually identical PDF with real, selectable, searchable text
# ─────────────────────────────────────────────────────────────────

def build_searchable_page(img: Image.Image) -> bytes:
    """
    Given a PIL image of one PDF page, return a PDF page (bytes)
    that looks exactly like the image but has invisible OCR text overlaid.
    """
    img_w, img_h = img.size  # pixels at OCR_DPI

    # PDF points = pixels * 72 / DPI
    pdf_w = img_w * 72.0 / OCR_DPI
    pdf_h = img_h * 72.0 / OCR_DPI

    # Run Tesseract → word-level bounding boxes
    data = pytesseract.image_to_data(img, lang="eng", output_type=Output.DICT)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(pdf_w, pdf_h))

    # ── 1. Draw the original page image as background ──────────────
    img_reader = ImageReader(img)
    c.drawImage(img_reader, 0, 0, width=pdf_w, height=pdf_h)

    # ── 2. Overlay invisible text at exact word positions ──────────
    # ReportLab origin is bottom-left; image origin is top-left → flip Y
    c.setFillColorRGB(0, 0, 0, alpha=0)   # fully transparent fill
    n = len(data["text"])
    for i in range(n):
        word = data["text"][i]
        if not word or not word.strip():
            continue
        conf = int(data["conf"][i])
        if conf < 0:   # -1 = Tesseract couldn't read
            continue

        # Bounding box in pixels (top-left origin)
        x_px  = data["left"][i]
        y_px  = data["top"][i]
        w_px  = data["width"][i]
        h_px  = data["height"][i]

        if w_px <= 0 or h_px <= 0:
            continue

        # Convert to PDF points
        x_pt = x_px * 72.0 / OCR_DPI
        # Flip Y: PDF y = page_height - (image_top + word_height)
        y_pt = pdf_h - (y_px + h_px) * 72.0 / OCR_DPI
        w_pt = w_px * 72.0 / OCR_DPI
        h_pt = h_px * 72.0 / OCR_DPI

        # Scale font so the invisible text fills the bounding box width
        font_size = max(h_pt * 0.85, 1)
        c.setFont("Helvetica", font_size)

        # Measure how wide the word would render at this font size
        text_w = c.stringWidth(word, "Helvetica", font_size)
        if text_w <= 0:
            continue

        # Horizontal scale to match the detected word width exactly
        scale = w_pt / text_w
        c.saveState()
        c.transform(scale, 0, 0, 1, x_pt, y_pt)
        c.drawString(0, 0, word)
        c.restoreState()

    c.save()
    buf.seek(0)
    return buf.read()


def process_pdf(pdf_bytes: bytes) -> tuple[bytes, int, int, int]:
    """OCR all pages; return (output_pdf_bytes, pages, words, chars)."""
    poppler_kwargs = {}
    poppler = get_poppler_path()
    if poppler:
        poppler_kwargs["poppler_path"] = poppler

    images = convert_from_bytes(pdf_bytes, dpi=OCR_DPI, **poppler_kwargs)

    writer = PdfWriter()
    total_words = 0
    total_chars = 0

    for img in images:
        page_pdf_bytes = build_searchable_page(img)
        # Read the single-page PDF and add to writer
        page_reader = PdfReader(io.BytesIO(page_pdf_bytes))
        writer.add_page(page_reader.pages[0])

        # Count stats via plain text too
        text = pytesseract.image_to_string(img, lang="eng")
        words = text.split()
        total_words += len(words)
        total_chars += len(text)

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    return out_buf.read(), len(images), total_words, total_chars


def process_image(image_bytes: bytes) -> tuple[bytes, int, int, int]:
    """OCR a single image; return (output_pdf_bytes, pages, words, chars)."""
    img = Image.open(io.BytesIO(image_bytes))
    # Ensure RGB (no alpha channel issues)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # If image DPI metadata exists, re-render at OCR_DPI
    page_pdf_bytes = build_searchable_page(img)

    writer = PdfWriter()
    page_reader = PdfReader(io.BytesIO(page_pdf_bytes))
    writer.add_page(page_reader.pages[0])

    text = pytesseract.image_to_string(img, lang="eng")
    words = text.split()

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    return out_buf.read(), 1, len(words), len(text)


def get_preview_text(pdf_bytes: bytes = None, image_bytes: bytes = None):
    """Fast text extraction for preview (no PDF building)."""
    pages = []
    poppler_kwargs = {}
    poppler = get_poppler_path()
    if poppler:
        poppler_kwargs["poppler_path"] = poppler

    if pdf_bytes:
        images = convert_from_bytes(pdf_bytes, dpi=150, **poppler_kwargs)
        for i, img in enumerate(images):
            text = pytesseract.image_to_string(img, lang="eng")
            pages.append({"page": i + 1, "text": text})
    elif image_bytes:
        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img, lang="eng")
        pages.append({"page": 1, "text": text})

    total_words = sum(len(p["text"].split()) for p in pages)
    return pages, total_words


# ─────────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/check", methods=["GET"])
def check():
    info = {"platform": sys.platform, "tesseract_ok": False, "poppler_ok": False}
    try:
        ver = pytesseract.get_tesseract_version()
        info["tesseract_ok"] = True
        info["tesseract_path"] = pytesseract.pytesseract.tesseract_cmd
        info["tesseract_version"] = str(ver)
    except Exception as e:
        info["tesseract_error"] = str(e)
    poppler = get_poppler_path()
    if poppler:
        info["poppler_ok"] = True
        info["poppler_path"] = poppler
    elif not IS_WINDOWS:
        info["poppler_ok"] = True
        info["poppler_path"] = "system PATH"
    return jsonify(info)


@app.route("/ocr", methods=["POST"])
def ocr():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    filename = f.filename.lower()
    file_bytes = f.read()
    if not file_bytes:
        return jsonify({"error": "Empty file"}), 400
    try:
        if filename.endswith(".pdf"):
            out_bytes, pages, words, chars = process_pdf(file_bytes)
        elif filename.endswith((".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")):
            out_bytes, pages, words, chars = process_image(file_bytes)
        else:
            return jsonify({"error": "Unsupported file type."}), 400

        out_buf = io.BytesIO(out_bytes)
        base_name = os.path.splitext(f.filename)[0]
        response = send_file(out_buf, mimetype="application/pdf",
                             as_attachment=True,
                             download_name=f"{base_name}_searchable.pdf")
        response.headers["X-Page-Count"] = str(pages)
        response.headers["X-Word-Count"]  = str(words)
        response.headers["X-Char-Count"]  = str(chars)
        response.headers["Access-Control-Expose-Headers"] = \
            "X-Page-Count, X-Word-Count, X-Char-Count"
        return response
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/preview", methods=["POST"])
def preview():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    filename = f.filename.lower()
    file_bytes = f.read()
    try:
        if filename.endswith(".pdf"):
            pages, total_words = get_preview_text(pdf_bytes=file_bytes)
        elif filename.endswith((".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")):
            pages, total_words = get_preview_text(image_bytes=file_bytes)
        else:
            return jsonify({"error": "Unsupported file type"}), 400
        return jsonify({"pages": pages, "total_words": total_words})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("\n" + "="*55)
    print("  OCR Web App — Layout-Preserving Edition")
    print("="*55)
    print(f"  Tesseract : {TESSERACT_PATH}")
    print(f"  Poppler   : {POPPLER_PATH}")
    print(f"  Health    : http://localhost:5000/check")
    print("="*55 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
