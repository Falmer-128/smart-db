import os
import re
import json
import hashlib
import time
import subprocess
from datetime import datetime
import shutil
import fitz  # PyMuPDF — used ONLY for Tier 3 heuristic trigger & page pixmap rendering
from paddleocr import PaddleOCR
import pandas as pd
import google.generativeai as genai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from markitdown import MarkItDown
from dotenv import load_dotenv

load_dotenv()

# ── Directory Layout ─────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "OUTPUT")          # Quarantine for corrupted/unreadable files
PROCESSED_DIR = os.path.join(BASE_DIR, "PROCESSED")    # Successfully processed originals
CHUNKS_DIR = os.path.join(BASE_DIR, "CHUNKS_STAGING")  # JSON chunk files
HASHES_FILE = os.path.join(BASE_DIR, "content_hashes.json")
API_LIMITS_FILE = os.path.join(BASE_DIR, "api_limits.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(CHUNKS_DIR, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# Deduplication — MD5 hash of first 300 words
# ═════════════════════════════════════════════════════════════════════════════
class SemanticHasher:
    @staticmethod
    def get_hash(text):
        words = text.split()
        if len(words) > 300:
            words = words[:300]
        normalized = "".join(words).lower()
        normalized = "".join(c for c in normalized if c.isalnum())
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def is_duplicate(file_hash):
        if not os.path.exists(HASHES_FILE):
            return False
        with open(HASHES_FILE, 'r') as f:
            try:
                hashes = json.load(f)
            except json.JSONDecodeError:
                hashes = []
        return file_hash in hashes

    @staticmethod
    def mark_seen(file_hash):
        hashes = []
        if os.path.exists(HASHES_FILE):
            with open(HASHES_FILE, 'r') as f:
                try:
                    hashes = json.load(f)
                except json.JSONDecodeError:
                    pass
        if file_hash not in hashes:
            hashes.append(file_hash)
            with open(HASHES_FILE, 'w') as f:
                json.dump(hashes, f)


# ═════════════════════════════════════════════════════════════════════════════
# Rate Limiter for Gemini API (Tier 3)
# ═════════════════════════════════════════════════════════════════════════════
class RateLimiter:
    @staticmethod
    def check_and_update():
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        limits = {"date": today_str, "daily_count": 0, "minute_counts": {}}
        if os.path.exists(API_LIMITS_FILE):
            with open(API_LIMITS_FILE, 'r') as f:
                try:
                    loaded = json.load(f)
                    if loaded.get("date") == today_str:
                        limits = loaded
                except json.JSONDecodeError:
                    pass

        if limits["daily_count"] >= 500:
            return False, "Daily limit reached"

        current_minute = now.strftime("%H:%M")
        minute_count = limits["minute_counts"].get(current_minute, 0)

        if minute_count >= 15:
            sleep_time = 60 - now.second
            print(f"Minute limit reached. Sleeping for {sleep_time} seconds...")
            time.sleep(sleep_time)
            return RateLimiter.check_and_update()

        limits["daily_count"] += 1
        limits["minute_counts"][current_minute] = minute_count + 1

        # Prune stale minute buckets
        for k in list(limits["minute_counts"].keys()):
            if k != current_minute:
                del limits["minute_counts"][k]

        with open(API_LIMITS_FILE, 'w') as f:
            json.dump(limits, f)

        return True, ""


# ═════════════════════════════════════════════════════════════════════════════
# Markdown Formatting Helpers for Tier 2/3 raw text
# ═════════════════════════════════════════════════════════════════════════════
def _format_ocr_as_markdown(raw_text, page_num=None):
    """Wrap raw PaddleOCR output into a Markdown section."""
    header = f"## OCR — Page {page_num}\n\n" if page_num is not None else "## OCR Output\n\n"
    # Normalise whitespace into proper paragraphs
    paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [raw_text.strip()]
    body = "\n\n".join(paragraphs)
    return header + body


def _format_gemini_as_markdown(raw_text, page_num=None):
    """Ensure Gemini output is wrapped in a Markdown section header.
    Gemini is already prompted to return Markdown, so we only add a
    contextual header if one is missing."""
    header = f"## Complex Content — Page {page_num}\n\n" if page_num is not None else "## Complex Content\n\n"
    # If Gemini already starts with a heading, skip the extra header
    stripped = raw_text.strip()
    if stripped.startswith("#"):
        return stripped
    return header + stripped


# ═════════════════════════════════════════════════════════════════════════════
# Document Router — Tier 3 (Gemini Vision API)
# ═════════════════════════════════════════════════════════════════════════════
class DocumentRouter:
    def __init__(self):
        self._ocr = None

    def _get_ocr_reader(self):
        """Lazy-initialise the PaddleOCR engine (loaded once, reused)."""
        if self._ocr is None:
            self._ocr = PaddleOCR(use_textline_orientation=True, lang='ru', show_log=False)
        return self._ocr

    @staticmethod
    def _parse_paddle_result(result):
        """Parse PaddleOCR result into (full_text, avg_confidence).

        PaddleOCR returns a list of pages, each page is a list of
        (bbox, (text, confidence)) tuples.  We sort bounding boxes
        top-to-bottom then left-to-right to reconstruct the natural
        reading order, which is critical for preserving table layouts."""
        lines = []
        confidences = []

        if not result or not result[0]:
            return "", 0.0

        detections = result[0]  # First (only) page image

        # Sort by vertical centre (top→bottom), then horizontal left edge
        def _sort_key(det):
            bbox = det[0]  # list of 4 corner points
            y_centre = sum(pt[1] for pt in bbox) / len(bbox)
            x_left = min(pt[0] for pt in bbox)
            return (y_centre, x_left)

        detections_sorted = sorted(detections, key=_sort_key)

        for det in detections_sorted:
            text = det[1][0]
            conf = det[1][1]
            lines.append(text)
            confidences.append(conf)

        full_text = " ".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return full_text, avg_conf

    def process_tier3_image(self, image_path):
        """Send a single page image to Gemini Vision API.  Accepts a
        file path to a PNG/JPG image — never a full multi-page PDF."""
        can_proceed, msg = RateLimiter.check_and_update()
        if not can_proceed:
            print(f"Skipping Gemini Vision API: {msg}")
            raise Exception("DailyLimitReached")

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("GEMINI_API_KEY not found in environment. Skipping Tier 3 processing.")
            return ""

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        try:
            sample_file = genai.upload_file(path=image_path)
            response = model.generate_content([
                sample_file,
                "Extract all text and describe any complex schematics or diagrams. "
                "Format the output as valid Markdown with headers, lists, and tables where appropriate."
            ])
            return response.text
        except Exception as e:
            print(f"Error with Gemini API: {e}")
            return ""


# ═════════════════════════════════════════════════════════════════════════════
# Chunking & Context Injection
# ═════════════════════════════════════════════════════════════════════════════
def chunk_and_inject(text, original_filename, doc_type, method):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=5000,
        chunk_overlap=500,
        separators=["\n\n## ", "\n\n", "\n", " ", ""]
    )
    raw_chunks = splitter.split_text(text)

    final_chunks = []
    for chunk in raw_chunks:
        injected = f"[Файл: {original_filename} | Тип оригинала: {doc_type} | Метод: {method}] \n\n {chunk}"
        final_chunks.append({
            "text": injected,
            "metadata": {
                "filename": original_filename,
                "doc_type": doc_type,
                "method": method
            }
        })
    return final_chunks


# ═════════════════════════════════════════════════════════════════════════════
# Legacy .doc → PDF Conversion via LibreOffice Headless
# ═════════════════════════════════════════════════════════════════════════════
def convert_doc_to_pdf(doc_path):
    """Convert a legacy .doc file to PDF using LibreOffice headless.
    Returns the path to the generated PDF in /tmp, or None on failure."""
    try:
        result = subprocess.run(
            [
                'libreoffice', '--headless', '--convert-to', 'pdf',
                '--outdir', '/tmp', doc_path
            ],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f"LibreOffice conversion failed: {result.stderr}")
            return None

        # LibreOffice outputs to /tmp/<basename_without_ext>.pdf
        base_name = os.path.splitext(os.path.basename(doc_path))[0]
        pdf_path = os.path.join('/tmp', f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            return pdf_path
        else:
            print(f"Expected PDF not found at {pdf_path}")
            return None
    except FileNotFoundError:
        print("LibreOffice is not installed. Cannot convert .doc files.")
        return None
    except subprocess.TimeoutExpired:
        print(f"LibreOffice conversion timed out for {doc_path}")
        return None
    except Exception as e:
        print(f"Error converting .doc to PDF: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═════════════════════════════════════════════════════════════════════════════
def process_file(filepath, save_to_disk=False):
    filename = os.path.basename(filepath)
    ext = filepath.lower().split('.')[-1]

    # ── Step 0: .doc Pre-Processing ──────────────────────────────────────────
    # Legacy binary .doc files cannot be parsed by MarkItDown or accepted by
    # Gemini.  Convert to PDF via LibreOffice headless, then process as PDF.
    original_filepath = filepath  # Preserve for PROCESSED move / quarantine
    tmp_pdf_path = None
    if ext == 'doc':
        print(f"Legacy .doc detected: {filename}. Converting to PDF via LibreOffice...")
        tmp_pdf_path = convert_doc_to_pdf(filepath)
        if tmp_pdf_path is None:
            print(f"Conversion failed for {filename}. Moving to OUTPUT (Quarantine).")
            shutil.move(filepath, os.path.join(OUTPUT_DIR, filename))
            return []
        # Swap to the temp PDF for all downstream processing
        # but keep original filename for metadata/context injection
        filepath = tmp_pdf_path
        ext = 'pdf'

    router = DocumentRouter()

    # ── Step 1: Early Deduplication ──────────────────────────────────────────
    # Extract a lightweight first-pass text via MarkItDown (cheap, no API).
    # Hash the first 300 words and bail immediately if duplicate.
    # Excel files (.xls/.xlsx) are intercepted and processed via pandas to
    # avoid NaN / "Unnamed" garbage that MarkItDown produces on complex
    # corporate spreadsheets with merged cells and padding rows.
    try:
        if ext in ('xls', 'xlsx'):
            xls = pd.ExcelFile(filepath)
            excel_text = []
            for sheet_name in xls.sheet_names:
                # Read sheet, dropping completely empty rows and columns
                df = pd.read_excel(xls, sheet_name=sheet_name, dtype=str)
                df.dropna(how='all', inplace=True)
                df.dropna(axis=1, how='all', inplace=True)
                # Fill remaining NaNs with empty string
                df.fillna("", inplace=True)

                # Convert to markdown table
                sheet_md = f"## Лист: {sheet_name}\n\n" + df.to_markdown(index=False)
                excel_text.append(sheet_md)
            xls.close()
            quick_text = "\n\n".join(excel_text)
        else:
            md = MarkItDown()
            quick_result = md.convert(filepath)
            quick_text = quick_result.text_content or ""
    except Exception:
        quick_text = ""

    # For PDFs where MarkItDown returned nothing, grab first-page text via fitz
    if not quick_text.strip() and ext == 'pdf':
        try:
            doc = fitz.open(filepath)
            if len(doc) > 0:
                quick_text = doc[0].get_text() or ""
            doc.close()
        except Exception:
            quick_text = ""

    if quick_text and len(quick_text.strip()) > 10:
        file_hash = SemanticHasher.get_hash(quick_text)
        if SemanticHasher.is_duplicate(file_hash):
            print(f"Duplicate file detected: {filename}. Permanently deleting.")
            os.remove(filepath)
            return []
    else:
        file_hash = None  # Will compute after full extraction

    # ── Step 2: Tier Routing ─────────────────────────────────────────────────
    raw_texts = []

    try:
        # --- PDF-specific: check the Tier 3 heuristic per page ---------------
        if ext == 'pdf':
            doc = fitz.open(filepath)
            for page_num, page in enumerate(doc):
                is_complex = len(page.get_drawings()) > 100 or len(page.get_images()) > 5

                if is_complex:
                    # Tier 3: render THIS page as image → send to Gemini
                    pix = page.get_pixmap()
                    img_path = f"/tmp/smartdb_page_{page_num}.png"
                    pix.save(img_path)
                    try:
                        desc = router.process_tier3_image(img_path)
                        if desc:
                            md_text = _format_gemini_as_markdown(desc, page_num=page_num)
                            raw_texts.append((md_text, "Tier 3-Complex", "Gemini-API"))
                    finally:
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    continue

            doc.close()

            # If no pages were Tier 3, check if Tier 1 (MarkItDown) succeeded
            if not raw_texts:
                if quick_text and len(quick_text.strip()) > 50:
                    # Tier 1: MarkItDown already gave us clean Markdown
                    raw_texts.append((quick_text, "Tier 1-Digital", "MarkItDown"))
                else:
                    # Tier 2: scan pages with PaddleOCR
                    doc = fitz.open(filepath)
                    ocr_engine = router._get_ocr_reader()
                    for page_num, page in enumerate(doc):
                        pix = page.get_pixmap()
                        img_path = f"/tmp/smartdb_page_{page_num}.png"
                        pix.save(img_path)
                        try:
                            ocr_result = ocr_engine.ocr(img_path, cls=True)
                            page_text, avg_conf = DocumentRouter._parse_paddle_result(ocr_result)

                            if page_text:
                                if avg_conf >= 0.7:
                                    md_text = _format_ocr_as_markdown(page_text, page_num=page_num)
                                    raw_texts.append((md_text, "Tier 2-Scan", "PaddleOCR"))
                                else:
                                    # Low confidence → escalate to Tier 3
                                    desc = router.process_tier3_image(img_path)
                                    if desc:
                                        md_text = _format_gemini_as_markdown(desc, page_num=page_num)
                                        raw_texts.append((md_text, "Tier 3-Complex", "Gemini-API"))
                            else:
                                # No OCR results at all → escalate to Tier 3
                                desc = router.process_tier3_image(img_path)
                                if desc:
                                    md_text = _format_gemini_as_markdown(desc, page_num=page_num)
                                    raw_texts.append((md_text, "Tier 3-Complex", "Gemini-API"))
                        finally:
                            if os.path.exists(img_path):
                                os.remove(img_path)
                    doc.close()

        # --- Image files: Tier 2 (OCR) → Tier 3 (Gemini) fallback -----------
        elif ext in ('jpg', 'jpeg', 'png'):
            ocr_engine = router._get_ocr_reader()
            ocr_result = ocr_engine.ocr(filepath, cls=True)
            page_text, avg_conf = DocumentRouter._parse_paddle_result(ocr_result)
            if page_text:
                if avg_conf >= 0.7:
                    md_text = _format_ocr_as_markdown(page_text)
                    raw_texts.append((md_text, "Tier 2-Scan", "PaddleOCR"))
                else:
                    desc = router.process_tier3_image(filepath)
                    if desc:
                        md_text = _format_gemini_as_markdown(desc)
                        raw_texts.append((md_text, "Tier 3-Complex", "Gemini-API"))
            else:
                desc = router.process_tier3_image(filepath)
                if desc:
                    md_text = _format_gemini_as_markdown(desc)
                    raw_texts.append((md_text, "Tier 3-Complex", "Gemini-API"))

        # --- Excel files: Tier 1 (Pandas) — NO Gemini fallback ----------------
        elif ext in ('xls', 'xlsx'):
            try:
                engine = 'xlrd' if ext == 'xls' else 'openpyxl'
                xls_file = pd.ExcelFile(filepath, engine=engine)
                excel_text = []
                for sheet_name in xls_file.sheet_names:
                    df = pd.read_excel(xls_file, sheet_name=sheet_name, dtype=str)
                    df.dropna(how='all', inplace=True)
                    df.dropna(axis=1, how='all', inplace=True)
                    df.fillna("", inplace=True)
                    if not df.empty:
                        sheet_md = f"## Лист: {sheet_name}\n\n" + df.to_markdown(index=False)
                        excel_text.append(sheet_md)
                xls_file.close()

                quick_text = "\n\n".join(excel_text)
                if quick_text.strip():
                    raw_texts.append((quick_text, "Tier 1-Digital", "Pandas-Excel"))
                else:
                    raise ValueError("Pandas extracted empty text.")
            except Exception as e:
                print(f"Pandas failed for {filename}: {e}. Likely password protected or corrupted. Moving to OUTPUT.")

        # --- Word files: Tier 1 (Mammoth) — NO Gemini fallback ----------------
        elif ext == 'docx':
            try:
                import mammoth
                with open(filepath, "rb") as docx_file:
                    # Convert docx to markdown, ignoring images entirely
                    result = mammoth.convert_to_markdown(docx_file, ignore_empty_paragraphs=True)
                    doc_text = result.value
                    doc_text = re.sub(r'!\[.*?\]\(data:image/.*?\)', '', doc_text)
                    if doc_text.strip():
                        raw_texts.append((doc_text, "Tier 1-Digital", "Mammoth-Word"))
                    else:
                        raise ValueError("Mammoth extracted empty text.")
            except Exception as e:
                print(f"Mammoth failed for {filename}: {e}. Likely corrupted. Moving to OUTPUT.")

        # --- All other digital formats: Tier 1 (MarkItDown) → Tier 3 fallback -
        else:
            if quick_text and len(quick_text.strip()) > 50:
                raw_texts.append((quick_text, "Tier 1-Digital", "MarkItDown"))
            else:
                # MarkItDown returned empty/short (e.g. scanned-image-only .docx).
                # Fallback to Tier 3 (Gemini Vision) instead of quarantining.
                print(f"MarkItDown returned empty for {filename}. Falling back to Tier 3 (Gemini).")
                desc = router.process_tier3_image(filepath)
                if desc:
                    md_text = _format_gemini_as_markdown(desc)
                    raw_texts.append((md_text, "Tier 3-Complex", "Gemini-API"))

    except Exception as e:
        if str(e) == "DailyLimitReached":
            print(f"Daily limit reached. Skipping {filename}.")
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)
            return []
        else:
            print(f"Processing failed for {filename}: {e}. Moving to OUTPUT (Quarantine).")
            if os.path.exists(original_filepath):
                shutil.move(original_filepath, os.path.join(OUTPUT_DIR, filename))
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)
            return []

    # ── Step 3: Quarantine if nothing was extracted ──────────────────────────
    if not raw_texts:
        print(f"No text extracted for {filename}. Moving to OUTPUT (Quarantine).")
        if os.path.exists(original_filepath):
            shutil.move(original_filepath, os.path.join(OUTPUT_DIR, filename))
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.remove(tmp_pdf_path)
        return []

    # ── Step 4: Final dedup (if early hash was skipped) ─────────────────────
    if file_hash is None:
        full_text = "\n\n".join(t[0] for t in raw_texts)
        file_hash = SemanticHasher.get_hash(full_text)
        if SemanticHasher.is_duplicate(file_hash):
            print(f"Duplicate file detected: {filename}. Permanently deleting.")
            if os.path.exists(original_filepath):
                os.remove(original_filepath)
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)
            return []

    SemanticHasher.mark_seen(file_hash)

    # ── Step 5: Save human-readable Markdown archive ────────────────────────
    full_text = "\n\n".join(t[0] for t in raw_texts)
    md_archive_path = os.path.join(PROCESSED_DIR, f"{filename}.md")
    try:
        with open(md_archive_path, 'w', encoding='utf-8') as f:
            f.write(full_text)
        print(f"Saved Markdown archive: {md_archive_path}")
    except Exception as e:
        print(f"Warning: failed to save .md archive for {filename}: {e}")

    # ── Step 6: Chunk & Inject Context ──────────────────────────────────────
    final_chunks = []
    for text, doc_type, method in raw_texts:
        chunks = chunk_and_inject(text, filename, doc_type, method)
        final_chunks.extend(chunks)

    if save_to_disk:
        out_file = os.path.join(CHUNKS_DIR, f"{filename}.json")
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(final_chunks, f, ensure_ascii=False, indent=2)

    # ── Step 7: Move original to PROCESSED & clean up temp PDF ──────────────
    if os.path.exists(original_filepath):
        shutil.move(original_filepath, os.path.join(PROCESSED_DIR, filename))
    if tmp_pdf_path and os.path.exists(tmp_pdf_path):
        os.remove(tmp_pdf_path)

    return final_chunks
