# Call QA Service (Google Drive → Gemini AI → Database)

Сервіс на Python, який автоматично відстежує нові аудіозаписи дзвінків на Google Drive (режим поллінгу), перевіряє/створює менеджера в БД, валідує папку типу дзвінка, передає аудіо в **Google Gemini** на транскрибацію, потім оцінює якість розмови за критеріями і зберігає структурований результат у базу даних (**PostgreSQL** або **SQLite**).

## Можливості
- **Універсальне налаштування структури папок у `config.yaml`**: шаблон шляху (наприклад, `{manager_name}/{call_type}` або `{call_type}/{manager_name}`), білий список типів дзвінків (`valid_call_types`) та розширень аудіофайлів.
- **Керування промптами в `config.yaml`**: окремий промпт для транскрибації, базовий промпт оцінки якості та можливість задавати специфічні промпти для кожного типу дзвінка (`evaluation_by_call_type`).
- **Гарантований JSON-вивід (Structured Outputs)**: оцінка якості повертається за схемою `CallEvaluationResult` (Pydantic v2) і зберігається в таблицю `call_evaluations`.
- **Захист від дублювання**: кожен файл прив'язується до `drive_file_id` і не обробляється повторно при наступних циклах поллінгу.

## Швидкий старт

### 1. Налаштування змінних середовища
Скопіюйте `.env.example` у `.env` та вкажіть ключі:
```bash
cp .env.example .env
```
Покладіть JSON-ключ сервісного акаунта Google Cloud у `./credentials.json` та надайте цьому сервісному акаунту доступ (Reader) до кореневої папки на Google Drive (`GDRIVE_ROOT_FOLDER_ID`).

### 2. Запуск через Docker Compose (PostgreSQL + Worker)
```bash
docker compose up --build -d
```

### 3. Локальний запуск
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Постійний режим поллінгу
python -m src.main

# Разовий запуск (один цикл перевірки)
python -m src.main --once
```

### 4. Запуск тестів
```bash
pytest -v
```

# AICallAnalyzeApp
