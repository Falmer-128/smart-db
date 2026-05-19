# ============================================================
# Production-ready Dockerfile for Smart Document Parser (ETL)
# Base: python:3.10-slim  |  OCR: Tesseract (rus + eng)
# ============================================================
FROM python:3.10-slim AS builder

# Prevent interactive prompts during apt-get
ENV DEBIAN_FRONTEND=noninteractive

# Install OS-level dependencies required by the pipeline:
#   - tesseract-ocr          : OCR engine
#   - tesseract-ocr-rus/eng  : language data files
#   - poppler-utils           : pdf2image backend (pdfinfo, pdftoppm)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-rus \
        tesseract-ocr-eng \
        poppler-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create volume mount-points so they exist even without -v flags
RUN mkdir -p /app/INPUT /app/PROCESSED /app/OUTPUT

# Default command
CMD ["python", "main.py"]
