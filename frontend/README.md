# Фронтенд «Что наделал агент»

Тонкий клиент к API бекенда: загружаем лог сессии Claude Code и запускаем разбор.
React 18+ / TypeScript / Vite / React Router, обычный `fetch`, без Redux и без моков.

## Запуск

```bash
cd frontend
npm install
npm run dev
```

Откроется http://localhost:5173. Бекенд должен слушать `http://localhost:8080`
(адрес берётся из `VITE_API_BASE`, см. `.env.development` и `.env.example`).

Бекенд поднимается из ветки `backend`:

```bash
git worktree add ../cu-backend backend
cd ../cu-backend
docker compose up -d --build
```

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
| `/analyses/:analysisId/report` | `ReportPage` — заглушка отчёта со скачиванием артефактов | макета пока нет |

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
