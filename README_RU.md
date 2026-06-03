<div align="center">

# 📄 Smart Document Parser

**Локальный модульный ETL-конвейер, превращающий сырые корпоративные документы в идеальные JSON-чанки для LLM.**

[![Status: v0.5-alpha](https://img.shields.io/badge/status-v0.5--alpha-orange?style=for-the-badge)](https://github.com/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Deployment: Local / .venv](https://img.shields.io/badge/deployment-Local%20%2F%20.venv-2496ED?style=for-the-badge&logo=linux&logoColor=white)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)

---

*Положите документы в папку. Получите чистые JSON-чанки. Одна команда. Полностью локально.*

[🇬🇧 Read in English](README.md) · [Ключевые фичи](#-ключевые-фичи) · [Быстрый старт](#-быстрый-старт) · [Как это работает](#-как-это-работает) · [Roadmap](#-roadmap)

</div>

---

> [!WARNING]
> **ПО стадии v0.5-alpha.** Активная разработка. Реализована Фаза 1 (умный парсинг, маршрутизация и чанкинг). API, структура директорий и конфигурация могут быть изменены без предупреждения.

## 📋 О проекте

Smart Document Parser — это первый структурный блок полностью локального RAG-конвейера (Retrieval-Augmented Generation). Он поглощает сырые корпоративные документы — **PDF, DOCX, DOC, XLSX, CSV и отсканированные изображения** — и создает чистые `.json` файлы с чанками, готовые к векторизации и использованию LLM.

Вся система работает как легковесный фоновый Python-демон (Watchdog) и разворачивается **одной командой** локально, без необходимости использования Docker.

## ✨ Ключевые фичи

### 🚀 Развертывание в один клик (Zero-Touch Deployment)
Один скрипт `setup.sh` делает **всё**:
- Автоматически создает изолированное виртуальное окружение Python (`.venv`).
- Устанавливает все необходимые зависимости, включая `pandas`, `mammoth`, `paddleocr` и `markitdown`.
- Запускает фоновый демон-Watchdog `ingestion_daemon.py`.

### 🛡️ Умная маршрутизация и отказоустойчивость (Body Armor)
- Файлы интеллектуально маршрутизируются к специализированным парсерам на основе их расширений.
- **Body Armor:** Демон защищен надежными блоками `try/except`. Excel-файлы под паролем, поврежденные Word-документы или некорректные PDF не обрушат демона; они безопасно отправляются в карантин в папку `OUTPUT/`.
- **Kill Switch для Gemini:** Для обработки сложных изображений (Tier 3) конвейер проверяет наличие API-ключа Gemini. Если ключ отсутствует в вашем `.env`, он безопасно пропускает Tier 3 без падения всего конвейера.

### 🔁 Дедупликация
- Демон вычисляет MD5-хэш первых 300 слов каждого документа и сохраняет их в `content_hashes.json`.
- Идентичные документы удаляются мгновенно, что предотвращает их повторную обработку и экономит дисковое пространство и API-запросы.

### 📊 Поддержка множества форматов

| Формат | Движок | Метод и стратегия |
|:-------|:-------|:-------|
| PDF, TXT, CSV | `MarkItDown` | Быстрое нативное извлечение текста с использованием движка Microsoft MarkItDown. |
| XLSX / XLS | `pandas` | Использует `dtype=str`, чтобы игнорировать математические/float ошибки в пустых ячейках. Файл разбивается на массивные чанки по 5000 символов, чтобы сохранить таблицы в идеальном виде. |
| DOCX | `mammoth` + Regex | Конвертирует Word в Markdown, используя Regex для удаления огромных инлайн-изображений в формате Base64 (например, логотипов), чтобы сохранить контекст LLM чистым. |
| DOC (Legacy) | LibreOffice (headless) | Невидимая фоновая конвертация в `.pdf`, который затем направляется в MarkItDown для чистого извлечения текста. |
| Scanned PDF | `PaddleOCR` (Tier 2) | Применяет PaddleOCR с PP-Structure для визуального распознавания таблиц (WIP). |

## 📁 Структура директорий

```text
smart-db/
│
├── setup.sh                 # 🚀 Скрипт развертывания (venv + зависимости + демон)
├── .env                     # Переменные окружения (API-ключи, конфиг)
├── ingestion_daemon.py      # Watchdog демон, мониторящий директорию INPUT/
│
├── INPUT/                   # 📥 Положите сырые документы сюда.
├── PROCESSED/               # 📤 Оригинальные файлы и полные .md архивы.
├── CHUNKS_STAGING/          # 📦 Финальные .json чанки для Vector DB.
└── OUTPUT/                  # 🛡️ Карантин для поврежденных файлов и файлов под паролем.
```

## 🚀 Быстрый старт

### Требования

- Linux-машина (протестировано на Linux Mint/Ubuntu).
- Python 3.10+

### Запуск конвейера

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/Falmer-128/smart-db.git
cd smart-db

# 2. Запустите скрипт развертывания (создает venv, ставит зависимости, запускает демона)
./setup.sh

# 3. Переместите ваши документы в папку INPUT/
cp /path/to/your/documents/* INPUT/
```

Извлеченные чанки начнут появляться в `CHUNKS_STAGING/`.

### Остановка демона

Если вы хотите остановить фоновый демон, просто выполните:

```bash
pkill -f "python3.*ingestion_daemon.py"
```

## 🔍 Как это работает

```mermaid
graph TD
    A["📥 INPUT/"] --> B{"🧠 Router"}
    
    B -->|"PDF, TXT, CSV"| C["MarkItDown"]
    B -->|".docx"| E["mammoth + Regex"]
    B -->|".xlsx / .xls"| F["pandas"]
    B -->|".doc (Legacy)"| L["LibreOffice (headless) → PDF"]
    L --> C
    B -->|"Scanned PDF"| G["PaddleOCR (Tier 2)"]
    
    C --> I["⚙️ Chunker (5000 chars)"]
    E --> I
    F --> I
    G --> I
    
    I --> J["📦 CHUNKS_STAGING/ (JSON)"]
    I --> K["📤 PROCESSED/ (.md Archives)"]
    
    B -.->|"Corrupted / Protected"| O["🛡️ OUTPUT/ (Quarantine)"]
```

## 🗺️ Roadmap

Этот проект является частью более масштабного видения: полностью локальной, приватной системы RAG, которая работает исключительно на вашем оборудовании.

```mermaid
graph TB
    subgraph "✅ Stage 1 — Document ETL (Current)"
        A["Raw Documents<br/>PDF · DOCX · XLSX"] --> B["Smart Document Parser<br/>(v0.5-alpha)"]
        B --> C["Clean JSON Chunks"]
    end

    subgraph "🔜 Stage 2 — Vector Store"
        C --> D["LanceDB<br/>Vectorization + Storage"]
    end

    subgraph "🔜 Stage 3 — Local LLM RAG"
        D <-->|"RAG queries"| E["Ollama / Qwen 2.5<br/>Local Question Answering"]
    end

    style A fill:#ff6b6b,stroke:#c0392b,color:#fff
    style B fill:#ffd93d,stroke:#f39c12,color:#333
    style C fill:#6bcb77,stroke:#27ae60,color:#fff
    style D fill:#4d96ff,stroke:#2980b9,color:#fff
    style E fill:#9b59b6,stroke:#8e44ad,color:#fff
```

| Стадия | Компонент | Роль | Статус |
|:------|:----------|:-----|:-------|
| **1** | **Smart Document Parser** | Извлечение, очистка и чанкинг текста из корпоративных документов | ✅ v0.5-alpha |
| **2** | **LanceDB** | Векторная база данных для сверхбыстрого поиска эмбеддингов документов | 🔜 Запланировано |
| **3** | **Ollama + Qwen 2.5** | Локальная LLM для приватных, быстрых ответов на вопросы | 🔜 Запланировано |

## 🤝 Вклад в проект (Contributing)

Проект находится на самых ранних этапах. Если вы хотите внести свой вклад:

1. Сделайте форк (Fork) репозитория
2. Создайте ветку для фичи (`git checkout -b feature/amazing-feature`)
3. Закоммитьте изменения (`git commit -m 'Add amazing feature'`)
4. Запушьте в ветку (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

## 📄 Лицензия

Этот проект лицензируется на условиях MIT License — подробнее смотрите в файле [LICENSE](LICENSE).

---

<div align="center">

**Сделано с ❤️ для локального AI-комьюнити**

*Если этот проект вам помог, пожалуйста, поставьте ⭐*

</div>
