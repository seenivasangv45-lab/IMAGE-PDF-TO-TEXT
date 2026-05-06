# gunicorn.conf.py
# Optimised for Hugging Face Spaces (Docker) — OCR Web App

import os

# ── Binding ────────────────────────────────────────────────────────────────────
# Hugging Face Spaces requires port 7860
bind = f"0.0.0.0:{os.environ.get('PORT', '7860')}"

# ── Workers ────────────────────────────────────────────────────────────────────
# OCR is CPU-intensive and memory-heavy (300 DPI images in RAM).
# Keep workers low to avoid OOM — 2 is safe on HF free tier (16 GB RAM shared).
workers = 2
worker_class = "sync"   # sync is best for long-running OCR tasks
threads = 1             # 1 thread per worker — OCR is not thread-safe with pytesseract

# ── Timeouts ──────────────────────────────────────────────────────────────────
# OCR at 300 DPI on a large multi-page PDF can take 60-180 seconds.
timeout = 300           # 5 minutes max per request
keepalive = 5

# ── Upload size ────────────────────────────────────────────────────────────────
limit_request_line       = 0
limit_request_fields     = 200
limit_request_field_size = 0   # no limit — allows large PDF uploads

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"    # stdout → visible in HF Space logs
errorlog  = "-"    # stderr
loglevel  = "info"

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "ocr_web_app"
