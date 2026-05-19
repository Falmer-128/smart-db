# 📄 Smart Document Parser (ETL Pipeline for RAG)

A modular, containerized ETL pipeline that converts raw documents (PDF, DOCX, XLSX) into clean text/Markdown and stores them in a knowledge base directory for consumption by an LLM (RAG pipeline).

## Project Structure

```
.
├── main.py                  # Entry point — orchestrates the pipeline
├── config.py                # Configuration (reads from .env)
├── .env                     # Environment variables
├── core/
│   └── router.py            # Routes files to the correct extractor
├── extractors/
│   ├── pdf_extractor.py     # Fast text-layer PDF extraction (pypdf)
│   ├── ocr_extractor.py     # OCR for scanned PDFs (Tesseract)
│   ├── docx_extractor.py    # Word document extraction
│   └── excel_extractor.py   # Excel → Markdown tables (pandas)
├── utils/
│   └── file_manager.py      # Directory scanning, idempotency, file I/O
├── INPUT/                   # Drop raw documents here
├── PROCESSED/               # Extracted texts (knowledge base)
├── OUTPUT/                  # Reserved for future reports
├── requirements.txt
├── Dockerfile
└── README.md
```

## Quick Start (Local)

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Place documents into the INPUT/ directory

# 4. Run the parser
python main.py
```

> **Note:** For OCR to work locally you need `tesseract-ocr` and `poppler-utils` installed on your OS.

## Docker Usage

### Build the Image

```bash
docker build -t smart-parser .
```

### Run the Container

Mount your local `INPUT` and `PROCESSED` directories as volumes so that documents persist outside the container:

```bash
docker run --rm \
  -v "$(pwd)/INPUT:/app/INPUT" \
  -v "$(pwd)/PROCESSED:/app/PROCESSED" \
  smart-parser
```

### Override Configuration

You can pass environment variables at runtime to override defaults from `.env`:

```bash
docker run --rm \
  -v "$(pwd)/INPUT:/app/INPUT" \
  -v "$(pwd)/PROCESSED:/app/PROCESSED" \
  -e OCR_DPI=200 \
  -e OCR_LANGUAGES=eng \
  smart-parser
```

## How It Works

1. **Scan** — `utils/file_manager.py` lists all files in `INPUT/` and skips any that already have a corresponding `.txt` in `PROCESSED/` (idempotency).
2. **Route** — `core/router.py` inspects each file's extension and, for PDFs, checks whether a usable text layer exists.
3. **Extract** — The appropriate extractor is called:
   | Format | Extractor | Method |
   |--------|-----------|--------|
   | PDF (text layer) | `pdf_extractor` | pypdf direct read |
   | PDF (scanned) | `ocr_extractor` | pdf2image → Tesseract |
   | DOCX | `docx_extractor` | python-docx |
   | XLSX / XLS | `excel_extractor` | pandas → Markdown |
4. **Save** — Extracted text is written to `PROCESSED/<filename>.txt`.

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `INPUT_DIR` | `INPUT` | Directory to scan for raw documents |
| `PROCESSED_DIR` | `PROCESSED` | Directory for extracted texts |
| `OUTPUT_DIR` | `OUTPUT` | Reserved for future pipeline stages |
| `OCR_LANGUAGES` | `rus+eng` | Tesseract language packs |
| `OCR_DPI` | `300` | Resolution for PDF rasterization |
| `PDF_TEXT_THRESHOLD` | `50` | Min chars to consider a text layer valid |

## Dependencies

All Python packages are listed in `requirements.txt`. The Docker image also installs:

- `tesseract-ocr` + language packs (`rus`, `eng`)
- `poppler-utils` (backend for `pdf2image`)
