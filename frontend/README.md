# Фронтенд «Что наделал агент»

Тонкий клиент к API бекенда: загружаем лог сессии Claude Code и запускаем разбор.
React 18+ / TypeScript / Vite / React Router, обычный `fetch`, без Redux и без моков.

## Запуск

```bash
cd frontend
npm ci
npm run dev
```

Откроется http://localhost:5173. Бекенд должен слушать `http://localhost:8080`
(адрес берётся из `VITE_API_BASE`, см. `.env.development` и `.env.example`).

Бекенд уже находится в этой же ветке `liza`. Из корня репозитория:

```bash
docker compose up -d --build --wait
```

Для ML заполняем корневой `.env` по `.env.example`; если используем `ml/.env`, добавляем к Docker-команде `--env-file ml/.env` перед `up`. Не передаём API-ключ модели в frontend. При другом адресе API задаём `VITE_API_BASE` в `frontend/.env.local` и перезапускаем Vite.

Требуется Node.js 20.19+ или 22.12+; для команды предпочтительна актуальная LTS-ветка. Зависимости устанавливаем через `npm ci` по lock-файлу.

Сборка и проверка типов:

```bash
npm run build
npm run lint
```

## Экраны

| Путь | Экран | Слайд макета |
|---|---|---|
| `/` | `ModelPage` — выбор модели | 1 |
| `/upload` | `UploadPage` — загрузка лога | 2 |
| `/analyses/:analysisId` | `AnalysisPage` — стадии обработки, опрос статуса | 3 |
| `/analyses/:analysisId/report` | `ReportPage` — метрики, находки, доказательства и скачивание артефактов | 4 |

Опрос статуса живёт в `src/hooks/useAnalysisStatus.ts`: рекурсивный `setTimeout` раз в 2 секунды,
остановка на терминальном статусе, кнопка «Повторить» после трёх неудач подряд.

## Структура

```
src/
├── main.tsx              # роутер
├── api/
│   ├── config.ts         # API_BASE и лимит 50 МБ
│   ├── types.ts          # типы контракта (snake_case, как у бекенда)
│   └── client.ts         # createSession/getAnalysisState/getReport/getSteps/getStep/artifactUrl
├── components/           # TopBar, Layout, Button, StageList, WarningsBox, иконки
├── hooks/useAnalysisStatus.ts  # опрос статуса анализа
├── pages/                # ModelPage, UploadPage, AnalysisPage, ReportPage
├── styles/tokens.css     # токены дизайна из PDF-макета
└── utils/format.ts       # размер файла по-человечески
```

Все цвета, размеры, отступы и радиусы лежат в `src/styles/tokens.css` — значения сняты
из макета (`docs/ЦУ хак.pdf`), в вёрстке используются только переменные.
