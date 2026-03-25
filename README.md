# TON 10K Club Domain Game

Игра в стиле Викигачи для TON DNS-доменов (0000-9999.ton).

## Особенности

- Flask-приложение в одном основном файле
- Подключение кошелька через TonConnect или TonAPI
- Проверка домена на dns.ton.org
- Генерация карт на основе 10K Club паттернов
- Wiki gachi процесс боя: 5 раундов по статам с детальным логом раундов
- Интеграция с Telegram Mini App

## Установка

1. `python3 -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`

## Запуск локально

`python3 app.py`

Открыть: http://127.0.0.1:5000

## Развертывание на PythonAnywhere (бесплатно)

### Шаг 1: Регистрация
- Перейдите на [pythonanywhere.com](https://www.pythonanywhere.com/)
- Зарегистрируйтесь (бесплатный тариф: Beginner)

### Шаг 2: Загрузка кода
- В панели: "Files" → "Upload a file" или "Open bash console"
- Загрузите все файлы проекта в `/home/yourusername/ton-domain-game`
- Или: `git clone https://github.com/yourrepo/ton-domain-game.git`

### Шаг 3: Установка зависимостей
- Откройте Bash console
- `cd ton-domain-game`
- `python3 -m venv venv`
- `source venv/bin/activate`
- `pip install -r requirements.txt`

### Шаг 4: Настройка веб-приложения
- В панели: "Web" → "Add a new web app"
- Выберите: "Flask" → "Python 3.10"
- Source code: `/home/yourusername/ton-domain-game`
- Working directory: `/home/yourusername/ton-domain-game`
- WSGI configuration file: `/home/yourusername/ton-domain-game/wsgi.py`

### Шаг 5: Переменные окружения
- В "Web" → "Environment variables"
- Добавьте:
  - `TONAPI_KEY=your_tonapi_key`
  - `TG_WEBAPP_URL=https://yourusername.pythonanywhere.com`
  - `FLASK_ENV=production`

### Шаг 6: Перезагрузка
- Нажмите "Reload" в панели Web

### Шаг 7: Проверка
- Откройте `https://yourusername.pythonanywhere.com`
- Должен работать TonConnect и API

## Настройка характеристик

В `config.py`:
- ATTACK_BASE, DEFENSE_BASE
- PATTERN_BONUSES (бонусы за паттерны)
- TIERS (пороги редкости)
- TONAPI_KEY через `.env` или переменные окружения

## API Endpoints

- `/` - Главная страница
- `/api/nft-domains/<wallet>` - Получить домен из NFT
- `/api/check-domain/<domain>` - Проверить домен на dns.ton.org
- `/api/domain/<domain>` - Статистика домена
- `/api/open-pack/<domain>` - Открыть пак с 5 картами

## Telegram Mini App

Для Telegram Mini App разверните это Flask-приложение и укажите его URL в BotFather как Web App URL.
