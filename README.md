# Telegram-бот проверки задания №13 ЕГЭ

Оценка фото рукописного решения (0/1 за пункт а) + поиск похожих задач с решениями.

## Запуск (docker compose)

```bash
cp .env.example .env   # вписать BOT_TOKEN и GOOGLE_API_KEY
docker compose up -d --build
docker compose run --rm worker python -m core.build_equation_index  # 1 раз: собрать векторную базу
```

Сервисы: `bot` (aiogram, long polling), `worker` (Grader: OCR → чекер → LLM),
`api` (REST, порт 8000), `redis` (очередь RQ + FSM + rate-limit),
`qdrant` (векторная база, дашборд http://localhost:6333/dashboard).
Фото и SQLite — в `./storage/` (общий volume). Логи: `docker compose logs -f worker`.

### Масштабирование воркеров

```bash
docker compose up -d --scale worker=3
```

Воркеры делят одну очередь RQ (каждая задача достаётся ровно одному),
а лимит внешнего API (15 rpm Gemini, настраивается `GEMINI_RPM`) держит
общий счётчик в Redis — `bot/ratelimit.py`: слот берётся перед каждым
обращением к модели, при исчерпании окна воркер ждёт следующей минуты.

## Доменная модель

```mermaid
erDiagram
    STUDENT ||--o{ SUBMISSION : "присылает фото"
    SUBMISSION ||--o| OCR : "распознаётся в"
    OCR ||--o| OCR_EDIT : "правится пользователем"
    SUBMISSION ||--o| VERDICT : "оценивается"
    SUBMISSION ||--o| RATING : "оценка сервиса 👍/👎"
    SUBMISSION ||--o| USER_EQUATION : "пополняет базу (если нет дубля)"
    EQUATION ||--o{ EQUATION : "похожа на (косинусная близость)"
    SUBMISSION }o--o{ EQUATION : "похожие задачи"

    SUBMISSION {
        string id PK
        string status "new / awaiting_confirm / editing / grading / done / rejected / error"
        string photo_path
        int chat_id "0 - заявка из REST"
        float created_at
    }
    OCR {
        string equation "LaTeX"
        json steps "тип + LaTeX + комментарий"
        string answer
        bool not_math "фото без решения"
    }
    VERDICT {
        int score "0 / 1"
        string verdict_source "checker / gemma"
        bool suspicious_ocr
        string llm_comment
    }
    EQUATION {
        string equation "LaTeX, вектор TF-IDF+SVD-128"
        string solution
        string answer
    }
    USER_EQUATION {
        string equation
        int score
        date added_at
    }
```

Ключевое решение модели: у заявки хранятся **оба** состояния распознавания —
исходное (`ocr_original`) и исправленное пользователем (`ocr`). Их расхождение —
готовая разметка ошибок OCR для дообучения. Статусная машина заявки полностью
проживается и из Telegram, и через REST — ядро не знает о канале.

Поток: фото (альбом склеивается вертикально) → OCR (фото без решения
уравнения отсеиваются: правило not_math в промпте + проверка структуры) →
рендер распознанного LaTeX картинкой → пользователь подтверждает или правит
построчно («3: …», «У: …», «О: …») → оценка → вердикт + оценка 👍/👎 +
похожие задачи. Правки пользователя сохраняются в SQLite (`ocr_original`
vs `ocr`) — бесплатная разметка мисридов OCR; подтверждённые уравнения
копятся в коллекции `user_equations` (дедуп по нормализованному виду).

## REST API

Тот же конвейер, что у бота (общая очередь и БД), Swagger: http://localhost:8000/docs

```bash
curl -X POST localhost:8000/submissions -F "photo=@solution.jpg"   # → {"id": ...}
curl localhost:8000/submissions/<id>                # polling: статус/OCR/вердикт
curl -X PATCH localhost:8000/submissions/<id>/ocr \
     -H 'Content-Type: application/json' -d '{"equation": "..."}'  # правка OCR
curl -X POST localhost:8000/submissions/<id>/confirm               # запустить оценку
curl -X POST localhost:8000/submissions/<id>/rating \
     -H 'Content-Type: application/json' -d '{"rating": 1}'        # 👍/👎
```

## Тесты

```bash
pytest tests/                                # локально
docker compose run --rm worker pytest tests/ # в контейнере
```

## Ядро (Grader)

`core/grader.py` → класс `Grader`:

```python
from core.grader import Grader
grader = Grader()                          # ключи из окружения

ocr = grader.recognize('photo.jpg')        # показать пользователю, дать исправить
result = grader.grade('photo.jpg', ocr)    # {'score': 0|1, 'verdict_source', ...}
similar = grader.similar_tasks(ocr['equation'], top_k=3)
```

`result['suspicious_ocr'] == True` — сигнал переспросить пользователя
(условие противоречит шагам / уравнение не решается): показать распознанный
текст и дать исправить ошибки сканирования перед оценкой.

Проверка одного фото из консоли: `python -m core.grader photo.jpg`
(запускать из корня проекта — пути к моделям и базе относительные).

## Структура проекта

| Путь | Роль |
|---|---|
| `core/grader.py` | точка входа ядра: OCR → чекер → LLM-верификация |
| `core/checker_v2.py` | формальный чекер: sympy + Wolfram, восстановление условия |
| `core/pipeline.py` | OCR (дословная транскрипция) + FORMAL VERIFICATION (Gemma) |
| `core/normalize.py`, `core/verdict.py` | нормализация LaTeX, извлечение балла из ответа LLM |
| `core/search_equations.py` | поиск похожих задач (Qdrant, косинусная близость) |
| `core/user_equations.py` | накопление присланных уравнений с дедупликацией |
| `core/build_equation_index.py` | пересборка векторной базы из `data/*.jsonl` |
| `bot/` | Telegram-бот: хендлеры, FSM правок OCR, рендер LaTeX→PNG, SQLite |
| `worker/` | RQ-воркер: задачи recognize / grade / similar, доставка в чат |
| `api/` | REST (FastAPI): POST/GET/PATCH заявок, Swagger на /docs |
| `tests/` | pytest критических частей (42 теста) |
| `models/` | логрег типа уравнения + векторизатор запросов |
| `data/` | исходник векторной базы (jsonl, ~470 уравнений с решениями) |

Ограничение API Gemini (15 запросов/мин) соблюдает общий лимитер
в Redis (`bot/ratelimit.py`) + ретраи с паузами внутри ядра.

## Метрики

Валидация (на этих данных настраивались промпты и чекер):

| Сет | N | Accuracy | F1 (верные) | Weighted-F1 |
|---|---|---|---|---|
| Валидационная часть (после выверки) | 200 | 1.000 | 1.000 | 1.000 |

Отложенные данные (система их не видела):

| Сет | N | Accuracy | F1 (верные) | Weighted-F1 |
|---|---|---|---|---|
| Отложенные: чистые сканы | 67 | 0.955 | 0.975 | 0.960 |
| Отложенные: полные бланки ЕГЭ | 166 | 0.970 | 0.985 | 0.985 |
| Синтетика (решения с ошибками) | 46 | 1.000 | — | — |
| **Все данные суммарно** | **479** | **0.983** | **0.990** | **0.984** |

Ключевые свойства системы: не выставляет незаслуженных баллов, не пропускает
ошибок, ~60% решений оценивает мгновенно и бесплатно формальным чекером.
Известное ограничение — строгость к опискам ученика в условии и к ошибкам
распознавания мелких символов; закрывается подтверждением распознанного
текста пользователем в боте.
