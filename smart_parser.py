import os
import pytesseract
from pdf2image import convert_from_path
from pypdf import PdfReader
import docx  # (pip install python-docx)

# --- НАСТРОЙКИ ПАПОК (3 Уровня) ---
INPUT_DIR = "INPUT"           # 1. Сырые документы от пользователя
PROCESSED_DIR = "PROCESSED"   # 2. Чистые тексты для Нейросети (Скрытая база)
OUTPUT_DIR = "OUTPUT"         # 3. Финальные отчеты (Пока пустует)

# Создаем папки
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def ocr_pdf_file(pdf_path):
    print("  🟡 Текстового слоя нет. Включаю Tesseract OCR...")
    pages = convert_from_path(pdf_path, dpi=300)
    full_text = []
    for idx, page in enumerate(pages):
        text = pytesseract.image_to_string(page, lang='rus+eng')
        full_text.append(f"--- СТРАНИЦА {idx + 1} ---\n{text}\n")
    return "\n".join(full_text)


def extract_from_docx(docx_path):
    print("  🔵 Формат DOCX. Читаю напрямую...")
    doc = docx.Document(docx_path)
    full_text = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(full_text)


def extract_text_smart(file_path):
    ext = file_path.lower().split('.')[-1]
    
    if ext == 'docx':
        return extract_from_docx(file_path)
    elif ext == 'pdf':
        try:
            reader = PdfReader(file_path)
            direct_text = "".join([page.extract_text() or "" for page in reader.pages])
            if len(direct_text.strip()) > 50:
                print("  🟢 УСПЕХ: Найден текстовый слой! (PDF)")
                return direct_text.strip()
        except Exception:
            pass
        return ocr_pdf_file(file_path)
    else:
        print(f"  ❌ Неизвестный формат: {ext}")
        return None


def process_folder():
    print(f"🚀 Запуск сканера папки: {INPUT_DIR}")
    
    all_files = [f for f in os.listdir(INPUT_DIR) if os.path.isfile(os.path.join(INPUT_DIR, f))]
    if not all_files:
        print("Папка пуста. Нет файлов для обработки.")
        return

    processed_count = 0
    skipped_count = 0

    for filename in all_files:
        if filename.startswith('.'):
            continue
            
        input_path = os.path.join(INPUT_DIR, filename)
        base_name = os.path.splitext(filename)[0]
        
        # Теперь сохраняем в PROCESSED, а не в OUTPUT
        processed_filename = f"{base_name}.txt"
        processed_path = os.path.join(PROCESSED_DIR, processed_filename)
        
        # Проверка на идемпотентность идет по папке PROCESSED
        if os.path.exists(processed_path):
            print(f"⏭️ Пропуск: {filename} (уже в базе знаний)")
            skipped_count += 1
            continue
            
        print(f"\n📄 Обработка: {filename}")
        result_text = extract_text_smart(input_path)
        
        if result_text:
            with open(processed_path, "w", encoding="utf-8") as f:
                f.write(result_text)
            print(f"  ✅ Добавлено в базу знаний: {processed_path}")
            processed_count += 1
            
    print("\n" + "="*30)
    print(f"🏁 Итог работы:")
    print(f"   Добавлено новых текстов: {processed_count}")
    print(f"   Пропущено старых: {skipped_count}")
    print("="*30)

if __name__ == "__main__":
    process_folder()