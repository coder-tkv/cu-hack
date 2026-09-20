# Подключение ИИ-агентов к нашему прокси

**Ключ вам уже выдан** — он пришёл вам лично (в сообщении от администратора). Выпускать его самостоятельно не нужно, никуда заходить и регистрироваться тоже не нужно.

Один и тот же ключ работает сразу для **Claude Code**, **Codex** и **Pi агента**.

Всё, что нужно сделать — прописать в конфиг вашего клиента две вещи:

| | значение |
|---|---|
| **Адрес (Base URL)** | `https://cli.infra.skdtechai.com` |
| **Ключ (токен)** | тот, что вам выдали, вида `sk-...` |

Дальше по тексту выданный вам ключ обозначен как `ВАШ_КЛЮЧ` — везде подставляйте вместо него свой.

> **Что это такое.** Прокси объединяет несколько аккаунтов Claude: когда лимит одного заканчивается,
> запросы автоматически уходят на другой. Плюс он делает эти аккаунты совместимыми с обычным API,
> так что любой агент видит в нём привычный OpenAI/Anthropic-эндпоинт.

> ⚠️ Ключ личный. Не пересылайте его в общие чаты и не вставляйте в код или документацию.
> Файлы с ключом держите с правами `600` (команды ниже это делают).

---

## Выберите свой клиент

- [Claude Code](#claude-code) — CLI или плагин в VS Code
- [Codex](#codex)
- [Pi агент](#pi-агент)
- [Любой другой агент](#любой-другой-агент)

---

## Claude Code

Настройка общая и для CLI (`claude` в терминале), и для плагина в VS Code.

### 1. Проверьте, что Claude установлен

```bash
which claude
claude --version
```

Если плагин в VS Code предлагает авторизоваться через сайт Anthropic — **пропустите это окно**.
Авторизация пойдёт через наш ключ.

### 2. Пропишите прокси в `~/.claude/settings.json`

```bash
mkdir -p ~/.claude
```

Откройте (или создайте) файл `~/.claude/settings.json` и приведите его к виду:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://cli.infra.skdtechai.com",
    "ANTHROPIC_AUTH_TOKEN": "ВАШ_КЛЮЧ"
  }
}
```

Если в файле **уже были** другие настройки — не затирайте их, добавьте только блок `env`.
Если блок `env` уже есть — просто допишите внутрь него эти две строки.

```bash
chmod 600 ~/.claude/settings.json
```

### 3. Проверка

В терминале:

```bash
claude -p "ответь одним словом: работает"
```

В VS Code: перезапустите окно (`Cmd+Shift+P` → `Developer: Reload Window`), откройте **новую** вкладку
Claude и напишите «привет». Должен ответить без запроса авторизации.

### 4. Если у вас уже есть работающий агент

Можно не править файлы руками, а попросить его дословно:

> В `~/.claude/settings.json` добавь:
> ```json
> {
>   "env": {
>     "ANTHROPIC_BASE_URL": "https://cli.infra.skdtechai.com",
>     "ANTHROPIC_AUTH_TOKEN": "ВАШ_КЛЮЧ"
>   }
> }
> ```
> Существующие настройки не удаляй. Потом проверь, что `claude` (посмотри `which claude`) подхватывает конфиг.

---

## Codex

### 1. Установите Codex

Как CLI или как плагин. Запустите `codex` в терминале — откроется окно авторизации.
Логиниться через OpenAI **не нужно**, вместо этого подставим наш ключ.

### 2. Файл `~/.codex/config.toml`

```bash
mkdir -p ~/.codex
```

Содержимое:

```toml
model = "gpt-5.6-terra"
model_provider = "cliproxyapi"
model_reasoning_effort = "high"
approval_policy = "never"
sandbox_mode = "danger-full-access"

[model_providers.cliproxyapi]
name = "cliproxyapi"
base_url = "https://cli.infra.skdtechai.com/v1"
wire_api = "responses"
```

> Обратите внимание: у Codex в адресе обязательно есть `https://` и `/v1` на конце.
>
> `approval_policy = "never"` и `sandbox_mode = "danger-full-access"` дают агенту полный доступ
> к файлам без подтверждений. Хотите осторожнее — поставьте `approval_policy = "on-request"`
> и `sandbox_mode = "workspace-write"`.

### 3. Файл `~/.codex/auth.json`

```json
{
  "OPENAI_API_KEY": "ВАШ_КЛЮЧ"
}
```

```bash
chmod 600 ~/.codex/auth.json
```

Ключ тот же самый, что и для Claude, — не пугайтесь названия поля `OPENAI_API_KEY`.

### 4. Проверка

```bash
codex exec "ответь одним словом: работает"
```

---

## Pi агент

Pi хранит секреты и адреса в двух разных файлах.

```bash
mkdir -p ~/.pi/agent && chmod 700 ~/.pi/agent
```

### 1. Файл `~/.pi/agent/auth.json` — ключ

```json
{
  "anthropic": {
    "type": "api_key",
    "key": "ВАШ_КЛЮЧ"
  },
  "openai": {
    "type": "api_key",
    "key": "ВАШ_КЛЮЧ"
  }
}
```

Да, ключ **один и тот же** в обоих блоках — это не опечатка.

### 2. Файл `~/.pi/agent/models.json` — адреса

```json
{
  "providers": {
    "anthropic": {
      "baseUrl": "https://cli.infra.skdtechai.com",
      "api": "anthropic-messages",
      "modelOverrides": {
        "claude-opus-5": { "compat": { "allowedFallbackModels": [] } },
        "claude-fable-5": { "compat": { "allowedFallbackModels": [] } }
      }
    },
    "openai": {
      "baseUrl": "https://cli.infra.skdtechai.com/v1",
      "api": "openai-responses",
      "compat": {
        "supportsExplicitPromptCacheMode": false
      }
    }
  }
}
```

```bash
chmod 600 ~/.pi/agent/auth.json ~/.pi/agent/models.json
```

### 3. Проверка

```bash
pi -p "ответь одним словом: работает" --model anthropic/claude-opus-5
pi -p "ответь одним словом: работает" --model openai/gpt-5.6-terra
```

---

## Любой другой агент

Общее правило: выбираете провайдера **OpenAI-compatible**, и указываете

- **URL:** `https://cli.infra.skdtechai.com` (или `https://cli.infra.skdtechai.com/v1`, если клиент требует полный путь до эндпоинта)
- **API key / Token:** `ВАШ_КЛЮЧ`

---

## Шпаргалка

| Клиент | Файл(ы) | Поле с ключом | Base URL |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json` | `env.ANTHROPIC_AUTH_TOKEN` | `https://cli.infra.skdtechai.com` |
| Codex | `~/.codex/config.toml` + `~/.codex/auth.json` | `OPENAI_API_KEY` | `https://cli.infra.skdtechai.com/v1` |
| Pi | `~/.pi/agent/auth.json` + `~/.pi/agent/models.json` | `anthropic.key` / `openai.key` | `…` и `…/v1` |

Доступные модели: `claude-opus-5`, `claude-fable-5`, `gpt-5.6-terra`.

---

## Если не работает

| Симптом | Что делать |
|---|---|
| `401 Unauthorized`, `invalid api key` | Ключ скопирован не полностью (проверьте пробелы и переносы строк по краям) или он больше не активен — напишите администратору. |
| Claude всё равно просит залогиниться через браузер | Конфиг не подхватился. Проверьте, что JSON валиден: `cat ~/.claude/settings.json \| python3 -m json.tool`, затем перезапустите терминал / окно VS Code. |
| `404 Not Found` у Codex | В `base_url` забыли `https://` или `/v1`. Должно быть ровно `https://cli.infra.skdtechai.com/v1`. |
| Работает в терминале, но не в VS Code | Плагин читает конфиг при старте — нужен полный перезапуск окна и **новая** вкладка чата. |
| Игнорирует настройки, лезет не туда | Старые переменные окружения перебивают конфиг. Проверьте `env \| grep -i -E "anthropic\|openai"` и уберите `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` из `~/.zshrc` или `~/.bashrc`. |
| `model not found` | Опечатка в названии модели — сверьтесь со списком выше. |
| Ответы перестали приходить / лимиты | Прокси сам переключается на свободный аккаунт. Если не помогло — сообщите администратору. |
