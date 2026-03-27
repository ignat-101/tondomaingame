# TON Domain Game

Flask-игра для TON-доменов с колодами, матчмейкингом, Telegram Mini App и PvP.

## Быстрый запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Открыть: `http://127.0.0.1:5000`

## Запуск под хостинг (Play2Go style)

Проект готов для процесса через `gunicorn` и переменные окружения.

```bash
./run.sh
```

Используемые переменные:
- `PORT` (по умолчанию `5000`)
- `WEB_CONCURRENCY` (по умолчанию `2`)
- `GUNICORN_THREADS` (по умолчанию `4`)
- `GUNICORN_TIMEOUT` (по умолчанию `90`)

Команда запуска без скрипта:

```bash
gunicorn --bind 0.0.0.0:${PORT:-5000} app:app
```

## Настройки через терминал

Теперь настройки можно менять прямо из терминала без ручного редактирования кода:

```bash
./run.sh settings list
./run.sh settings get PORT
./run.sh settings set PORT 5000
./run.sh settings set ALLOW_GUEST_WITHOUT_DOMAIN 1
./run.sh settings unset TG_BOT_TOKEN
```

Аналогично:

```bash
python3 app.py settings list
python3 app.py settings set MATCHMAKING_REMATCH_COOLDOWN_SECONDS 5
```

Изменения записываются в `.env`.

## Основные переменные

- `TONAPI_KEY`
- `TG_WEBAPP_URL`
- `TG_BOT_TOKEN`
- `TG_BOT_USERNAME`
- `APP_DB_PATH`
- `ALLOW_GUEST_WITHOUT_DOMAIN`
- `MATCHMAKING_SEARCH_TTL_SECONDS`
- `MATCHMAKING_REMATCH_COOLDOWN_SECONDS`
- `PACK_PRICE_NANO`
- `PACK_RECEIVER_WALLET`

