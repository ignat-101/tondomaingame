# configuration file for TON Domain Game
# Здесь можно менять все параметры баланса/паттернов/TIERS и API-ключ.

# Базовый уровень атаки и защиты
ATTACK_BASE = 10
DEFENSE_BASE = 8

# Бонусы по паттернам 10K Club (настраиваемые)
PATTERN_BONUSES = {
    'mirror': {'attack': 20, 'defense': 20},
    'all_same': {'attack': 50, 'defense': 50},
    'stairs_up': {'attack': 15, 'defense': 10},
    'stairs_down': {'attack': 15, 'defense': 10},
    'double_repeat': {'attack': 10, 'defense': 8},
    'ambigram': {'attack': 25, 'defense': 25},
    'first_100': {'attack': 12, 'defense': 12},
    'zero_frames': {'attack': 8, 'defense': 12},
}

# Тиры редкости
TIERS = [
    {'name': 'Tier-0', 'min_score': 100},
    {'name': 'Tier-1', 'min_score': 70},
    {'name': 'Tier-2', 'min_score': 40},
    {'name': 'Tier-3', 'min_score': 0},
]

# TON API (пример: TonAPI), можно изменить на ваш endpoint
TONAPI_BASE_URL = 'https://tonapi.io/v2/accounts/{wallet}/nfts'
# В продакшене заполняется через переменную окружения
TONAPI_KEY = ''

# DNS TON API для проверки существования домена
DNS_TON_BASE_URL = 'https://dns.ton.org/v1/domains/{domain}'

# Конфиг webapp
HOST = '0.0.0.0'
PORT = 5000
DEBUG = False

# Production settings
RATE_LIMIT = '60 per minute'

# Telegram Mini App / Bot
TG_WEBAPP_URL = 'https://www.tondomaingame.online'
