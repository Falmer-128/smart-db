import os
import json
import hashlib
import time
import subprocess
from datetime import datetime
import shutil
import gc
import logging
import io
import fitz  # PyMuPDF
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

import pandas as pd
import google.generativeai as genai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice

print("Initializing Docling DocumentConverter with Russian OCR...")
pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = True
pipeline_options.do_table_structure = True
pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CUDA)

# Explicitly set Tesseract to use Russian and English dictionaries
pipeline_options.ocr_options = TesseractCliOcrOptions(lang=["rus", "eng"])

converter = DocumentConverter(
    allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.XLSX, InputFormat.IMAGE],
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)
print("Docling ready.")

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
            logger.warning("⏳ Local daily API counter reached 500. Sleeping for 3600 seconds (1 hour)...")
            time.sleep(3600)
            return RateLimiter.check_and_update()

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
# Markdown Formatting Helper for Tier 3 (Gemini) output
# ═════════════════════════════════════════════════════════════════════════════
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
# Document Router — Tier 3 (Vision API)
# ═════════════════════════════════════════════════════════════════════════════
class DocumentRouter:
    def _encode_image_to_base64(self, image_path):
        import base64
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _is_quota_error(self, e):
        """Check if an exception is a Google API quota/rate-limit error."""
        error_str = str(e).lower()
        return any(keyword in error_str for keyword in ["429", "quota", "exhausted", "resource_exhausted", "rate limit"])

    def process_tier3_image(self, image_path):
        """Send a single page image to a Vision API.
        Implements infinite sleep-and-retry on quota/rate-limit errors."""
        can_proceed, msg = RateLimiter.check_and_update()
        if not can_proceed:
            print(f"Skipping Vision API: {msg}")
            raise Exception("DailyLimitReached")

        provider = os.environ.get("VISION_PROVIDER", "google")
        api_key = os.environ.get("VISION_API_KEY")
        
        if not api_key:
            print("VISION_API_KEY not found in environment. Skipping Tier 3 processing.")
            return ""

        model_id = os.environ.get("VISION_MODEL", "")
        prompt = "Task: Transcribe all text from the image into Markdown. Format tables using Markdown syntax. Describe any complex schematics. Output ONLY the raw markdown content."

        while True:
            try:
                if provider == "google":
                    import google.generativeai as genai
                    genai.configure(api_key=api_key)
                    target_model = model_id if model_id else "gemini-3.1-flash-lite"
                    model = genai.GenerativeModel(target_model)
                    sample_file = genai.upload_file(path=image_path)
                    response = model.generate_content([sample_file, prompt])
                    return response.text

                elif provider == "anthropic":
                    import anthropic
                    import mimetypes
                    client = anthropic.Anthropic(api_key=api_key)
                    target_model = model_id if model_id else "claude-3-5-sonnet-20241022"
                    
                    media_type, _ = mimetypes.guess_type(image_path)
                    if not media_type:
                        media_type = "image/png"
                        
                    base64_image = self._encode_image_to_base64(image_path)
                    
                    response = client.messages.create(
                        model=target_model,
                        max_tokens=4096,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": media_type,
                                            "data": base64_image,
                                        },
                                    },
                                    {
                                        "type": "text",
                                        "text": prompt
                                    }
                                ],
                            }
                        ],
                    )
                    return response.content[0].text

                elif provider in ["openai", "openrouter", "nvidia"]:
                    import openai
                    import mimetypes
                    
                    base_url = None
                    target_model = model_id
                    
                    if provider == "openai":
                        if not target_model:
                            target_model = "gpt-4o"
                    elif provider == "openrouter":
                        base_url = "https://openrouter.ai/api/v1"
                    elif provider == "nvidia":
                        base_url = "https://integrate.api.nvidia.com/v1"
                    
                    client_args = {"api_key": api_key}
                    if base_url:
                        client_args["base_url"] = base_url
                        
                    client = openai.OpenAI(**client_args)
                    
                    media_type, _ = mimetypes.guess_type(image_path)
                    if not media_type:
                        media_type = "image/png"
                        
                    base64_image = self._encode_image_to_base64(image_path)
                    data_uri = f"data:{media_type};base64,{base64_image}"
                    
                    response = client.chat.completions.create(
                        model=target_model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": prompt
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": data_uri
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                    return response.choices[0].message.content

                else:
                    print(f"Unknown VISION_PROVIDER: {provider}")
                    return ""

            except Exception as e:
                if self._is_quota_error(e):
                    logger.warning("⏳ Google API Quota exceeded. Sleeping for 3600 seconds (1 hour)...")
                    time.sleep(3600)
                    continue
                print(f"Error with {provider} API: {e}")
                return ""


# ═════════════════════════════════════════════════════════════════════════════
# Chunking & Context Injection
# ═════════════════════════════════════════════════════════════════════════════
def chunk_and_inject(text, original_filename, doc_type, method, last_modified="Неизвестно"):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=5000,
        chunk_overlap=500,
        separators=["\n\n## ", "\n\n", "\n", " ", ""]
    )
    raw_chunks = splitter.split_text(text)

    final_chunks = []
    for chunk in raw_chunks:
        injected = f"[Файл: {original_filename} | Изменен: {last_modified} | Тип оригинала: {doc_type} | Метод: {method}] \n\n {chunk}"
        final_chunks.append({
            "text": injected,
            "metadata": {
                "filename": original_filename,
                "last_modified": last_modified,
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
def process_file(filepath, save_to_disk=False, enable_tier3=False):
    filename = os.path.basename(filepath)
    ext = filepath.lower().split('.')[-1]

    # ── Step 0: .doc Pre-Processing ──────────────────────────────────────────
    # Legacy binary .doc files cannot be parsed by Docling directly.
    # Convert to PDF via LibreOffice headless, then process as PDF.
    original_filepath = filepath  # Preserve for PROCESSED move / quarantine

    try:
        mtime = os.path.getmtime(original_filepath)
        last_modified_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        last_modified_date = "Неизвестно"

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

    # ── Step 1: Docling Conversion ───────────────────────────────────────────
    # Unified engine for all file types (PDF, DOCX, XLSX, Images).
    full_md = ""
    cloud_pages = []

    if ext in ['xlsx', 'xls']:
        # ── Pandas Intercept for Excel ───────────────────────────────────────
        # Docling hangs on massive .xlsx files (pure-Python cell-graph).
        # Pandas (C-backend) converts sheets to Markdown tables instantly.
        try:
            print(f"Processing {filename} with Pandas (Excel intercept)...")
            xls = pd.read_excel(filepath, sheet_name=None, header=None)
            md_parts = []

            for sheet_name, df in xls.items():
                # 1. Жесткая зачистка: удаляем полностью пустые строки/столбцы
                df.dropna(how='all', inplace=True)
                df.dropna(axis=1, how='all', inplace=True)
                
                if df.empty:
                    continue
                    
                md_parts.append(f"### Данные из листа Excel: {sheet_name}\n")
                
                # 2. Bulletproof sanitization: convert everything to text safely
                for col in df.columns:
                    # Safely replace NaNs with empty strings and cast everything to string element-by-element
                    df[col] = df[col].apply(lambda x: "" if pd.isna(x) else str(x))
                    # Sanitize for Markdown tables
                    df[col] = df[col].str.replace('\n', ' ', regex=False).str.replace('|', ' / ', regex=False).str.strip()

                # Build Markdown table
                header = df.iloc[0]
                md_parts.append("| " + " | ".join(header) + " |")
                md_parts.append("| " + " | ".join(["---"] * len(header)) + " |")

                for _, row in df.iloc[1:].iterrows():
                    values = list(row)
                    if all(v == "" for v in values):
                        continue
                    md_parts.append("| " + " | ".join(values) + " |")

                md_parts.append("")  # Blank line between sheets

            full_md = "\n".join(md_parts)
            print(f"Excel processed: {len(xls)} sheet(s) converted to Markdown.")

        except Exception as e:
            print(f"Pandas Excel processing failed for {filename}: {e}. Moving to OUTPUT (Quarantine).")
            if os.path.exists(original_filepath):
                shutil.move(original_filepath, os.path.join(OUTPUT_DIR, filename))
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)
            return []

    else:
        # ── Standard Docling Processing ──────────────────────────────────────
        try:
            print(f"Processing {filename} with Docling...")
            result = converter.convert(filepath)
            doc = result.document

            # Extract full document as Markdown
            full_md = doc.export_to_markdown()

            # ── Layout Router: Smart Fallback API Conservation ───
            cloud_pages_set = set()
            try:
                for item, _ in doc.iterate_items():
                    label_str = str(getattr(item, 'label', '')).lower()
                    
                    # 1. Route Figures (Always) and Large Pictures (Ignore small logos/stamps)
                    if "figure" in label_str:
                        for prov in getattr(item, 'prov', []):
                            if hasattr(prov, 'page_no'):
                                cloud_pages_set.add(prov.page_no)
                    elif "picture" in label_str:
                        is_large = False
                        for prov in getattr(item, 'prov', []):
                            if hasattr(prov, 'bbox'):
                                bbox = prov.bbox
                                # Check if width or height is substantial (e.g., > 200 points) to filter out small stamps
                                if (bbox.r - bbox.l) > 200 or (bbox.b - bbox.t) > 200:
                                    is_large = True
                                    break
                        if is_large:
                            for prov in getattr(item, 'prov', []):
                                if hasattr(prov, 'page_no'):
                                    cloud_pages_set.add(prov.page_no)
                    # 2. Smart Fallback for Tables (Conserve API limits)
                    elif "table" in label_str:
                        try:
                            item_text = item.export_to_markdown(doc=doc)
                            if "&#124;" in item_text or "tan" in item_text:
                                for prov in getattr(item, 'prov', []):
                                    if hasattr(prov, 'page_no'):
                                        cloud_pages_set.add(prov.page_no)
                        except Exception as e:
                            print(f"Warning: Failed to extract table text for Smart Fallback: {e}", flush=True)
                            # Fallback: assume failure and route to Cloud Vision
                            for prov in getattr(item, 'prov', []):
                                if hasattr(prov, 'page_no'):
                                    cloud_pages_set.add(prov.page_no)

            except Exception as e:
                print(f"Warning: Failed to iterate doc items for routing: {e}", flush=True)

            cloud_pages = sorted(list(cloud_pages_set))

            if cloud_pages:
                print(f"☁️ Complex elements (tables/figures) detected on pages: {cloud_pages}", flush=True)
            else:
                print("ℹ️ No complex elements flagged for Tier 3 processing.", flush=True)

        except Exception as e:
            print(f"Docling conversion failed for {filename}: {e}. Moving to OUTPUT (Quarantine).")
            if os.path.exists(original_filepath):
                shutil.move(original_filepath, os.path.join(OUTPUT_DIR, filename))
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)
            return []

    # ── Step 2: Early Deduplication ──────────────────────────────────────────
    if full_md and len(full_md.strip()) > 10:
        file_hash = SemanticHasher.get_hash(full_md)
        if SemanticHasher.is_duplicate(file_hash):
            print(f"Duplicate file detected: {filename}. Permanently deleting.")
            if os.path.exists(original_filepath):
                os.remove(original_filepath)
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)
            return []
    else:
        file_hash = None  # Will compute after Tier 3 enrichment if needed

    # ── Step 3: Build combined text ───────────────────────────────────────────
    tier3_texts = []

    # ── Step 4: Tier 3 Cloud Processing for Figure Pages ─────────────────────
    # If cloud_pages were detected and VISION_API_KEY is available,
    # render those pages as images and send to Gemini for detailed description.
    vision_api_key = os.environ.get("VISION_API_KEY")
    if cloud_pages and vision_api_key:
        genai.configure(api_key=vision_api_key)
        vision_model_name = os.environ.get("VISION_MODEL", "gemini-1.5-flash")
        vision_model = genai.GenerativeModel(vision_model_name)

        try:
            pdf_doc = fitz.open(filepath)
            num_pages = len(pdf_doc)

            for page_num in cloud_pages:
                # Docling page_num is 1-indexed; fitz is 0-indexed
                fitz_page_idx = page_num - 1
                if fitz_page_idx < 0 or fitz_page_idx >= num_pages:
                    continue

                try:
                    fitz_page = pdf_doc[fitz_page_idx]
                    pix = fitz_page.get_pixmap(dpi=400)
                    img_bytes = pix.tobytes("png")
                    pil_img = Image.open(io.BytesIO(img_bytes))

                    prompt = (
                        f"Это страница {page_num} из технического документа. "
                        "Здесь присутствует сложная схема, чертеж или таблица с диагностическими данными (параметры трансформаторов, сопротивление, тангенс угла потерь и т.д.). "
                        "Опиши содержимое максимально подробно в формате Markdown. "
                        "Если это принципиальная электрическая схема — перечисли ключевые компоненты. "
                        "КРИТИЧЕСКИ ВАЖНО: Если на странице есть таблицы с числами, перенеси их в идеальные Markdown-таблицы. Сохраняй абсолютную точность каждого числа, запятой и единицы измерения (Ом, кВ, %, tan). Никаких галлюцинаций."
                    )

                    non_quota_retries = 0
                    max_non_quota_retries = 5
                    while True:
                        try:
                            time.sleep(4)
                            response = vision_model.generate_content([pil_img, prompt])
                            tier3_texts.append(
                                f"## ☁️ Детальное описание схемы (Страница {page_num})\n\n{response.text}"
                            )
                            print(f"Page {page_num}: Complex figure processed via Gemini Vision.", flush=True)
                            break
                        except Exception as e:
                            error_str = str(e).lower()
                            is_quota = any(kw in error_str for kw in ["429", "quota", "exhausted", "resource_exhausted", "rate limit"])
                            if is_quota:
                                logger.warning("⏳ Google API Quota exceeded. Sleeping for 3600 seconds (1 hour)...")
                                time.sleep(3600)
                                continue
                            # Non-quota error: limited retries
                            non_quota_retries += 1
                            if non_quota_retries < max_non_quota_retries:
                                print(f"⚠️ API or Network error on page {page_num} (attempt {non_quota_retries}/{max_non_quota_retries}): {e}. Waiting 60s...", flush=True)
                                time.sleep(60)
                            else:
                                print(f"❌ Failed to process page {page_num} after {max_non_quota_retries} non-quota attempts: {e}", flush=True)
                                tier3_texts.append(
                                    f"## ☁️ Детальное описание схемы (Страница {page_num})\n\n"
                                    f"[Изображение пропущено из-за отсутствия сети или ответа сервера]"
                                )
                                break

                except Exception as e:
                    print(f"Tier 3 processing failed for page {page_num}: {e}", flush=True)

            pdf_doc.close()
        except Exception as e:
            print(f"Failed to open PDF for Tier 3 figure processing: {e}", flush=True)

    # ── Step 5: Quarantine if nothing was extracted ──────────────────────────
    if not full_md or not full_md.strip():
        print(f"No text extracted for {filename}. Moving to OUTPUT (Quarantine).")
        if os.path.exists(original_filepath):
            shutil.move(original_filepath, os.path.join(OUTPUT_DIR, filename))
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.remove(tmp_pdf_path)
        return []

    # ── Step 6: Final dedup ─────────────────────────────────────────────────
    if file_hash is None:
        file_hash = SemanticHasher.get_hash(full_md)
        if SemanticHasher.is_duplicate(file_hash):
            print(f"Duplicate file detected: {filename}. Permanently deleting.")
            if os.path.exists(original_filepath):
                os.remove(original_filepath)
            if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)
            return []

    SemanticHasher.mark_seen(file_hash)

    # ── Step 7: Save human-readable Markdown archive ────────────────────────
    # Combine Docling markdown with any Tier 3 enrichments
    full_text = full_md
    if tier3_texts:
        full_text = full_md + "\n\n" + "\n\n".join(tier3_texts)

    md_archive_path = os.path.join(PROCESSED_DIR, f"{filename}.md")
    try:
        with open(md_archive_path, 'w', encoding='utf-8') as f:
            f.write(full_text)
        print(f"Saved Markdown archive: {md_archive_path}")
    except Exception as e:
        print(f"Warning: failed to save .md archive for {filename}: {e}")

    # ── Step 8: Chunk & Inject Context ──────────────────────────────────────
    final_chunks = chunk_and_inject(full_text, filename, doc_type="Document", method="Docling", last_modified=last_modified_date)

    if save_to_disk:
        out_file = os.path.join(CHUNKS_DIR, f"{filename}.json")
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(final_chunks, f, ensure_ascii=False, indent=2)

    # ── Step 9: Move original to PROCESSED & clean up temp PDF ──────────────
    if os.path.exists(original_filepath):
        shutil.move(original_filepath, os.path.join(PROCESSED_DIR, filename))
    if tmp_pdf_path and os.path.exists(tmp_pdf_path):
        os.remove(tmp_pdf_path)

    gc.collect()

    return final_chunks
