import hashlib
import hmac
import html
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
import uuid
import calendar
import base64
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template_string, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import (
    ATTACK_BASE,
    DEBUG,
    DEFENSE_BASE,
    DNS_TON_BASE_URL,
    HOST,
    PATTERN_BONUSES,
    PORT,
    RATE_LIMIT,
    TG_WEBAPP_URL,
    TIERS,
    TONAPI_BASE_URL,
    TONAPI_KEY,
)
from tenkclub_service import explainDomainUniqueness, getDomainMetadata

load_dotenv()

app = Flask(__name__)
RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://').strip()

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT],
    storage_uri=RATELIMIT_STORAGE_URI,
)

HTTP = requests.Session()
HTTP.headers.update({'User-Agent': 'tondomaingame/1.0'})

APP_ROOT = os.getenv('APP_ROOT_URL', TG_WEBAPP_URL).rstrip('/')
TONAPI_KEY = os.getenv('TONAPI_KEY', TONAPI_KEY)
TG_WEBAPP_URL = os.getenv('TG_WEBAPP_URL', TG_WEBAPP_URL).rstrip('/')
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '').strip()
TG_BOT_USERNAME = os.getenv('TG_BOT_USERNAME', '').lstrip('@').strip()
TG_WEBHOOK_SECRET = os.getenv('TG_WEBHOOK_SECRET', '').strip()
TG_SETUP_TOKEN = os.getenv('TG_SETUP_TOKEN', '').strip()
HOST = os.getenv('HOST', HOST).strip()
PORT = int(os.getenv('PORT', str(PORT)))
DEBUG = os.getenv('DEBUG', str(DEBUG)).strip().lower() in {'1', 'true', 'yes', 'on'}
BASE_RATING = int(os.getenv('BASE_RATING', '1000'))
RATING_K_FACTOR = int(os.getenv('RATING_K_FACTOR', '32'))
DOMAIN_CACHE_TTL = int(os.getenv('DOMAIN_CACHE_TTL', '300'))
DEFAULT_INVITE_TIMEOUT_SECONDS = int(os.getenv('DEFAULT_INVITE_TIMEOUT_SECONDS', '60'))
MIN_INVITE_TIMEOUT_SECONDS = int(os.getenv('MIN_INVITE_TIMEOUT_SECONDS', '30'))
MAX_INVITE_TIMEOUT_SECONDS = int(os.getenv('MAX_INVITE_TIMEOUT_SECONDS', '600'))
TELEGRAM_INITDATA_MAX_AGE = int(os.getenv('TELEGRAM_INITDATA_MAX_AGE', '86400'))
ACTIVE_USER_WINDOW_SECONDS = int(os.getenv('ACTIVE_USER_WINDOW_SECONDS', '900'))
MATCHMAKING_SEARCH_TTL_SECONDS = int(os.getenv('MATCHMAKING_SEARCH_TTL_SECONDS', '150'))
MATCHMAKING_REMATCH_COOLDOWN_SECONDS = int(os.getenv('MATCHMAKING_REMATCH_COOLDOWN_SECONDS', '5'))
DB_PATH = Path(os.getenv('APP_DB_PATH', 'tondomaingame.db'))
TEN_K_CONFIG_TTL = int(os.getenv('TEN_K_CONFIG_TTL', '900'))
TEN_K_CONFIG_URL = 'https://10kclub.com/api/clubs/10k/config'
DAILY_FREE_PACKS = int(os.getenv('DAILY_FREE_PACKS', '1'))
PACK_PRICE_NANO = int(os.getenv('PACK_PRICE_NANO', '1000000000'))  # 1 TON
PACK_RECEIVER_WALLET = os.getenv('PACK_RECEIVER_WALLET', '').strip()
SEASON_PASS_PRICE_NANO = int(os.getenv('SEASON_PASS_PRICE_NANO', '1490000000'))
SEASON_PASS_RECEIVER_WALLET = os.getenv('SEASON_PASS_RECEIVER_WALLET', PACK_RECEIVER_WALLET).strip()
ALLOW_GUEST_WITHOUT_DOMAIN = os.getenv('ALLOW_GUEST_WITHOUT_DOMAIN', '0').strip().lower() in {'1', 'true', 'yes', 'on'}
ENV_FILE_PATH = Path(os.getenv('ENV_FILE_PATH', '.env'))
PACK_PITY_THRESHOLD = int(os.getenv('PACK_PITY_THRESHOLD', '20'))
TELEGRAM_NOTIFY_SCAN_INTERVAL_SECONDS = int(os.getenv('TELEGRAM_NOTIFY_SCAN_INTERVAL_SECONDS', '300'))

DOMAIN_CACHE = {}
TEN_K_CONFIG_CACHE = {'config': None, 'expires_at': 0.0}
TONCONNECT_SCRIPT_CACHE = {'body': None, 'content_type': 'application/javascript; charset=utf-8'}
TELEGRAM_NOTIFY_THREAD = None
TELEGRAM_NOTIFY_THREAD_LOCK = threading.Lock()

TONCONNECT_MANIFEST = {
    'url': APP_ROOT or None,
    'name': 'tondomaingame',
    'iconUrl': 'https://10kclub.com/favicon.ico',
    'termsOfUseUrl': 'https://ton.org',
    'privacyPolicyUrl': 'https://ton.org',
}

MARKETPLACE_LINKS = [
    {'label': 'Getgems', 'url': 'https://getgems.io/'},
    {'label': '10K Club', 'url': 'https://10kclub.com/'},
    {'label': 'TON DNS', 'url': 'https://dns.ton.org/'},
]

TEAM_NAMES = ('Cipher Squad', 'Domain Raiders')
CARD_TITLES = [
    'Mirror Pulse',
    'Zero Frame',
    'Cipher Surge',
    'Neon Relay',
    'DNS Breaker',
    'Ton Storm',
    'Pattern Lock',
    'Signal Bloom',
]
CARD_ABILITIES = [
    'Ускоряет атаку в первом раунде',
    'Поднимает защиту всей колоды',
    'Усиливает карты с редкими паттернами',
    'Даёт бонус против сильных соперников',
    'Добавляет критический урон по рейтингу',
    'Стабилизирует итоговую сумму очков',
]

PACK_TYPES = {
    'common': {
        'label': 'Обычный пак',
        'count': 3,
        'weights': {'basic': 70, 'rare': 20, 'epic': 9, 'legendary': 1},
        'lucky_bonus': False,
        'costs': {'pack_shards': 3},
    },
    'rare': {
        'label': 'Редкий пак',
        'count': 4,
        'weights': {'basic': 52, 'rare': 28, 'epic': 15, 'mythic': 4, 'legendary': 1},
        'lucky_bonus': False,
        'costs': {'rare_tokens': 1},
    },
    'epic': {
        'label': 'Эпический пак',
        'count': 5,
        'weights': {'basic': 35, 'rare': 33, 'epic': 22, 'mythic': 8, 'legendary': 2},
        'lucky_bonus': False,
        'costs': {'pack_shards': 6, 'rare_tokens': 1},
    },
    'lucky': {
        'label': 'Счастливый пак',
        'count': 4,
        'weights': {'basic': 42, 'rare': 26, 'epic': 18, 'mythic': 10, 'legendary': 4},
        'lucky_bonus': True,
        'costs': {'lucky_tokens': 1},
    },
    'cosmetic': {
        'label': 'Косметический пак',
        'count': 1,
        'weights': {'basic': 100},
        'lucky_bonus': False,
        'costs': {'cosmetic_packs': 1},
    },
}

COSMETIC_PACK_RARITY_WEIGHTS = {
    'basic': 32,
    'rare': 27,
    'epic': 20,
    'mythic': 13,
    'legendary': 8,
}

COSMETIC_THEME_DEFS = [
    {'slug': 'black', 'name': 'Black'},
    {'slug': 'onyx_black', 'name': 'Onyx Black'},
    {'slug': 'gunmetal', 'name': 'Gunmetal'},
    {'slug': 'ivory_white', 'name': 'Ivory White'},
    {'slug': 'platinum', 'name': 'Platinum'},
    {'slug': 'midnight_blue', 'name': 'Midnight Blue'},
    {'slug': 'rifle_green', 'name': 'Rifle Green'},
    {'slug': 'fire_engine', 'name': 'Fire Engine'},
    {'slug': 'deep_cyan', 'name': 'Deep Cyan'},
    {'slug': 'khaki_green', 'name': 'Khaki Green'},
    {'slug': 'emerald', 'name': 'Emerald'},
    {'slug': 'tactical_pine', 'name': 'Tactical Pine'},
    {'slug': 'ranger_green', 'name': 'Ranger Green'},
    {'slug': 'moonstone', 'name': 'Moonstone'},
    {'slug': 'cobalt_blue', 'name': 'Cobalt Blue'},
    {'slug': 'satin_gold', 'name': 'Satin Gold'},
    {'slug': 'old_gold', 'name': 'Old Gold'},
    {'slug': 'copper', 'name': 'Copper'},
    {'slug': 'neon_blue', 'name': 'Neon Blue'},
    {'slug': 'raspberry', 'name': 'Raspberry'},
]

COSMETIC_THEME_RARITY = {
    'black': 'legendary',
    'onyx_black': 'mythic',
    'gunmetal': 'mythic',
    'midnight_blue': 'epic',
    'ivory_white': 'epic',
    'platinum': 'rare',
    'rifle_green': 'epic',
    'old_gold': 'legendary',
    'neon_blue': 'legendary',
    'satin_gold': 'mythic',
    'fire_engine': 'mythic',
    'cobalt_blue': 'epic',
    'moonstone': 'epic',
    'emerald': 'epic',
    'tactical_pine': 'mythic',
    'ranger_green': 'mythic',
    'copper': 'epic',
    'raspberry': 'rare',
}

COSMETIC_THEME_DROP_WEIGHTS = {
    'black': 8,
    'onyx_black': 10,
    'gunmetal': 11,
    'midnight_blue': 12,
    'ivory_white': 14,
    'platinum': 17,
    'rifle_green': 13,
    'old_gold': 9,
    'neon_blue': 10,
    'satin_gold': 11,
    'fire_engine': 11,
    'deep_cyan': 15,
    'khaki_green': 16,
    'emerald': 14,
    'tactical_pine': 12,
    'ranger_green': 13,
    'moonstone': 14,
    'cobalt_blue': 15,
    'copper': 14,
    'raspberry': 15,
}

EMOJI_MONOGRAMS = [
    {'slug': 'sparkle', 'emoji': '✨', 'name': 'Sparkle Monogram'},
    {'slug': 'diamond', 'emoji': '💠', 'name': 'Diamond Monogram'},
    {'slug': 'crown', 'emoji': '👑', 'name': 'Crown Monogram'},
    {'slug': 'shield', 'emoji': '🛡️', 'name': 'Shield Monogram'},
    {'slug': 'swords', 'emoji': '⚔️', 'name': 'Swords Monogram'},
    {'slug': 'flame', 'emoji': '🔥', 'name': 'Flame Monogram'},
    {'slug': 'moon', 'emoji': '🌙', 'name': 'Moon Monogram'},
    {'slug': 'wave', 'emoji': '🌊', 'name': 'Wave Monogram'},
    {'slug': 'leaf', 'emoji': '🌿', 'name': 'Leaf Monogram'},
    {'slug': 'star', 'emoji': '⭐', 'name': 'Star Monogram'},
    {'slug': 'bolt', 'emoji': '⚡', 'name': 'Bolt Monogram'},
    {'slug': 'gem', 'emoji': '💎', 'name': 'Gem Monogram'},
    {'slug': 'eye', 'emoji': '🧿', 'name': 'Eye Monogram'},
    {'slug': 'ice', 'emoji': '❄️', 'name': 'Ice Monogram'},
    {'slug': 'sun', 'emoji': '☀️', 'name': 'Sun Monogram'},
    {'slug': 'comet', 'emoji': '☄️', 'name': 'Comet Monogram'},
    {'slug': 'trident', 'emoji': '🔱', 'name': 'Trident Monogram'},
    {'slug': 'anchor', 'emoji': '⚓', 'name': 'Anchor Monogram'},
    {'slug': 'club', 'emoji': '♣️', 'name': 'Club Monogram'},
    {'slug': 'spade', 'emoji': '♠️', 'name': 'Spade Monogram'},
]

SEASON_PASS_TRACK = [
    {'level': 1, 'free_reward': {'kind': 'currency', 'label': '💠 4 осколка', 'pack_shards': 4}, 'premium_reward': {'kind': 'currency', 'label': '💠 8 осколков', 'pack_shards': 8}},
    {'level': 2, 'free_reward': None, 'premium_reward': {'kind': 'currency', 'label': '🎟️ 1 редкий токен', 'rare_tokens': 1}},
    {'level': 3, 'free_reward': {'kind': 'currency', 'label': '🎟️ 1 редкий токен', 'rare_tokens': 1}, 'premium_reward': {'kind': 'currency', 'label': '💠 10 осколков', 'pack_shards': 10}},
    {'level': 4, 'free_reward': None, 'premium_reward': {'kind': 'cosmetic_pack'}},
    {'level': 5, 'free_reward': {'kind': 'currency', 'label': '✨ 1 lucky-токен', 'lucky_tokens': 1}, 'premium_reward': {'kind': 'currency', 'label': '🎟️ 2 редких токена', 'rare_tokens': 2}},
    {'level': 6, 'free_reward': None, 'premium_reward': {'kind': 'currency', 'label': '💠 12 осколков', 'pack_shards': 12}},
    {'level': 7, 'free_reward': {'kind': 'currency', 'label': '💠 5 осколков', 'pack_shards': 5}, 'premium_reward': {'kind': 'currency', 'label': '✨ 1 lucky-токен', 'lucky_tokens': 1}},
    {'level': 8, 'free_reward': None, 'premium_reward': {'kind': 'cosmetic_pack'}},
    {'level': 9, 'free_reward': {'kind': 'currency', 'label': '🎟️ 1 редкий токен', 'rare_tokens': 1}, 'premium_reward': {'kind': 'currency', 'label': '💠 14 осколков', 'pack_shards': 14}},
    {'level': 10, 'free_reward': None, 'premium_reward': {'kind': 'currency', 'label': '🎟️ 2 редких токена', 'rare_tokens': 2}},
    {'level': 11, 'free_reward': {'kind': 'currency', 'label': '✨ 1 lucky-токен', 'lucky_tokens': 1}, 'premium_reward': {'kind': 'currency', 'label': '💠 16 осколков', 'pack_shards': 16}},
    {'level': 12, 'free_reward': None, 'premium_reward': {'kind': 'cosmetic_pack'}},
    {'level': 13, 'free_reward': {'kind': 'currency', 'label': '💠 6 осколков', 'pack_shards': 6}, 'premium_reward': {'kind': 'currency', 'label': '✨ 2 lucky-токена', 'lucky_tokens': 2}},
    {'level': 14, 'free_reward': None, 'premium_reward': {'kind': 'currency', 'label': '🎟️ 2 редких токена', 'rare_tokens': 2}},
    {'level': 15, 'free_reward': {'kind': 'currency', 'label': '💠 8 осколков', 'pack_shards': 8}, 'premium_reward': {'kind': 'currency', 'label': '💠 20 осколков', 'pack_shards': 20}},
    {'level': 16, 'free_reward': {'kind': 'cosmetic_pack'}, 'premium_reward': {'kind': 'currency', 'label': '✨ 2 lucky-токена', 'lucky_tokens': 2}},
]


def _build_cosmetic_catalog():
    catalog = []
    type_rarity_boost = {
        'frame': 0,
        'cardback': 0,
        'arena': 1,
        'guild': 1,
    }
    type_drop_multiplier = {
        'frame': 1.0,
        'cardback': 1.05,
        'arena': 0.95,
        'guild': 1.0,
    }
    rarity_ladder = ['basic', 'rare', 'epic', 'mythic', 'legendary']
    premium_map = {
        'black': {'frame': 'season_pass'},
        'onyx_black': {'cardback': 'season_pass'},
        'ivory_white': {'arena': 'season_pass'},
        'midnight_blue': {'guild': 'season_pass'},
        'fire_engine': {'frame': 'season_pass'},
        'deep_cyan': {'cardback': 'season_pass'},
        'khaki_green': {'arena': 'season_pass'},
        'satin_gold': {'guild': 'season_pass'},
        'old_gold': {'frame': 'season_pass'},
        'neon_blue': {'arena': 'season_pass'},
    }
    for theme in COSMETIC_THEME_DEFS:
        slug = theme['slug']
        name = theme['name']
        theme_sources = premium_map.get(slug, {})
        themed_items = [
            {'key': f'frame_{slug}', 'type': 'frame', 'name': f'{name} Frame', 'source': theme_sources.get('frame', 'cosmetics')},
            {'key': f'cardback_{slug}', 'type': 'cardback', 'name': f'{name} Monogram', 'source': theme_sources.get('cardback', 'season_pass')},
            {'key': f'arena_{slug}', 'type': 'arena', 'name': f'{name} Arena', 'source': theme_sources.get('arena', 'cosmetics')},
            {'key': f'guild_banner_{slug}', 'type': 'guild', 'name': f'{name} Banner', 'source': theme_sources.get('guild', 'cosmetics')},
        ]
        for item in themed_items:
            base_rarity = COSMETIC_THEME_RARITY.get(slug, 'rare')
            base_index = rarity_ladder.index(base_rarity)
            boosted_index = min(len(rarity_ladder) - 1, base_index + type_rarity_boost.get(item['type'], 0))
            item['rarity_key'] = rarity_ladder[boosted_index]
            base_drop_weight = float(COSMETIC_THEME_DROP_WEIGHTS.get(slug, 15))
            item['drop_weight'] = round(base_drop_weight * type_drop_multiplier.get(item['type'], 1.0), 2)
            item['nft_family'] = item['type']
            catalog.append(item)
    emoji_rarities = ['basic', 'rare', 'rare', 'epic', 'epic', 'mythic', 'mythic', 'legendary', 'basic', 'rare', 'epic', 'legendary']
    for index, item in enumerate(EMOJI_MONOGRAMS):
        catalog.append({
            'key': f'emoji_{item["slug"]}',
            'type': 'emoji',
            'name': item['name'],
            'emoji': item['emoji'],
            'source': 'cosmetics',
            'nft_family': 'emoji',
            'rarity_key': emoji_rarities[index % len(emoji_rarities)],
            'drop_weight': 16,
        })
    catalog.extend([
        {'key': 'frame_stock_gray', 'type': 'frame', 'name': 'Stock Gray Frame', 'source': 'stock', 'nft_family': 'frame', 'rarity_key': 'basic', 'drop_weight': 22},
        {'key': 'cardback_stock_plain', 'type': 'cardback', 'name': 'Stock Plain Cardback', 'source': 'stock', 'nft_family': 'cardback', 'rarity_key': 'basic', 'drop_weight': 22},
        {'key': 'arena_stock_grid', 'type': 'arena', 'name': 'Stock Grid Arena', 'source': 'stock', 'nft_family': 'arena', 'rarity_key': 'basic', 'drop_weight': 20},
        {'key': 'guild_banner_stock_plain', 'type': 'guild', 'name': 'Stock Plain Banner', 'source': 'stock', 'nft_family': 'guild', 'rarity_key': 'basic', 'drop_weight': 20},
        {'key': 'emoji_stock_dot', 'type': 'emoji', 'name': 'Stock Dot Monogram', 'emoji': '•', 'source': 'stock', 'nft_family': 'emoji', 'rarity_key': 'basic', 'drop_weight': 18},
    ])
    return catalog


COSMETIC_CATALOG = _build_cosmetic_catalog()
DEFAULT_STOCK_COSMETICS = [
    'frame_stock_gray',
    'cardback_stock_plain',
    'arena_stock_grid',
    'guild_banner_stock_plain',
    'emoji_stock_dot',
]

PAGE_TEMPLATE = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>tondomaingame</title>
  <meta name="theme-color" content="#09111f">
  <meta name="description" content="TON 10K Club mini game with wallet connection, real domain checks and Telegram integration.">
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="/vendor/tonconnect-ui.min.js"></script>
  <script>
    function loadExternalScript(src) {
      return new Promise((resolve, reject) => {
        const existing = Array.from(document.scripts || []).find((node) => node.src === src);
        if (existing) {
          if (existing.dataset.loaded === 'true') {
            resolve(true);
            return;
          }
          existing.addEventListener('load', () => resolve(true), {once: true});
          existing.addEventListener('error', () => reject(new Error(`Не удалось загрузить ${src}`)), {once: true});
          return;
        }
        const script = document.createElement('script');
        script.src = src;
        script.async = true;
        script.crossOrigin = 'anonymous';
        script.addEventListener('load', () => {
          script.dataset.loaded = 'true';
          resolve(true);
        }, {once: true});
        script.addEventListener('error', () => reject(new Error(`Не удалось загрузить ${src}`)), {once: true});
        document.head.appendChild(script);
      });
    }

    async function ensureTonConnectUiScript() {
      if (window.TON_CONNECT_UI && window.TON_CONNECT_UI.TonConnectUI) {
        return true;
      }
      const candidates = [
        `${window.location.origin}/vendor/tonconnect-ui.min.js`,
        'https://cdn.jsdelivr.net/npm/@tonconnect/ui@2.0.9/dist/tonconnect-ui.min.js',
        'https://unpkg.com/@tonconnect/ui@2.0.9/dist/tonconnect-ui.min.js'
      ];
      for (const src of candidates) {
        try {
          await loadExternalScript(src);
          if (window.TON_CONNECT_UI && window.TON_CONNECT_UI.TonConnectUI) {
            return true;
          }
        } catch (_) {
        }
      }
      return false;
    }
  </script>
  <style>
    :root {
      --bg: #071019;
      --panel: rgba(9, 20, 37, 0.82);
      --panel-strong: rgba(10, 24, 44, 0.92);
      --line: rgba(121, 217, 255, 0.18);
      --text: #eef6ff;
      --muted: #97afc8;
      --accent: #45d7ff;
      --accent-2: #53f6b8;
      --danger: #ff7a86;
      --warning: #ffd36e;
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.38);
      --radius: 24px;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: var(--app-height, 100vh);
      overflow-x: hidden;
      color: var(--text);
      font-family: "Avenir Next", "Helvetica Neue", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(69, 215, 255, 0.18), transparent 30%),
        radial-gradient(circle at top right, rgba(83, 246, 184, 0.12), transparent 28%),
        linear-gradient(160deg, #030814 0%, #09111f 48%, #071a1d 100%);
    }

    a { color: var(--accent); }

    .shell {
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 20px 24px 132px;
    }

    .top-app-nav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 12px 18px;
      margin-bottom: 18px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      border-radius: 26px;
      background: rgba(250, 252, 255, 0.92);
      color: #6e7380;
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.14);
      backdrop-filter: blur(16px);
    }

    .top-app-brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
      color: #151b28;
      font-weight: 700;
      font-size: 16px;
    }

    .top-app-brand-badge {
      width: 46px;
      height: 46px;
      border-radius: 16px;
      border: 1px solid rgba(28, 39, 58, 0.1);
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(237,242,248,0.9));
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.55);
    }

    .top-app-brand-badge img {
      width: 44px;
      height: 44px;
      object-fit: contain;
      transform: translateY(2px);
    }

    .top-app-brand span {
      white-space: nowrap;
    }

    .top-app-nav-actions {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 20px;
      flex: 1 1 auto;
      min-width: 0;
    }

    .top-app-nav-link {
      border: 0;
      background: transparent;
      color: #8c909b;
      font-size: clamp(18px, 2.4vw, 28px);
      font-weight: 500;
      line-height: 1;
      padding: 10px 6px;
      min-height: auto;
      border-radius: 0;
      box-shadow: none;
      position: relative;
    }

    .top-app-nav-link:hover:not(:disabled) {
      transform: none;
      color: #434b59;
      background: transparent;
    }

    .top-app-nav-link.active {
      color: #171d29;
    }

    .top-app-nav-link.active::after {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      bottom: -8px;
      height: 3px;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(69, 215, 255, 0.94), rgba(83, 246, 184, 0.94));
    }

    .hero {
      display: grid;
      gap: 18px;
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 28px;
      background: linear-gradient(150deg, rgba(12, 30, 55, 0.95), rgba(10, 18, 33, 0.9));
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
      overflow: hidden;
    }

    .hero-top {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
      min-width: 0;
    }

    .hero-top > div:first-child {
      min-width: 0;
      flex: 1 1 520px;
      overflow: hidden;
    }

    .hero-top .badge-row {
      flex: 0 0 auto;
    }

    @keyframes mascotFloat {
      0%, 100% { transform: translateY(0px); }
      50% { transform: translateY(-8px); }
    }

    .mascot-widget {
      position: fixed;
      left: 18px;
      bottom: calc(18px + env(safe-area-inset-bottom));
      z-index: 60;
      display: grid;
      gap: 10px;
      align-items: end;
      justify-items: start;
      pointer-events: none;
    }

    .mascot-widget.open .mascot-popover {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }

    .mascot-fab {
      width: 78px;
      height: 78px;
      border-radius: 24px;
      border: 1px solid rgba(111, 204, 255, 0.28);
      background:
        radial-gradient(circle at 50% 28%, rgba(69, 215, 255, 0.22), transparent 42%),
        linear-gradient(180deg, rgba(8, 20, 36, 0.96), rgba(4, 12, 24, 0.98));
      box-shadow: 0 20px 36px rgba(0, 0, 0, 0.32), inset 0 0 0 1px rgba(121, 217, 255, 0.08);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      cursor: pointer;
      pointer-events: auto;
      padding: 0;
    }

    .mascot-fab img {
      width: 82px;
      height: 82px;
      object-fit: contain;
      transform: translateY(3px);
      filter: drop-shadow(0 14px 20px rgba(0, 0, 0, 0.25));
    }

    .mascot-popover {
      width: min(320px, calc(100vw - 32px));
      padding: 14px;
      border-radius: 22px;
      border: 1px solid rgba(111, 204, 255, 0.24);
      background:
        radial-gradient(circle at top right, rgba(69, 215, 255, 0.16), transparent 36%),
        linear-gradient(180deg, rgba(10, 22, 38, 0.98), rgba(6, 14, 24, 0.98));
      box-shadow: 0 28px 50px rgba(0, 0, 0, 0.34);
      opacity: 0;
      transform: translateY(8px) scale(0.98);
      transform-origin: bottom left;
      transition: opacity 180ms ease, transform 180ms ease;
      pointer-events: none;
    }

    .mascot-popover-head {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }

    .mascot-popover-head img {
      width: 56px;
      height: 56px;
      object-fit: contain;
      flex: 0 0 auto;
    }

    .mascot-popover-title {
      font-size: 18px;
      font-weight: 800;
      line-height: 1.1;
    }

    .mascot-popover-copy {
      font-size: 13px;
      line-height: 1.45;
      color: var(--muted);
      margin-top: 4px;
    }

    .mascot-popover-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }

    .mascot-popover-actions button {
      min-height: 42px;
      padding: 10px 12px;
      font-size: 13px;
    }

    .eyebrow {
      color: var(--accent-2);
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      margin-bottom: 12px;
    }

    h1 {
      margin: 0;
      font-size: clamp(40px, 7vw, 72px);
      line-height: 0.95;
      overflow-wrap: anywhere;
      word-break: break-word;
      max-width: 100%;
    }

    h1 br {
      display: none;
    }

    .hero p {
      margin: 0;
      max-width: 720px;
      color: var(--muted);
      font-size: 17px;
      line-height: 1.6;
    }

    .badge-row, .stats-strip, .links-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .stepper {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      width: 100%;
    }

    .badge, .step-chip, .stat-chip, .market-link {
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.04);
      padding: 9px 14px;
      font-size: 14px;
      color: var(--muted);
    }

    .step-chip {
      width: 100%;
      text-align: center;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .step-chip.active {
      color: var(--text);
      border-color: rgba(69, 215, 255, 0.5);
      background: rgba(69, 215, 255, 0.16);
    }

    .layout {
      display: grid;
      grid-template-columns: 1.25fr 0.75fr;
      gap: 22px;
      margin-top: 22px;
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--panel);
      box-shadow: var(--shadow);
      padding: 22px;
      backdrop-filter: blur(12px);
    }

    .panel h2, .panel h3 {
      margin-top: 0;
    }

    .view {
      display: none;
      animation: reveal 280ms ease;
    }

    .view.active { display: block; }

    @keyframes reveal {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .actions, .row, .stack {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .stack {
      flex-direction: column;
      align-items: stretch;
    }

    button, select, input {
      font: inherit;
      border-radius: 14px;
      border: 1px solid rgba(121, 217, 255, 0.22);
    }

    button {
      cursor: pointer;
      background: linear-gradient(135deg, rgba(69, 215, 255, 0.18), rgba(83, 246, 184, 0.16));
      color: var(--text);
      padding: 13px 18px;
      min-height: 48px;
      transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
    }

    button:hover:not(:disabled) {
      transform: translateY(-1px);
      border-color: rgba(69, 215, 255, 0.52);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }

    .secondary {
      background: rgba(255, 255, 255, 0.04);
    }

    .danger {
      border-color: rgba(255, 122, 134, 0.34);
      background: rgba(255, 122, 134, 0.1);
    }

    input, select {
      width: 100%;
      min-height: 48px;
      padding: 12px 14px;
      background: rgba(3, 10, 20, 0.78);
      color: var(--text);
    }

    .domain-grid, .card-grid, .mode-grid, .leaderboard, .team-grid {
      display: grid;
      gap: 14px;
    }

    .domain-grid, .mode-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .card-grid { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
    .leaderboard, .team-grid { grid-template-columns: 1fr; }

    .domain-card, .game-card, .mode-card, .leaderboard-item, .team-card {
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.035);
      padding: 18px;
    }

    .domain-card.selected {
      border-color: rgba(83, 246, 184, 0.58);
      box-shadow: 0 0 0 1px rgba(83, 246, 184, 0.32);
    }

    .mode-grid {
      position: relative;
      perspective: 1400px;
    }

    .mode-grid.mode-focus::before {
      content: "";
      position: absolute;
      inset: -10px;
      border-radius: 28px;
      background: rgba(2, 8, 16, 0.58);
      backdrop-filter: blur(6px);
      z-index: 0;
      pointer-events: none;
    }

    .mode-grid.mode-focus .mode-card:not(.active-mode) {
      transform: scale(0.96);
      opacity: 0.52;
      filter: blur(1.5px);
    }

    .mode-card {
      position: relative;
      z-index: 1;
      overflow: hidden;
      isolation: isolate;
      transform-style: preserve-3d;
      transition: transform 320ms cubic-bezier(.2,.8,.2,1), box-shadow 320ms ease, border-color 320ms ease, opacity 260ms ease;
    }

    .mode-card.preferred-mode {
      padding-top: 62px;
      border-color: rgba(255, 211, 110, 0.58);
      box-shadow: 0 22px 44px rgba(255, 211, 110, 0.12);
    }

    .mode-card.preferred-mode::before {
      content: attr(data-usage-label);
      position: absolute;
      left: 16px;
      top: 14px;
      display: inline-flex;
      align-items: center;
      max-width: calc(100% - 32px);
      padding: 7px 12px;
      border-radius: 999px;
      background: linear-gradient(135deg, rgba(255, 211, 110, 0.16), rgba(255, 190, 92, 0.08));
      border: 1px solid rgba(255, 211, 110, 0.34);
      color: #ffe9a5;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      box-shadow: 0 10px 24px rgba(255, 211, 110, 0.12);
      backdrop-filter: blur(10px);
      pointer-events: none;
    }

    .mode-card::after {
      content: "";
      position: absolute;
      inset: 0;
      border-radius: 20px;
      background: linear-gradient(135deg, rgba(69, 215, 255, 0.18), rgba(83, 246, 184, 0.14), transparent 70%);
      opacity: 0;
      transition: opacity 320ms ease;
      pointer-events: none;
    }

    .mode-card:hover {
      transform: translateY(-2px) scale(1.01);
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.16);
    }

    .mode-card.active-mode {
      border-color: rgba(83, 246, 184, 0.58);
      box-shadow: 0 12px 30px rgba(69, 215, 255, 0.16);
      transform: translateY(-4px) scale(1.01);
    }

    .mode-card.active-mode::after {
      opacity: 1;
    }

    .mode-card.active-mode .mode-burst {
      opacity: 1;
      transform: scale(1);
    }

    .mode-grid.matchmaking-live {
      perspective: none;
    }

    .mode-grid.matchmaking-live::before,
    .mode-grid.matchmaking-live.mode-focus::before {
      display: none;
    }

    .mode-grid.matchmaking-live .mode-card {
      transform: none;
      filter: none;
      opacity: 0.82;
    }

    .mode-grid.matchmaking-live .mode-card:hover {
      transform: none;
      box-shadow: none;
    }

    .mode-grid.matchmaking-live .mode-card::after {
      inset: 0;
      opacity: 0;
    }

    .mode-grid.matchmaking-live .mode-card.active-mode {
      opacity: 1;
      transform: translateY(-2px) scale(1.01);
      box-shadow: 0 16px 30px rgba(69, 215, 255, 0.14);
      border-color: rgba(83, 246, 184, 0.5);
    }

    .mode-grid.matchmaking-live .mode-card.active-mode::after {
      opacity: 1;
    }

    .mode-burst {
      position: absolute;
      right: 16px;
      top: 16px;
      width: 54px;
      height: 54px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(83, 246, 184, 0.55), rgba(69, 215, 255, 0.1) 60%, transparent 70%);
      filter: blur(1px);
      opacity: 0;
      transform: scale(0.4);
      transition: transform 380ms ease, opacity 380ms ease;
      pointer-events: none;
    }

    .game-card {
      position: relative;
      overflow-x: auto;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior: contain;
      min-height: 250px;
      background:
        radial-gradient(circle at top right, rgba(69, 215, 255, 0.18), transparent 32%),
        linear-gradient(180deg, rgba(18, 41, 71, 0.9), rgba(11, 18, 35, 0.95));
    }

    .game-card::before {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, transparent, rgba(83, 246, 184, 0.05), transparent);
      pointer-events: none;
    }

    .card-grid.reveal .game-card {
      opacity: 0;
      transform: translateY(14px) rotateY(90deg);
      animation: cardFlipIn 650ms ease forwards;
    }

    .card-grid.reveal .game-card:nth-child(1) { animation-delay: 0.05s; }
    .card-grid.reveal .game-card:nth-child(2) { animation-delay: 0.15s; }
    .card-grid.reveal .game-card:nth-child(3) { animation-delay: 0.25s; }
    .card-grid.reveal .game-card:nth-child(4) { animation-delay: 0.35s; }
    .card-grid.reveal .game-card:nth-child(5) { animation-delay: 0.45s; }

    .card-grid.pack-emerge.reveal .game-card {
      animation: packCardRise 820ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .card-grid.pack-emerge.reveal .game-card:nth-child(1) { animation-delay: 0.06s; }
    .card-grid.pack-emerge.reveal .game-card:nth-child(2) { animation-delay: 0.14s; }
    .card-grid.pack-emerge.reveal .game-card:nth-child(3) { animation-delay: 0.22s; }
    .card-grid.pack-emerge.reveal .game-card:nth-child(4) { animation-delay: 0.30s; }
    .card-grid.pack-emerge.reveal .game-card:nth-child(5) { animation-delay: 0.38s; }

    @keyframes cardFlipIn {
      0% { opacity: 0; transform: translateY(18px) rotateY(90deg) scale(0.96); }
      60% { opacity: 1; transform: translateY(-4px) rotateY(0deg) scale(1.01); }
      100% { opacity: 1; transform: translateY(0) rotateY(0deg) scale(1); }
    }

    @keyframes packCardRise {
      0% { opacity: 0; transform: translateY(-130px) scale(0.72) rotateX(72deg); filter: blur(1.2px); }
      55% { opacity: 1; transform: translateY(-16px) scale(1.03) rotateX(8deg); filter: blur(0); }
      100% { opacity: 1; transform: translateY(0) scale(1) rotateX(0deg); filter: blur(0); }
    }

    .card-grid.sequence-prep .game-card {
      opacity: 0;
      transform: scale(0.86) translateY(18px);
      transition: opacity 320ms ease, transform 320ms ease;
    }

    .card-grid.sequence-prep .game-card.sequence-visible {
      opacity: 1;
      transform: scale(1) translateY(0);
    }

    .duel-anim {
      position: relative;
      overflow: hidden;
      border: 1px solid rgba(69, 215, 255, 0.35);
      background:
        radial-gradient(circle at center, rgba(69, 215, 255, 0.16), transparent 42%),
        linear-gradient(120deg, rgba(10, 18, 33, 0.95), rgba(16, 33, 58, 0.92));
    }

    .duel-anim::after {
      content: "";
      position: absolute;
      inset: -30%;
      background: linear-gradient(90deg, transparent, rgba(83, 246, 184, 0.16), transparent);
      animation: sweep 1.8s linear infinite;
      pointer-events: none;
    }

    @keyframes sweep {
      from { transform: translateX(-50%) rotate(8deg); }
      to { transform: translateX(50%) rotate(8deg); }
    }

    .friend-list, .active-users-list, .deck-list {
      display: grid;
      gap: 12px;
    }

    .catalog-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }

    .catalog-card {
      border-radius: 14px;
      border: 1px solid var(--line);
      padding: 10px 12px;
      background: rgba(255,255,255,0.03);
    }

    .catalog-card.basic { border-color: rgba(180, 180, 180, 0.35); }
    .catalog-card.rare { border-color: rgba(69, 215, 255, 0.42); }
    .catalog-card.epic { border-color: rgba(255, 122, 134, 0.5); }
    .catalog-card.mythic { border-color: rgba(188, 126, 255, 0.56); }
    .catalog-card.legendary { border-color: rgba(255, 211, 110, 0.56); }

    .catalog-card.skill-card {
      border-color: rgba(255, 211, 110, 0.34);
      background:
        radial-gradient(circle at top right, rgba(255, 211, 110, 0.12), transparent 38%),
        linear-gradient(180deg, rgba(24, 23, 14, 0.9), rgba(12, 16, 24, 0.96));
    }

    .catalog-kicker {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(255, 211, 110, 0.28);
      background: rgba(255, 211, 110, 0.08);
      color: #ffe6a0;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }

    .user-item {
      border-radius: 20px;
      border: 1px solid var(--line);
      padding: 14px;
      background: rgba(255,255,255,0.03);
    }

    .user-item strong {
      display: block;
      margin-bottom: 6px;
    }

    .player-card {
      position: relative;
      border-radius: 22px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      overflow: hidden;
      min-height: 148px;
      padding: 16px;
      background: rgba(9, 18, 31, 0.88);
      box-shadow: 0 18px 38px rgba(0, 0, 0, 0.22);
      cursor: pointer;
      isolation: isolate;
    }

    .player-card:hover {
      border-color: rgba(121, 217, 255, 0.28);
      transform: translateY(-1px);
    }

    .player-card.profile-preview {
      min-height: 124px;
      padding: 14px;
    }

    .player-card-banner {
      position: absolute;
      left: 50%;
      top: 18px;
      transform: translateX(-50%);
      width: 132px;
      height: 28px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.22);
      z-index: 2;
      opacity: 0.92;
      box-shadow: 0 10px 24px rgba(0,0,0,0.22);
      pointer-events: none;
    }

    .player-card-domain {
      position: absolute;
      left: 16px;
      top: 24px;
      z-index: 8;
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(5, 12, 22, 0.84);
      color: #f5fbff;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.04em;
      backdrop-filter: blur(10px);
      max-width: calc(100% - 84px);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .player-card-gift {
      position: absolute;
      right: 14px;
      top: 14px;
      z-index: 8;
      min-width: 36px;
      height: 36px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(5, 12, 22, 0.78);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      box-shadow: 0 10px 20px rgba(0,0,0,0.18);
      backdrop-filter: blur(8px);
    }

    .player-card-gift img {
      width: 24px;
      height: 24px;
      object-fit: contain;
      display: block;
    }

    .profile-gift-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
      gap: 10px;
    }

    .profile-gift-option {
      position: relative;
      min-height: 82px;
      border-radius: 18px;
      border: 1px solid rgba(121,217,255,0.18);
      background: rgba(7, 16, 29, 0.72);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      cursor: pointer;
      transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease;
    }

    .profile-gift-option:hover {
      transform: translateY(-2px);
      border-color: rgba(121,217,255,0.42);
    }

    .profile-gift-option.active {
      border-color: rgba(88, 210, 255, 0.92);
      box-shadow: 0 0 0 2px rgba(88, 210, 255, 0.14), 0 12px 22px rgba(0,0,0,0.22);
    }

    .profile-gift-option img {
      width: 54px;
      height: 54px;
      object-fit: contain;
      display: block;
      filter: drop-shadow(0 10px 14px rgba(0,0,0,0.18));
    }

    .profile-gift-option-empty {
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.03em;
      color: rgba(213, 235, 255, 0.82);
    }

    .player-card-back {
      position: absolute;
      left: 14px;
      bottom: 14px;
      width: 88px;
      height: 118px;
      border-radius: 18px;
      border: 1px solid rgba(121,217,255,0.18);
      box-shadow: 0 16px 28px rgba(0,0,0,0.28);
      z-index: 1;
      overflow: hidden;
      pointer-events: none;
    }

    .player-card.profile-preview .player-card-back {
      width: 64px;
      height: 88px;
      left: 14px;
      bottom: 14px;
      border-radius: 14px;
    }

    .player-card-frame {
      position: absolute;
      left: 8px;
      top: 8px;
      width: calc(100% - 16px);
      height: calc(100% - 16px);
      object-fit: contain;
      z-index: 2;
      pointer-events: none;
    }

    .player-card-content {
      position: relative;
      z-index: 4;
      display: grid;
      gap: 8px;
      margin-left: 106px;
      margin-top: 34px;
      min-height: 108px;
    }

    .player-card.profile-preview .player-card-content {
      margin-left: 78px;
      margin-top: 46px;
      min-height: 72px;
      gap: 6px;
    }

    .player-card-title {
      font-size: 24px;
      line-height: 1;
      font-weight: 900;
      margin: 0;
    }

    .player-card.profile-preview .player-card-title {
      font-size: 18px;
    }

    .player-card-meta {
      color: rgba(224, 238, 255, 0.78);
      font-size: 13px;
      line-height: 1.4;
    }

    .player-card.profile-preview .player-card-meta {
      font-size: 12px;
      line-height: 1.3;
    }

    .player-card-cosmetics {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 2px;
    }

    .player-cosmetic-chip {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 9px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.14);
      background: rgba(5,12,22,0.5);
      color: rgba(245, 250, 255, 0.9);
      font-size: 11px;
      font-weight: 700;
      backdrop-filter: blur(6px);
    }

    .player-card-actions {
      position: relative;
      z-index: 4;
      margin-left: 106px;
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .player-card.profile-preview .player-card-actions {
      margin-left: 78px;
      margin-top: 8px;
      gap: 8px;
    }

    .public-profile-hero {
      position: relative;
      min-height: 252px;
      border-radius: 24px;
      overflow: hidden;
      padding: 22px;
    }

    .public-profile-banner {
      position: absolute;
      left: 50%;
      top: 18px;
      transform: translateX(-50%);
      width: 164px;
      height: 40px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.24);
      box-shadow: 0 12px 24px rgba(0,0,0,0.22);
      z-index: 1;
    }

    .public-profile-domain {
      position: absolute;
      left: 24px;
      top: 24px;
      z-index: 8;
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 0 14px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(5,12,22,0.84);
      color: #f5fbff;
      font-weight: 900;
      max-width: 180px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .public-profile-cardback {
      position: absolute;
      left: 24px;
      bottom: 18px;
      width: 126px;
      height: 176px;
      border-radius: 24px;
      border: 1px solid rgba(121,217,255,0.18);
      box-shadow: 0 18px 32px rgba(0,0,0,0.28);
      z-index: 1;
    }

    .public-profile-frame {
      position: absolute;
      left: 14px;
      bottom: 8px;
      width: 146px;
      height: 196px;
      object-fit: contain;
      z-index: 2;
      pointer-events: none;
    }

    .public-profile-copy {
      position: relative;
      z-index: 4;
      margin-left: 156px;
      display: grid;
      gap: 12px;
      align-content: center;
      min-height: 204px;
    }

    .public-profile-cosmetics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }

    .public-profile-cosmetic {
      border-radius: 18px;
      border: 1px solid rgba(121,217,255,0.18);
      background: rgba(255,255,255,0.03);
      padding: 12px;
      min-height: 118px;
      display: grid;
      gap: 8px;
      align-content: start;
    }

    .public-profile-cosmetic-preview {
      position: relative;
      min-height: 62px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.14);
      overflow: hidden;
    }

    .public-profile-match-list {
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }

    .public-profile-match {
      border-radius: 16px;
      border: 1px solid rgba(121,217,255,0.14);
      background: rgba(255,255,255,0.03);
      padding: 12px;
      display: grid;
      gap: 6px;
    }

    .public-profile-backdrop {
      position: fixed;
      inset: 0;
      z-index: 1600;
      background: rgba(3, 8, 16, 0.76);
      backdrop-filter: blur(8px);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }

    .public-profile-backdrop.open {
      display: flex;
    }

    .public-profile-modal {
      width: min(960px, 100%);
      max-height: min(86vh, 920px);
      overflow: auto;
      border-radius: 28px;
      border: 1px solid rgba(121,217,255,0.18);
      background: linear-gradient(180deg, rgba(8,18,31,0.98), rgba(7,14,26,0.98));
      box-shadow: 0 30px 80px rgba(0,0,0,0.38);
      padding: 20px;
    }

    @media (max-width: 760px) {
      .player-card {
        min-height: 132px;
        padding: 14px;
      }

      .player-card-back {
        width: 74px;
        height: 102px;
      }

      .player-card.profile-preview {
        min-height: 118px;
      }

      .player-card.profile-preview .player-card-back {
        width: 58px;
        height: 80px;
      }

      .player-card-content,
      .player-card-actions {
        margin-left: 88px;
      }

      .player-card.profile-preview .player-card-content,
      .player-card.profile-preview .player-card-actions {
        margin-left: 72px;
      }

      .player-card-title {
        font-size: 20px;
      }

      .public-profile-backdrop {
        padding: 10px;
      }

      .public-profile-modal {
        padding: 14px;
        border-radius: 22px;
      }

      .public-profile-hero {
        min-height: auto;
        padding: 54px 16px 16px;
      }

      .public-profile-banner {
        width: 132px;
        height: 30px;
        top: 14px;
      }

      .public-profile-domain {
        left: 16px;
        top: 12px;
        min-height: 30px;
        padding: 0 12px;
        font-size: 12px;
      }

      .public-profile-cardback {
        position: relative;
        left: auto;
        bottom: auto;
        width: 82px;
        height: 114px;
        margin-top: 24px;
      }

      .public-profile-frame {
        left: 8px;
        bottom: auto;
        top: 58px;
        width: 98px;
        height: 132px;
      }

      .public-profile-copy {
        margin-left: 0;
        margin-top: 8px;
        padding-top: 6px;
        min-height: 0;
      }
    }

    .game-card h3, .mode-card h3, .domain-card h3 {
      margin: 0 0 10px;
    }

    .game-card h3,
    .mode-card h3,
    .domain-card h3,
    .catalog-card strong,
    .user-item strong,
    .wallet-domain-mainline,
    .wallet-flow-note,
    .wallet-section .tiny {
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .muted {
      color: var(--muted);
    }

    .status {
      min-height: 28px;
      color: var(--muted);
      margin-top: 8px;
    }

    .success { color: var(--accent-2); }
    .warning { color: var(--warning); }
    .error { color: var(--danger); }

    .side {
      display: grid;
      gap: 18px;
      align-content: start;
    }

    .kv {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }

    .kv:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }

    .mode-card p, .domain-card p, .game-card p {
      margin: 0 0 10px;
      color: var(--muted);
      line-height: 1.5;
    }

    .result-box {
      border-radius: 20px;
      border: 1px solid rgba(83, 246, 184, 0.24);
      background: rgba(83, 246, 184, 0.08);
      padding: 18px;
      margin-top: 16px;
    }

    body.showdown-open {
      overflow: auto;
    }

    .showdown-fullscreen {
      position: fixed;
      inset: 0;
      z-index: 5000;
      margin: 0;
      border-radius: 0;
      border: 0;
      padding:
        calc(12px + env(safe-area-inset-top))
        12px
        calc(16px + env(safe-area-inset-bottom));
      display: grid;
      grid-template-rows: auto auto auto auto;
      gap: 12px;
      background: linear-gradient(180deg, rgba(3, 10, 20, 1), rgba(6, 15, 28, 1));
      position: fixed;
      isolation: isolate;
      overflow: hidden;
    }

    .showdown-fullscreen.duel-anim::after {
      display: none;
    }

    .showdown-fullscreen::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 50% 10%, rgba(83, 246, 184, 0.12), transparent 44%),
        radial-gradient(circle at 50% 90%, rgba(69, 215, 255, 0.12), transparent 44%),
        rgba(3, 10, 20, 0.94);
      z-index: -1;
    }

    .showdown-fullscreen::after {
      content: "";
      position: absolute;
      inset: -22%;
      background:
        conic-gradient(from 180deg at 50% 50%, transparent, rgba(69, 215, 255, 0.08), transparent, rgba(83, 246, 184, 0.08), transparent);
      filter: blur(6px);
      animation: auroraRotate 16s linear infinite;
      pointer-events: none;
      z-index: -1;
    }

    .showdown-fullscreen.result-win {
      box-shadow: inset 0 0 160px rgba(83, 246, 184, 0.2);
    }

    .showdown-fullscreen.result-lose {
      box-shadow: inset 0 0 160px rgba(255, 122, 134, 0.17);
    }

    .showdown-fullscreen.result-draw {
      box-shadow: inset 0 0 160px rgba(255, 211, 110, 0.16);
    }

    .showdown-fullscreen.battle-live .showdown-main {
      animation: arenaShake 540ms cubic-bezier(.2,.82,.2,1);
    }

    .showdown-header {
      border: 1px solid rgba(121, 217, 255, 0.32);
      border-radius: 20px;
      padding: 9px;
      background: rgba(6, 18, 32, 0.96);
      backdrop-filter: blur(3px);
      overflow: hidden;
    }

    .showdown-main {
      border: 1px solid rgba(121, 217, 255, 0.25);
      border-radius: 20px;
      padding: 10px;
      background: rgba(4, 14, 27, 0.94);
      overflow-y: auto;
      overflow-x: hidden;
      -webkit-overflow-scrolling: touch;
      min-height: 66vh;
      max-height: 82vh;
    }

    .showdown-main.arena-board {
      background: transparent;
      box-shadow: none;
      padding: 12px;
    }

    .arena-shell {
      display: grid;
      gap: 10px;
      --arena-columns: 5;
      --arena-gap: 8px;
      --arena-card-width: calc((100% - (var(--arena-gap) * (var(--arena-columns) - 1))) / var(--arena-columns));
    }

    .arena-rail {
      display: grid;
      gap: 6px;
      padding: 6px 8px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(8, 20, 36, 0.66);
      box-shadow: inset 0 0 0 1px rgba(121, 217, 255, 0.04);
    }

    .arena-rail.enemy {
      order: 1;
    }

    .arena-core {
      order: 2;
      --arena-ui-base: rgba(8, 23, 43, 0.94);
      --arena-ui-secondary: rgba(10, 29, 34, 0.96);
      --arena-ui-accent: #45d7ff;
      --arena-ui-accent-soft: rgba(69, 215, 255, 0.18);
      --arena-ui-accent-border: rgba(69, 215, 255, 0.34);
      --arena-ui-text: #f4fbff;
      --arena-ui-chip-bg: rgba(255, 211, 110, 0.10);
      --arena-ui-chip-border: rgba(255, 211, 110, 0.34);
      --arena-ui-chip-text: #ffe59d;
    }

    .arena-rail.player {
      order: 3;
    }

    .arena-rail.enemy {
      border-color: rgba(255, 211, 110, 0.14);
    }

    .arena-deck-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: var(--arena-gap);
    }

    .arena-slot-card {
      position: relative;
      min-width: 0;
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      padding: 10px 10px 9px;
      background: linear-gradient(180deg, rgba(19, 34, 56, 0.96), rgba(9, 18, 31, 0.98));
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.03);
      transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
    }

    .arena-slot-card.player-card {
      border-color: rgba(69, 215, 255, 0.22);
    }

    .arena-slot-card.enemy-card {
      border-color: rgba(255, 211, 110, 0.18);
    }

    .arena-slot-card.active-slot {
      transform: translateY(-3px);
      border-color: rgba(83, 246, 184, 0.42);
      box-shadow:
        0 12px 24px rgba(0, 0, 0, 0.18),
        0 0 0 1px rgba(83, 246, 184, 0.14);
    }

    .arena-slot-card.featured-slot::after {
      content: "";
      position: absolute;
      inset: 0;
      border-radius: inherit;
      box-shadow: inset 0 0 0 1px rgba(255, 211, 110, 0.2);
      pointer-events: none;
    }

    .arena-slot-card.tutorial-focus {
      border-color: rgba(255, 211, 110, 0.56);
      box-shadow:
        0 0 0 1px rgba(255, 211, 110, 0.22),
        0 0 24px rgba(255, 211, 110, 0.18),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
      animation: tutorialPulse 1.6s ease-in-out infinite;
      z-index: 2;
    }

    .arena-route-path.tutorial-focus {
      stroke: rgba(255, 211, 110, 0.88);
      stroke-width: 4;
      filter: drop-shadow(0 0 10px rgba(255, 211, 110, 0.34));
      animation: tutorialRoutePulse 1.35s ease-in-out infinite;
    }

    .arena-slot-card strong {
      display: block;
      margin-bottom: 4px;
      font-size: 12px;
      line-height: 1.18;
      word-break: break-word;
    }

    .arena-slot-meta {
      color: rgba(213, 235, 255, 0.8);
      font-size: 11px;
      line-height: 1.22;
    }

    .arena-card-emoji {
      position: absolute;
      right: 8px;
      bottom: 8px;
      width: 24px;
      height: 24px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      line-height: 1;
      border: 1px solid rgba(255, 255, 255, 0.26);
      background: radial-gradient(circle at 40% 32%, rgba(255, 255, 255, 0.22), rgba(9, 18, 30, 0.74));
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.28);
      z-index: 2;
      pointer-events: none;
    }

    .arena-core {
      position: relative;
      min-height: 220px;
      border-radius: 26px;
      border: 1px solid rgba(121, 217, 255, 0.08);
      background:
        radial-gradient(circle at 50% 50%, rgba(14, 44, 55, 0.04), transparent 42%),
        linear-gradient(180deg, rgba(6, 14, 26, 0.08), rgba(3, 9, 18, 0.04));
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.01);
      overflow: hidden;
      isolation: isolate;
      --arena-overlay-text: rgba(245, 250, 255, 0.96);
      --arena-overlay-muted: rgba(224, 238, 255, 0.76);
      --arena-route-main: rgba(255, 255, 255, 0.76);
      --arena-route-alt: rgba(255, 255, 255, 0.52);
      --arena-route-active: rgba(255, 255, 255, 0.96);
      --arena-state-bg: rgba(255, 255, 255, 0.06);
      --arena-state-border: rgba(255, 255, 255, 0.16);
    }

    .arena-core::before {
      content: "";
      position: absolute;
      inset: 16px;
      border-radius: 20px;
      border: 1px solid rgba(255, 211, 110, 0.025);
      pointer-events: none;
    }

    .arena-route-overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 0;
    }

    .arena-route-overlay svg {
      width: 100%;
      height: 100%;
      display: block;
    }

    .arena-route-path {
      fill: none;
      stroke: var(--arena-route-main);
      stroke-width: 2.2;
      stroke-linecap: round;
      stroke-dasharray: 5 10;
      filter: drop-shadow(0 0 6px color-mix(in srgb, var(--arena-route-main) 24%, transparent));
      animation: arenaDashFlow 2.4s linear infinite;
      opacity: 0.84;
    }

    .arena-route-path.alt {
      stroke: var(--arena-route-alt);
      stroke-dasharray: 4 11;
      animation-duration: 2.8s;
    }

    .arena-route-path.active {
      stroke: var(--arena-route-active);
      stroke-width: 3;
      filter: drop-shadow(0 0 10px color-mix(in srgb, var(--arena-route-active) 28%, transparent));
    }

    .arena-choice-hub {
      position: relative;
      z-index: 1;
      min-height: 220px;
      display: grid;
      place-items: center;
      padding: 18px 10px 10px;
    }

    .arena-choice-panel {
      width: min(100%, 430px);
      padding: 18px 18px 16px;
      border-radius: 24px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background:
        linear-gradient(180deg, rgba(8, 21, 37, 0.96), rgba(8, 17, 29, 0.98)),
        radial-gradient(circle at top, rgba(69, 215, 255, 0.12), transparent 62%);
      box-shadow:
        0 24px 44px rgba(0, 0, 0, 0.24),
        inset 0 0 0 1px rgba(255, 255, 255, 0.03);
      backdrop-filter: blur(16px);
    }

    .arena-choice-panel .interactive-battle-actions {
      grid-template-columns: repeat(2, minmax(0, 88px));
      justify-content: center;
      gap: 14px;
    }

    .arena-choice-panel .interactive-action-btn {
      min-height: 82px;
      border-radius: 50%;
      aspect-ratio: 1 / 1;
      padding: 0 10px;
      font-size: 13px;
      line-height: 1.15;
      text-align: center;
    }

    .arena-choice-panel .interactive-action-btn.burst,
    .arena-battle-dock .interactive-action-btn.burst {
      border-color: rgba(255, 122, 134, 0.52);
      background: linear-gradient(135deg, rgba(255, 122, 134, 0.28), rgba(255, 255, 255, 0.10));
      color: #fff6f7;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06), 0 12px 28px rgba(255, 122, 134, 0.18);
    }

    .arena-choice-panel .interactive-action-btn.guard,
    .arena-battle-dock .interactive-action-btn.guard {
      border-color: rgba(83, 246, 184, 0.52);
      background: linear-gradient(135deg, rgba(83, 246, 184, 0.26), rgba(255, 255, 255, 0.10));
      color: #f3fffb;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06), 0 12px 28px rgba(83, 246, 184, 0.16);
    }

    .arena-round-choice-strip {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 2;
    }

    .arena-round-choice-slot {
      position: absolute;
      top: 70px;
      transform: translateX(-50%);
      display: grid;
      justify-items: center;
      gap: 8px;
      min-width: 40px;
      pointer-events: none;
    }

    .arena-round-choice-slot.active {
      z-index: 3;
      gap: 8px;
    }

    .arena-round-marker {
      width: 16px;
      height: 16px;
      padding: 0;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--arena-state-border);
      background: color-mix(in srgb, var(--arena-state-bg) 88%, rgba(8, 19, 34, 0.72));
      box-shadow: 0 8px 18px rgba(0, 0, 0, 0.16);
      pointer-events: none;
    }

    .arena-round-choice-slot.resolved .arena-round-marker {
      border-color: var(--arena-state-border);
      color: var(--arena-overlay-text);
    }

    .arena-round-choice-slot.active .arena-round-marker {
      border-color: var(--arena-route-active);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--arena-route-active) 16%, transparent), 0 10px 20px rgba(0, 0, 0, 0.18);
    }

    .arena-round-state {
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--arena-state-border);
      background: var(--arena-state-bg);
      color: var(--arena-overlay-muted);
      font-size: 11px;
      letter-spacing: 0.04em;
      white-space: nowrap;
      pointer-events: none;
      position: relative;
      z-index: 4;
    }

    .arena-round-state.win {
      border-color: color-mix(in srgb, var(--arena-route-active) 40%, transparent);
      background: color-mix(in srgb, var(--arena-route-active) 12%, transparent);
      color: var(--arena-overlay-text);
    }

    .arena-round-state.lose {
      border-color: color-mix(in srgb, var(--arena-overlay-text) 28%, transparent);
      background: color-mix(in srgb, var(--arena-overlay-text) 8%, transparent);
      color: var(--arena-overlay-text);
    }

    .arena-round-state.draw {
      border-color: color-mix(in srgb, var(--arena-overlay-text) 28%, transparent);
      background: color-mix(in srgb, var(--arena-overlay-text) 8%, transparent);
      color: var(--arena-overlay-text);
    }

    .summary-chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }

    .season-pass-track-spacer {
      flex: 0 0 520px;
      width: 520px;
      min-width: 520px;
      pointer-events: none;
    }

    .arena-battle-dock {
      position: absolute;
      left: 50%;
      top: 50%;
      bottom: auto;
      transform: translate(-50%, -50%);
      width: min(100%, 388px);
      z-index: 9;
      pointer-events: none;
    }

    .arena-battle-dock .interactive-battle-panel {
      margin: 0;
      pointer-events: auto;
      gap: 8px;
      padding: 8px 10px 10px;
      border-radius: 16px;
      color: var(--arena-ui-text);
      border: 1px solid var(--arena-ui-accent-border);
      background:
        linear-gradient(135deg, var(--arena-ui-base), var(--arena-ui-secondary)),
        radial-gradient(circle at top, var(--arena-ui-accent-soft), transparent 62%);
      box-shadow:
        0 16px 32px rgba(0, 0, 0, 0.26),
        0 0 0 1px rgba(255, 255, 255, 0.03);
    }

    .arena-battle-dock .interactive-battle-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .arena-battle-dock .interactive-battle-title {
      font-size: 16px;
      line-height: 1;
      text-align: left;
      flex: 1 1 auto;
    }

    .arena-battle-dock .interactive-timer {
      min-width: 58px;
      min-height: 28px;
      margin: 0;
      padding: 0 8px;
      font-size: 11px;
    }

    .arena-battle-dock .interactive-battle-actions {
      gap: 6px;
      perspective: none;
    }

    .arena-battle-dock .interactive-action-btn {
      min-height: 40px;
      border-radius: 12px;
      padding: 0 8px;
      font-size: 11px;
      line-height: 1.15;
    }

    .arena-player-resource-bar {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
      margin-top: 6px;
      transition: opacity 160ms ease, transform 160ms ease;
    }

    .arena-resource-pill {
      border: 1px solid rgba(121, 217, 255, 0.16);
      border-radius: 12px;
      padding: 5px 7px;
      background: rgba(8, 20, 36, 0.92);
      display: grid;
      gap: 3px;
    }

    .arena-resource-pill.tutorial-focus {
      border-color: rgba(255, 211, 110, 0.42);
      box-shadow:
        0 0 0 1px rgba(255, 211, 110, 0.18),
        0 0 18px rgba(255, 211, 110, 0.16);
      animation: tutorialPulse 1.45s ease-in-out infinite;
    }

    .arena-resource-topline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 9px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .arena-resource-topline strong {
      font-size: 11px;
      line-height: 1;
      color: var(--text);
    }

    .arena-resource-barline {
      height: 5px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      overflow: hidden;
      position: relative;
    }

    .arena-resource-barline::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: var(--fill, 0%);
      border-radius: inherit;
      background: linear-gradient(90deg, rgba(69, 215, 255, 0.84), rgba(83, 246, 184, 0.92));
      box-shadow: 0 0 12px rgba(69, 215, 255, 0.18);
    }

    .arena-resource-pill.cooldown .arena-resource-barline::before {
      background: linear-gradient(90deg, rgba(255, 211, 110, 0.84), rgba(255, 146, 85, 0.92));
      box-shadow: 0 0 12px rgba(255, 211, 110, 0.16);
    }

    .arena-resource-pill.ability .arena-resource-barline::before {
      background: linear-gradient(90deg, rgba(124, 191, 255, 0.88), rgba(69, 215, 255, 0.92));
    }

    .arena-resource-caption {
      font-size: 8px;
      line-height: 1.15;
      color: var(--muted);
      word-break: break-word;
    }

    .tutorial-action-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: center;
      margin-top: 2px;
    }

    .tutorial-action-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 9px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      background: rgba(8, 20, 36, 0.84);
      color: var(--muted);
      font-size: 10px;
      line-height: 1;
      white-space: nowrap;
    }

    .tutorial-action-chip.recommended {
      border-color: rgba(255, 211, 110, 0.36);
      background: rgba(255, 211, 110, 0.1);
      color: rgba(255, 240, 205, 0.98);
    }

    .tutorial-prebattle-guide {
      display: grid;
      gap: 6px;
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid rgba(255, 211, 110, 0.16);
      background: rgba(255, 211, 110, 0.08);
      text-align: left;
    }

    .tutorial-prebattle-guide .tiny {
      color: rgba(255, 240, 205, 0.92);
    }

    .arena-core.clash-live .arena-battle-dock {
      opacity: 0;
      visibility: hidden;
      transform: translate(-50%, 10px);
      pointer-events: none;
    }

    .arena-shell.clash-live .arena-player-resource-bar {
      opacity: 0.28;
      transform: translateY(4px);
    }

    .currency-badge {
      min-width: 210px;
    }

    .currency-float {
      position: fixed;
      top: 14px;
      right: 14px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(7, 16, 26, 0.92);
      backdrop-filter: blur(14px);
      z-index: 60;
      box-shadow: 0 16px 30px rgba(0, 0, 0, 0.28);
    }

    .currency-float-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.04);
      font-size: 11px;
      color: rgba(234, 248, 255, 0.94);
      white-space: nowrap;
    }

    .nav-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 18px;
      height: 18px;
      padding: 0 6px;
      margin-left: 6px;
      border-radius: 999px;
      background: rgba(255, 95, 95, 0.92);
      color: #fff;
      font-size: 10px;
      font-weight: 800;
      line-height: 1;
      box-shadow: 0 8px 18px rgba(255, 95, 95, 0.18);
    }

    .summary-chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }

    .summary-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(8, 20, 36, 0.84);
      color: var(--text);
      font-size: 11px;
      line-height: 1;
    }

    .battle-reward-line {
      width: 100%;
      text-align: center;
      font-size: 12px;
      color: rgba(213, 235, 255, 0.82);
    }

    .battle-reward-line strong {
      color: #7ff3c0;
    }

    .arena-round-choice-slot.active .arena-lane-choice-panel {
      margin-top: 8px;
      transform: none;
      pointer-events: auto;
    }

    .arena-round-choice-slot.clash-resolving .arena-lane-choice-panel {
      opacity: 0;
      visibility: hidden;
      transform: translateY(10px) scale(0.94);
      pointer-events: none;
    }

    .arena-lane-choice-panel {
      width: clamp(188px, calc(var(--arena-card-width) + 36px), 224px);
      max-width: 224px;
      min-width: 188px;
      padding: 12px 12px 12px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background:
        linear-gradient(180deg, rgba(8, 21, 37, 0.98), rgba(8, 17, 29, 0.99)),
        radial-gradient(circle at top, rgba(69, 215, 255, 0.12), transparent 62%);
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.24);
      backdrop-filter: blur(14px);
      pointer-events: auto;
      position: relative;
      z-index: 8;
      display: grid;
      gap: 10px;
    }

    .arena-round-floating-metrics {
      width: clamp(188px, calc(var(--arena-card-width) + 36px), 224px);
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      pointer-events: none;
      position: relative;
      z-index: 8;
    }

    .arena-floating-chip {
      min-height: 38px;
      padding: 7px 8px;
      border-radius: 12px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background: rgba(16, 34, 49, 0.9);
      display: grid;
      gap: 2px;
      align-content: center;
      text-align: center;
      box-shadow: 0 12px 24px rgba(0, 0, 0, 0.18);
    }

    .arena-floating-chip strong {
      font-size: 11px;
      line-height: 1;
    }

    .arena-floating-chip span {
      font-size: 10px;
      line-height: 1.1;
      color: var(--muted);
      word-break: break-word;
    }

    .arena-lane-choice-panel .interactive-battle-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: nowrap;
      min-width: 0;
    }

    .arena-lane-choice-panel .interactive-battle-title {
      font-size: 13px;
      line-height: 1;
      font-weight: 800;
      margin: 0;
      flex: 1 1 auto;
      white-space: nowrap;
    }

    .arena-lane-choice-panel .interactive-timer {
      min-width: 52px;
      min-height: 26px;
      font-size: 11px;
      margin: 0;
    }

    .interactive-battle-metrics {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .interactive-battle-metric {
      min-height: 42px;
      padding: 7px 8px;
      border-radius: 12px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(255, 255, 255, 0.03);
      display: grid;
      gap: 2px;
      align-content: center;
      text-align: center;
    }

    .interactive-battle-metric strong {
      font-size: 11px;
      line-height: 1;
    }

    .interactive-battle-metric span {
      font-size: 10px;
      line-height: 1.1;
      color: var(--muted);
    }

    .interactive-battle-prompt {
      min-height: 28px;
      font-size: 11px;
      line-height: 1.3;
      text-align: center;
      color: var(--muted);
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .arena-lane-choice-panel .interactive-battle-actions {
      grid-template-columns: repeat(2, minmax(0, 52px));
      gap: 10px;
      justify-content: center;
      pointer-events: auto;
    }

    .arena-lane-choice-panel .interactive-action-btn {
      min-height: 52px;
      border-radius: 50%;
      aspect-ratio: 1 / 1;
      padding: 0 6px;
      font-size: 10px;
      line-height: 1.1;
      text-align: center;
      position: relative;
      z-index: 9;
      touch-action: manipulation;
      pointer-events: auto;
    }

    .arena-lane-clash {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 11;
      opacity: 0;
      overflow: hidden;
    }

    .arena-lane-clash.visible {
      animation: laneClashIn 160ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .arena-lane-clash.resolving {
      animation: roundClashFadeOut 280ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .arena-shell.lane-clash-live .arena-rail .arena-slot-card.active-slot {
      opacity: 0;
      visibility: hidden;
      transform: none;
      box-shadow: none;
      transition: opacity 140ms ease, visibility 0s linear 140ms;
    }

    .arena-lane-card {
      position: absolute;
      width: var(--clash-card-width, 92px);
      min-height: var(--clash-card-height, 136px);
      padding: 9px 8px 10px;
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.28);
      background: linear-gradient(180deg, rgba(18, 33, 55, 0.98), rgba(8, 16, 29, 0.99));
      box-shadow:
        0 18px 34px rgba(0, 0, 0, 0.24),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
      pointer-events: none;
      opacity: 0;
      transform-origin: center center;
      display: flex;
      flex-direction: column;
      justify-content: flex-start;
      overflow: hidden;
      white-space: normal;
      word-break: break-word;
    }

    .arena-lane-card.simplified {
      padding: 0;
      display: block;
    }

    .arena-lane-card.player {
      border-color: rgba(83, 246, 184, 0.4);
      box-shadow:
        0 18px 34px rgba(0, 0, 0, 0.28),
        0 0 0 1px rgba(83, 246, 184, 0.16),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }

    .arena-lane-card.enemy {
      border-color: rgba(255, 122, 134, 0.34);
      box-shadow:
        0 18px 34px rgba(0, 0, 0, 0.28),
        0 0 0 1px rgba(255, 122, 134, 0.14),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }

    .arena-lane-card.burst {
      border-color: rgba(255, 122, 134, 0.56);
      background:
        linear-gradient(180deg, rgba(54, 27, 40, 0.92), rgba(14, 14, 26, 0.98)),
        linear-gradient(180deg, rgba(18, 33, 55, 0.98), rgba(8, 16, 29, 0.99));
      box-shadow:
        0 20px 36px rgba(0, 0, 0, 0.3),
        0 0 0 1px rgba(255, 122, 134, 0.24),
        0 0 28px rgba(255, 122, 134, 0.16),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }

    .arena-lane-card.guard {
      border-color: rgba(83, 246, 184, 0.56);
      background:
        linear-gradient(180deg, rgba(18, 46, 42, 0.92), rgba(8, 16, 29, 0.99)),
        linear-gradient(180deg, rgba(18, 33, 55, 0.98), rgba(8, 16, 29, 0.99));
      box-shadow:
        0 18px 34px rgba(0, 0, 0, 0.28),
        0 0 0 1px rgba(83, 246, 184, 0.22),
        0 0 24px rgba(83, 246, 184, 0.14),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }

    .arena-lane-card.ability {
      border-color: rgba(255, 211, 110, 0.58);
      background:
        linear-gradient(180deg, rgba(56, 42, 18, 0.92), rgba(14, 14, 24, 0.99)),
        linear-gradient(180deg, rgba(18, 33, 55, 0.98), rgba(8, 16, 29, 0.99));
      box-shadow:
        0 20px 36px rgba(0, 0, 0, 0.3),
        0 0 0 1px rgba(255, 211, 110, 0.24),
        0 0 28px rgba(255, 211, 110, 0.16),
        inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }

    .arena-lane-card strong {
      display: block;
      margin-bottom: 7px;
      font-size: 15px;
      line-height: 1.02;
    }

    .arena-lane-card .arena-slot-meta {
      font-size: 12px;
      line-height: 1.22;
      opacity: 0.94;
    }

    .arena-action-sticker {
      position: absolute;
      right: 8px;
      bottom: 8px;
      width: 34px;
      height: 34px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(216, 228, 255, 0.18);
      background: rgba(7, 16, 28, 0.38);
      backdrop-filter: blur(4px);
      opacity: 0.72;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    }

    .arena-lane-card.simplified .arena-action-sticker {
      left: 50%;
      top: 50%;
      right: auto;
      bottom: auto;
      transform: translate(-50%, -50%);
      width: auto;
      height: auto;
      padding: 0;
      opacity: 0.96;
      background: transparent;
      border: none;
      box-shadow: none;
      backdrop-filter: none;
    }

    .arena-action-sticker svg {
      width: 18px;
      height: 18px;
      display: block;
    }

    .arena-lane-card.simplified .arena-action-sticker svg {
      width: 32px;
      height: 32px;
    }

    .arena-action-sticker span {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      line-height: 1;
    }

    .arena-lane-card.simplified .arena-action-sticker span {
      font-size: 42px;
      line-height: 1;
      text-shadow: 0 8px 24px rgba(0, 0, 0, 0.42);
    }

    .arena-action-sticker.burst {
      border-color: rgba(255, 122, 134, 0.34);
      background: rgba(74, 24, 37, 0.34);
      color: rgba(255, 210, 216, 0.95);
    }

    .arena-action-sticker.guard {
      border-color: rgba(83, 246, 184, 0.34);
      background: rgba(18, 57, 50, 0.34);
      color: rgba(215, 255, 239, 0.95);
    }

    .arena-action-sticker.ability {
      border-color: rgba(255, 211, 110, 0.38);
      background: rgba(92, 67, 20, 0.36);
      color: rgba(255, 238, 179, 0.98);
    }

    .arena-lane-impact {
      position: absolute;
      left: 50%;
      top: 50%;
      width: 34px;
      height: 34px;
      border-radius: 999px;
      transform: translate(-50%, -50%) scale(0.3);
      border: 2px solid rgba(216, 228, 255, 0.18);
      background: radial-gradient(circle, rgba(216, 228, 255, 0.26), rgba(216, 228, 255, 0.02) 70%);
      box-shadow: 0 0 24px rgba(216, 228, 255, 0.18);
      opacity: 0;
    }

    .arena-lane-impact.visible {
      animation: laneImpactPulse 300ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .arena-lane-impact.win {
      border-color: rgba(83, 246, 184, 0.34);
      background: radial-gradient(circle, rgba(83, 246, 184, 0.28), rgba(83, 246, 184, 0.04) 72%);
      box-shadow: 0 0 28px rgba(83, 246, 184, 0.26);
    }

    .arena-lane-impact.lose {
      border-color: rgba(255, 122, 134, 0.34);
      background: radial-gradient(circle, rgba(255, 122, 134, 0.28), rgba(255, 122, 134, 0.04) 72%);
      box-shadow: 0 0 28px rgba(255, 122, 134, 0.24);
    }

    .arena-lane-impact.draw {
      border-color: rgba(255, 211, 110, 0.34);
      background: radial-gradient(circle, rgba(255, 211, 110, 0.26), rgba(255, 211, 110, 0.04) 72%);
      box-shadow: 0 0 28px rgba(255, 211, 110, 0.2);
    }

    .arena-clash-debug {
      position: absolute;
      left: 12px;
      top: 12px;
      z-index: 14;
      display: grid;
      gap: 6px;
      padding: 8px 10px;
      border-radius: 12px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background: rgba(4, 12, 22, 0.88);
      color: rgba(224, 239, 255, 0.96);
      font-size: 10px;
      line-height: 1.25;
      backdrop-filter: blur(10px);
      max-width: min(280px, calc(100% - 24px));
      pointer-events: none;
    }

    .season-pass-scroll {
      display: block;
      overflow-x: scroll;
      overflow-y: hidden;
      width: 100%;
      max-width: 100%;
      padding-bottom: 8px;
      padding-inline: 0 24px;
      -webkit-overflow-scrolling: touch;
      touch-action: pan-x;
      scroll-snap-type: x proximity;
      scroll-behavior: smooth;
      scrollbar-width: thin;
      overscroll-behavior-x: contain;
      cursor: grab;
      pointer-events: auto;
    }

    .season-pass-level-row {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-items: start;
    }

    .season-pass-level-meta {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
      flex-wrap: wrap;
    }

    .season-pass-level-badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(10, 23, 40, 0.78);
      color: #eef6ff;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .season-pass-level-row .catalog-card {
      min-width: 0 !important;
    }

    .season-pass-stage-card {
      display: none !important;
    }

    .season-pass-stage-card.is-active {
      display: grid !important;
    }

    .season-pass-scroll.dragging {
      cursor: grabbing;
      user-select: none;
    }

    .season-pass-track {
      display: flex;
      flex-wrap: nowrap;
      gap: 12px;
      width: max-content;
      min-width: max-content;
      padding-right: 320px;
    }

    .season-pass-track > * {
      scroll-snap-align: start;
      flex: 0 0 clamp(216px, 30vw, 260px);
    }

    .season-pass-scroll[data-pass-track] {
      max-width: 100%;
    }

    .season-pass-board .catalog-card strong {
      overflow-wrap: anywhere;
      word-break: break-word;
    }

    .season-pass-jump {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-top: 12px;
      flex-wrap: wrap;
    }

    .season-pass-nav-btn {
      min-width: 112px;
      justify-content: center;
      white-space: nowrap;
    }

    .arena-clash-debug strong {
      color: #fff1c5;
      font-size: 10px;
    }

    .arena-lane-card-debug {
      position: absolute;
      left: 6px;
      top: 6px;
      z-index: 15;
      max-width: calc(100% - 12px);
      padding: 3px 6px;
      border-radius: 999px;
      background: rgba(4, 12, 22, 0.78);
      border: 1px solid rgba(121, 217, 255, 0.16);
      color: rgba(230, 240, 255, 0.95);
      font-size: 9px;
      line-height: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      backdrop-filter: blur(8px);
    }

    .arena-score-card {
      width: min(100%, 360px);
      display: grid;
      gap: 10px;
      justify-items: center;
      padding: 18px 16px;
      border-radius: 22px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background: linear-gradient(180deg, rgba(8, 20, 34, 0.95), rgba(5, 11, 21, 0.98));
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
    }

    .arena-score-card .showdown-score {
      margin: 0;
    }

    .arena-score-card.prestart-hidden {
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
    }

    .arena-score-pips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: center;
    }

    .arena-score-pip {
      min-height: 30px;
      padding: 0 12px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(255, 211, 110, 0.22);
      background: rgba(255, 211, 110, 0.08);
      color: #ffe59d;
      font-size: 12px;
      letter-spacing: 0.05em;
    }

    .battleflow-shell {
      display: grid;
      gap: 14px;
    }

    .battleflow-summary {
      padding: 14px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(8, 20, 36, 0.86);
    }

    .battleflow-summary .showdown-score {
      margin: 8px 0 0;
    }

    .arena-core.flash-focus {
      animation: arenaFocusPulse 920ms cubic-bezier(.16,.84,.2,1);
    }

    @keyframes arenaDashFlow {
      0% {
        stroke-dashoffset: 0;
      }
      100% {
        stroke-dashoffset: -120;
      }
    }

    @keyframes arenaFocusPulse {
      0% {
        box-shadow:
          inset 0 0 0 1px rgba(255, 255, 255, 0.02),
          inset 0 0 90px rgba(0, 0, 0, 0.18),
          0 0 0 0 rgba(83, 246, 184, 0);
      }
      45% {
        box-shadow:
          inset 0 0 0 1px rgba(83, 246, 184, 0.08),
          inset 0 0 90px rgba(0, 0, 0, 0.18),
          0 0 0 8px rgba(83, 246, 184, 0.12);
      }
      100% {
        box-shadow:
          inset 0 0 0 1px rgba(255, 255, 255, 0.02),
          inset 0 0 90px rgba(0, 0, 0, 0.18),
          0 0 0 0 rgba(83, 246, 184, 0);
      }
    }

    .showdown-deck {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      overflow-y: hidden;
      scrollbar-width: thin;
      padding-bottom: 4px;
    }

    .showdown-deck::-webkit-scrollbar {
      height: 8px;
    }

    .showdown-deck::-webkit-scrollbar-thumb {
      background: rgba(121, 217, 255, 0.35);
      border-radius: 999px;
    }

    .showdown-card {
      flex: 0 0 188px;
      min-width: 188px;
      border: 1px solid rgba(121, 217, 255, 0.25);
      border-radius: 14px;
      padding: 10px;
      background: rgba(255, 255, 255, 0.04);
    }

    .showdown-card strong {
      display: block;
      margin-bottom: 6px;
      font-size: 13px;
    }

    .showdown-center {
      padding: 0;
      border: 0;
      background: transparent;
      backdrop-filter: none;
      box-shadow: none;
      overflow: visible;
    }

    .showdown-score {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 14px;
      font-size: clamp(24px, 6vw, 42px);
      font-weight: 800;
      letter-spacing: 0.06em;
      margin-bottom: 10px;
    }

    .showdown-score .count-up {
      text-shadow: 0 0 18px rgba(83, 246, 184, 0.45);
    }

    .discipline-list {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }

    .discipline-row {
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 12px;
      padding: 9px 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      opacity: 0;
      transform: translateY(8px);
      transition: opacity 260ms ease, transform 260ms ease;
    }

    .discipline-row.visible {
      opacity: 1;
      transform: translateY(0);
    }

    .discipline-row.win {
      border-color: rgba(83, 246, 184, 0.45);
      background: rgba(83, 246, 184, 0.1);
    }

    .discipline-row.lose {
      border-color: rgba(255, 122, 134, 0.45);
      background: rgba(255, 122, 134, 0.1);
    }

    .discipline-row.draw {
      border-color: rgba(255, 211, 110, 0.45);
      background: rgba(255, 211, 110, 0.1);
    }

    .discipline-row.round-clash {
      display: grid;
      gap: 12px;
      align-items: stretch;
      justify-content: stretch;
      padding: 14px;
      background:
        radial-gradient(circle at 50% 50%, rgba(69, 215, 255, 0.06), transparent 42%),
        rgba(255, 255, 255, 0.03);
      overflow: hidden;
    }

    .discipline-row.round-clash.visible {
      animation: clashRowReveal 420ms cubic-bezier(.16,.84,.2,1);
    }

    .discipline-row.round-clash.visible .arena-clash-card.player {
      animation: clashCardLeftIn 560ms cubic-bezier(.16,.84,.2,1);
    }

    .discipline-row.round-clash.visible .arena-clash-card.enemy {
      animation: clashCardRightIn 560ms cubic-bezier(.16,.84,.2,1);
    }

    .discipline-row.round-clash.visible .arena-clash-versus {
      animation: clashVersusPulse 520ms cubic-bezier(.16,.84,.2,1) 160ms both;
    }

    .discipline-row.round-clash.visible .arena-clash-winner {
      animation: clashResultIn 420ms cubic-bezier(.16,.84,.2,1) 360ms both;
    }

    .discipline-row.round-clash.visible .arena-decision-chips .arena-decision-chip {
      animation-duration: 440ms;
      animation-fill-mode: both;
    }

    @keyframes clashRowReveal {
      0% {
        opacity: 0;
        transform: translateY(10px) scale(0.985);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    @keyframes clashCardLeftIn {
      0% {
        opacity: 0;
        transform: translateX(-28px) scale(0.94) rotate(-4deg);
      }
      60% {
        opacity: 1;
        transform: translateX(8px) scale(1.02) rotate(1deg);
      }
      100% {
        opacity: 1;
        transform: translateX(0) scale(1) rotate(0deg);
      }
    }

    @keyframes clashCardRightIn {
      0% {
        opacity: 0;
        transform: translateX(28px) scale(0.94) rotate(4deg);
      }
      60% {
        opacity: 1;
        transform: translateX(-8px) scale(1.02) rotate(-1deg);
      }
      100% {
        opacity: 1;
        transform: translateX(0) scale(1) rotate(0deg);
      }
    }

    @keyframes clashVersusPulse {
      0% {
        opacity: 0;
        transform: scale(0.82);
      }
      60% {
        opacity: 1;
        transform: scale(1.08);
      }
      100% {
        opacity: 1;
        transform: scale(1);
      }
    }

    @keyframes clashResultIn {
      0% {
        opacity: 0;
        transform: translateY(8px) scale(0.9);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    @keyframes laneImpactPulse {
      0% {
        opacity: 0;
        transform: translate(-50%, -50%) scale(0.28);
      }
      45% {
        opacity: 1;
        transform: translate(-50%, -50%) scale(1.18);
      }
      100% {
        opacity: 0;
        transform: translate(-50%, -50%) scale(1.7);
      }
    }

    @keyframes roundClashFadeOut {
      0% {
        opacity: 1;
      }
      100% {
        opacity: 0;
      }
    }

    @keyframes laneClashIn {
      0% {
        opacity: 0;
        transform: translateY(10px) scale(0.96);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    @keyframes laneCardTopDown {
      0% {
        opacity: 0;
        transform: translateY(-86px) scale(0.92);
      }
      72% {
        opacity: 1;
        transform: translateY(14px) scale(1.03);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    @keyframes laneCardBottomUp {
      0% {
        opacity: 0;
        transform: translateY(86px) scale(0.92);
      }
      72% {
        opacity: 1;
        transform: translateY(-14px) scale(1.03);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    .strategy-note-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }

    .action-chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(255, 255, 255, 0.04);
      font-size: 12px;
    }

    .action-chip.burst { border-color: rgba(255, 122, 134, 0.48); }
    .action-chip.guard { border-color: rgba(83, 246, 184, 0.48); }
    .action-chip.channel { border-color: rgba(69, 215, 255, 0.48); }

    .match-outcome {
      transition: opacity 300ms ease, transform 300ms ease;
    }

    .delayed-outcome {
      opacity: 0;
      transform: translateY(6px) scale(0.98);
      pointer-events: none;
    }

    .delayed-outcome.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }

    .prebattle-stage {
      display: grid;
      gap: 8px;
      justify-items: center;
      padding: 8px 4px;
    }

    .prebattle-stage.accept-pop,
    .showdown-main.accept-pop {
      animation: acceptGamePop 720ms cubic-bezier(.16,.84,.2,1);
      transform-origin: center center;
    }

    @keyframes acceptGamePop {
      0% {
        opacity: 0;
        transform: scale(0.72) translateY(26px);
        filter: blur(4px);
      }
      55% {
        opacity: 1;
        transform: scale(1.04) translateY(-6px);
        filter: blur(0);
      }
      100% {
        opacity: 1;
        transform: scale(1) translateY(0);
        filter: blur(0);
      }
    }

    .prebattle-stage.hidden {
      display: none;
    }

    .battle-stage {
      display: none;
    }

    .battle-stage.visible {
      display: grid;
      gap: 12px;
      align-content: start;
    }

    .interactive-battle-panel {
      position: relative;
      display: grid;
      gap: 12px;
      margin: 14px 0 10px;
      padding: 14px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.2);
      background: linear-gradient(135deg, rgba(8, 23, 43, 0.82), rgba(10, 29, 34, 0.88));
      box-shadow: 0 18px 44px rgba(0, 0, 0, 0.22);
      isolation: isolate;
      overflow: hidden;
    }

    .interactive-battle-panel::before,
    .interactive-battle-panel::after {
      content: "";
      position: absolute;
      inset: -24%;
      opacity: 0;
      pointer-events: none;
      z-index: -1;
    }

    .interactive-battle-panel::before {
      background:
        radial-gradient(circle at 50% 50%, rgba(69, 215, 255, 0.18), transparent 34%),
        radial-gradient(circle at 50% 50%, rgba(83, 246, 184, 0.14), transparent 54%);
      transform: scale(0.72);
      filter: blur(10px);
    }

    .interactive-battle-panel::after {
      inset: -10%;
      border-radius: 32px;
      border: 1px solid rgba(121, 217, 255, 0.2);
      background: conic-gradient(from 180deg, transparent, rgba(69, 215, 255, 0.16), transparent, rgba(83, 246, 184, 0.14), transparent);
      filter: blur(2px);
    }

    .interactive-battle-panel.menu-live {
      animation: battleMenuRise 760ms cubic-bezier(.16,.84,.2,1);
    }

    .interactive-battle-panel.menu-live .interactive-battle-title,
    .interactive-battle-panel.menu-live #interactive-battle-status {
      animation: battleMenuFade 520ms ease forwards;
    }

    .interactive-battle-panel.menu-live::before {
      animation: battleMenuAura 980ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .interactive-battle-panel.menu-live::after {
      animation: battleMenuRing 1200ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .interactive-battle-panel.floating {
      position: relative;
      top: auto;
      z-index: 12;
      width: min(100%, 560px);
      margin: 0 0 14px;
      padding: 18px 16px 16px;
      border-radius: 24px;
      border-color: rgba(121, 217, 255, 0.32);
      background:
        linear-gradient(135deg, rgba(7, 19, 35, 0.96), rgba(10, 31, 39, 0.97)),
        radial-gradient(circle at top, rgba(69, 215, 255, 0.16), transparent 55%);
      box-shadow:
        0 20px 54px rgba(0, 0, 0, 0.38),
        0 0 0 1px rgba(121, 217, 255, 0.08);
      backdrop-filter: blur(18px);
    }

    .interactive-battle-title {
      text-align: center;
      font-weight: 800;
      letter-spacing: 0.03em;
      font-size: clamp(18px, 5vw, 24px);
      color: var(--arena-ui-text);
    }

    .interactive-timer {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      min-width: 92px;
      margin: 0 auto;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid var(--arena-ui-chip-border);
      background: var(--arena-ui-chip-bg);
      color: var(--arena-ui-chip-text);
      font-weight: 800;
      letter-spacing: 0.04em;
      box-shadow: 0 10px 24px var(--arena-ui-accent-soft);
    }

    .interactive-battle-actions {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));
      gap: 10px;
      perspective: 1200px;
    }

    .interactive-action-btn {
      min-height: 54px;
      border-radius: 16px;
      border: 1px solid var(--arena-ui-accent-border);
      background: linear-gradient(135deg, var(--arena-ui-accent-soft), rgba(255, 255, 255, 0.04));
      color: var(--arena-ui-text);
      font-weight: 800;
      opacity: 0;
      transform: translateY(12px) scale(0.94);
      transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease, opacity 220ms ease;
    }

    .interactive-action-btn:hover,
    .interactive-action-btn:active {
      transform: translateY(-1px) scale(1.01);
      box-shadow: 0 12px 28px var(--arena-ui-accent-soft);
    }

    .interactive-action-btn.burst {
      border-color: var(--arena-ui-accent-border);
      background: linear-gradient(135deg, var(--arena-ui-accent-soft), rgba(255, 255, 255, 0.04));
    }

    .interactive-action-btn.guard {
      border-color: var(--arena-ui-accent-border);
      background: linear-gradient(135deg, var(--arena-ui-accent-soft), rgba(255, 255, 255, 0.04));
    }

    .interactive-action-btn.channel {
      border-color: var(--arena-ui-accent-border);
      background: linear-gradient(135deg, var(--arena-ui-accent-soft), rgba(255, 255, 255, 0.04));
    }

    .interactive-action-btn.ability {
      border-color: var(--arena-ui-chip-border);
      background: linear-gradient(135deg, var(--arena-ui-chip-bg), rgba(255, 255, 255, 0.04));
      color: var(--arena-ui-chip-text);
    }

    .interactive-action-btn.choice-ready {
      opacity: 1;
      transform: translateY(0) scale(1);
      animation: choiceBreath 1.7s ease-in-out infinite;
    }

    .interactive-battle-panel.menu-live .interactive-action-btn:nth-child(1) {
      animation: choiceEnterLeft 560ms cubic-bezier(.16,.84,.2,1) forwards, choiceBreath 1.7s ease-in-out 620ms infinite;
    }

    .interactive-battle-panel.menu-live .interactive-action-btn:nth-child(2) {
      animation: choiceEnterCenter 620ms cubic-bezier(.16,.84,.2,1) forwards, choiceBreath 1.7s ease-in-out 700ms infinite;
    }

    .interactive-battle-panel.menu-live .interactive-action-btn:nth-child(3) {
      animation: choiceEnterRight 560ms cubic-bezier(.16,.84,.2,1) forwards, choiceBreath 1.7s ease-in-out 780ms infinite;
    }

    .interactive-action-btn.choice-picked {
      opacity: 1;
      animation: choiceConfirm 520ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .interactive-action-btn.tutorial-focus {
      opacity: 1;
      transform: translateY(0) scale(1.03);
      border-color: rgba(255, 211, 110, 0.72);
      box-shadow:
        0 0 0 1px rgba(255, 211, 110, 0.22),
        0 16px 32px rgba(255, 211, 110, 0.18);
      animation: tutorialPulse 1.45s ease-in-out infinite;
    }

    .tutorial-tip-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 12px;
      border-radius: 999px;
      border: 1px solid rgba(255, 211, 110, 0.26);
      background: rgba(255, 211, 110, 0.1);
      color: rgba(255, 236, 189, 0.98);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      width: fit-content;
      margin-bottom: 10px;
    }

    @keyframes battleMenuRise {
      0% {
        opacity: 0;
        transform: translateY(34px) scale(0.9) rotateX(18deg);
        filter: blur(8px);
      }
      62% {
        opacity: 1;
        transform: translateY(-8px) scale(1.02) rotateX(-4deg);
        filter: blur(0);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1) rotateX(0deg);
        filter: blur(0);
      }
    }

    @keyframes tutorialPulse {
      0% { transform: translateY(0) scale(1); }
      50% { transform: translateY(-2px) scale(1.02); }
      100% { transform: translateY(0) scale(1); }
    }

    @keyframes tutorialRoutePulse {
      0% { opacity: 0.7; }
      50% { opacity: 1; }
      100% { opacity: 0.7; }
    }

    @keyframes battleMenuFade {
      0% {
        opacity: 0;
        transform: translateY(10px);
      }
      100% {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @keyframes battleMenuAura {
      0% {
        opacity: 0;
        transform: scale(0.62);
      }
      45% {
        opacity: 1;
        transform: scale(1.02);
      }
      100% {
        opacity: 0.46;
        transform: scale(1.18);
      }
    }

    @keyframes battleMenuRing {
      0% {
        opacity: 0;
        transform: scale(0.86) rotate(-14deg);
      }
      55% {
        opacity: 0.9;
        transform: scale(1.03) rotate(4deg);
      }
      100% {
        opacity: 0.24;
        transform: scale(1.08) rotate(10deg);
      }
    }

    @keyframes choiceBreath {
      0%, 100% {
        box-shadow: 0 0 0 rgba(69, 215, 255, 0);
      }
      50% {
        box-shadow: 0 14px 30px rgba(69, 215, 255, 0.18);
      }
    }

    @keyframes choiceEnterLeft {
      0% {
        opacity: 0;
        transform: translate3d(-42px, 22px, 0) rotate(-9deg) scale(0.88);
      }
      70% {
        opacity: 1;
        transform: translate3d(4px, -4px, 0) rotate(2deg) scale(1.02);
      }
      100% {
        opacity: 1;
        transform: translate3d(0, 0, 0) rotate(0deg) scale(1);
      }
    }

    @keyframes choiceEnterCenter {
      0% {
        opacity: 0;
        transform: translate3d(0, 28px, 0) scale(0.84);
      }
      68% {
        opacity: 1;
        transform: translate3d(0, -6px, 0) scale(1.04);
      }
      100% {
        opacity: 1;
        transform: translate3d(0, 0, 0) scale(1);
      }
    }

    @keyframes choiceEnterRight {
      0% {
        opacity: 0;
        transform: translate3d(42px, 22px, 0) rotate(9deg) scale(0.88);
      }
      70% {
        opacity: 1;
        transform: translate3d(-4px, -4px, 0) rotate(-2deg) scale(1.02);
      }
      100% {
        opacity: 1;
        transform: translate3d(0, 0, 0) rotate(0deg) scale(1);
      }
    }

    @keyframes choiceConfirm {
      0% {
        transform: translateY(0) scale(1);
        box-shadow: 0 0 0 rgba(255,255,255,0);
      }
      45% {
        transform: translateY(-3px) scale(1.08);
        box-shadow: 0 0 0 10px rgba(255,255,255,0.08);
      }
      100% {
        transform: translateY(0) scale(1);
        box-shadow: 0 0 0 0 rgba(255,255,255,0);
      }
    }

    @keyframes floatingBattlePanelIn {
      from {
        opacity: 0;
        transform: translateY(10px) scale(0.96);
      }
      to {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }


    .showdown-entry-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: center;
      margin: 2px 0 2px;
    }

    .victory-banner {
      margin-top: 12px;
      border: 1px solid rgba(83, 246, 184, 0.55);
      border-radius: 14px;
      padding: 10px 12px;
      text-align: center;
      font-weight: 700;
      color: #d9ffe8;
      background: linear-gradient(135deg, rgba(83, 246, 184, 0.24), rgba(69, 215, 255, 0.16));
      box-shadow: 0 10px 26px rgba(83, 246, 184, 0.2);
      animation: victoryPulse 1.1s ease-in-out infinite;
    }

    .team-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 0;
    }

    .tiny {
      font-size: 13px;
      color: var(--muted);
    }

    .discipline-build-grid {
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(2, minmax(140px, 1fr));
      margin-top: 10px;
    }

    .discipline-build-grid label {
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
    }

    .mobile-nav {
      position: fixed;
      left: 106px;
      right: 12px;
      bottom: 12px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      width: auto;
      padding: 8px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(7, 16, 25, 0.96);
      backdrop-filter: blur(16px);
      z-index: 40;
      box-shadow: 0 18px 34px rgba(0, 0, 0, 0.34);
    }

    .mobile-nav button {
      min-height: 42px;
      height: 42px;
      padding: 6px 10px;
      font-size: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      line-height: 1;
      white-space: normal;
      word-break: break-word;
      min-width: 0;
      border-radius: 12px;
    }

    .mobile-nav button.active {
      border-color: rgba(83, 246, 184, 0.58);
      background: linear-gradient(135deg, rgba(69, 215, 255, 0.2), rgba(83, 246, 184, 0.18));
    }

    .startup-guide {
      position: fixed;
      inset: 0;
      z-index: 6200;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 16px;
      background: rgba(2, 8, 16, 0.82);
      backdrop-filter: blur(9px);
    }

    .startup-guide.visible {
      display: flex;
    }

    .startup-guide-card {
      width: min(760px, calc(100vw - 28px));
      border-radius: 22px;
      border: 1px solid var(--line);
      background: linear-gradient(165deg, rgba(8, 20, 36, 0.96), rgba(10, 18, 33, 0.94));
      box-shadow: var(--shadow);
      padding: 18px;
    }

    .startup-guide-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
      font-size: 12px;
      color: var(--muted);
    }

    .startup-guide-dots {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .startup-guide-dots i {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: rgba(151, 175, 200, 0.36);
      transition: transform 0.2s ease, background 0.2s ease;
    }

    .startup-guide-dots i.active {
      background: rgba(83, 246, 184, 0.9);
      transform: scale(1.12);
    }

    .startup-guide-stage {
      position: relative;
      height: 260px;
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.2);
      background: radial-gradient(circle at center, rgba(69, 215, 255, 0.2), rgba(8, 20, 36, 0.94));
      overflow: hidden;
      margin-bottom: 12px;
    }

    .startup-guide-gif {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      border-radius: 16px;
      display: block;
    }

    .startup-guide-stage-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 22px;
      font-size: 30px;
      color: #ecf7ff;
      text-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
      background: linear-gradient(180deg, rgba(8, 18, 30, 0.25), rgba(8, 18, 30, 0.5));
    }

    .startup-guide-copy {
      display: grid;
      gap: 8px;
      margin-bottom: 10px;
    }

    .startup-guide-copy strong {
      display: block;
      font-size: 18px;
      line-height: 1.2;
      color: #f4fbff;
    }

    .startup-guide-copy .tiny {
      margin: 0;
      line-height: 1.45;
      color: rgba(223, 243, 255, 0.8);
    }

    .startup-guide-scene {
      position: relative;
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #eaf6ff;
    }

    .startup-guide-scene-column {
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 18px;
    }

    .startup-guide-note {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      max-width: min(560px, calc(100% - 52px));
      min-height: 56px;
      padding: 14px 18px;
      border-radius: 18px;
      border: 1px solid rgba(255, 211, 110, 0.34);
      background:
        radial-gradient(circle at top, rgba(255, 211, 110, 0.16), transparent 65%),
        rgba(10, 20, 34, 0.88);
      color: #fff4cf;
      font-size: 16px;
      font-weight: 800;
      line-height: 1.35;
      text-align: center;
      box-shadow: 0 16px 28px rgba(0, 0, 0, 0.22);
      backdrop-filter: blur(10px);
    }

    .startup-guide-scene-grid {
      position: absolute;
      inset: 18px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background:
        linear-gradient(90deg, rgba(121, 217, 255, 0.08) 1px, transparent 1px) 0 0 / 25% 100%,
        linear-gradient(0deg, rgba(121, 217, 255, 0.08) 1px, transparent 1px) 0 0 / 100% 50%;
      pointer-events: none;
    }

    .startup-guide-flowboard {
      position: relative;
      width: min(620px, calc(100% - 52px));
      height: 186px;
      border-radius: 28px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background:
        radial-gradient(circle at 50% 50%, rgba(88, 210, 255, 0.09), transparent 42%),
        linear-gradient(135deg, rgba(10, 22, 40, 0.92), rgba(7, 16, 29, 0.9));
      overflow: hidden;
    }

    .startup-guide-flowboard::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, transparent 0 24%, rgba(121, 217, 255, 0.05) 24% 24.3%, transparent 24.3% 100%),
        linear-gradient(0deg, transparent 0 50%, rgba(121, 217, 255, 0.05) 50% 50.3%, transparent 50.3% 100%);
      pointer-events: none;
    }

    .startup-guide-wallet-card {
      position: absolute;
      left: 34px;
      top: 24px;
      width: 210px;
      height: 138px;
      border-radius: 24px;
      border: 1px solid rgba(96, 213, 255, 0.5);
      background: linear-gradient(180deg, rgba(9, 21, 37, 0.98), rgba(6, 15, 27, 0.94));
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.28);
      overflow: hidden;
      animation: startupGuideFloatCard 4.6s ease-in-out infinite;
    }

    .startup-guide-wallet-card::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 18% 18%, rgba(88, 210, 255, 0.14), transparent 28%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent 34%);
      pointer-events: none;
    }

    .startup-guide-wallet-card .head {
      position: absolute;
      left: 18px;
      top: 16px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.16em;
      color: rgba(160, 220, 245, 0.74);
      text-transform: uppercase;
    }

    .startup-guide-wallet-card .name {
      position: absolute;
      left: 18px;
      top: 44px;
      font-size: 24px;
      font-weight: 900;
      color: #eef8ff;
    }

    .startup-guide-wallet-card .rows {
      position: absolute;
      left: 18px;
      right: 18px;
      bottom: 18px;
      display: grid;
      gap: 9px;
    }

    .startup-guide-wallet-card .rows i {
      display: block;
      height: 10px;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(88, 210, 255, 0.18), rgba(88, 210, 255, 0.58), rgba(88, 210, 255, 0.18));
      background-size: 180% 100%;
      animation: startupGuideShimmer 3s linear infinite;
    }

    .startup-guide-wallet-card .rows i:nth-child(2) { width: 82%; }
    .startup-guide-wallet-card .rows i:nth-child(3) { width: 66%; }

    .startup-guide-domain-panel {
      position: absolute;
      right: 36px;
      top: 40px;
      width: 260px;
      height: 104px;
      border-radius: 24px;
      border: 1px solid rgba(96, 213, 255, 0.44);
      background: linear-gradient(180deg, rgba(8, 18, 32, 0.96), rgba(8, 18, 32, 0.88));
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.24);
      overflow: hidden;
      animation: startupGuideDomainGlow 3.8s ease-in-out infinite;
    }

    .startup-guide-domain-panel::before {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(88, 210, 255, 0.06), transparent 55%);
      pointer-events: none;
    }

    .startup-guide-domain-panel .tag {
      position: absolute;
      left: 18px;
      top: 18px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(96, 213, 255, 0.22);
      background: rgba(88, 210, 255, 0.08);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: rgba(190, 232, 245, 0.76);
      text-transform: uppercase;
    }

    .startup-guide-domain-panel .domain {
      position: absolute;
      left: 18px;
      top: 48px;
      font-size: 28px;
      font-weight: 900;
      letter-spacing: 0.02em;
      color: #f4fbff;
    }

    .startup-guide-bridge {
      position: absolute;
      left: 244px;
      right: 296px;
      top: 93px;
      height: 4px;
      transform: translateY(-50%);
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(88, 210, 255, 0.22), rgba(88, 210, 255, 0.62), rgba(88, 210, 255, 0.22));
      box-shadow: 0 0 18px rgba(88, 210, 255, 0.18);
    }

    .startup-guide-bridge::before,
    .startup-guide-bridge::after {
      content: "";
      position: absolute;
      border-radius: 50%;
    }

    .startup-guide-bridge::before {
      left: 12%;
      top: -8px;
      width: 20px;
      height: 20px;
      background: rgba(88, 210, 255, 0.92);
      box-shadow: 0 0 24px rgba(88, 210, 255, 0.52);
      animation: startupGuideBridgePulse 2.8s ease-in-out infinite;
    }

    .startup-guide-bridge::after {
      right: -6px;
      top: -3px;
      width: 10px;
      height: 10px;
      background: rgba(88, 210, 255, 0.44);
      box-shadow: 0 0 12px rgba(88, 210, 255, 0.26);
    }

    .startup-guide-pack-board {
      position: relative;
      width: min(600px, calc(100% - 60px));
      height: 182px;
      border-radius: 28px;
      border: 1px solid rgba(255, 208, 106, 0.18);
      background:
        radial-gradient(circle at 50% 48%, rgba(255, 208, 106, 0.08), transparent 40%),
        linear-gradient(135deg, rgba(10, 22, 40, 0.92), rgba(7, 16, 29, 0.9));
      overflow: hidden;
    }

    .startup-guide-pack-board::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, transparent 0 24%, rgba(255, 208, 106, 0.05) 24% 24.3%, transparent 24.3% 100%),
        linear-gradient(0deg, transparent 0 50%, rgba(255, 208, 106, 0.04) 50% 50.3%, transparent 50.3% 100%);
      pointer-events: none;
    }

    .startup-guide-pack-main {
      position: absolute;
      left: 50%;
      top: 24px;
      transform: translateX(-50%);
      width: 160px;
      height: 134px;
      border-radius: 26px;
      border: 2px solid rgba(255, 208, 106, 0.84);
      background: linear-gradient(180deg, rgba(10, 21, 37, 0.98), rgba(8, 16, 28, 0.96));
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.3);
      animation: startupGuidePackMainFloat 3.6s ease-in-out infinite;
    }

    .startup-guide-pack-main::before {
      content: "";
      position: absolute;
      inset: 14px 18px;
      border-radius: 18px;
      border: 1px solid rgba(255, 208, 106, 0.3);
      background: linear-gradient(180deg, rgba(255, 208, 106, 0.08), rgba(255, 208, 106, 0.02));
    }

    .startup-guide-pack-main::after {
      content: "";
      position: absolute;
      top: 18px;
      bottom: 18px;
      left: 50%;
      width: 3px;
      transform: translateX(-50%);
      background: rgba(255, 208, 106, 0.82);
      border-radius: 999px;
    }

    .startup-guide-pack-side {
      position: absolute;
      top: 44px;
      width: 108px;
      height: 92px;
      border-radius: 20px;
      border: 1px solid rgba(255, 208, 106, 0.28);
      background: rgba(8, 18, 32, 0.72);
    }

    .startup-guide-pack-side.left {
      left: 124px;
      transform: rotate(-6deg);
      animation: startupGuidePackLeft 3.6s ease-in-out infinite;
    }

    .startup-guide-pack-side.right {
      right: 124px;
      transform: rotate(6deg);
      animation: startupGuidePackRight 3.6s ease-in-out infinite;
    }

    .startup-guide-pack-side::before {
      content: "";
      position: absolute;
      inset: 14px 18px;
      border-radius: 14px;
      border: 1px solid rgba(255, 208, 106, 0.16);
    }

    .startup-guide-pack-pips {
      position: absolute;
      left: 50%;
      bottom: 18px;
      transform: translateX(-50%);
      display: flex;
      gap: 8px;
    }

    .startup-guide-pack-pips i {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: rgba(255, 208, 106, 0.82);
      box-shadow: 0 0 14px rgba(255, 208, 106, 0.28);
    }

    .startup-guide-connection-board {
      position: relative;
      width: min(640px, calc(100% - 44px));
      min-height: 198px;
      padding: 26px 30px;
      border-radius: 28px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background:
        radial-gradient(circle at 50% 50%, rgba(88, 210, 255, 0.11), transparent 42%),
        linear-gradient(135deg, rgba(10, 22, 40, 0.94), rgba(7, 16, 29, 0.92));
      display: grid;
      grid-template-columns: minmax(180px, 230px) minmax(76px, 108px) minmax(220px, 1fr);
      align-items: center;
      gap: 18px;
      overflow: hidden;
    }

    .startup-guide-connection-board::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(121, 217, 255, 0.06) 1px, transparent 1px) 0 0 / 25% 100%,
        linear-gradient(0deg, rgba(121, 217, 255, 0.06) 1px, transparent 1px) 0 0 / 100% 50%;
      pointer-events: none;
    }

    .startup-guide-connection-node {
      position: relative;
      z-index: 1;
      min-height: 132px;
      padding: 18px 20px;
      border-radius: 24px;
      border: 1px solid rgba(96, 213, 255, 0.36);
      background: linear-gradient(180deg, rgba(9, 21, 37, 0.98), rgba(6, 15, 27, 0.94));
      box-shadow: 0 18px 36px rgba(0, 0, 0, 0.26);
      display: grid;
      align-content: center;
      gap: 10px;
      overflow: hidden;
    }

    .startup-guide-connection-node::before {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(88, 210, 255, 0.1), transparent 56%);
      pointer-events: none;
    }

    .startup-guide-connection-node .kicker {
      position: relative;
      z-index: 1;
      display: inline-flex;
      align-items: center;
      width: fit-content;
      min-height: 28px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(96, 213, 255, 0.18);
      background: rgba(88, 210, 255, 0.08);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(198, 234, 244, 0.82);
    }

    .startup-guide-connection-node strong {
      position: relative;
      z-index: 1;
      font-size: 32px;
      font-weight: 900;
      line-height: 1;
      color: #f3fbff;
    }

    .startup-guide-connection-node span {
      position: relative;
      z-index: 1;
      font-size: 14px;
      line-height: 1.4;
      color: rgba(198, 224, 242, 0.78);
    }

    .startup-guide-connection-node.wallet {
      animation: startupGuideFloatCard 4.6s ease-in-out infinite;
    }

    .startup-guide-connection-node.domain {
      animation: startupGuideDomainGlow 3.8s ease-in-out infinite;
    }

    .startup-guide-connection-line {
      position: relative;
      z-index: 1;
      height: 6px;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(88, 210, 255, 0.18), rgba(88, 210, 255, 0.58), rgba(88, 210, 255, 0.18));
      box-shadow: 0 0 22px rgba(88, 210, 255, 0.16);
      overflow: visible;
    }

    .startup-guide-connection-line::before {
      content: "";
      position: absolute;
      left: 0;
      top: 50%;
      width: 20px;
      height: 20px;
      transform: translateY(-50%);
      border-radius: 50%;
      background: rgba(88, 210, 255, 0.92);
      box-shadow: 0 0 26px rgba(88, 210, 255, 0.52);
      animation: startupGuideBridgePulse 2.8s ease-in-out infinite;
    }

    .startup-guide-connection-line::after {
      content: "";
      position: absolute;
      right: -4px;
      top: 50%;
      width: 10px;
      height: 10px;
      transform: translateY(-50%);
      border-radius: 50%;
      background: rgba(88, 210, 255, 0.38);
      box-shadow: 0 0 12px rgba(88, 210, 255, 0.24);
    }

    .startup-guide-connection-line i {
      position: absolute;
      left: 18%;
      right: 18%;
      top: 50%;
      height: 2px;
      transform: translateY(-50%);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.18);
    }

    .startup-guide-pack-reveal {
      position: relative;
      width: min(620px, calc(100% - 44px));
      min-height: 194px;
      padding: 24px 28px;
      border-radius: 28px;
      border: 1px solid rgba(255, 208, 106, 0.18);
      background:
        radial-gradient(circle at 50% 46%, rgba(255, 208, 106, 0.1), transparent 42%),
        linear-gradient(135deg, rgba(10, 22, 40, 0.94), rgba(7, 16, 29, 0.92));
      overflow: hidden;
    }

    .startup-guide-pack-reveal::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(255, 208, 106, 0.05) 1px, transparent 1px) 0 0 / 25% 100%,
        linear-gradient(0deg, rgba(255, 208, 106, 0.05) 1px, transparent 1px) 0 0 / 100% 50%;
      pointer-events: none;
    }

    .startup-guide-pack-reveal-card {
      position: absolute;
      top: 30px;
      width: 124px;
      height: 136px;
      border-radius: 20px;
      border: 1px solid rgba(255, 208, 106, 0.24);
      background: linear-gradient(180deg, rgba(9, 20, 35, 0.96), rgba(8, 16, 28, 0.94));
      box-shadow: 0 18px 32px rgba(0, 0, 0, 0.24);
      overflow: hidden;
    }

    .startup-guide-pack-reveal-card::before {
      content: "";
      position: absolute;
      inset: 12px;
      border-radius: 14px;
      border: 1px solid rgba(255, 208, 106, 0.18);
      background: linear-gradient(180deg, rgba(255, 208, 106, 0.04), transparent 80%);
    }

    .startup-guide-pack-reveal-card::after {
      content: attr(data-tier);
      position: absolute;
      left: 14px;
      bottom: 14px;
      min-height: 24px;
      padding: 0 10px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(255, 244, 220, 0.92);
      border: 1px solid rgba(255, 208, 106, 0.26);
      background: rgba(255, 208, 106, 0.08);
    }

    .startup-guide-pack-reveal-card.left {
      left: 108px;
      transform: rotate(-10deg);
      opacity: 0.86;
      animation: startupGuidePackLeft 3.6s ease-in-out infinite;
    }

    .startup-guide-pack-reveal-card.center {
      left: 50%;
      transform: translateX(-50%);
      width: 148px;
      height: 156px;
      z-index: 2;
      border-width: 2px;
      border-color: rgba(255, 208, 106, 0.68);
      animation: startupGuidePackMainFloat 3.6s ease-in-out infinite;
    }

    .startup-guide-pack-reveal-card.right {
      right: 108px;
      transform: rotate(10deg);
      opacity: 0.86;
      animation: startupGuidePackRight 3.6s ease-in-out infinite;
    }

    .startup-guide-pack-reveal-card .glyph {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 48px;
      filter: drop-shadow(0 10px 18px rgba(0,0,0,0.24));
    }

    .startup-guide-pack-reveal-card.center .glyph {
      font-size: 58px;
    }

    .startup-guide-pack-reveal-burst {
      position: absolute;
      left: 50%;
      top: 50%;
      width: 220px;
      height: 220px;
      transform: translate(-50%, -50%);
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255, 208, 106, 0.18), rgba(255, 208, 106, 0.02) 58%, transparent 72%);
      filter: blur(2px);
      opacity: 0.88;
      animation: startupGuideCenterPulse 2.8s ease-in-out infinite;
    }

    @keyframes startupGuideFloatCard {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-4px); }
    }

    @keyframes startupGuideDomainGlow {
      0%, 100% { box-shadow: 0 18px 36px rgba(0, 0, 0, 0.24); }
      50% { box-shadow: 0 18px 36px rgba(0, 0, 0, 0.24), 0 0 26px rgba(88, 210, 255, 0.14); }
    }

    @keyframes startupGuideBridgePulse {
      0%, 100% { left: 8%; opacity: 0.7; }
      50% { left: calc(100% - 28px); opacity: 1; }
    }

    @keyframes startupGuideBridgePulseVertical {
      0%, 100% { top: 4px; opacity: 0.7; }
      50% { top: calc(100% - 18px); opacity: 1; }
    }

    @keyframes startupGuideShimmer {
      0% { background-position: 100% 0; }
      100% { background-position: -100% 0; }
    }

    @keyframes startupGuidePackMainFloat {
      0%, 100% { transform: translateX(-50%) translateY(0); }
      50% { transform: translateX(-50%) translateY(-5px); }
    }

    @keyframes startupGuidePackLeft {
      0%, 100% { transform: rotate(-6deg) translateY(0); }
      50% { transform: rotate(-9deg) translateY(3px); }
    }

    @keyframes startupGuidePackRight {
      0%, 100% { transform: rotate(6deg) translateY(0); }
      50% { transform: rotate(9deg) translateY(3px); }
    }

    @keyframes startupGuideBarWave {
      0%, 100% { transform: scaleY(1); opacity: 0.9; }
      50% { transform: scaleY(1.08); opacity: 1; }
    }

    @keyframes startupGuideSoftPulse {
      0%, 100% { transform: translateY(0); box-shadow: 0 12px 24px rgba(0, 0, 0, 0.22); }
      50% { transform: translateY(-3px); box-shadow: 0 16px 28px rgba(0, 0, 0, 0.24), 0 0 18px rgba(121, 217, 255, 0.08); }
    }

    @keyframes startupGuideNodePulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.04); }
    }

    @keyframes startupGuideCenterPulse {
      0%, 100% { transform: translateX(-50%) scale(1); }
      50% { transform: translateX(-50%) scale(1.03); }
    }

    @keyframes startupGuideRailSize {
      0%, 100% { width: 58%; }
      50% { width: 44%; }
    }

    @keyframes startupGuideTileLift {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-4px); }
    }

    @media (max-width: 700px) {
      .startup-guide-flowboard {
        height: 214px;
      }

      .startup-guide-wallet-card {
        left: 14px;
        top: 16px;
        width: calc(100% - 28px);
        height: 82px;
      }

      .startup-guide-wallet-card .head {
        font-size: 9px;
      }

      .startup-guide-wallet-card .name {
        top: 26px;
        font-size: 18px;
      }

      .startup-guide-wallet-card .rows {
        left: 12px;
        right: 12px;
        top: 62px;
        bottom: auto;
        gap: 6px;
      }

      .startup-guide-wallet-card .rows i {
        height: 6px;
      }

      .startup-guide-domain-panel {
        left: 14px;
        right: 14px;
        top: 112px;
        width: auto;
        height: 74px;
      }

      .startup-guide-domain-panel .domain {
        top: 32px;
        font-size: 18px;
      }

      .startup-guide-bridge {
        left: calc(50% - 2px);
        right: auto;
        top: 92px;
        width: 4px;
        height: 24px;
        transform: none;
        background: linear-gradient(180deg, rgba(88, 210, 255, 0.22), rgba(88, 210, 255, 0.62), rgba(88, 210, 255, 0.22));
      }

      .startup-guide-bridge::before {
        left: -8px;
        top: 4px;
      }

      .startup-guide-bridge::after {
        right: -2px;
        top: auto;
        bottom: -5px;
      }
    }

    .startup-guide-chart {
      position: relative;
      width: 420px;
      height: 136px;
      display: flex;
      align-items: end;
      justify-content: center;
      gap: 26px;
      padding: 0 26px 8px;
      border-bottom: 2px solid rgba(134, 243, 191, 0.28);
      border-left: 2px solid rgba(134, 243, 191, 0.28);
    }

    .startup-guide-bar {
      width: 52px;
      border-radius: 12px 12px 8px 8px;
      background: linear-gradient(180deg, rgba(134, 243, 191, 0.96), rgba(98, 196, 156, 0.78));
      box-shadow: inset 0 -10px 18px rgba(255, 255, 255, 0.12);
    }

    .startup-guide-bar.h1 { height: 74px; }
    .startup-guide-bar.h2 { height: 106px; }
    .startup-guide-bar.h3 { height: 132px; }
    .startup-guide-bar.h4 { height: 98px; }
    .startup-guide-bar.h5 { height: 64px; }
    .startup-guide-bar.h1 { animation: startupGuideBarWave 2.9s ease-in-out infinite; }
    .startup-guide-bar.h2 { animation: startupGuideBarWave 2.9s ease-in-out infinite 0.14s; }
    .startup-guide-bar.h3 { animation: startupGuideBarWave 2.9s ease-in-out infinite 0.28s; }
    .startup-guide-bar.h4 { animation: startupGuideBarWave 2.9s ease-in-out infinite 0.42s; }
    .startup-guide-bar.h5 { animation: startupGuideBarWave 2.9s ease-in-out infinite 0.56s; }

    .startup-guide-pill-row {
      display: flex;
      gap: 14px;
      align-items: center;
      justify-content: center;
      flex-wrap: nowrap;
      padding: 0 12px;
      width: 100%;
    }

    .startup-guide-pill {
      min-width: 0;
      width: 31%;
      padding: 16px 18px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(7, 17, 31, 0.84);
      box-shadow: 0 12px 24px rgba(0, 0, 0, 0.22);
      font-size: 18px;
      font-weight: 800;
      text-align: center;
      animation: startupGuideSoftPulse 3.2s ease-in-out infinite;
    }

    .startup-guide-pill:nth-child(2) { animation-delay: 0.18s; }
    .startup-guide-pill:nth-child(3) { animation-delay: 0.36s; }

    .startup-guide-pill small {
      display: block;
      margin-top: 6px;
      font-size: 12px;
      font-weight: 600;
      color: rgba(223, 243, 255, 0.74);
    }

    .startup-guide-ready-board {
      position: relative;
      width: 500px;
      height: 172px;
    }

    .startup-guide-ready-node {
      position: absolute;
      top: 42px;
      width: 112px;
      height: 112px;
      border-radius: 50%;
      border: 2px solid rgba(121, 217, 255, 0.34);
      background: rgba(7, 17, 31, 0.88);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      font-weight: 700;
    }

    .startup-guide-ready-node.left { left: 0; animation: startupGuideNodePulse 2.6s ease-in-out infinite; }
    .startup-guide-ready-node.right { right: 0; animation: startupGuideNodePulse 2.6s ease-in-out infinite 0.24s; }

    .startup-guide-ready-center {
      position: absolute;
      left: 50%;
      top: 24px;
      transform: translateX(-50%);
      width: 156px;
      height: 124px;
      border-radius: 24px;
      border: 2px solid rgba(121, 217, 255, 0.34);
      background: rgba(7, 17, 31, 0.9);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 6px;
      box-shadow: 0 14px 26px rgba(0, 0, 0, 0.22);
      animation: startupGuideCenterPulse 2.8s ease-in-out infinite;
    }

    .startup-guide-ready-center strong {
      font-size: 38px;
      line-height: 1;
    }

    .startup-guide-ready-center span {
      font-size: 18px;
      font-weight: 700;
      line-height: 1;
    }

    .startup-guide-ready-center small {
      font-size: 14px;
      font-weight: 700;
      color: rgba(223, 243, 255, 0.72);
    }

    .startup-guide-rail {
      position: relative;
      width: 460px;
      height: 24px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background: rgba(7, 17, 31, 0.76);
      overflow: hidden;
    }

    .startup-guide-rail-fill {
      position: absolute;
      inset: 4px;
      width: 58%;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(83, 246, 184, 0.92), rgba(69, 215, 255, 0.78));
      animation: startupGuideRailSize 2.8s ease-in-out infinite;
    }

    .startup-guide-tile-row {
      display: flex;
      gap: 18px;
      align-items: stretch;
      justify-content: center;
      padding: 0 14px;
      flex-wrap: nowrap;
      width: 100%;
    }

    .startup-guide-tile {
      width: 31%;
      min-height: 104px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(7, 17, 31, 0.82);
      padding: 16px 14px;
      box-shadow: 0 12px 24px rgba(0, 0, 0, 0.22);
      font-size: 14px;
      font-weight: 700;
      text-align: center;
      line-height: 1.25;
      animation: startupGuideTileLift 4s ease-in-out infinite;
    }

    .startup-guide-tile:nth-child(2) { animation-delay: 0.18s; }
    .startup-guide-tile:nth-child(3) { animation-delay: 0.36s; }

    .startup-guide-tile b {
      display: block;
      margin-bottom: 8px;
      font-size: 18px;
    }

    .startup-guide-actions {
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }

    .startup-guide-lane {
      position: absolute;
      inset: 0;
      background:
        repeating-linear-gradient(
          90deg,
          transparent 0 18%,
          rgba(121, 217, 255, 0.14) 18% 18.6%,
          transparent 18.6% 20%
        );
    }

    .startup-guide-card-demo {
      position: absolute;
      width: 76px;
      height: 112px;
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.28);
      background: linear-gradient(180deg, rgba(14, 28, 48, 0.98), rgba(8, 20, 36, 0.96));
      box-shadow: 0 16px 28px rgba(0, 0, 0, 0.35);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 30px;
      color: #f2fbff;
      top: calc(50% - 56px);
      left: calc(50% - 38px);
    }

    .startup-guide-card-demo.player {
      border-color: rgba(83, 246, 184, 0.65);
      box-shadow: 0 12px 24px rgba(83, 246, 184, 0.34);
      animation: startupGuidePlayer 2.6s ease-in-out infinite;
    }

    .startup-guide-card-demo.enemy {
      border-color: rgba(255, 122, 134, 0.62);
      box-shadow: 0 12px 24px rgba(255, 122, 134, 0.3);
      animation: startupGuideEnemy 2.6s ease-in-out infinite;
    }

    .startup-guide-pulse {
      position: absolute;
      width: 132px;
      height: 132px;
      border-radius: 50%;
      border: 2px solid rgba(255, 211, 110, 0.5);
      top: calc(50% - 66px);
      left: calc(50% - 66px);
      animation: startupGuidePulse 2.6s ease-in-out infinite;
      pointer-events: none;
    }

    @keyframes startupGuidePlayer {
      0%, 100% { transform: translate(-118px, 0); }
      45% { transform: translate(-24px, 0); }
      62% { transform: translate(-38px, 0); }
    }

    @keyframes startupGuideEnemy {
      0%, 100% { transform: translate(118px, 0); }
      45% { transform: translate(24px, 0); }
      62% { transform: translate(38px, 0); }
    }

    @keyframes startupGuidePulse {
      0%, 38% {
        opacity: 0;
        transform: scale(0.88);
      }
      52% {
        opacity: 1;
        transform: scale(1);
      }
      100% {
        opacity: 0;
        transform: scale(1.25);
      }
    }

    .result-flip {
      perspective: 1400px;
      margin-bottom: 14px;
    }

    .result-flip-card {
      position: relative;
      min-height: 140px;
      transform-style: preserve-3d;
      animation-duration: 2.2s;
      animation-timing-function: cubic-bezier(.16,.84,.2,1);
      animation-fill-mode: forwards;
    }

    .result-flip-face {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 20px;
      backface-visibility: hidden;
      font-size: clamp(34px, 9vw, 62px);
      font-weight: 800;
      letter-spacing: 0.08em;
    }

    .result-flip-face.front {
      background: linear-gradient(135deg, rgba(83, 246, 184, 0.24), rgba(69, 215, 255, 0.22));
    }

    .result-flip-face.draw {
      background: linear-gradient(135deg, rgba(255, 211, 110, 0.26), rgba(69, 215, 255, 0.18));
    }

    .result-flip-face.back {
      transform: rotateY(180deg);
      background: linear-gradient(135deg, rgba(255, 122, 134, 0.22), rgba(255, 211, 110, 0.14));
    }

    .result-flip-card.to-win {
      animation-name: resultFlipWin;
    }

    .result-flip-card.to-lose {
      animation-name: resultFlipLose;
    }

    .result-flip-card.to-draw {
      animation-name: resultFlipDraw;
    }

    @keyframes resultFlipWin {
      0% { transform: translateZ(0) scale(0.96) rotateY(0deg); }
      68% { transform: translateZ(34px) scale(1.03) rotateY(900deg); }
      100% { transform: translateZ(0) scale(1) rotateY(1080deg); }
    }

    @keyframes resultFlipLose {
      0% { transform: translateZ(0) scale(0.96) rotateY(0deg); }
      68% { transform: translateZ(34px) scale(1.03) rotateY(990deg); }
      100% { transform: translateZ(0) scale(1) rotateY(1260deg); }
    }

    @keyframes resultFlipDraw {
      0% { transform: translateZ(0) scale(0.96) rotateY(0deg); }
      68% { transform: translateZ(34px) scale(1.03) rotateY(900deg); }
      100% { transform: translateZ(0) scale(1) rotateY(1080deg); }
    }

    .result-actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 0;
      justify-content: center;
    }

    .final-climax {
      position: fixed;
      inset: 0;
      z-index: 6200;
      pointer-events: none;
      overflow: hidden;
      background: rgba(2, 6, 12, 0);
      backdrop-filter: blur(0);
      animation: finalBackdrop 1320ms ease forwards;
    }

    @keyframes finalBackdrop {
      from { background: rgba(2, 6, 12, 0); backdrop-filter: blur(0); }
      to { background: rgba(2, 6, 12, 0.86); backdrop-filter: blur(8px); }
    }

    .final-climax::before,
    .final-climax::after {
      content: "";
      position: absolute;
      inset: -18%;
      pointer-events: none;
    }

    .final-climax::before {
      background:
        radial-gradient(circle at 50% 50%, rgba(255,255,255,0.12), transparent 16%),
        radial-gradient(circle at 50% 50%, rgba(69, 215, 255, 0.18), transparent 36%),
        radial-gradient(circle at 50% 50%, rgba(83, 246, 184, 0.12), transparent 56%);
      animation: finalAuraPulse 2.4s ease-in-out infinite;
    }

    .final-climax.shake {
      animation:
        finalBackdrop 1080ms ease forwards,
        arenaShake 620ms cubic-bezier(.2,.82,.2,1) 2;
    }

    .final-climax::after {
      background:
        conic-gradient(from 0deg at 50% 50%, transparent, rgba(69, 215, 255, 0.08), transparent, rgba(83, 246, 184, 0.08), transparent);
      filter: blur(8px);
      animation: auroraRotate 10s linear infinite;
    }

    @keyframes finalAuraPulse {
      0%, 100% { transform: scale(0.94); opacity: 0.72; }
      50% { transform: scale(1.08); opacity: 1; }
    }

    .final-chip {
      position: fixed;
      left: 50%;
      top: 50%;
      min-width: 120px;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.34);
      background: rgba(6, 18, 32, 0.92);
      color: #e8fbff;
      font-size: 13px;
      font-weight: 700;
      text-align: center;
      transform: translate(-50%, -50%);
      box-shadow: 0 16px 34px rgba(0, 0, 0, 0.3);
      opacity: 0;
      transition:
        left 760ms cubic-bezier(.16,.84,.2,1),
        top 760ms cubic-bezier(.16,.84,.2,1),
        transform 760ms cubic-bezier(.16,.84,.2,1),
        opacity 320ms ease;
    }

    .final-chip.win {
      border-color: rgba(83, 246, 184, 0.5);
      color: #d8ffe7;
    }

    .final-chip.lose {
      border-color: rgba(255, 122, 134, 0.5);
      color: #ffe0e5;
    }

    .final-chip.draw {
      border-color: rgba(255, 211, 110, 0.5);
      color: #fff1c9;
    }

    .final-chip.fly {
      opacity: 1;
      left: 50% !important;
      top: 47% !important;
      transform: translate(-50%, -50%) scale(0.5);
    }

    .final-core {
      position: fixed;
      left: 50%;
      top: 50%;
      width: min(92vw, 760px);
      min-height: min(64vh, 560px);
      padding: 26px 18px 22px;
      border-radius: 28px;
      border: 1px solid rgba(121, 217, 255, 0.34);
      background:
        radial-gradient(circle at center, rgba(255,255,255,0.16), transparent 28%),
        radial-gradient(circle at center, rgba(69, 215, 255, 0.2), transparent 48%),
        linear-gradient(180deg, rgba(5, 14, 27, 0.96), rgba(3, 10, 20, 0.98));
      transform: translate(-50%, -50%) scale(0.28);
      opacity: 0;
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 14px;
      box-shadow: 0 30px 90px rgba(0, 0, 0, 0.56);
      transition: transform 920ms cubic-bezier(.12,.86,.12,1), opacity 320ms ease;
      overflow: hidden;
    }

    .final-core::before {
      content: "";
      position: absolute;
      inset: -14%;
      background:
        radial-gradient(circle, rgba(255,255,255,0.3), transparent 18%),
        radial-gradient(circle, rgba(69, 215, 255, 0.28), transparent 38%),
        radial-gradient(circle, rgba(83, 246, 184, 0.16), transparent 62%);
      opacity: 0;
      transform: scale(0.16);
      transition: transform 640ms cubic-bezier(.16,.84,.2,1), opacity 220ms ease;
    }

    .final-core.visible {
      opacity: 1;
      transform: translate(-50%, -50%) scale(1);
    }

    .final-core.visible::before {
      opacity: 1;
      transform: scale(1.28);
    }

    .final-core::after {
      content: "";
      position: absolute;
      inset: -28%;
      border-radius: 50%;
      background: conic-gradient(from 0deg, transparent, rgba(255,255,255,0.12), transparent, rgba(69, 215, 255, 0.18), transparent);
      filter: blur(6px);
      opacity: 0;
      transform: rotate(0deg) scale(0.7);
    }

    .final-core.win {
      box-shadow: 0 0 140px rgba(83, 246, 184, 0.3), 0 30px 90px rgba(0, 0, 0, 0.56);
    }

    .final-core.lose {
      box-shadow: 0 0 140px rgba(255, 122, 134, 0.28), 0 30px 90px rgba(0, 0, 0, 0.56);
    }

    .final-core.draw {
      box-shadow: 0 0 140px rgba(255, 211, 110, 0.26), 0 30px 90px rgba(0, 0, 0, 0.56);
    }

    .final-boom {
      position: absolute;
      width: 220px;
      height: 220px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255,255,255,0.95), rgba(69, 215, 255, 0.34) 42%, transparent 72%);
      opacity: 0;
      transform: scale(0.18);
      pointer-events: none;
    }

    .final-core.visible .final-boom {
      animation: finalBoom 1240ms cubic-bezier(.12,.86,.12,1) forwards;
    }

    .final-core.visible::after {
      opacity: 1;
      animation: finalOrbit 4.4s linear infinite;
    }

    @keyframes finalOrbit {
      from { transform: rotate(0deg) scale(0.74); }
      to { transform: rotate(360deg) scale(1); }
    }

    @keyframes finalBoom {
      0% { opacity: 0.96; transform: scale(0.06); }
      34% { opacity: 1; transform: scale(2.2); }
      70% { opacity: 0.96; transform: scale(4.2); }
      100% { opacity: 0; transform: scale(5.4); }
    }

    .final-label {
      position: relative;
      z-index: 1;
      font-size: clamp(54px, 15vw, 142px);
      font-weight: 900;
      line-height: 0.9;
      letter-spacing: 0.08em;
      text-align: center;
      text-shadow: 0 0 32px rgba(255,255,255,0.18);
    }

    .final-sub {
      position: relative;
      z-index: 1;
      font-size: clamp(18px, 4.4vw, 30px);
      text-align: center;
      color: #d7ecf7;
    }

    .final-buttons {
      position: relative;
      z-index: 1;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: center;
      pointer-events: auto;
    }

    @media (max-width: 700px) {
      .showdown-fullscreen {
        padding: 10px 10px calc(12px + env(safe-area-inset-bottom));
        grid-template-rows: auto minmax(0, 1fr) auto auto;
      }

      .showdown-score {
        font-size: clamp(18px, 7vw, 30px);
      }

      .showdown-card {
        flex-basis: 152px;
        min-width: 152px;
      }

      .result-flip-card {
        min-height: 90px;
      }
    }

    .battle-cinematic {
      position: relative;
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 14px;
      margin: 12px 0 18px;
      padding: 24px 14px 20px;
      border-radius: 26px;
      border: 1px solid rgba(255, 211, 110, 0.14);
      background:
        radial-gradient(circle at 50% 18%, rgba(255, 211, 110, 0.08), transparent 28%),
        linear-gradient(180deg, rgba(10, 22, 38, 0.96), rgba(4, 12, 23, 0.98));
      box-shadow:
        inset 0 0 0 1px rgba(121, 217, 255, 0.04),
        0 22px 40px rgba(0, 0, 0, 0.24);
      isolation: isolate;
    }

    .battle-cinematic.round-reveal {
      margin: 0;
      min-height: 100%;
      padding: 22px 16px 18px;
      border-radius: 22px;
      border-color: rgba(121, 217, 255, 0.18);
    }

    .round-clash-overlay {
      position: absolute;
      inset: 0;
      display: grid;
      align-items: center;
      padding: 18px;
      background:
        radial-gradient(circle at 50% 50%, rgba(12, 34, 48, 0.28), transparent 42%),
        rgba(4, 10, 18, 0.82);
      backdrop-filter: blur(12px);
      z-index: 12;
      pointer-events: none;
    }

    .round-clash-overlay.resolving {
      animation: roundClashFadeOut 420ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .round-clash-overlay .battle-fighter {
      opacity: 1;
    }

    .round-clash-actions {
      display: grid;
      gap: 8px;
      justify-items: center;
      margin-top: 10px;
    }

    .round-clash-result {
      min-height: 42px;
      padding: 0 16px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(216, 228, 255, 0.22);
      background: rgba(216, 228, 255, 0.08);
      color: #eef6ff;
      font-weight: 800;
      letter-spacing: 0.08em;
      opacity: 0;
      transform: translateY(10px) scale(0.92);
    }

    .round-clash-result.visible {
      animation: clashResultIn 320ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .round-clash-result.win {
      border-color: rgba(83, 246, 184, 0.34);
      background: rgba(83, 246, 184, 0.14);
      color: #dfffee;
    }

    .round-clash-result.lose {
      border-color: rgba(255, 122, 134, 0.34);
      background: rgba(255, 122, 134, 0.14);
      color: #ffe0e5;
    }

    .round-clash-result.draw {
      border-color: rgba(255, 211, 110, 0.34);
      background: rgba(255, 211, 110, 0.14);
      color: #ffe9ad;
    }

    .battle-cinematic::before {
      content: "";
      position: absolute;
      inset: 22% 8% 16%;
      border-radius: 999px;
      background:
        radial-gradient(circle at 50% 50%, rgba(69, 215, 255, 0.18), transparent 34%),
        linear-gradient(90deg, rgba(83, 246, 184, 0.14), rgba(255, 211, 110, 0.18), rgba(255, 122, 134, 0.14));
      filter: blur(18px);
      opacity: 0.9;
      z-index: -2;
    }

    .battle-cinematic::after {
      content: "";
      position: absolute;
      left: 16%;
      right: 16%;
      top: 50%;
      height: 1px;
      background: linear-gradient(90deg, transparent, rgba(121, 217, 255, 0.38), transparent);
      box-shadow: 0 0 18px rgba(69, 215, 255, 0.28);
      z-index: -1;
    }

    .battle-cinematic-floor {
      position: absolute;
      left: 10%;
      right: 10%;
      bottom: 10px;
      height: 56px;
      border-radius: 999px;
      background:
        radial-gradient(circle at 50% 50%, rgba(255, 211, 110, 0.16), rgba(69, 215, 255, 0.08) 45%, transparent 72%);
      filter: blur(16px);
      opacity: 0.92;
      pointer-events: none;
      z-index: -1;
    }

    .battle-cinematic-label {
      position: absolute;
      top: 10px;
      left: 50%;
      transform: translateX(-50%);
      padding: 0 12px;
      min-height: 28px;
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      border: 1px solid rgba(255, 211, 110, 0.24);
      background: rgba(255, 211, 110, 0.08);
      color: #ffe59d;
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .battle-fighter {
      position: relative;
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.26);
      padding: 12px;
      background: linear-gradient(145deg, rgba(18, 39, 67, 0.9), rgba(8, 16, 30, 0.92));
      box-shadow:
        inset 0 0 22px rgba(83, 246, 184, 0.08),
        0 18px 36px rgba(0, 0, 0, 0.24);
      opacity: 0;
      transform-style: preserve-3d;
      animation: fighterIn 460ms cubic-bezier(.2,.82,.2,1) forwards;
      overflow: hidden;
    }

    .battle-fighter.player {
      text-align: left;
      transform-origin: center right;
      animation-name: fighterFacePlayer;
    }

    .battle-fighter strong {
      display: block;
      margin: 4px 0;
      font-size: 18px;
      line-height: 1.2;
    }

    .battle-fighter-cardline {
      display: grid;
      gap: 4px;
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
    }

    .battle-fighter-slot {
      color: #ffe59d;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .battle-fighter.enemy {
      text-align: right;
      transform-origin: center left;
      animation-delay: 100ms;
      animation-name: fighterFaceEnemy;
    }

    .battle-fighter::before {
      content: "";
      position: absolute;
      inset: 8px;
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      pointer-events: none;
    }

    .battle-fighter.player::after,
    .battle-fighter.enemy::after {
      content: "";
      position: absolute;
      top: 50%;
      width: 44px;
      height: 2px;
      background: linear-gradient(90deg, rgba(255, 211, 110, 0.7), transparent);
      filter: blur(0.4px);
      opacity: 0.78;
    }

    .battle-fighter.player::after {
      right: -20px;
      transform: translateY(-50%);
    }

    .battle-fighter.enemy::after {
      left: -20px;
      transform: translateY(-50%) rotate(180deg);
    }

    .battle-vs-orb {
      width: 64px;
      height: 64px;
      border-radius: 50%;
      border: 1px solid rgba(83, 246, 184, 0.5);
      display: grid;
      place-items: center;
      font-weight: 800;
      letter-spacing: 0.06em;
      color: #dffff0;
      background:
        radial-gradient(circle at 30% 30%, rgba(83, 246, 184, 0.38), rgba(69, 215, 255, 0.18) 60%, rgba(7, 14, 25, 0.95));
      box-shadow: 0 0 24px rgba(83, 246, 184, 0.28);
      animation: vsPulse 1.2s ease-in-out infinite;
    }

    .arena-decision-track {
      display: grid;
      gap: 10px;
      margin: 0 0 16px;
      padding: 16px;
      border-radius: 24px;
      border: 1px solid rgba(255, 211, 110, 0.14);
      background:
        radial-gradient(circle at 50% 0%, rgba(255, 211, 110, 0.1), transparent 28%),
        linear-gradient(180deg, rgba(9, 19, 32, 0.96), rgba(4, 12, 23, 0.98));
      box-shadow:
        inset 0 0 0 1px rgba(255, 211, 110, 0.03),
        0 16px 32px rgba(0, 0, 0, 0.16);
    }

    .arena-decision-headline {
      text-align: center;
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: rgba(213, 235, 255, 0.76);
    }

    .arena-decision-bursts {
      display: grid;
      gap: 10px;
    }

    .arena-decision-burst {
      display: grid;
      gap: 8px;
      padding: 12px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.07);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.035), rgba(255, 255, 255, 0.02));
      opacity: 0;
      transform: translateY(12px) scale(0.97);
      animation: decisionTrackRise 520ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .arena-decision-burst.latest {
      border-color: rgba(255, 211, 110, 0.34);
      background: linear-gradient(135deg, rgba(255, 211, 110, 0.1), rgba(255, 255, 255, 0.03));
      box-shadow: 0 0 0 1px rgba(255, 211, 110, 0.08), 0 16px 34px rgba(0, 0, 0, 0.16);
    }

    .arena-decision-burst.win {
      border-color: rgba(83, 246, 184, 0.22);
    }

    .arena-decision-burst.lose {
      border-color: rgba(255, 122, 134, 0.24);
    }

    .arena-decision-roundline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
      font-weight: 700;
    }

    .arena-decision-roundline strong {
      font-size: 14px;
      letter-spacing: 0.04em;
    }

    .arena-decision-score {
      color: #ffe59d;
      white-space: nowrap;
    }

    .arena-clash-lane {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
      align-items: center;
      gap: 10px;
    }

    .arena-clash-card {
      display: grid;
      gap: 4px;
      padding: 12px;
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.14);
      background: rgba(255, 255, 255, 0.035);
      min-width: 0;
    }

    .arena-clash-card.player {
      border-color: rgba(69, 215, 255, 0.24);
      box-shadow: inset 0 0 18px rgba(69, 215, 255, 0.05);
    }

    .arena-clash-card.enemy {
      border-color: rgba(255, 122, 134, 0.22);
      box-shadow: inset 0 0 18px rgba(255, 122, 134, 0.05);
      text-align: right;
    }

    .arena-clash-slot {
      color: rgba(213, 235, 255, 0.68);
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    .arena-clash-title {
      font-weight: 800;
      font-size: 15px;
      line-height: 1.2;
      word-break: break-word;
    }

    .arena-clash-meta {
      color: rgba(213, 235, 255, 0.78);
      font-size: 12px;
    }

    .arena-clash-versus {
      display: grid;
      justify-items: center;
      gap: 6px;
      min-width: 72px;
    }

    .arena-clash-badge {
      min-height: 36px;
      padding: 0 12px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(255, 211, 110, 0.26);
      background: rgba(255, 211, 110, 0.09);
      color: #ffe59d;
      font-weight: 800;
      letter-spacing: 0.08em;
    }

    .arena-clash-winner {
      font-size: 11px;
      text-align: center;
      color: rgba(213, 235, 255, 0.72);
      line-height: 1.25;
    }

    .arena-decision-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .arena-decision-chip {
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background: rgba(255, 255, 255, 0.04);
      color: #eaf8ff;
      font-size: 12px;
      line-height: 1;
      opacity: 0;
      transform: translateY(10px) scale(0.92);
      animation: decisionChipIn 420ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .arena-decision-chip.player {
      border-color: rgba(69, 215, 255, 0.34);
      background: rgba(69, 215, 255, 0.1);
    }

    .arena-decision-chip.enemy {
      border-color: rgba(255, 122, 134, 0.3);
      background: rgba(255, 122, 134, 0.1);
    }

    .arena-decision-chip.strategy {
      border-color: rgba(255, 211, 110, 0.34);
      background: rgba(255, 211, 110, 0.1);
    }

    .arena-decision-chip.featured {
      border-color: rgba(83, 246, 184, 0.34);
      background: rgba(83, 246, 184, 0.1);
    }

    .arena-decision-chip.outcome {
      border-color: rgba(216, 228, 255, 0.26);
      background: rgba(216, 228, 255, 0.08);
    }

    .arena-decision-chip.action {
      box-shadow: inset 0 0 14px rgba(255, 255, 255, 0.03);
    }

    .arena-decision-chip.burst {
      border-color: rgba(255, 122, 134, 0.36);
    }

    .arena-decision-chip.guard {
      border-color: rgba(83, 246, 184, 0.36);
    }

    .arena-decision-chip.ability {
      border-color: rgba(255, 211, 110, 0.4);
      background: rgba(255, 211, 110, 0.12);
      color: #ffe7a4;
    }

    .arena-decision-chip.channel {
      border-color: rgba(69, 215, 255, 0.36);
    }

    @keyframes fighterFacePlayer {
      0% {
        opacity: 0;
        transform: translateX(-22px) rotateY(24deg) scale(0.9);
        filter: blur(4px);
      }
      100% {
        opacity: 1;
        transform: perspective(1200px) rotateY(12deg) scale(1);
        filter: blur(0);
      }
    }

    @keyframes fighterFaceEnemy {
      0% {
        opacity: 0;
        transform: translateX(22px) rotateY(-24deg) scale(0.9);
        filter: blur(4px);
      }
      100% {
        opacity: 1;
        transform: perspective(1200px) rotateY(-12deg) scale(1);
        filter: blur(0);
      }
    }

    @keyframes decisionTrackRise {
      0% {
        opacity: 0;
        transform: translateY(18px) scale(0.96);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    @keyframes decisionChipIn {
      0% {
        opacity: 0;
        transform: translateY(10px) scale(0.9);
        filter: blur(4px);
      }
      100% {
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: blur(0);
      }
    }

    .battle-fx-layer {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 6000;
      overflow: hidden;
    }

    .battle-flash {
      position: absolute;
      inset: 0;
      background: radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.56), rgba(69, 215, 255, 0.18) 35%, transparent 65%);
      opacity: 0;
      animation: flashBoom 460ms cubic-bezier(.2,.82,.2,1) forwards;
    }

    .battle-ring {
      position: absolute;
      left: var(--fx-x, 50%);
      top: var(--fx-y, 52%);
      width: 28px;
      height: 28px;
      margin: -14px 0 0 -14px;
      border-radius: 50%;
      border: 2px solid rgba(83, 246, 184, 0.74);
      box-shadow: 0 0 22px rgba(83, 246, 184, 0.45);
      animation: ringBlast 920ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .battle-particle {
      position: absolute;
      left: var(--fx-x, 50%);
      top: var(--fx-y, 52%);
      width: 8px;
      height: 16px;
      border-radius: 3px;
      background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(83,246,184,0.8));
      opacity: 0;
      transform-origin: center center;
      animation: particleBurst var(--dur, 900ms) cubic-bezier(.16,.84,.2,1) forwards;
      animation-delay: var(--delay, 0ms);
    }

    .count-up {
      font-variant-numeric: tabular-nums;
    }

    @keyframes fighterIn {
      0% { opacity: 0; transform: translateY(8px) scale(0.96); }
      100% { opacity: 1; transform: translateY(0) scale(1); }
    }

    @keyframes vsPulse {
      0%, 100% { transform: scale(1); box-shadow: 0 0 18px rgba(83, 246, 184, 0.2); }
      50% { transform: scale(1.06); box-shadow: 0 0 28px rgba(83, 246, 184, 0.38); }
    }

    @keyframes auroraRotate {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }

    @keyframes arenaShake {
      0% { transform: translateX(0); }
      15% { transform: translateX(-4px); }
      30% { transform: translateX(4px); }
      45% { transform: translateX(-3px); }
      60% { transform: translateX(3px); }
      75% { transform: translateX(-2px); }
      100% { transform: translateX(0); }
    }

    @keyframes flashBoom {
      0% { opacity: 0; }
      25% { opacity: 1; }
      100% { opacity: 0; }
    }

    @keyframes ringBlast {
      0% { transform: scale(0.8); opacity: 1; }
      100% { transform: scale(20); opacity: 0; }
    }

    @keyframes particleBurst {
      0% { opacity: 0; transform: translate3d(0, 0, 0) rotate(var(--rot, 0deg)); }
      20% { opacity: 1; }
      100% {
        opacity: 0;
        transform: translate3d(var(--tx, 0px), var(--ty, 0px), 0) rotate(var(--rot, 0deg));
      }
    }

    @keyframes scorePulse {
      0% { transform: scale(0.82); opacity: 0.55; }
      70% { transform: scale(1.08); opacity: 1; }
      100% { transform: scale(1); opacity: 1; }
    }

    @keyframes rowPop {
      0% { transform: translateY(12px) scale(0.98); }
      70% { transform: translateY(-2px) scale(1.01); }
      100% { transform: translateY(0) scale(1); }
    }

    @keyframes victoryPulse {
      0%, 100% { box-shadow: 0 10px 22px rgba(83, 246, 184, 0.2); }
      50% { box-shadow: 0 14px 30px rgba(83, 246, 184, 0.38); }
    }

    @media (prefers-reduced-motion: reduce) {
      .showdown-fullscreen::after,
      .showdown-fullscreen.battle-live .showdown-main,
      .battle-vs-orb,
      .showdown-score .count-up,
      .discipline-row.visible,
      .victory-banner {
        animation: none !important;
      }
    }

    .pack-showcase {
      position: relative;
      margin-top: 16px;
      display: grid;
      justify-items: center;
      border-radius: 28px;
      background:
        radial-gradient(circle at 50% 0%, rgba(255, 212, 92, 0.18), transparent 38%),
        linear-gradient(180deg, rgba(14, 10, 4, 0.98), rgba(5, 5, 5, 0.97));
      padding: 18px 16px 20px;
      text-align: center;
      overflow: hidden;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.44);
    }

    .pack-showcase::after {
      content: "";
      position: absolute;
      inset: 0;
      background: rgba(3, 9, 18, 0);
      transition: background 260ms ease;
      pointer-events: none;
      border-radius: 24px;
    }

    .pack-showcase.cinematic::after {
      background: rgba(3, 9, 18, 0.36);
    }

    .pack-showcase.pack-type-common {
      background:
        radial-gradient(circle at 50% 0%, rgba(69, 215, 255, 0.18), transparent 38%),
        linear-gradient(180deg, rgba(8, 16, 30, 0.98), rgba(5, 8, 14, 0.97));
    }

    .pack-showcase.pack-type-rare {
      background:
        radial-gradient(circle at 50% 0%, rgba(83, 246, 184, 0.18), transparent 38%),
        linear-gradient(180deg, rgba(8, 22, 24, 0.98), rgba(5, 9, 12, 0.97));
    }

    .pack-showcase.pack-type-epic {
      background:
        radial-gradient(circle at 50% 0%, rgba(188, 126, 255, 0.22), transparent 38%),
        linear-gradient(180deg, rgba(20, 11, 33, 0.98), rgba(8, 7, 14, 0.97));
    }

    .pack-showcase.pack-type-lucky {
      background:
        radial-gradient(circle at 50% 0%, rgba(255, 212, 92, 0.22), transparent 38%),
        linear-gradient(180deg, rgba(20, 14, 5, 0.98), rgba(5, 5, 5, 0.97));
    }

    .pack-counter {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      min-width: 260px;
      border-radius: 999px;
      border: 1px solid rgba(255, 212, 92, 0.42);
      color: rgba(255, 231, 161, 0.96);
      letter-spacing: 0.14em;
      font-weight: 700;
      padding: 0 20px;
      background: linear-gradient(180deg, rgba(34, 25, 8, 0.9), rgba(8, 8, 8, 0.96));
      box-shadow: 0 0 20px rgba(255, 212, 92, 0.08);
      margin-bottom: 10px;
      text-transform: uppercase;
    }

    .pack-note {
      color: rgba(255, 220, 126, 0.82);
      margin: 0 0 12px;
      font-size: 14px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-family: Georgia, "Times New Roman", serif;
    }

    .foil-pack {
      position: relative;
      width: min(380px, 92vw);
      aspect-ratio: 2 / 3;
      margin: 0 auto;
      border-radius: 26px;
      border: 1px solid rgba(255, 212, 92, 0.32);
      background: linear-gradient(180deg, rgba(15, 15, 15, 0.98), rgba(4, 4, 4, 0.98));
      color: #ffd95d;
      padding: 0;
      box-shadow:
        inset 0 0 0 1px rgba(255, 220, 120, 0.08),
        0 34px 52px rgba(0, 0, 0, 0.52);
      overflow: visible;
      transform-origin: center center;
      transition: transform 420ms ease, opacity 420ms ease, filter 420ms ease;
    }

    .pack-showcase.cinematic .foil-pack {
      position: relative;
      left: auto;
      top: auto;
      width: min(380px, 92vw);
      transform: scale(1);
      z-index: 7100;
    }

    .foil-pack-frame {
      position: absolute;
      inset: 0;
      border-radius: inherit;
      overflow: hidden;
    }

    .foil-pack-frame::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(255, 212, 92, 0.06), transparent 10%, transparent 90%, rgba(255, 212, 92, 0.06)),
        radial-gradient(circle at 50% 10%, rgba(255, 223, 130, 0.12), transparent 30%);
      pointer-events: none;
      z-index: 3;
    }

    .pack-face {
      position: absolute;
      left: 50%;
      width: 100%;
      top: 2.5%;
      bottom: -2.5%;
      border-radius: 26px;
      background-image: url('/static/pack-10k-club.png');
      background-size: 100% 100%;
      background-position: center center;
      background-repeat: no-repeat;
      clip-path: inset(0 0 0 0 round 26px);
      z-index: 1;
      transform-origin: top center;
      transform: translateX(-50%);
    }

    .pack-rip-strip {
      position: absolute;
      left: 50%;
      width: 100%;
      top: 2.5%;
      height: 15%;
      border-radius: 26px 26px 0 0;
      background-image: url('/static/pack-10k-club.png');
      background-size: 100% auto;
      background-position: center top;
      background-repeat: no-repeat;
      z-index: 4;
      transform-origin: right bottom;
      box-shadow: 0 8px 18px rgba(0, 0, 0, 0.36);
      transform: translateX(-50%);
      opacity: 0;
    }

    .pack-cap {
      position: absolute;
      left: 6%;
      right: 6%;
      top: 11%;
      height: 2px;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(255, 214, 101, 0), rgba(255, 214, 101, 0.96), rgba(255, 214, 101, 0));
      box-shadow: 0 0 16px rgba(255, 214, 101, 0.6);
      transform-origin: top center;
      z-index: 5;
    }

    .pack-mouth-glow {
      position: absolute;
      left: 14%;
      right: 14%;
      top: 11%;
      height: 14%;
      background:
        radial-gradient(circle at 50% 0%, rgba(255, 223, 130, 0.86), rgba(255, 188, 52, 0.42) 28%, rgba(255, 160, 48, 0.12) 52%, transparent 78%);
      filter: blur(10px);
      opacity: 0;
      z-index: 2;
      pointer-events: none;
      transform: translateY(-10px) scaleY(0.3);
    }

    .foil-pack.opening {
      animation: packLunge 1400ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .pack-showcase.opened .foil-pack {
      filter: brightness(1.08);
      transform: scale(1);
    }

    .foil-pack.vanishing {
      animation: packVanish 1.5s cubic-bezier(.16,.84,.2,1) forwards;
    }

    .foil-pack.opening .pack-rip-strip {
      animation: packRipAway 1400ms cubic-bezier(.15,.86,.2,1) forwards;
    }

    .foil-pack.opening .pack-face {
      animation: packBodyOpen 1400ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .foil-pack.opening .pack-mouth-glow {
      animation: packMouthGlow 1400ms ease forwards;
    }

    .pack-tap {
      margin-top: 14px;
      color: rgba(255, 223, 130, 0.92);
      letter-spacing: 0.24em;
      font-size: clamp(14px, 3.6vw, 18px);
      font-weight: 700;
      text-transform: uppercase;
      font-family: Georgia, "Times New Roman", serif;
    }

    .cosmetic-roulette {
      position: relative;
      width: min(760px, 96vw);
      margin: 8px auto 0;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.28);
      background: linear-gradient(180deg, rgba(8, 16, 30, 0.96), rgba(5, 11, 22, 0.98));
      padding: 14px 12px 12px;
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.42);
      overflow: hidden;
    }

    .cosmetic-roulette::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(8,16,30,0.94), transparent 16%, transparent 84%, rgba(8,16,30,0.94)),
        radial-gradient(circle at center, rgba(255, 211, 110, 0.06), transparent 55%);
      pointer-events: none;
      z-index: 4;
    }

    .cosmetic-roulette::before {
      content: "";
      position: absolute;
      left: calc(50% - 1px);
      top: 0;
      bottom: 0;
      width: 2px;
      background: linear-gradient(180deg, rgba(255, 211, 110, 0.14), rgba(255, 211, 110, 0.82), rgba(255, 211, 110, 0.14));
      pointer-events: none;
      z-index: 5;
    }

    .cosmetic-roulette-window {
      overflow: hidden;
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background: radial-gradient(circle at top, rgba(69, 215, 255, 0.08), rgba(5, 10, 20, 0.98) 66%);
    }

    .cosmetic-roulette-track {
      display: inline-flex;
      gap: 10px;
      align-items: stretch;
      padding: 10px;
      transform: translateX(0);
      transition: transform 4400ms cubic-bezier(.08,.86,.16,1);
      will-change: transform;
    }

    .cosmetic-roulette-track.spinning {
      filter: saturate(1.12) contrast(1.06);
    }

    .cosmetic-roulette-card {
      width: 128px;
      min-width: 128px;
      border-radius: 12px;
      border: 1px solid rgba(121, 217, 255, 0.2);
      padding: 9px 8px;
      background: linear-gradient(180deg, rgba(11, 20, 35, 0.95), rgba(7, 14, 25, 0.98));
      text-align: left;
      display: grid;
      gap: 6px;
      align-content: start;
      min-height: 134px;
      position: relative;
      overflow: hidden;
    }

    .cosmetic-roulette-card::before {
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      top: 0;
      height: 2px;
      background: rgba(255,255,255,0.2);
      opacity: 0.7;
    }

    .cosmetic-roulette-card .icon {
      font-size: 26px;
      line-height: 1;
      width: 44px;
      height: 44px;
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: radial-gradient(circle at 30% 24%, rgba(255,255,255,0.24), rgba(10,20,34,0.74));
      border: 1px solid rgba(255,255,255,0.16);
    }

    .cosmetic-roulette-card .name {
      font-size: 12px;
      line-height: 1.2;
      color: rgba(236, 246, 255, 0.94);
      min-height: 30px;
      max-height: 30px;
      overflow: hidden;
    }

    .cosmetic-roulette-card .rarity {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 22px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.2);
      padding: 0 8px;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      width: fit-content;
    }

    .cosmetic-roulette-card .beam {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 4px;
      opacity: 0.9;
    }

    .cosmetic-roulette-card.basic { border-color: rgba(180, 180, 180, 0.32); }
    .cosmetic-roulette-card.rare { border-color: rgba(69, 215, 255, 0.42); }
    .cosmetic-roulette-card.epic { border-color: rgba(255, 122, 134, 0.48); }
    .cosmetic-roulette-card.mythic { border-color: rgba(188, 126, 255, 0.56); }
    .cosmetic-roulette-card.legendary { border-color: rgba(255, 211, 110, 0.58); box-shadow: 0 0 0 1px rgba(255, 211, 110, 0.25), 0 8px 22px rgba(255, 211, 110, 0.18); }

    .cosmetic-roulette-card.basic .rarity { color: #d7dde8; border-color: rgba(215,221,232,0.28); }
    .cosmetic-roulette-card.rare .rarity { color: #7de9ff; border-color: rgba(125,233,255,0.38); }
    .cosmetic-roulette-card.epic .rarity { color: #ff96b0; border-color: rgba(255,150,176,0.4); }
    .cosmetic-roulette-card.mythic .rarity { color: #d2a8ff; border-color: rgba(210,168,255,0.44); }
    .cosmetic-roulette-card.legendary .rarity { color: #ffe08a; border-color: rgba(255,224,138,0.5); }
    .cosmetic-roulette-card.basic .beam { background: linear-gradient(90deg, rgba(215,221,232,0), rgba(215,221,232,0.9), rgba(215,221,232,0)); }
    .cosmetic-roulette-card.rare .beam { background: linear-gradient(90deg, rgba(125,233,255,0), rgba(125,233,255,0.95), rgba(125,233,255,0)); }
    .cosmetic-roulette-card.epic .beam { background: linear-gradient(90deg, rgba(255,150,176,0), rgba(255,150,176,0.95), rgba(255,150,176,0)); }
    .cosmetic-roulette-card.mythic .beam { background: linear-gradient(90deg, rgba(210,168,255,0), rgba(210,168,255,0.95), rgba(210,168,255,0)); }
    .cosmetic-roulette-card.legendary .beam { background: linear-gradient(90deg, rgba(255,224,138,0), rgba(255,224,138,0.98), rgba(255,224,138,0)); }

    .cosmetic-roulette-marker {
      position: absolute;
      left: 50%;
      top: 6px;
      transform: translateX(-50%);
      width: 34px;
      height: 18px;
      border-radius: 999px;
      border: 1px solid rgba(255, 211, 110, 0.45);
      color: rgba(255, 230, 159, 0.95);
      background: rgba(17, 26, 41, 0.88);
      font-size: 11px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      z-index: 6;
      pointer-events: none;
    }

    .cosmetic-roulette-marker-bottom {
      position: absolute;
      left: 50%;
      bottom: 6px;
      transform: translateX(-50%) rotate(180deg);
      width: 34px;
      height: 18px;
      border-radius: 999px;
      border: 1px solid rgba(255, 211, 110, 0.45);
      color: rgba(255, 230, 159, 0.95);
      background: rgba(17, 26, 41, 0.88);
      font-size: 11px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      z-index: 6;
      pointer-events: none;
    }

    .pack-sequence-layer {
      position: fixed;
      inset: 0;
      z-index: 7300;
      pointer-events: none;
      overflow: hidden;
      background: rgba(3, 8, 14, 0);
      transition: background 260ms ease;
    }

    .pack-sequence-layer.dimmed {
      background: rgba(3, 8, 14, 0.72);
    }

    .pack-preview-card {
      position: fixed;
      width: min(430px, 88vw);
      max-height: 86vh;
      z-index: 7010;
      border-radius: 20px;
      border: 1px solid rgba(121, 217, 255, 0.4);
      padding: 0;
      background: transparent;
      box-shadow: 0 32px 72px rgba(0, 0, 0, 0.56);
      color: var(--text);
      transform: perspective(1400px) translate(-50%, -50%) rotateY(88deg) scale(0.32);
      transform-style: preserve-3d;
      backface-visibility: hidden;
      opacity: 0;
      transition:
        left 820ms cubic-bezier(.16,.84,.2,1),
        top 820ms cubic-bezier(.16,.84,.2,1),
        transform 820ms cubic-bezier(.16,.84,.2,1),
        opacity 260ms ease;
      overflow: hidden;
    }

    .pack-preview-card .game-card {
      min-height: 0;
      height: 100%;
      border-radius: 20px;
      margin: 0;
      border: 0;
      padding: 18px;
      overflow: hidden;
      box-shadow: inset 0 0 0 1px rgba(121, 217, 255, 0.24);
    }

    .pack-preview-card.focused {
      opacity: 1;
      box-shadow:
        0 36px 88px rgba(0, 0, 0, 0.62),
        0 0 0 1px rgba(121, 217, 255, 0.26);
    }

    .owned-decks {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }

    .wallet-quick-panel {
      display: grid;
      gap: 10px;
      margin: 12px 0 16px;
      padding: 14px;
      border-radius: 18px;
      border: 1px solid rgba(111, 204, 255, 0.24);
      background:
        radial-gradient(circle at top right, rgba(69, 215, 255, 0.16), transparent 36%),
        linear-gradient(180deg, rgba(12, 24, 38, 0.95), rgba(8, 15, 27, 0.98));
    }

    .wallet-quick-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }

    .wallet-quick-item {
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid rgba(111, 204, 255, 0.16);
      background: rgba(255, 255, 255, 0.03);
    }

    .wallet-quick-item strong {
      display: block;
      margin-bottom: 4px;
    }

    .wallet-quick-currency {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: rgba(213, 235, 255, 0.88);
    }

    .wallet-currency-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 26px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(255, 255, 255, 0.04);
      font-size: 11px;
      white-space: nowrap;
    }

    .wallet-quick-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .wallet-flow-note {
      margin: 2px 0 0;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.45;
    }

    .wallet-telegram-panel {
      display: grid;
      gap: 10px;
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid rgba(111, 204, 255, 0.16);
      background: rgba(255, 255, 255, 0.03);
    }

    .wallet-telegram-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }

    #telegram-login-widget {
      min-height: 40px;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }

    #telegram-miniapp-link-btn {
      display: none;
    }

    #telegram-login-widget > iframe {
      max-width: 100%;
    }

    .wallet-section {
      margin-top: 14px;
      padding: 14px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(255, 255, 255, 0.025);
    }

    .wallet-section h3 {
      margin: 0 0 6px;
    }

    .wallet-section .tiny {
      line-height: 1.45;
    }

    .wallet-section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }

    .wallet-section-kicker {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 34px;
      height: 34px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(69, 215, 255, 0.08);
      color: #dff7ff;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }

    .wallet-domain-card {
      position: relative;
      overflow: hidden;
    }

    .wallet-domain-card::before {
      content: "";
      position: absolute;
      inset: 0;
      background: radial-gradient(circle at top right, rgba(69, 215, 255, 0.12), transparent 38%);
      pointer-events: none;
    }

    .wallet-domain-stats {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0;
    }

    .wallet-domain-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(121, 217, 255, 0.18);
      background: rgba(255, 255, 255, 0.04);
      font-size: 12px;
      color: var(--text);
    }

    .wallet-domain-action {
      width: 100%;
      margin-top: 2px;
    }

    .wallet-domain-mainline {
      margin-top: 8px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.42;
    }

    .wallet-domain-more {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid rgba(255, 255, 255, 0.06);
    }

    .wallet-domain-more summary {
      cursor: pointer;
      color: #dff7ff;
      font-size: 13px;
      list-style: none;
    }

    .wallet-domain-more summary::-webkit-details-marker {
      display: none;
    }

    .global-players-list {
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }

    @keyframes packLunge {
      0% {
        transform: scale(1);
      }
      18% {
        transform: scale(1.02);
      }
      52% {
        transform: scale(1.08);
      }
      100% {
        transform: scale(1.14);
      }
    }

    @keyframes packRipAway {
      0% {
        transform: translateX(-50%) translate3d(0, 0, 0) rotate(0deg);
        opacity: 0;
      }
      8% {
        transform: translateX(-50%) translate3d(0, 0, 0) rotate(0deg);
        opacity: 1;
      }
      28% {
        transform: translateX(-50%) translate3d(-10px, -8px, 0) rotate(-5deg);
        opacity: 1;
      }
      100% {
        transform: translateX(-50%) translate3d(-280px, -220px, 0) rotate(-34deg);
        opacity: 0;
      }
    }

    @keyframes packBodyOpen {
      0% {
        clip-path: inset(0 0 0 0 round 26px);
        transform: translateX(-50%) perspective(1200px) rotateX(0deg) scaleY(1);
      }
      54% {
        clip-path: inset(2.8% 0 0 0 round 0 0 26px 26px);
        transform: translateX(-50%) perspective(1200px) rotateX(-12deg) scaleY(1.01);
      }
      100% {
        clip-path: inset(6.5% 0 0 0 round 0 0 26px 26px);
        transform: translateX(-50%) perspective(1200px) rotateX(-18deg) scaleY(1.02);
      }
    }

    @keyframes packMouthGlow {
      0% {
        opacity: 0;
        transform: translateY(-10px) scaleY(0.3);
      }
      58% {
        opacity: 0.9;
        transform: translateY(0) scaleY(1.15);
      }
      100% {
        opacity: 0.5;
        transform: translateY(12px) scaleY(1.45);
      }
    }

    @keyframes packVanish {
      0% { opacity: 1; transform: scale(1.14); }
      100% { opacity: 0; transform: scale(1.02); }
    }

    @media (max-width: 920px) {
      body {
        padding-bottom: calc(116px + env(safe-area-inset-bottom));
      }

      .shell {
        overflow-x: hidden;
        padding: 12px 10px calc(126px + env(safe-area-inset-bottom));
      }

      .layout { grid-template-columns: 1fr; }
      .side { display: none; }

      .showdown-fullscreen {
        width: 100vw;
        max-width: 100vw;
        padding:
          calc(8px + env(safe-area-inset-top))
          8px
          calc(10px + env(safe-area-inset-bottom));
        gap: 8px;
        overflow-x: hidden;
      }

      .showdown-header,
      .showdown-main,
      .showdown-main.arena-board,
      .arena-shell,
      .arena-rail,
      .arena-core,
      .arena-choice-hub,
      .arena-deck-grid {
        width: 100%;
        max-width: 100%;
        min-width: 0;
      }

      .showdown-main.arena-board {
        padding: 8px 6px;
      }

      .arena-shell {
        gap: 8px;
      }

      .startup-guide {
        padding: 12px;
      }

      .startup-guide-card {
        width: calc(100vw - 18px);
        padding: 12px;
      }

      .startup-guide-stage {
        height: 210px;
      }

      .startup-guide-stage-overlay {
        font-size: 24px;
        padding: 14px;
      }

      .startup-guide-copy strong {
        font-size: 16px;
      }

      .startup-guide-flowboard,
      .startup-guide-pack-board,
      .startup-guide-connection-board,
      .startup-guide-pack-reveal {
        width: calc(100% - 14px);
        height: 214px;
      }

      .startup-guide-connection-board {
        min-height: 214px;
        padding: 14px;
        grid-template-columns: 1fr;
        gap: 10px;
      }

      .startup-guide-connection-node {
        min-height: 82px;
        padding: 14px 16px;
        border-radius: 20px;
      }

      .startup-guide-connection-node .kicker {
        min-height: 24px;
        padding: 0 10px;
        font-size: 10px;
      }

      .startup-guide-connection-node strong {
        font-size: 22px;
      }

      .startup-guide-connection-node span {
        font-size: 12px;
      }

      .startup-guide-connection-line {
        justify-self: center;
        width: 4px;
        height: 24px;
        background: linear-gradient(180deg, rgba(88, 210, 255, 0.18), rgba(88, 210, 255, 0.62), rgba(88, 210, 255, 0.18));
      }

      .startup-guide-connection-line::before {
        left: 50%;
        top: 0;
        transform: translate(-50%, 0);
        animation: startupGuideBridgePulseVertical 2.8s ease-in-out infinite;
      }

      .startup-guide-connection-line::after {
        left: 50%;
        right: auto;
        top: auto;
        bottom: -2px;
        transform: translateX(-50%);
      }

      .startup-guide-connection-line i {
        left: 50%;
        right: auto;
        top: 18%;
        bottom: 18%;
        width: 2px;
        height: auto;
        transform: translateX(-50%);
      }

      .startup-guide-pack-reveal {
        min-height: 214px;
        padding: 18px 14px;
      }

      .startup-guide-pack-reveal-card {
        top: 58px;
        width: 88px;
        height: 102px;
        border-radius: 18px;
      }

      .startup-guide-pack-reveal-card::after {
        left: 10px;
        bottom: 10px;
        min-height: 20px;
        padding: 0 8px;
        font-size: 9px;
      }

      .startup-guide-pack-reveal-card.left {
        left: 20px;
      }

      .startup-guide-pack-reveal-card.center {
        width: 106px;
        height: 122px;
      }

      .startup-guide-pack-reveal-card.right {
        right: 20px;
      }

      .startup-guide-pack-reveal-card .glyph {
        font-size: 34px;
      }

      .startup-guide-pack-reveal-card.center .glyph {
        font-size: 42px;
      }

      .startup-guide-pack-reveal-burst {
        width: 150px;
        height: 150px;
      }

      .startup-guide-wallet-card {
        left: 14px;
        top: 16px;
        width: calc(100% - 28px);
        height: 82px;
        border-radius: 18px;
      }

      .startup-guide-wallet-card .head {
        left: 12px;
        top: 10px;
        font-size: 9px;
      }

      .startup-guide-wallet-card .name {
        left: 12px;
        top: 26px;
        font-size: 17px;
      }

      .startup-guide-wallet-card .rows {
        left: 12px;
        right: 12px;
        bottom: 10px;
        gap: 6px;
      }

      .startup-guide-wallet-card .rows i {
        height: 6px;
      }

      .startup-guide-domain-panel {
        left: 14px;
        right: 14px;
        top: 112px;
        width: auto;
        height: 74px;
        border-radius: 18px;
      }

      .startup-guide-domain-panel .tag {
        left: 10px;
        top: 10px;
        padding: 4px 8px;
        font-size: 9px;
      }

      .startup-guide-domain-panel .domain {
        left: 10px;
        top: 32px;
        font-size: 18px;
      }

      .startup-guide-bridge {
        left: calc(50% - 2px);
        right: auto;
        top: 92px;
        width: 4px;
        height: 24px;
        transform: none;
        background: linear-gradient(180deg, rgba(88, 210, 255, 0.22), rgba(88, 210, 255, 0.62), rgba(88, 210, 255, 0.22));
      }

      .startup-guide-bridge::before {
        width: 14px;
        height: 14px;
        top: 4px;
        left: -5px;
        animation: startupGuideBridgePulseVertical 2.8s ease-in-out infinite;
      }

      .startup-guide-bridge::after {
        right: -2px;
        top: auto;
        bottom: -5px;
        width: 8px;
        height: 8px;
      }

      .startup-guide-pack-main {
        width: 118px;
        height: 106px;
        top: 22px;
        border-radius: 22px;
      }

      .startup-guide-pack-side {
        top: 42px;
        width: 82px;
        height: 70px;
      }

      .startup-guide-pack-side.left {
        left: 38px;
      }

      .startup-guide-pack-side.right {
        right: 38px;
      }

      .startup-guide-chart {
        width: 294px;
        height: 124px;
        gap: 14px;
        padding: 0 14px 8px;
      }

      .startup-guide-bar {
        width: 36px;
      }

      .startup-guide-pill-row {
        gap: 8px;
        padding: 0;
      }

      .startup-guide-pill {
        padding: 10px 8px;
        font-size: 14px;
      }

      .startup-guide-pill small {
        font-size: 10px;
      }

      .startup-guide-ready-board {
        width: 300px;
        height: 128px;
      }

      .startup-guide-ready-node {
        top: 34px;
        width: 76px;
        height: 76px;
        font-size: 14px;
      }

      .startup-guide-ready-center {
        top: 18px;
        width: 108px;
        height: 92px;
      }

      .startup-guide-ready-center strong {
        font-size: 28px;
      }

      .startup-guide-ready-center span {
        font-size: 14px;
      }

      .startup-guide-ready-center small {
        font-size: 11px;
      }

      .startup-guide-tile-row {
        gap: 8px;
        padding: 0;
      }

      .startup-guide-tile {
        min-height: 84px;
        padding: 10px 8px;
        font-size: 11px;
      }

      .startup-guide-tile b {
        font-size: 15px;
      }

      .startup-guide-scene-column {
        gap: 12px;
      }

      .startup-guide-note {
        max-width: calc(100% - 24px);
        min-height: 52px;
        padding: 12px 14px;
        font-size: 13px;
        line-height: 1.3;
      }

      .startup-guide-rail {
        width: 280px;
      }

      .startup-guide-pack-pips {
        bottom: 14px;
      }

      .arena-rail {
        padding: 7px 6px;
      }

      .arena-rail .tiny {
        min-width: 0;
        overflow-wrap: anywhere;
      }

      .season-pass-track {
        gap: 8px;
        padding-right: 120px;
      }

      .season-pass-track > * {
        flex-basis: min(68vw, 196px);
      }

      .hero,
      .panel {
        border-radius: 20px;
      }

      .panel,
      .domain-card,
      .game-card,
      .mode-card,
      .leaderboard-item,
      .team-card,
      .user-item,
      .catalog-card {
        padding: 12px;
      }

      h1 {
        font-size: clamp(30px, 9vw, 44px);
      }

      h2 {
        font-size: 24px;
      }

      h3 {
        font-size: 18px;
      }

      p,
      .muted,
      .tiny,
      .status,
      .wallet-flow-note,
      .wallet-domain-mainline {
        font-size: 12px;
        line-height: 1.45;
      }

      button,
      select,
      input {
        min-height: 44px;
      }

      button {
        padding: 11px 14px;
      }

      input,
      select {
        padding: 10px 12px;
      }

      .actions,
      .row {
        gap: 6px;
      }

      .badge,
      .step-chip,
      .stat-chip,
      .market-link {
        padding: 7px 10px;
        font-size: 11px;
      }

      .stats-strip {
        gap: 6px;
      }

      .mode-grid.mode-focus::before {
        inset: -4px;
        background: rgba(2, 8, 16, 0.38);
        backdrop-filter: blur(2px);
      }
      .mode-card:hover {
        transform: none;
        box-shadow: none;
      }
      .mode-card.preferred-mode {
        padding-top: 74px;
      }
      .mode-card.preferred-mode::before {
        top: 12px;
        left: 12px;
        right: auto;
        max-width: calc(100% - 24px);
        padding: 6px 10px;
        font-size: 10px;
        letter-spacing: 0.05em;
      }
      .mode-card.active-mode {
        transform: translateY(-4px) scale(1.01);
        box-shadow: 0 12px 30px rgba(69, 215, 255, 0.16);
      }
      .mobile-nav {
        position: fixed;
        left: 82px;
        right: 8px;
        bottom: calc(8px + env(safe-area-inset-bottom));
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
        padding: 8px;
        border-radius: 18px;
        border: 1px solid var(--line);
        background: rgba(7, 16, 25, 0.96);
        backdrop-filter: blur(16px);
        z-index: 40;
        box-shadow: 0 18px 34px rgba(0, 0, 0, 0.34);
      }
      .mobile-nav button {
        min-height: 40px;
        height: 40px;
        padding: 6px 3px;
        font-size: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        line-height: 1;
        white-space: normal;
        word-break: break-word;
        min-width: 0;
        border-radius: 12px;
      }

      #nav-achievements {
        font-size: 9px;
      }

      .hero {
        padding: 14px;
      }

      .top-app-nav {
        display: none;
      }

      .mascot-widget {
        left: 8px;
        bottom: calc(8px + env(safe-area-inset-bottom));
      }

      .mascot-fab {
        width: 66px;
        height: 66px;
        border-radius: 20px;
      }

      .mascot-fab img {
        width: 70px;
        height: 70px;
      }

      .mascot-popover {
        width: min(290px, calc(100vw - 20px));
      }

      .hero-top p,
      .stepper {
        display: none;
      }

      #view-wallet > h2,
      #view-wallet > p.muted {
        display: none;
      }

      .wallet-quick-grid {
        grid-template-columns: 1fr;
      }

      .wallet-quick-actions {
        display: grid;
        grid-template-columns: 1fr;
      }

      #view-wallet {
        display: grid;
        gap: 12px;
      }

      .wallet-quick-panel {
        margin: 0;
        padding: 12px;
        border-radius: 16px;
        box-shadow: 0 14px 28px rgba(0, 0, 0, 0.18);
      }

      .wallet-quick-grid {
        gap: 8px;
      }

      .wallet-quick-item {
        padding: 10px 12px;
      }

      .wallet-quick-item strong {
        font-size: 13px;
        margin-bottom: 4px;
      }

      .wallet-quick-actions button,
      .wallet-domain-action {
        min-height: 44px;
        font-size: 13px;
      }

      #view-wallet .actions {
        margin-top: -2px;
      }

      #ton-connect {
        width: 100%;
      }

      #ton-connect > div {
        width: 100%;
      }

      #telegram-miniapp-link-btn {
        width: 100%;
      }

      .wallet-section {
        margin-top: 0;
        padding: 12px;
        border-radius: 16px;
      }

      .wallet-section-head {
        gap: 8px;
        margin-bottom: 8px;
      }

      .wallet-section h3 {
        font-size: 15px;
        line-height: 1.25;
      }

      .wallet-section-kicker {
        min-width: 30px;
        height: 30px;
        font-size: 11px;
      }

      .domain-grid,
      .owned-decks,
      .card-grid,
      .catalog-grid,
      .mode-grid {
        grid-template-columns: 1fr;
      }

      .owned-decks,
      .card-grid,
      .catalog-grid,
      .domain-grid,
      .mode-grid {
        gap: 10px;
      }

      .catalog-card {
        padding: 10px 12px;
      }

      .catalog-kicker {
        min-height: 24px;
        padding: 0 8px;
        margin-bottom: 8px;
        font-size: 10px;
      }

      .pack-showcase {
        margin-top: 12px;
        padding: 12px 10px 14px;
        border-radius: 22px;
      }

      .pack-counter {
        min-width: 0;
        width: 100%;
        max-width: 250px;
        min-height: 36px;
        margin-bottom: 8px;
        padding: 0 14px;
        font-size: 11px;
        letter-spacing: 0.12em;
      }

      .pack-note {
        margin-bottom: 8px;
        font-size: 11px;
        letter-spacing: 0.12em;
      }

      .foil-pack,
      .pack-showcase.cinematic .foil-pack {
        width: min(280px, calc(100vw - 70px));
        border-radius: 20px;
      }

      .pack-face {
        border-radius: 20px;
      }

      .pack-rip-strip {
        border-radius: 20px 20px 0 0;
      }

      .pack-tap {
        margin-top: 10px;
        font-size: 13px;
        letter-spacing: 0.18em;
      }

      .pack-preview-card {
        width: min(300px, calc(100vw - 28px));
      }

      .pack-preview-card .game-card {
        padding: 14px;
      }

      .wallet-domain-card,
      .domain-card.user-item,
      .user-item.wallet-domain-card {
        padding: 12px;
      }

      .wallet-domain-stats {
        gap: 6px;
        margin: 8px 0;
      }

      .showdown-main {
        min-height: 0;
        max-height: none;
      }

      .showdown-deck {
        display: grid;
        grid-template-columns: 1fr;
        overflow: visible;
        padding-bottom: 0;
      }

      .showdown-card {
        min-width: 0;
        flex: 1 1 auto;
      }

      .battle-cinematic {
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: 8px;
        padding: 20px 8px 14px;
      }

      .battle-vs-orb {
        margin: 0 auto;
        width: 54px;
        height: 54px;
        font-size: 13px;
      }

      .battle-fighter,
      .battle-fighter.enemy {
        min-width: 0;
        padding: 10px;
      }

      .battle-fighter.player {
        text-align: left;
        transform: perspective(900px) rotateY(9deg) scale(1);
      }

      .battle-fighter.enemy {
        text-align: right;
        transform: perspective(900px) rotateY(-9deg) scale(1);
      }

      .battle-fighter strong {
        font-size: 15px;
      }

      .arena-decision-track {
        padding: 12px;
      }

      .arena-clash-lane {
        grid-template-columns: 1fr;
      }

      .arena-clash-versus {
        order: 2;
        min-width: 0;
      }

      .arena-clash-card.enemy {
        text-align: left;
      }

      .arena-core,
      .arena-choice-hub {
        min-height: 0;
      }

      .arena-choice-panel,
      .arena-score-card {
        width: 100%;
      }

      .arena-decision-roundline {
        align-items: flex-start;
        flex-direction: column;
        gap: 4px;
      }

      .arena-deck-grid {
        grid-template-columns: repeat(5, minmax(56px, 1fr));
        gap: 6px;
        --arena-gap: 6px;
        align-items: stretch;
      }

      .arena-slot-card {
        padding: 7px 5px;
        border-radius: 12px;
      }

      .arena-slot-card strong {
        font-size: 9px;
        margin-bottom: 4px;
      }

      .arena-slot-meta {
        font-size: 9px;
        line-height: 1.18;
      }

      .arena-core {
        min-height: 212px;
      }

      .season-pass-jump {
        display: grid;
        grid-template-columns: 1fr;
        gap: 8px;
      }

      .season-pass-nav-btn {
        width: 100%;
      }

      .season-pass-track {
        gap: 8px;
        padding-right: 140px;
      }

      .season-pass-track > * {
        flex-basis: min(58vw, 176px);
      }

      .season-pass-board .catalog-card {
        min-height: 104px !important;
        padding: 10px !important;
        min-width: 0 !important;
      }

      .season-pass-level-row {
        grid-template-columns: 1fr;
        gap: 10px;
      }

      .season-pass-board .catalog-card strong {
        font-size: 13px;
        line-height: 1.14;
      }

      .season-pass-board .catalog-kicker,
      .season-pass-board .tiny,
      .season-pass-board .secondary {
        font-size: 11px;
      }

      .arena-choice-hub {
        min-height: 212px;
        padding: 14px 0 8px;
      }

      .arena-choice-panel {
        padding: 12px 10px;
        border-radius: 16px;
      }

      .arena-choice-panel .interactive-battle-actions {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }

      .arena-choice-panel .interactive-action-btn {
        min-height: 62px;
        font-size: 11px;
      }

      .arena-round-choice-slot {
        top: 58px;
      }

      .arena-round-marker {
        width: 12px;
        height: 12px;
        min-width: 12px;
      }

      .arena-round-state {
        min-height: 22px;
        padding: 0 8px;
        font-size: 10px;
        transform: none;
      }

      .arena-battle-dock {
        left: 50%;
        right: auto;
        width: min(calc(100% - 16px), 360px);
        top: 50%;
        bottom: auto;
        transform: translate(-50%, -50%);
      }

      .arena-battle-dock .interactive-battle-panel {
        padding: 10px 10px 12px;
        border-radius: 16px;
      }

      .arena-battle-dock .interactive-battle-head {
        gap: 8px;
      }

      .arena-battle-dock .interactive-battle-title {
        font-size: 16px;
      }

      .arena-battle-dock .interactive-timer {
        min-width: 60px;
        min-height: 28px;
        font-size: 11px;
      }

      .arena-battle-dock .interactive-battle-actions {
        gap: 6px;
      }

      .arena-battle-dock .interactive-action-btn {
        min-height: 40px;
        font-size: 11px;
        border-radius: 12px;
      }

      .arena-player-resource-bar {
        grid-template-columns: 1fr;
        gap: 6px;
      }

      .arena-resource-pill {
        padding: 6px 8px;
      }

      .arena-resource-caption {
        font-size: 9px;
      }

      .tutorial-action-legend {
        gap: 5px;
      }

      .tutorial-action-chip {
        font-size: 9px;
        padding: 5px 8px;
      }

      .interactive-battle-prompt {
        min-height: 20px;
        font-size: 10px;
      }

      .currency-badge {
        min-width: 0;
      }

      .currency-float {
        top: calc(8px + env(safe-area-inset-top));
        right: 8px;
        left: auto;
        max-width: calc(100vw - 16px);
        padding: 6px 8px;
        gap: 6px;
      }

      .currency-float-chip {
        min-height: 22px;
        padding: 0 7px;
        font-size: 10px;
      }

      .arena-lane-card {
        padding: 7px 6px 8px;
        border-radius: 14px;
      }

      .arena-lane-card strong {
        font-size: 10px;
        margin-bottom: 4px;
      }

      .arena-lane-card .arena-slot-meta {
        font-size: 8px;
        line-height: 1.12;
      }

      .arena-action-sticker {
        right: 6px;
        bottom: 6px;
        width: 28px;
        height: 28px;
      }

      .arena-action-sticker svg {
        width: 14px;
        height: 14px;
      }

      .interactive-battle-actions {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .wallet-domain-chip {
        min-height: 24px;
        padding: 0 7px;
        font-size: 10px;
      }

      .wallet-domain-mainline,
      .wallet-domain-more summary,
      .wallet-section .tiny,
      .wallet-flow-note {
        font-size: 12px;
      }

      .discipline-build-grid {
        grid-template-columns: 1fr 1fr;
        gap: 6px;
      }

      .discipline-build-grid label {
        font-size: 12px;
      }

      .result-actions {
        gap: 8px;
      }
    }

    body.tma-app {
      padding-bottom: calc(116px + env(safe-area-inset-bottom));
      touch-action: pan-y;
    }

    body.tma-app .shell {
      overflow-x: hidden;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
      touch-action: pan-y;
      padding: 12px 10px calc(126px + env(safe-area-inset-bottom));
    }

    body.tma-app .layout {
      grid-template-columns: 1fr;
    }

    body.tma-app .side {
      display: none;
    }

    body.tma-app .hero,
    body.tma-app .panel {
      border-radius: 20px;
    }

    body.tma-app .panel,
    body.tma-app .domain-card,
    body.tma-app .game-card,
    body.tma-app .mode-card,
    body.tma-app .leaderboard-item,
    body.tma-app .team-card,
    body.tma-app .user-item,
    body.tma-app .catalog-card {
      padding: 12px;
    }

    body.tma-app .hero {
      padding: 14px;
    }

    body.tma-app h1 {
      font-size: clamp(34px, 11vw, 52px);
      line-height: 0.94;
    }

    body.tma-app h1 br {
      display: block;
    }

    body.tma-app .top-app-nav {
      display: none;
    }

    body.tma-app .mascot-widget {
      left: 8px;
      bottom: calc(8px + env(safe-area-inset-bottom));
    }

    body.tma-app .mascot-fab {
      width: 64px;
      height: 64px;
      border-radius: 20px;
    }

    body.tma-app .mascot-fab img {
      width: 68px;
      height: 68px;
    }

    body.tma-app .mascot-popover {
      width: min(286px, calc(100vw - 20px));
    }

    body.tma-app .mode-card.preferred-mode {
      padding-top: 76px;
    }

    body.tma-app .mode-card.preferred-mode::before {
      top: 12px;
      left: 12px;
      right: auto;
      max-width: calc(100% - 24px);
      padding: 6px 10px;
      font-size: 10px;
      letter-spacing: 0.05em;
    }

    body.tma-app .hero-top p,
    body.tma-app .stepper {
      display: none;
    }

    body.tma-app #view-wallet > h2,
    body.tma-app #view-wallet > p.muted {
      display: none;
    }

    body.tma-app .domain-grid,
    body.tma-app .owned-decks,
    body.tma-app .card-grid,
    body.tma-app .catalog-grid,
    body.tma-app .mode-grid {
      grid-template-columns: 1fr;
      gap: 10px;
    }

    body.tma-app .mobile-nav {
      position: fixed;
      left: 82px;
      right: 8px;
      bottom: calc(8px + env(safe-area-inset-bottom));
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      padding: 8px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(7, 16, 25, 0.96);
      backdrop-filter: blur(16px);
      z-index: 40;
      box-shadow: 0 18px 34px rgba(0, 0, 0, 0.34);
    }

    body.tma-app .mobile-nav button {
      min-height: 40px;
      height: 40px;
      padding: 6px 3px;
      font-size: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      line-height: 1;
      white-space: normal;
      word-break: break-word;
      min-width: 0;
      border-radius: 12px;
    }

    body.tma-app #nav-achievements {
      font-size: 9px;
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="top-app-nav">
      <div class="top-app-brand">
        <div class="top-app-brand-badge">
          <img src="/static/mascot-ton-bot.png" alt="">
        </div>
        <span>tondomain game</span>
      </div>
      <div class="top-app-nav-actions">
        <button type="button" class="top-app-nav-link active" id="top-nav-profile">Profile</button>
        <button type="button" class="top-app-nav-link" id="top-nav-pack">Cards</button>
        <button type="button" class="top-app-nav-link" id="top-nav-modes">Game</button>
        <button type="button" class="top-app-nav-link" id="top-nav-guilds">Clans</button>
        <button type="button" class="top-app-nav-link" id="top-nav-achievements">Pass</button>
      </div>
    </div>
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow">TON 10K Club Battle Flow</div>
          <h1>tondomain<br>game</h1>
          <p>
            Подключи кошелек для проверки владение доменом для начала игры.
          </p>
        </div>
        <div class="badge-row">
          <div class="badge" id="wallet-badge">Кошелёк не подключен</div>
          <div class="badge currency-badge" id="currency-badge">Осколки: 0 • Редкие: 0 • Lucky: 0</div>
        </div>
      </div>

      <div class="stepper">
        <div class="step-chip active" data-step-chip="profile">1. Профиль</div>
        <div class="step-chip" data-step-chip="pack">2. Карты</div>
        <div class="step-chip" data-step-chip="modes">3. Игра</div>
        <div class="step-chip" data-step-chip="guilds">4. Кланы</div>
        <div class="step-chip" data-step-chip="achievements">5. Пропуск</div>
      </div>
    </section>

    <div class="layout">
      <main class="stack">
        <section class="panel view active" id="view-wallet">
          <h2>Шаг 1. Подключение кошелька и проверка доменов</h2>
          <p class="muted">Подключение происходит через настоящий TonConnect UI. После этого можно проверить NFT в кошельке и найти 4-значные домены клуба 10K.</p>

          <div class="wallet-quick-panel">
            <div class="wallet-quick-grid" id="wallet-quick-grid">
              <div class="wallet-quick-item">
                <strong>Кошелёк</strong>
                <div class="tiny" id="wallet-quick-wallet">Не подключен</div>
              </div>
              <div class="wallet-quick-item">
                <strong>Активный домен</strong>
                <div class="tiny" id="wallet-quick-domain">Не выбран</div>
              </div>
              <div class="wallet-quick-item">
                <strong>Валюта</strong>
                <div class="wallet-quick-currency" id="wallet-quick-currency">
                  <span class="wallet-currency-chip">💠 0</span>
                  <span class="wallet-currency-chip">🎟️ 0</span>
                  <span class="wallet-currency-chip">✨ 0</span>
                </div>
              </div>
            </div>
            <div class="wallet-flow-note">Подключи кошелёк, проверь свои `.ton` домены и сразу переходи к готовой колоде. Если карты для домена уже были открыты, они подтянутся автоматически.</div>
            <div class="wallet-quick-actions">
              <button type="button" id="connect-wallet-btn" onclick="window.openWalletConnect && window.openWalletConnect(); return false;">Подключить кошелёк</button>
              <button type="button" id="check-domains-btn" onclick="window.checkDomains && window.checkDomains(); return false;">Проверить наличие доменов</button>
              <button type="button" class="secondary" id="wallet-open-pack-btn" disabled>К распаковке</button>
            </div>
            <div class="wallet-telegram-panel">
              <div class="wallet-telegram-head">
                <strong>Telegram</strong>
                <div class="tiny" id="telegram-link-summary">Не привязан</div>
              </div>
              <div class="tiny">Привяжи Telegram прямо на сайте. После этого можно получать уведомления о приглашениях в бой, ежедневной награде и наградах пропуска.</div>
              <div id="telegram-login-widget"></div>
              <button type="button" class="secondary" id="telegram-miniapp-link-btn">Включить уведомления Telegram в mini app</button>
              <div class="status" id="telegram-link-status"></div>
            </div>
            <div class="tiny" style="margin-top:8px; color: var(--warning);">Чтобы откалибровать экран в TMA, нажми «Проверить наличие доменов».</div>
            <div class="tiny" id="wallet-tech-status" style="margin-top:6px; color: var(--muted);"></div>
          </div>

          <div class="actions">
            <div id="ton-connect"></div>
          </div>

          <div class="status" id="wallet-status"></div>
          <div class="wallet-section">
            <div class="wallet-section-head">
              <div>
                <h3>Домены для игры</h3>
                <div class="tiny">Выбери домен, которым хочешь играть прямо сейчас.</div>
              </div>
              <div class="wallet-section-kicker">TON</div>
            </div>
            <div class="domain-grid" id="domains-list"></div>
          </div>
          <div class="wallet-section">
            <div class="wallet-section-head">
              <div>
                <h3>Уже открытые колоды</h3>
                <div class="tiny">Если колода уже есть в базе, можно сразу продолжать игру.</div>
              </div>
              <div class="wallet-section-kicker">DECK</div>
            </div>
            <div class="owned-decks" id="wallet-owned-decks-list"></div>
          </div>
          <div class="result-box" id="marketplaces-box" style="display:none;">
            <strong>Доменов клуба 10K не найдено.</strong>
            <p class="muted">Можно купить 4-значный .ton на площадках и затем вернуться к игре с новым доменом.</p>
            <div class="links-row" id="marketplaces-links"></div>
          </div>
        </section>

        <section class="panel view" id="view-pack">
          <h2>Шаг 2. Распаковка 5 карточек</h2>
          <p class="muted">Карты генерируются из реально найденного домена. Колода фиксируется только по домену, поэтому её можно воспроизводить и использовать в режимах игры.</p>
          <div class="result-box" style="margin-top:10px;">
            <strong>Характеристики карт</strong>
            <div class="tiny" style="margin-top:8px;">Карты отличаются только редкостью: Basic, Rare, Epic, Mythic, Legendary.</div>
            <div class="tiny">Карты вносят вклад в пул, который потом можно распределять по 5 дисциплинам: атака, защита, удача, скорость, магия.</div>
            <div class="tiny">У каждого игрока стартовый пул 2500 + бонусы тира/паттернов домена с 10kclub.</div>
          </div>

          <div class="stats-strip">
            <div class="stat-chip" id="selected-domain-label">Домен не выбран</div>
            <div class="stat-chip" id="pack-score-label">Вклад карт: -</div>
          </div>

          <div class="actions">
            <button class="secondary" id="back-to-wallet-btn">Назад</button>
            <button class="secondary" id="rebind-domain-btn">Перепривязать домен</button>
            <button class="secondary" id="shuffle-deck-btn" disabled>Перемешать карты</button>
            <button id="open-pack-btn" disabled>Открыть ежедневный пак</button>
            <button id="buy-pack-btn" disabled>Купить премиум-пропуск</button>
          </div>

          <div class="actions" id="pack-type-picker" style="margin-top:10px;"></div>

          <div class="result-box" id="pack-economy-box" style="margin-top:12px;">
            <strong>Экономика паков</strong>
            <div class="tiny" id="pack-rewards-summary">Подключи кошелёк, чтобы видеть осколки, токены и сезонный прогресс.</div>
            <div class="tiny" id="pack-season-summary" style="margin-top:6px;">Сезон: -</div>
            <div class="tiny" style="margin-top:6px;">Платный пак карт убран. Донат идёт в премиум-пропуск и сезонные награды.</div>
            <div class="actions" style="margin-top:10px;">
              <button class="secondary" id="claim-daily-reward-btn" disabled>Забрать дейлик</button>
              <button class="secondary" id="claim-quest-reward-btn" disabled>Забрать квест побед</button>
            </div>
            <div class="actions" style="margin-top:10px;">
              <button class="secondary reward-pack-btn" data-reward-pack="common" disabled>Обычный пак за 3 осколка</button>
              <button class="secondary reward-pack-btn" data-reward-pack="rare" disabled>Редкий пак за 1 редкий токен</button>
              <button class="secondary reward-pack-btn" data-reward-pack="epic" disabled>Эпический пак за 6 осколков + 1 редкий токен</button>
              <button class="secondary reward-pack-btn" data-reward-pack="lucky" disabled>Счастливый пак за 1 lucky-токен</button>
              <button class="secondary reward-pack-btn" data-reward-pack="cosmetic" disabled>Косметический пак из пропуска</button>
            </div>
          </div>

          <div class="pack-showcase" id="pack-showcase">
            <div class="pack-counter" id="pack-counter" style="display:none;"></div>
            <p class="pack-note" id="pack-note">НАЖМИ, ЧТОБЫ ОТКРЫТЬ</p>
            <div class="foil-pack" id="foil-pack">
              <div class="pack-cap"></div>
              <div class="foil-pack-frame" aria-hidden="true">
                <div class="pack-rip-strip"></div>
                <div class="pack-mouth-glow"></div>
                <div class="pack-face"></div>
              </div>
            </div>
          <div class="pack-tap">Нажми, чтобы открыть</div>
          </div>

          <div class="status" id="pack-status"></div>
          <div class="actions" id="pack-restore-actions" style="display:none; margin-top:10px;">
            <button class="secondary" id="restore-previous-deck-btn">Оставить прошлую колоду</button>
          </div>
          <div class="card-grid" id="pack-cards"></div>
          <h3 style="margin-top:18px;">Прокачка дисциплин</h3>
          <div class="tiny">Распредели базовую силу колоды. Эти очки применяются в раундах и дают итоговый перевес.</div>
          <div class="discipline-build-grid">
            <label>Атака <input id="build-attack" type="number" min="0" step="1"></label>
            <label>Защита <input id="build-defense" type="number" min="0" step="1"></label>
            <label>Удача <input id="build-luck" type="number" min="0" step="1"></label>
            <label>Скорость <input id="build-speed" type="number" min="0" step="1"></label>
            <label>Магия <input id="build-magic" type="number" min="0" step="1"></label>
          </div>
          <div class="actions" style="margin-top:10px;">
            <button class="secondary" id="save-build-btn" disabled>Сохранить прокачку</button>
          </div>
          <div class="status tiny" id="build-status"></div>
          <div class="actions" style="margin-top:12px;">
            <button id="continue-to-modes-btn" disabled>Продолжить</button>
          </div>
          <h3 style="margin-top:18px;">Редкости карт</h3>
          <div class="deck-list" id="card-catalog-list"></div>
        </section>

        <section class="panel view" id="view-modes">
          <h2>Шаг 3. Режимы игры</h2>
          <p class="muted">Бой проходит как серия 5 карт на 5. Важны порядок колоды, размены карт, тактическая карта на матч и скиллы. Прокачка дисциплин остается как фоновая поддержка стратегии.</p>
          <div id="tutorial-panel" class="deck-list" style="margin-bottom:18px;"></div>

          <div class="team-card" style="margin-bottom:18px;">
            <h3>Автопоиск соперника</h3>
            <div class="tiny">Нажми кнопку рейтингового или обычного режима. Если соперник уже ищет матч, бой стартует мгновенно.</div>
            <div class="row" style="margin-top:10px;">
              <select id="battle-card-slot">
                <option value="">Выбери тактическую карту на матч</option>
              </select>
            </div>
            <div class="tiny">Тактическая карта даёт скилл на весь матч.</div>
            <div class="actions" style="margin-top:10px;">
              <button class="secondary" id="cancel-matchmaking-btn" disabled>Отменить поиск</button>
            </div>
            <div class="status" id="matchmaking-status"></div>
          </div>

          <div class="mode-grid">
            <div class="mode-card" data-mode-card="ranked">
              <div class="mode-burst"></div>
              <h3>Рейтинговый</h3>
              <p>Автопоиск соперника среди активных игроков. После матча рейтинг пересчитывается по ELO.</p>
              <button id="play-ranked-btn" disabled>Найти рейтинговый матч</button>
            </div>
            <div class="mode-card" data-mode-card="casual">
              <div class="mode-burst"></div>
              <h3>Обычный</h3>
              <p>Автопоиск соперника среди активных игроков без изменения рейтинга.</p>
              <button id="play-casual-btn" disabled>Найти обычный матч</button>
            </div>
            <div class="mode-card" data-mode-card="bot">
              <div class="mode-burst"></div>
              <h3>С ботом</h3>
              <p>Тестовый 5-раундовый бой против бота с рандомной колодой.</p>
              <button id="play-bot-btn" disabled>Играть с ботом</button>
            </div>
            <div class="mode-card" data-mode-card="duel">
              <div class="mode-burst"></div>
              <h3>Дуэль</h3>
              <p>Обычный бой, но матч стартует после принятия приглашения от соперника. Время на принятия боя 30 секунд.</p>
              <input id="opponent-wallet" placeholder="Ник или домен соперника">
              <button id="play-duel-btn" disabled>Пригласить в дуэль</button>
            </div>
          </div>

          <div class="result-box" id="battle-result" style="display:none;"></div>
          <div class="result-box" id="invite-result" style="display:none;"></div>
        </section>

        <section class="panel view" id="view-battleflow">
          <h2>Ход боя</h2>
          <p class="muted">Подробный разбор раундов матча: какие карты сошлись, какие решения были выбраны и как сложился итог.</p>
          <div id="battle-flow-view"></div>
        </section>

        <section class="panel view" id="view-profile">
          <h2>Профиль</h2>
          <div id="profile-wallet-hub" class="deck-list"></div>
          <div id="mobile-profile-summary" class="deck-list"></div>
          <div id="mobile-rewards-panel" class="deck-list" style="margin-top:14px;"></div>
          <h3 style="margin-top:20px;">Публичный профиль</h3>
          <div id="profile-identity-panel" class="deck-list"></div>
          <h3 style="margin-top:20px;">Косметика и превью</h3>
          <div id="profile-cosmetics-panel" class="deck-list"></div>
          <h3 style="margin-top:20px;">FAQ</h3>
          <div id="faq-panel" class="deck-list"></div>
          <h3 style="margin-top:20px;">Друзья и лобби</h3>
          <div id="social-panel" class="deck-list"></div>
          <div class="actions" style="margin-top:14px;">
            <button class="secondary" id="mobile-show-deck-btn">Моя колода</button>
          </div>
          <div id="mobile-deck-view" class="deck-list" style="margin-top:14px;"></div>
          <h3 style="margin-top:20px;">Рейтинг</h3>
          <div id="mobile-leaderboard" class="leaderboard"></div>
          <h3 style="margin-top:20px;">Общая база игроков</h3>
          <div id="mobile-global-players-list" class="global-players-list"></div>
        </section>

        <section class="panel view" id="view-guilds">
          <h2>Кланы и клановые войны</h2>
          <p class="muted">Отдельный экран кланов: состав, заявки, чат, недельные цели, война недели и награда клана.</p>
          <div id="guild-panel" class="deck-list"></div>
        </section>

        <section class="panel view" id="view-achievements">
          <h2>Сезонный пропуск</h2>
          <p class="muted">Отдельный экран бесплатного и премиум-трека. Премиум даёт только косметику и ускоряет сбор сезонной валюты.</p>
          <div class="actions">
            <button id="refresh-achievements-btn" disabled>Обновить пропуск</button>
          </div>
          <div class="deck-list" id="achievements-list"></div>
        </section>
      </main>

      <aside class="side">
        <section class="panel">
          <h3>Моя колода</h3>
          <div class="actions">
            <button class="secondary" id="show-deck-btn" disabled>Открыть колоду</button>
            <button class="secondary" id="toggle-deck-btn">Скрыть</button>
          </div>
          <div class="deck-list" id="deck-view"></div>
          <h3 style="margin-top:18px;">Колоды кошелька</h3>
          <div class="owned-decks" id="owned-decks-list"></div>
        </section>

        <section class="panel">
          <h3>Профиль игрока</h3>
          <div class="kv"><span class="muted">Кошелёк</span><span id="profile-wallet">-</span></div>
          <div class="kv"><span class="muted">Активный домен</span><span id="profile-domain">-</span></div>
          <div class="kv"><span class="muted">Рейтинг</span><span id="profile-rating">1000</span></div>
          <div class="kv"><span class="muted">Сыграно матчей</span><span id="profile-games">0</span></div>
          <div id="profile-rewards-panel" class="deck-list" style="margin-top:14px;"></div>
        </section>

        <section class="panel">
          <h3>Активные юзеры сейчас</h3>
          <div class="active-users-list" id="active-users-list"></div>
        </section>

        <section class="panel">
          <h3>Общая база игроков</h3>
          <div class="global-players-list" id="global-players-list"></div>
        </section>

        <section class="panel">
          <h3>Топ рейтинга</h3>
          <div class="leaderboard" id="leaderboard"></div>
        </section>
      </aside>
    </div>
  </div>

  <nav class="mobile-nav">
    <button id="nav-pack">Карты</button>
    <button id="nav-modes">Игра</button>
    <button id="nav-guilds">Кланы</button>
    <button id="nav-achievements">Пропуск</button>
  </nav>

  <div class="currency-float" id="global-currency-float">
    <span class="currency-float-chip">💠 <span id="global-currency-shards">0</span></span>
    <span class="currency-float-chip">🎟️ <span id="global-currency-rare">0</span></span>
    <span class="currency-float-chip">✨ <span id="global-currency-lucky">0</span></span>
  </div>

  <div class="startup-guide" id="startup-guide">
    <div class="startup-guide-card">
      <div class="startup-guide-meta">
        <span id="startup-guide-step-label">Шаг 1 / 8</span>
        <span class="startup-guide-dots" id="startup-guide-dots"></span>
      </div>
      <div class="startup-guide-stage" aria-hidden="true">
        <img class="startup-guide-gif" id="startup-guide-gif" src="/static/tutorial/start-guide.gif?v=20260403" alt="Гайд по бою Ton Domain Game">
        <div class="startup-guide-stage-overlay" id="startup-guide-stage-overlay" style="display:none;"></div>
      </div>
      <div class="startup-guide-copy">
        <strong id="startup-guide-title">Короткий гайд</strong>
        <div class="tiny" id="startup-guide-body">1) Выбери домен и колоду. 2) В бою жми «Натиск»/«Блок» и «Готов». 3) Побеждай раунды на дорожках и собирай награды.</div>
      </div>
      <div class="actions startup-guide-actions">
        <button class="secondary" id="startup-guide-prev-btn">Назад</button>
        <button id="startup-guide-next-btn">Далее</button>
        <button id="startup-guide-close-btn">Завершить</button>
        <button class="secondary" id="startup-guide-skip-btn">Пропустить</button>
      </div>
    </div>
  </div>

  <div class="mascot-widget" id="mascot-widget">
    <div class="mascot-popover" id="mascot-popover">
      <div class="mascot-popover-head">
        <img src="/static/mascot-ton-bot.png" alt="">
        <div>
          <div class="mascot-popover-title">Помощник Ton Domain</div>
          <div class="mascot-popover-copy" id="mascot-popover-copy">Быстрый доступ к основным разделам и гайду.</div>
        </div>
      </div>
      <div class="mascot-popover-actions">
        <button type="button" id="mascot-open-profile-btn">Профиль</button>
        <button type="button" id="mascot-open-pack-btn">Карты</button>
        <button type="button" id="mascot-open-battle-btn">Игра</button>
        <button type="button" class="secondary" id="mascot-open-guide-btn">Гайд</button>
      </div>
    </div>
    <button type="button" class="mascot-fab" id="mascot-fab" aria-label="Открыть помощника">
      <img src="/static/mascot-ton-bot.png" alt="">
    </button>
  </div>

  <div class="public-profile-backdrop" id="public-profile-backdrop">
    <div class="public-profile-modal" id="public-profile-modal">
      <div id="public-profile-content"></div>
    </div>
  </div>

  <script>
    const state = {
      wallet: null,
      domains: [],
      domainsChecked: false,
      selectedDomain: null,
      cards: [],
      pendingPackSource: null,
      pendingPackPaymentId: null,
      pendingRewardPackType: null,
      packOpening: false,
      selectedBattleSlot: null,
      playerProfile: null,
      lastResult: null,
      roomId: null,
      room: null,
      activeUsers: [],
      friends: [],
      socialData: null,
      guildData: null,
      tutorialData: null,
      ownedDecks: [],
      allPlayers: [],
      achievements: [],
      cardCatalog: [],
      packTypes: [],
      selectedPackType: 'common',
      packPityThreshold: 20,
      showAllCosmetics: false,
      profileTab: 'overview',
      publicProfile: null,
      canRestorePreviousDeck: false,
      matchmakingMode: null,
      matchmakingPolling: false,
      matchmakingErrorStreak: 0,
      disciplineBuild: null,
      battleLaunchInFlight: false,
      lastReplayTapAt: 0,
      interactiveActionInFlight: false,
      telegramWidgetSignature: '',
      telegramMiniLinkInFlight: false
    };

    const telegramBotUsername = {{ telegram_bot_username|tojson }};
    const telegramWebappUrl = {{ telegram_webapp_url|tojson }};
    const marketplaceLinks = {{ marketplace_links|tojson }};

    const walletBadge = document.getElementById('wallet-badge');
    const currencyBadge = document.getElementById('currency-badge');
    const walletStatus = document.getElementById('wallet-status');
    const walletTechStatus = document.getElementById('wallet-tech-status');
    const telegramLinkSummary = document.getElementById('telegram-link-summary');
    const telegramLinkStatus = document.getElementById('telegram-link-status');
    const telegramLoginWidget = document.getElementById('telegram-login-widget');
    const telegramMiniappLinkBtn = document.getElementById('telegram-miniapp-link-btn');
    const walletQuickWallet = document.getElementById('wallet-quick-wallet');
    const walletQuickDomain = document.getElementById('wallet-quick-domain');
    const walletQuickCurrency = document.getElementById('wallet-quick-currency');
    const globalCurrencyShards = document.getElementById('global-currency-shards');
    const globalCurrencyRare = document.getElementById('global-currency-rare');
    const globalCurrencyLucky = document.getElementById('global-currency-lucky');
    const walletOpenPackBtn = document.getElementById('wallet-open-pack-btn');
    const profileWallet = document.getElementById('profile-wallet');
    const profileDomain = document.getElementById('profile-domain');
    const profileRating = document.getElementById('profile-rating');
    const profileGames = document.getElementById('profile-games');
    const selectedDomainLabel = document.getElementById('selected-domain-label');
    const packScoreLabel = document.getElementById('pack-score-label');
    const packCards = document.getElementById('pack-cards');
    const battleResult = document.getElementById('battle-result');
    const inviteResult = document.getElementById('invite-result');
    const tutorialPanel = document.getElementById('tutorial-panel');
    const mascotWidget = document.getElementById('mascot-widget');
    const mascotFab = document.getElementById('mascot-fab');
    const mascotOpenProfileBtn = document.getElementById('mascot-open-profile-btn');
    const mascotOpenPackBtn = document.getElementById('mascot-open-pack-btn');
    const mascotOpenBattleBtn = document.getElementById('mascot-open-battle-btn');
    const mascotOpenGuideBtn = document.getElementById('mascot-open-guide-btn');
    const mascotPopoverCopy = document.getElementById('mascot-popover-copy');
    const battleFlowView = document.getElementById('battle-flow-view');
    const leaderboard = document.getElementById('leaderboard');
    const marketplacesBox = document.getElementById('marketplaces-box');
    const marketplacesLinks = document.getElementById('marketplaces-links');
    const activeUsersList = document.getElementById('active-users-list');
    const deckView = document.getElementById('deck-view');
    const profileRewardsPanel = document.getElementById('profile-rewards-panel');
    const showDeckBtn = document.getElementById('show-deck-btn');
    const toggleDeckBtn = document.getElementById('toggle-deck-btn');
    const mobileProfileSummary = document.getElementById('mobile-profile-summary');
    const mobileRewardsPanel = document.getElementById('mobile-rewards-panel');
    const profileIdentityPanel = document.getElementById('profile-identity-panel');
    const profileCosmeticsPanel = document.getElementById('profile-cosmetics-panel');
    const faqPanel = document.getElementById('faq-panel');
    const socialPanel = document.getElementById('social-panel');
    const guildPanel = document.getElementById('guild-panel');
    const profileWalletHub = document.getElementById('profile-wallet-hub');
    const mobileLeaderboard = document.getElementById('mobile-leaderboard');
    const mobileDeckView = document.getElementById('mobile-deck-view');
    const mobileGlobalPlayersList = document.getElementById('mobile-global-players-list');
    const startupGuide = document.getElementById('startup-guide');
    const startupGuideGif = document.getElementById('startup-guide-gif');
    const startupGuideStageOverlay = document.getElementById('startup-guide-stage-overlay');
    const startupGuideStepLabel = document.getElementById('startup-guide-step-label');
    const startupGuideDots = document.getElementById('startup-guide-dots');
    const startupGuideTitle = document.getElementById('startup-guide-title');
    const startupGuideBody = document.getElementById('startup-guide-body');
    const startupGuideCloseBtn = document.getElementById('startup-guide-close-btn');
    const startupGuideSkipBtn = document.getElementById('startup-guide-skip-btn');
    const startupGuidePrevBtn = document.getElementById('startup-guide-prev-btn');
    const startupGuideNextBtn = document.getElementById('startup-guide-next-btn');
    const publicProfileBackdrop = document.getElementById('public-profile-backdrop');
    const publicProfileContent = document.getElementById('public-profile-content');
    const ownedDecksList = document.getElementById('owned-decks-list');
    const walletOwnedDecksList = document.getElementById('wallet-owned-decks-list');
    const topNavProfile = document.getElementById('top-nav-profile');
    const topNavPack = document.getElementById('top-nav-pack');
    const topNavModes = document.getElementById('top-nav-modes');
    const topNavGuilds = document.getElementById('top-nav-guilds');
    const topNavAchievements = document.getElementById('top-nav-achievements');
    const globalPlayersList = document.getElementById('global-players-list');
    const packShowcase = document.getElementById('pack-showcase');
    const foilPack = document.getElementById('foil-pack');
    const packCounter = document.getElementById('pack-counter');
    const packNote = document.getElementById('pack-note');
    const buyPackBtn = document.getElementById('buy-pack-btn');
    const packTypePicker = document.getElementById('pack-type-picker');
    const packRewardsSummary = document.getElementById('pack-rewards-summary');
    const packSeasonSummary = document.getElementById('pack-season-summary');
    const packRestoreActions = document.getElementById('pack-restore-actions');
    const restorePreviousDeckBtn = document.getElementById('restore-previous-deck-btn');
    const claimDailyRewardBtn = document.getElementById('claim-daily-reward-btn');
    const claimQuestRewardBtn = document.getElementById('claim-quest-reward-btn');
    const cardCatalogList = document.getElementById('card-catalog-list');
    const oneCardSlot = document.getElementById('one-card-slot');
    const battleCardSlot = document.getElementById('battle-card-slot');
    const teamPanel = document.getElementById('team-panel');
    const playOnecardBtn = document.getElementById('play-onecard-btn');
    const createRoomBtn = document.getElementById('create-room-btn');
    const joinRoomBtn = document.getElementById('join-room-btn');
    const refreshRoomBtn = document.getElementById('refresh-room-btn');
    const startRoomBtn = document.getElementById('start-room-btn');
    const showTeamBtn = document.getElementById('show-team-btn');
    const achievementsList = document.getElementById('achievements-list');
    const refreshAchievementsBtn = document.getElementById('refresh-achievements-btn');
    const matchmakingStatus = document.getElementById('matchmaking-status');
    const cancelMatchmakingBtn = document.getElementById('cancel-matchmaking-btn');
    const buildAttack = document.getElementById('build-attack');
    const buildDefense = document.getElementById('build-defense');
    const buildLuck = document.getElementById('build-luck');
    const buildSpeed = document.getElementById('build-speed');
    const buildMagic = document.getElementById('build-magic');
    const saveBuildBtn = document.getElementById('save-build-btn');
    const buildStatus = document.getElementById('build-status');
    if (startupGuideGif && startupGuideStageOverlay) {
      startupGuideGif.addEventListener('error', () => {
        startupGuideGif.style.display = 'none';
        startupGuideStageOverlay.style.display = 'flex';
        startupGuideStageOverlay.textContent = 'Мини-видео временно недоступно';
      });
    }
    let tonConnectUI = null;
    let matchmakingPollTimer = null;
    let modeFocusTimer = null;
    let interactiveChoiceTimer = null;
    let interactiveChoiceExpireTimer = null;
    let battleAutostartTimer = null;
    const usageStorageKey = 'tondomaingame_ui_usage_v1';
    const startupGuideStorageKey = 'tondomaingame_startup_guide_v1';
    const startupGuideSteps = [
      {
        title: 'Подключи кошелёк и проверь домены',
        body: 'Нажми «Подключить кошелёк», затем «Проверить наличие доменов». Для боя выбираются 4-значные .ton домены из кошелька.',
        overlayHtml: `
          <div class="startup-guide-scene">
            <div class="startup-guide-flowboard">
              <div class="startup-guide-wallet-card">
                <div class="head">TonConnect</div>
                <div class="name">TON</div>
                <div class="rows"><i></i><i></i><i></i></div>
              </div>
              <div class="startup-guide-bridge"></div>
              <div class="startup-guide-domain-panel">
                <div class="tag">Найден домен</div>
                <div class="domain">7288.ton</div>
              </div>
            </div>
          </div>
        `
      },
      {
        title: 'Собери колоду через паки',
        body: 'Открой пак и получи 5 карт. Колода хранится по домену. Можно менять активный домен и играть разными сборками.',
        overlayHtml: `
          <div class="startup-guide-scene">
            <div class="startup-guide-pack-reveal">
              <div class="startup-guide-pack-reveal-burst"></div>
              <div class="startup-guide-pack-reveal-card left" data-tier="basic">
                <div class="glyph">🃏</div>
              </div>
              <div class="startup-guide-pack-reveal-card center" data-tier="rare">
                <div class="glyph">✨</div>
              </div>
              <div class="startup-guide-pack-reveal-card right" data-tier="epic">
                <div class="glyph">💠</div>
              </div>
            </div>
          </div>
        `
      },
      {
        title: 'Распредели пул дисциплин',
        body: 'Пул влияет на атаку, защиту, удачу, скорость и магию. Чем точнее распределение под стиль, тем стабильнее результат.',
        overlayHtml: `
          <div class="startup-guide-scene">
            <div class="startup-guide-chart">
              <div class="startup-guide-bar h1"></div>
              <div class="startup-guide-bar h2"></div>
              <div class="startup-guide-bar h3"></div>
              <div class="startup-guide-bar h4"></div>
              <div class="startup-guide-bar h5"></div>
            </div>
          </div>
        `
      },
      {
        title: 'Бой идёт по дорожкам раундов',
        body: 'Каждый раунд: выбирай Натиск или Блок и жми «Готов». Побеждай раунды на дорожках, чтобы забрать матч.',
        overlayHtml: `
          <div class="startup-guide-lane"></div>
          <div class="startup-guide-card-demo enemy">⚔️</div>
          <div class="startup-guide-card-demo player">🛡️</div>
          <div class="startup-guide-pulse"></div>
        `
      },
      {
        title: 'Энергия, КД и активная способность',
        body: 'Натиск стоит 2 энергии, Блок 1, способность 3. Следи за КД и зарядами: тайминг способности часто решает бой.',
        overlayHtml: `
          <div class="startup-guide-scene">
            <div class="startup-guide-pill-row">
              <div class="startup-guide-pill">Энергия 3<small>Натиск 2 • Блок 1</small></div>
              <div class="startup-guide-pill">КД 1<small>Следи за откатом</small></div>
              <div class="startup-guide-pill">Способность<small>3 энергии и заряды</small></div>
            </div>
          </div>
        `
      },
      {
        title: 'PvP и Дуэль',
        body: 'В PvP после подбора оба игрока подтверждают готовность (2/2). В дуэли соперник принимает приглашение 30 секунд.',
        overlayHtml: `
          <div class="startup-guide-scene">
            <div class="startup-guide-ready-board">
              <div class="startup-guide-ready-node left">Игрок 1</div>
              <div class="startup-guide-ready-center"><strong>2/2</strong><span>Готовы</span><small>30 сек</small></div>
              <div class="startup-guide-ready-node right">Игрок 2</div>
            </div>
          </div>
        `
      },
      {
        title: 'Кланы, сезонный пропуск и награды',
        body: 'Играй клановые активности, забирай награды пропуска вручную, получай осколки/токены и открывай новые паки.',
        overlayHtml: `
          <div class="startup-guide-scene">
            <div class="startup-guide-scene-column">
              <div class="startup-guide-tile-row">
                <div class="startup-guide-tile"><b>Кланы</b>Войны и недельные цели</div>
                <div class="startup-guide-tile"><b>Пропуск</b>Забирай награды вручную</div>
                <div class="startup-guide-tile"><b>Награды</b>Осколки, токены и паки</div>
              </div>
              <div class="startup-guide-rail"><div class="startup-guide-rail-fill"></div></div>
            </div>
          </div>
        `
      },
      {
        title: 'Косметика и прогресс',
        body: 'Рубашки, арены и баннеры меняют визуал боя. Домены и колоды прокачиваются, но победа зависит от решений в раундах.',
        overlayHtml: `
          <div class="startup-guide-scene">
            <div class="startup-guide-scene-column">
              <div class="startup-guide-tile-row">
                <div class="startup-guide-tile"><b>Рубашка</b>Видна всем игрокам</div>
                <div class="startup-guide-tile"><b>Арена</b>Меняет фон боя</div>
                <div class="startup-guide-tile"><b>Баннер</b>Добивает стиль матча</div>
              </div>
              <div class="startup-guide-note">Если вы в TMA, нажмите «Проверить наличие доменов» для калибровки экрана.</div>
            </div>
          </div>
        `
      }
    ];
    startupGuideSteps.forEach((step) => {
      step.useGif = false;
      step.gifSrc = '';
    });
    let startupGuideStepIndex = 0;

    function shortAddress(value) {
      if (!value) return '-';
      return `${value.slice(0, 6)}...${value.slice(-6)}`;
    }

    function shouldShowStartupGuide() {
      try {
        return window.localStorage.getItem(startupGuideStorageKey) !== 'seen';
      } catch (_) {
        return true;
      }
    }

    function closeStartupGuide(markSeen = true) {
      if (!startupGuide) return;
      startupGuide.classList.remove('visible');
      if (markSeen) {
        try {
          window.localStorage.setItem(startupGuideStorageKey, 'seen');
        } catch (_) {
        }
      }
    }

    function showStartupGuideIfNeeded() {
      if (!startupGuide || !shouldShowStartupGuide()) return;
      startupGuideStepIndex = 0;
      renderStartupGuideStep();
      startupGuide.classList.add('visible');
    }

    function renderStartupGuideStep() {
      if (!startupGuide) return;
      const maxIndex = Math.max(0, startupGuideSteps.length - 1);
      startupGuideStepIndex = Math.max(0, Math.min(maxIndex, Number(startupGuideStepIndex || 0)));
      const step = startupGuideSteps[startupGuideStepIndex] || startupGuideSteps[0];
      if (startupGuideTitle) startupGuideTitle.textContent = step.title || '';
      if (startupGuideBody) startupGuideBody.textContent = step.body || '';
      if (startupGuideStepLabel) startupGuideStepLabel.textContent = `Шаг ${startupGuideStepIndex + 1} / ${startupGuideSteps.length}`;
      if (startupGuideDots) {
        startupGuideDots.innerHTML = startupGuideSteps.map((_, index) => `<i class="${index === startupGuideStepIndex ? 'active' : ''}"></i>`).join('');
      }
      if (startupGuideGif && startupGuideStageOverlay) {
        const useGif = Boolean(step.useGif);
        startupGuideGif.style.display = useGif ? 'block' : 'none';
        startupGuideStageOverlay.style.display = useGif ? 'none' : 'flex';
        if (useGif) {
          const gifSrc = step.gifSrc || startupGuideGifData(step, startupGuideStepIndex);
          if (gifSrc && startupGuideGif.getAttribute('src') !== gifSrc) {
            startupGuideGif.setAttribute('src', gifSrc);
          }
          startupGuideStageOverlay.textContent = '';
        } else if (step.overlayHtml) {
          startupGuideStageOverlay.innerHTML = step.overlayHtml;
        } else {
          startupGuideStageOverlay.textContent = step.overlay || '';
        }
      }
      if (startupGuidePrevBtn) {
        startupGuidePrevBtn.disabled = startupGuideStepIndex <= 0;
      }
      if (startupGuideNextBtn) {
        startupGuideNextBtn.textContent = startupGuideStepIndex >= maxIndex ? 'Готово' : 'Далее';
      }
      if (startupGuideCloseBtn) {
        startupGuideCloseBtn.style.display = startupGuideStepIndex >= maxIndex ? 'inline-flex' : 'none';
      }
    }

    function nextStartupGuideStep() {
      const maxIndex = Math.max(0, startupGuideSteps.length - 1);
      if (startupGuideStepIndex >= maxIndex) {
        closeStartupGuide(true);
        return;
      }
      startupGuideStepIndex += 1;
      renderStartupGuideStep();
    }

    function prevStartupGuideStep() {
      startupGuideStepIndex = Math.max(0, startupGuideStepIndex - 1);
      renderStartupGuideStep();
    }

    function isTelegramMiniApp() {
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      const search = new URLSearchParams(window.location.search || '');
      const hash = (window.location.hash || '').toLowerCase();
      const ua = (navigator.userAgent || '').toLowerCase();
      const hasTelegramQuery = Array.from(search.keys()).some((key) => key.toLowerCase().startsWith('tgwebapp'));
      const hasTelegramHash = hash.includes('tgwebapp') || hash.includes('telegram');
      const hasTelegramUA = ua.includes('telegram') || ua.includes('telegrambot');
      if (!tg) {
        return hasTelegramQuery || hasTelegramHash || hasTelegramUA;
      }
      return Boolean(
        tg.initData
        || (tg.initDataUnsafe && Object.keys(tg.initDataUnsafe).length)
        || tg.platform
        || hasTelegramQuery
        || hasTelegramHash
        || hasTelegramUA
      );
    }

    function syncTmaMode() {
      const active = isTelegramMiniApp();
      document.body.classList.toggle('tma-app', active);
      document.documentElement.classList.toggle('tma-app', active);
      document.body.dataset.appMode = active ? 'tma' : 'site';
      return active;
    }

    let tmaSyncRaf = null;
    function syncTmaViewport() {
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      const viewportHeight = tg && Number.isFinite(Number(tg.viewportHeight)) && Number(tg.viewportHeight) > 0
        ? Number(tg.viewportHeight)
        : window.innerHeight;
      const viewportWidth = tg && Number.isFinite(Number(tg.viewportStableWidth)) && Number(tg.viewportStableWidth) > 0
        ? Number(tg.viewportStableWidth)
        : window.innerWidth;
      document.documentElement.style.setProperty('--app-height', `${viewportHeight}px`);
      document.documentElement.style.setProperty('--app-width', `${viewportWidth}px`);
      if (tg && typeof tg.expand === 'function') {
        try {
          tg.expand();
        } catch (error) {
          // Ignore Telegram viewport sync errors and keep the local CSS vars updated.
        }
      }
    }

    function queueTmaModeSync() {
      if (tmaSyncRaf) {
        return;
      }
      tmaSyncRaf = window.requestAnimationFrame(() => {
        tmaSyncRaf = null;
        syncTmaMode();
        syncTmaViewport();
      });
    }

    function resetHorizontalViewportDrift() {
      document.documentElement.scrollLeft = 0;
      document.body.scrollLeft = 0;
      window.scrollTo({ left: 0, top: window.scrollY, behavior: 'auto' });
    }

    function shouldSyncForFunctionalTarget(target) {
      if (!target || typeof target.closest !== 'function') {
        return false;
      }
      return Boolean(target.closest('button, select, input, textarea, label[for], [role="button"], [data-mode-card], .mode-card, .mobile-nav button'));
    }

    function syncTmaModeForFunctionalAction(event) {
      if (shouldSyncForFunctionalTarget(event.target)) {
        queueTmaModeSync();
      }
    }

    async function prepareFunctionalInteraction() {
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      syncTmaMode();
      syncTmaViewport();
      if (tg && typeof tg.ready === 'function') {
        try {
          tg.ready();
        } catch (error) {
          // Ignore Telegram readiness errors and continue with local viewport sync.
        }
      }
      await new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
      syncTmaMode();
      syncTmaViewport();
      await new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
      syncTmaMode();
      syncTmaViewport();
    }

    function bindFunctionalControl(node, handler, eventName = 'click', options = {}) {
      if (!node) {
        return;
      }
      node.addEventListener(eventName, async (event) => {
        if (!options.skipPrepare) {
          await prepareFunctionalInteraction();
        }
        return handler(event);
      });
    }

    async function interceptDeckDomainAction(event) {
      const control = event.target && typeof event.target.closest === 'function'
        ? event.target.closest('.wallet-domain-action[data-domain-action]')
        : null;
      if (!control) {
        return;
      }
      if (control.dataset.domainActionBusy === '1') {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      const domain = (control.dataset.domainAction || '').trim();
      if (!domain) {
        return;
      }
      control.dataset.domainActionBusy = '1';
      control.disabled = true;
      control.dataset.loading = '1';
      try {
        await prepareFunctionalInteraction();
        await new Promise((resolve) => window.setTimeout(resolve, 110));
        syncTmaMode();
        syncTmaViewport();
        await new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
        await selectDeckDomain(domain, {skipSync: true});
      } finally {
        delete control.dataset.loading;
        delete control.dataset.domainActionBusy;
        control.disabled = false;
      }
    }

    async function interceptInteractiveBattleAction(event) {
      const control = event.target && typeof event.target.closest === 'function'
        ? event.target.closest('.interactive-action-btn[data-action-key]')
        : null;
      if (!control) {
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      const actionKey = (control.dataset.actionKey || '').trim();
      if (!actionKey) {
        return;
      }
      await handleInteractiveBattleChoice(actionKey);
    }

    async function interceptSocialAction(event) {
      const control = event.target && typeof event.target.closest === 'function'
        ? event.target.closest('[data-social-action]')
        : null;
      if (!control) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      try {
        await handleSocialAction(control.dataset.socialAction, control.dataset);
      } catch (error) {
        setStatus(walletStatus, error.message, 'error');
      }
    }

    async function interceptGuildAction(event) {
      const control = event.target && typeof event.target.closest === 'function'
        ? event.target.closest('[data-guild-action]')
        : null;
      if (!control) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      try {
        await handleGuildAction(control.dataset.guildAction, control.dataset);
      } catch (error) {
        setStatus(walletStatus, error.message, 'error');
      }
    }

    function setStatus(element, text, kind = '') {
      element.className = `status ${kind}`.trim();
      element.textContent = text;
    }

    function escapeHtml(value) {
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function clearInteractiveChoiceTimer() {
      if (interactiveChoiceTimer) {
        window.clearInterval(interactiveChoiceTimer);
        interactiveChoiceTimer = null;
      }
      if (interactiveChoiceExpireTimer) {
        window.clearTimeout(interactiveChoiceExpireTimer);
        interactiveChoiceExpireTimer = null;
      }
    }

    function startInteractiveChoiceTimer(node, onExpire, delayMs = 0) {
      clearInteractiveChoiceTimer();
      const startAt = Date.now() + delayMs;
      const endAt = startAt + 5000;
      if (node) {
        node.textContent = '5 c';
      }
      interactiveChoiceTimer = window.setInterval(() => {
        const now = Date.now();
        if (now < startAt) {
          return;
        }
        const remaining = Math.max(0, Math.ceil((endAt - now) / 1000));
        if (node) {
          node.textContent = `${remaining} c`;
        }
      }, 120);
      interactiveChoiceExpireTimer = window.setTimeout(() => {
        clearInteractiveChoiceTimer();
        if (typeof onExpire === 'function') {
          onExpire();
        }
      }, delayMs + 5000);
    }

    function clearBattleAutostartTimer() {
      if (battleAutostartTimer) {
        window.clearTimeout(battleAutostartTimer);
        battleAutostartTimer = null;
      }
    }

    function actionRuleMeta(actionKey) {
      const liveResult = state.lastResult || {};
      const activeAbility = liveResult.interactive_active_ability || {};
      return {
        burst: {ruLabel: 'Натиск', beats: 'Блок', losesTo: 'Блок'},
        guard: {ruLabel: 'Блок', beats: 'Натиск', losesTo: 'Натиск'},
        ability: {ruLabel: activeAbility.name || 'Способность', beats: 'Тайминг', losesTo: 'Кулдаун'},
      }[actionKey] || {ruLabel: 'Блок', cost: 0, beats: 'Натиск', losesTo: 'Натиск'};
    }

    function skillCounterText(card) {
      const key = card && card.skill_key;
      const mapping = {
        underdog: 'Сильнее, когда твоя карта слабее или ты проседаешь по темпу. Слабее, если ты и так доминируешь.',
        tempo: 'Сильнее после проигранного раунда и в длинных сериях. Слабее при ровном сухом размене.',
        mirror: 'Сильнее против мощной карты соперника. Слабее, когда оппонент и так слабее тебя.',
        attack_burst: 'Сильнее в агрессивных раундах и на добивании. Слабее, если матч уходит в контроль.',
        defense_lock: 'Сильнее против прямого натиска и быстрых ходов. Слабее против затяжной подготовки.',
        wildcard: 'Сильнее в рисковых раундах и при нестандартном размене. Слабее, когда бой идет слишком предсказуемо.',
        anchor: 'Сильнее в тяжёлых защитных и ровных разменах. Слабее, когда бой слишком быстрый.',
        overclock: 'Сильнее в темпе и ближе к финалу. Слабее, если матч ломается в самом начале.',
        oracle: 'Сильнее в рискованных раундах и на чтении контров. Слабее в прямолинейной драке.',
        reactor: 'Сильнее, когда твоя карта уже мощная и можно добить перевес. Слабее на слабых картах.',
      };
      return mapping[key] || 'Скилл дает ситуативный бонус в зависимости от темпа и контр-хода.';
    }

    function strategyMeta(strategyKey) {
      return {
        attack_boost: {label: 'Атакующий буст', description: 'Больше давления в атакующих раундах.'},
        defense_boost: {label: 'Защитный буст', description: 'Надежнее держит контр-ход и защиту.'},
        energy_boost: {label: 'Энергобуст', description: 'Лучше раскрывает способности домена.'},
        aggressive: {label: 'Агрессия', description: 'Больше натиска и давления по раундам.'},
        balanced: {label: 'Баланс', description: 'Ровная стратегия без явных дыр.'},
        tricky: {label: 'Хитрость', description: 'Больше контров и неожиданных разменов.'},
      }[strategyKey] || {label: 'Баланс', description: 'Ровная стратегия без явных дыр.'};
    }

    function profileAbilityMeta(key) {
      return {
        burst: {label: 'Натиск', description: 'Любимый ход через давление и силовой размен.'},
        guard: {label: 'Блок', description: 'Опора на защиту, контр-ход и удержание темпа.'},
        ability: {label: 'Способность', description: 'Ставка на доменную ульту и тайминг.'},
      }[key] || {label: 'Не выбрано', description: 'Выбери любимое действие в профиле.'};
    }

    function profilePlayStyleMeta(key) {
      return {
        aggressive: {label: 'Агрессивный', description: 'Давление, риск и раннее добивание.'},
        balanced: {label: 'Сбалансированный', description: 'Ровная игра без перекоса в одну ось.'},
        control: {label: 'Контроль', description: 'Игра от чтения соперника и затяжных разменов.'},
        tempo: {label: 'Темп', description: 'Ценность тайминга и сильных средних раундов.'},
        fortune: {label: 'Удача', description: 'Ставка на fortune, rare turns и swing-моменты.'},
        trickster: {label: 'Хитрость', description: 'Обманки, контры и неожиданные решения.'},
      }[key] || {label: 'Не выбран', description: 'Задай свой стиль игры в профиле.'};
    }

    function profileRoleMeta(key) {
      return {
        tank: 'Tank',
        damage: 'Damage',
        control: 'Control',
        support: 'Support',
        trickster: 'Trickster',
        guardian: 'Guardian',
        fortune: 'Fortune',
        combo: 'Combo',
        disruptor: 'Disruptor',
        sniper: 'Sniper',
      }[key] || 'Не выбрана';
    }

    function renderCompactPlayerCard(player, options = {}) {
      if (!player) return '';
      const cosmetics = player.equipped_cosmetics || {};
      const arenaKey = ((cosmetics.arena || {}).key) || 'arena_stock_grid';
      const backKey = ((cosmetics.cardback || {}).key) || 'cardback_stock_plain';
      const frameKey = ((cosmetics.frame || {}).key) || '';
      const guildKey = player.profile_banner_key || ((cosmetics.guild || {}).key) || '';
      const emoji = cosmeticEmojiSymbol(cosmetics);
      const frameAsset = cosmeticAssetUrl('frame', frameKey);
      const domain = player.current_domain || player.domain || '';
      const domainLabel = domain ? `${domain}.ton` : 'без домена';
      const actionsHtml = options.actionsHtml || '';
      const extraClass = options.className ? ` ${options.className}` : '';
      return `
        <article class="player-card${extraClass}" data-open-profile-wallet="${escapeHtml(player.wallet)}" style="background:${giftArenaSurface(arenaKey, emoji)};">
          ${guildKey ? `<div class="player-card-banner" style="background:${giftGuildSurface(guildKey, '')};"></div>` : ''}
          <div class="player-card-domain">${escapeHtml(domainLabel)}</div>
          <div class="player-card-back" style="background:${giftCardbackSurface(backKey, emoji)};">
            ${frameAsset ? `<img class="player-card-frame" src="${frameAsset}" alt="">` : ''}
          </div>
          <div class="player-card-content">
            <div class="player-card-title">${escapeHtml(player.display_name || shortAddress(player.wallet))}</div>
            <div class="player-card-meta">${escapeHtml(player.profile_title || 'Без титула')} • рейтинг ${Number(player.rating || 1000)} • матчей ${Number(player.games_played || 0)}</div>
          </div>
          ${actionsHtml ? `<div class="player-card-actions">${actionsHtml}</div>` : ''}
        </article>
      `;
    }

    function formatDateTime(value) {
      if (!value) return '-';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      try {
        return new Intl.DateTimeFormat('ru-RU', {
          day: '2-digit',
          month: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
        }).format(date);
      } catch (_) {
        return date.toLocaleString('ru-RU');
      }
    }

    function duelReferenceForPlayer(player) {
      const domain = player && (player.current_domain || player.domain);
      if (domain) return `${domain}.ton`;
      return (player && (player.display_name || player.wallet)) || '';
    }

    function compactActionButton(label, dataset = {}, secondary = true) {
      const attrs = Object.entries(dataset || {}).map(([key, value]) => {
        if (value === undefined || value === null || value === '') return '';
        return `data-${key}="${escapeHtml(String(value))}"`;
      }).filter(Boolean).join(' ');
      return `<button type="button" class="${secondary ? 'secondary' : ''}" ${attrs}>${escapeHtml(label)}</button>`;
    }

    function renderCompactPlayerGrid(items, actionBuilder, emptyMarkup) {
      const list = Array.isArray(items) ? items : [];
      if (!list.length) return emptyMarkup;
      return list.map((item) => renderCompactPlayerCard(item, { actionsHtml: actionBuilder ? actionBuilder(item) : '' })).join('');
    }

    function closePublicProfile() {
      state.publicProfile = null;
      if (publicProfileBackdrop) publicProfileBackdrop.classList.remove('open');
      if (publicProfileContent) publicProfileContent.innerHTML = '';
    }

    function renderPublicProfileModal() {
      if (!publicProfileContent || !state.publicProfile) return;
      const profile = state.publicProfile;
      const cosmetics = profile.equipped_cosmetics || {};
      const arenaKey = ((cosmetics.arena || {}).key) || 'arena_stock_grid';
      const backKey = ((cosmetics.cardback || {}).key) || 'cardback_stock_plain';
      const frameKey = ((cosmetics.frame || {}).key) || '';
      const guildKey = profile.profile_banner_key || ((cosmetics.guild || {}).key) || '';
      const emoji = cosmeticEmojiSymbol(cosmetics);
      const frameAsset = cosmeticAssetUrl('frame', frameKey);
      const analytics = profile.analytics || {};
      const actionRates = analytics.action_rates || {};
      const rewardDeck = profile.deck_summary || null;
      const recentMatches = Array.isArray(profile.recent_matches) ? profile.recent_matches : [];
      const favoriteDomain = profile.favorite_domain || profile.best_domain || profile.current_domain || '';
      const cosmeticsCards = [
        { label: 'Рамка', key: frameKey, type: 'frame', preview: frameAsset ? `<img src="${frameAsset}" alt="" style="position:absolute; inset:0; width:100%; height:100%; object-fit:contain;">` : '<div class="tiny">Не выбрана</div>' },
        { label: 'Рубашка', key: backKey, type: 'cardback', preview: `<div style="position:absolute; inset:0; background:${giftCardbackSurface(backKey, emoji)};"></div>` },
        { label: 'Арена', key: arenaKey, type: 'arena', preview: `<div style="position:absolute; inset:0; background:${giftArenaSurface(arenaKey, emoji)};"></div>` },
        { label: 'Баннер', key: guildKey, type: 'guild', preview: guildKey ? `<div style="position:absolute; inset:0; background:${giftGuildSurface(guildKey, '')};"></div>` : '<div class="tiny">Не выбран</div>' },
      ];
      publicProfileContent.innerHTML = `
        <div class="actions" style="justify-content:space-between; align-items:center; margin-bottom:14px;">
          <strong style="font-size:24px;">Полный профиль</strong>
          <button type="button" class="secondary" id="public-profile-close-btn">Закрыть</button>
        </div>
        <div class="user-item" style="background:${giftArenaSurface(arenaKey, emoji)};">
          <div class="public-profile-hero">
            ${guildKey ? `<div class="public-profile-banner" style="background:${giftGuildSurface(guildKey, '')};"></div>` : ''}
            <div class="public-profile-domain">${escapeHtml(profile.current_domain ? `${profile.current_domain}.ton` : 'без домена')}</div>
            <div class="public-profile-cardback" style="background:${giftCardbackSurface(backKey, emoji)};"></div>
            ${frameAsset ? `<img class="public-profile-frame" src="${frameAsset}" alt="">` : ''}
            <div class="public-profile-copy">
              <div style="font-size:36px; line-height:1; font-weight:900;">${escapeHtml(profile.display_name || shortAddress(profile.wallet))}</div>
              <div class="summary-chip-row">
                <span class="summary-chip">${escapeHtml(profile.profile_title || 'Без титула')}</span>
                <span class="summary-chip">Рейтинг ${Number(profile.rating || 1000)}</span>
                <span class="summary-chip">Матчей ${Number(profile.games_played || 0)}</span>
                <span class="summary-chip">Сезон ${Number(profile.season_level || 1)}</span>
                <span class="summary-chip">Любимый домен: ${escapeHtml(favoriteDomain ? `${favoriteDomain}.ton` : 'не выбран')}</span>
              </div>
              <div class="tiny">${escapeHtml(profile.bio || 'Описание профиля пока пустое.')}</div>
              <div class="summary-chip-row">
                <span class="summary-chip">Стиль: ${escapeHtml(profilePlayStyleMeta(profile.play_style || '').label)}</span>
                <span class="summary-chip">Любимый ход: ${escapeHtml(profileAbilityMeta(profile.favorite_ability || '').label)}</span>
                <span class="summary-chip">Стратегия: ${escapeHtml(strategyMeta(profile.favorite_strategy || '').label)}</span>
                <span class="summary-chip">Роль: ${escapeHtml(profileRoleMeta(profile.favorite_role || ''))}</span>
              </div>
              <div class="summary-chip-row">
                <span class="summary-chip">Натиск ${(Number(actionRates.burst || 0) * 100).toFixed(0)}%</span>
                <span class="summary-chip">Блок ${(Number(actionRates.guard || 0) * 100).toFixed(0)}%</span>
                <span class="summary-chip">Способность ${(Number(actionRates.ability || 0) * 100).toFixed(0)}%</span>
                <span class="summary-chip">Winrate ${(Number(analytics.win_rate || 0) * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>
        </div>
        ${profile.guild ? `<div class="user-item"><strong>Клан</strong><div class="tiny">${escapeHtml(profile.guild.name)} • роль ${escapeHtml(profile.guild.role)}</div></div>` : ''}
        ${rewardDeck ? `<div class="user-item"><strong>Текущая колода</strong><div class="tiny">Пул: ${Number(rewardDeck.discipline_pool || 0)} • Счёт колоды: ${Number(rewardDeck.total_score || 0)} • Синергии: ${(rewardDeck.synergies && rewardDeck.synergies.labels && rewardDeck.synergies.labels.length) ? escapeHtml(rewardDeck.synergies.labels.join(' • ')) : 'нет'}</div></div>` : ''}
        <div class="user-item">
          <strong>Косметика</strong>
          <div class="public-profile-cosmetics-grid">
            ${cosmeticsCards.map((item) => `
              <article class="public-profile-cosmetic">
                <strong>${escapeHtml(item.label)}</strong>
                <div class="public-profile-cosmetic-preview">${item.preview}</div>
                <div class="tiny">${escapeHtml(item.key || 'не выбрано')}</div>
              </article>
            `).join('')}
          </div>
        </div>
        <div class="user-item">
          <strong>История рейтинговых матчей</strong>
          <div class="public-profile-match-list">
            ${recentMatches.length ? recentMatches.map((item) => `
              <article class="public-profile-match">
                <div class="team-line"><strong>${escapeHtml((item.domain || '----') + '.ton')}</strong><strong>${escapeHtml(String(item.player_score || 0))}:${escapeHtml(String(item.opponent_score || 0))}</strong></div>
                <div class="tiny">Против ${escapeHtml((item.opponent_domain || '----') + '.ton')} • ${escapeHtml(item.result || '-')} • рейтинг ${escapeHtml(String(item.rating_before || 0))} → ${escapeHtml(String(item.rating_after || 0))}</div>
                <div class="tiny">${escapeHtml(formatDateTime(item.created_at))}</div>
              </article>
            `).join('') : '<div class="tiny">Рейтинговых матчей пока нет.</div>'}
          </div>
        </div>
      `;
      const closeBtn = document.getElementById('public-profile-close-btn');
      if (closeBtn) bindFunctionalControl(closeBtn, closePublicProfile);
      if (publicProfileBackdrop) publicProfileBackdrop.classList.add('open');
    }

    async function openPublicProfile(wallet) {
      if (!wallet) return;
      const data = await api(`/api/player/public/${encodeURIComponent(wallet)}${state.wallet ? `?viewer=${encodeURIComponent(state.wallet)}` : ''}`);
      state.publicProfile = data.player || null;
      renderPublicProfileModal();
    }

    async function interceptPublicProfileAction(event) {
      const trigger = event.target.closest('[data-open-profile-wallet]');
      if (!trigger) return;
      if (event.target.closest('button, select, input, textarea, label[for], [role="button"]')) return;
      const wallet = trigger.dataset.openProfileWallet || '';
      if (!wallet) return;
      event.preventDefault();
      await openPublicProfile(wallet);
    }

    function packTypeMeta(packType) {
      return (state.packTypes || []).find((item) => item.key === packType) || null;
    }

    function packCostText(costs) {
      const entries = Object.entries(costs || {}).filter(([, value]) => Number(value || 0) > 0);
      if (!entries.length) return 'free';
      return entries.map(([key, value]) => {
        const label = key === 'pack_shards'
          ? 'осколка'
          : (key === 'rare_tokens'
            ? 'редкий токен'
            : (key === 'lucky_tokens'
              ? 'lucky-токен'
              : (key === 'cosmetic_packs' ? 'косметический пак' : key)));
        return `${value} ${label}`;
      }).join(' + ');
    }

    function canAffordPack(costs, rewards) {
      const balances = rewards || {};
      return Object.entries(costs || {}).every(([key, value]) => Number(balances[key] || 0) >= Number(value || 0));
    }

    function renderPackEconomy() {
      const rewards = state.playerProfile && state.playerProfile.rewards ? state.playerProfile.rewards : null;
      if (!rewards) {
        packRewardsSummary.textContent = 'Подключи кошелёк и выбери домен, чтобы открывать наградные паки.';
        packSeasonSummary.textContent = 'Сезон: -';
        claimDailyRewardBtn.disabled = true;
        claimQuestRewardBtn.disabled = true;
        document.querySelectorAll('.reward-pack-btn').forEach((button) => {
          button.disabled = true;
        });
        return;
      }
      const seasonTarget = Number(rewards.season_target || (Number(rewards.season_level || 1) * 16));
      packRewardsSummary.textContent = `Баланс: ${rewards.pack_shards || 0} осколков • ${rewards.rare_tokens || 0} редких токенов • ${rewards.lucky_tokens || 0} lucky-токенов • ${rewards.cosmetic_packs || 0} косметических паков`;
      packSeasonSummary.textContent = `Сезон ${rewards.season_level || 1} • ${rewards.season_points || 0}/${seasonTarget} очков • пропуск ${rewards.premium_pass_active ? 'premium' : 'free'} • квест ${rewards.quest_ready ? 'готов' : `до цели ${Math.max(0, Number(rewards.next_quest_target || 0) - Number(rewards.wins_for_quest || 0))} побед`}`;
      claimDailyRewardBtn.disabled = !(state.wallet && rewards.daily_available);
      claimQuestRewardBtn.disabled = !(state.wallet && rewards.quest_ready);
      document.querySelectorAll('.reward-pack-btn').forEach((button) => {
        const meta = packTypeMeta(button.dataset.rewardPack);
        const costs = (meta && meta.costs) || {};
        button.textContent = `${meta ? meta.label : button.dataset.rewardPack} за ${packCostText(costs)}`;
        button.disabled = !(state.wallet && state.selectedDomain && canAffordPack(costs, rewards));
      });
    }

    function syncSelectedPackVisuals() {
      if (!packShowcase) return;
      packShowcase.classList.remove('pack-type-common', 'pack-type-rare', 'pack-type-epic', 'pack-type-lucky');
      packShowcase.classList.add(`pack-type-${state.selectedPackType || 'common'}`);
      const meta = packTypeMeta(state.selectedPackType || 'common');
      if (packCounter) {
        packCounter.style.display = meta ? 'inline-flex' : 'none';
        packCounter.textContent = meta ? meta.label : '';
      }
    }

    function renderPackTypePicker() {
      if (!packTypePicker) return;
      const items = (state.packTypes || []).filter((item) => ['common', 'rare', 'epic', 'lucky'].includes(item.key));
      if (!items.length) {
        packTypePicker.innerHTML = '';
        syncSelectedPackVisuals();
        return;
      }
      packTypePicker.innerHTML = items.map((item) => {
        const active = state.selectedPackType === item.key;
        const tone = item.key === 'common' ? 'rgba(69, 215, 255, 0.16)'
          : item.key === 'rare' ? 'rgba(83, 246, 184, 0.16)'
          : item.key === 'epic' ? 'rgba(188, 126, 255, 0.18)'
          : 'rgba(255, 211, 110, 0.18)';
        const border = item.key === 'common' ? 'rgba(69, 215, 255, 0.34)'
          : item.key === 'rare' ? 'rgba(83, 246, 184, 0.34)'
          : item.key === 'epic' ? 'rgba(188, 126, 255, 0.34)'
          : 'rgba(255, 211, 110, 0.36)';
        return `<button type="button" class="${active ? '' : 'secondary'}" data-pack-type="${item.key}" style="background:${tone}; border-color:${border};">${item.label}</button>`;
      }).join('');
      packTypePicker.querySelectorAll('[data-pack-type]').forEach((button) => {
        button.addEventListener('click', () => {
          state.selectedPackType = button.dataset.packType || 'common';
          renderPackTypePicker();
          updateButtons();
        });
      });
      syncSelectedPackVisuals();
    }

    function updatePreviousDeckRestoreButton() {
      if (!packRestoreActions || !restorePreviousDeckBtn) return;
      const visible = Boolean(state.canRestorePreviousDeck && state.wallet && state.selectedDomain);
      packRestoreActions.style.display = visible ? 'flex' : 'none';
      restorePreviousDeckBtn.disabled = !visible;
    }

    function renderRewardsPanels() {
      const rewards = state.playerProfile && state.playerProfile.rewards ? state.playerProfile.rewards : null;
      const synergies = state.playerProfile && state.playerProfile.synergies ? state.playerProfile.synergies : null;
      const seasonTasks = rewards && Array.isArray(rewards.season_tasks) ? rewards.season_tasks : [];
      const content = rewards ? `
        <div class="user-item">
          <strong>Награды и сезон</strong>
          <div class="tiny">Осколки: ${rewards.pack_shards || 0} • Редкие токены: ${rewards.rare_tokens || 0} • Lucky-токены: ${rewards.lucky_tokens || 0}</div>
          <div class="tiny">Сезон: ур. ${rewards.season_level || 1} • ${rewards.season_points || 0}/${rewards.season_target || 16} очков • ${rewards.premium_pass_active ? 'премиум активен' : 'free-трек'}</div>
          <div class="tiny">Дейлик: ${rewards.daily_available ? 'готов' : 'получен'} • Квест: ${rewards.quest_ready ? 'готов' : `до цели ${Math.max(0, Number(rewards.next_quest_target || 0) - Number(rewards.wins_for_quest || 0))} побед`}</div>
          <div class="tiny">Задания пропуска: ${seasonTasks.length ? seasonTasks.map((item) => `${item.label} ${item.progress}/${item.target}${item.claimable ? ' • можно забрать' : (item.claimed ? ' • забрано' : '')}`).join(' • ') : 'нет'}</div>
          <div class="tiny">Синергии: ${synergies && synergies.labels && synergies.labels.length ? synergies.labels.join(' • ') : 'нет'}</div>
          <div class="tiny">Косметика: ${Array.isArray(rewards.cosmetics) && rewards.cosmetics.length ? rewards.cosmetics.map((item) => item.name).join(' • ') : 'ещё не открыта'}</div>
        </div>
      ` : '<div class="user-item muted">Подключи кошелёк, чтобы видеть награды и сезонный прогресс.</div>';
      if (profileRewardsPanel) profileRewardsPanel.innerHTML = content;
      if (mobileRewardsPanel) mobileRewardsPanel.innerHTML = content;
    }

    function renderSocialGuildBadges() {
      const navProfile = document.getElementById('nav-profile');
      if (!navProfile) return;
      const social = state.socialData || {};
      const guilds = state.guildData || {};
      const count =
        Number((social.incoming_requests || []).length || 0) +
        Number((social.incoming_duel_invites || []).length || 0) +
        Number((guilds.pending_invites || []).length || 0) +
        Number((((guilds.current_guild || {}).pending_requests) || []).length || 0);
      navProfile.innerHTML = count > 0 ? `Профиль <span class="nav-badge">${count}</span>` : 'Профиль';
    }

    function renderTutorialPanel() {
      if (!tutorialPanel) return;
      const tutorial = state.tutorialData || (state.playerProfile && state.playerProfile.tutorial) || null;
      if (!state.wallet || !tutorial) {
        tutorialPanel.innerHTML = '';
        return;
      }
      if (tutorial.completed) {
        tutorialPanel.innerHTML = `
          <div class="user-item">
            <strong>Боевой туториал завершён</strong>
            <div class="tiny">Побед: ${tutorial.wins || 1} • попыток: ${tutorial.attempts || 1}</div>
            <div class="tiny">Первый успех уже засчитан. Можно идти в обычный или рейтинговый режим.</div>
            <div class="actions" style="margin-top:10px;">
              <button id="tutorial-go-casual-btn">Обычный бой</button>
              <button class="secondary" id="tutorial-go-ranked-btn">Рейтинг</button>
            </div>
          </div>
        `;
        const casualBtn = document.getElementById('tutorial-go-casual-btn');
        const rankedBtn = document.getElementById('tutorial-go-ranked-btn');
        if (casualBtn) bindFunctionalControl(casualBtn, () => launchRecommendedMode('casual'));
        if (rankedBtn) bindFunctionalControl(rankedBtn, () => launchRecommendedMode('ranked'));
        return;
      }
      tutorialPanel.innerHTML = `
        <div class="user-item">
          <strong>Интерактивный туториал боя</strong>
          <div class="tiny">Покажет порядок колоды, тактическую карту и разницу действий прямо в бою. Первый матч настроен так, чтобы при следовании подсказкам ты почти наверняка выиграл.</div>
          <div class="tiny">Статус: ${tutorial.skipped ? 'пропущен' : (tutorial.started ? 'начат' : 'не начат')} • попыток: ${tutorial.attempts || 0}</div>
          <div class="actions" style="margin-top:10px;">
            <button id="start-tutorial-btn"${!(state.wallet && state.selectedDomain && state.cards.length) ? ' disabled' : ''}>${tutorial.started ? 'Пройти заново' : 'Начать туториал'}</button>
            <button class="secondary" id="skip-tutorial-btn">Пропустить</button>
          </div>
        </div>
      `;
      const startBtn = document.getElementById('start-tutorial-btn');
      const skipBtn = document.getElementById('skip-tutorial-btn');
      if (startBtn) bindFunctionalControl(startBtn, startTutorialBattle);
      if (skipBtn) bindFunctionalControl(skipBtn, skipTutorialBattle);
    }

    function tutorialActionLegendHtml(tutorial, roundIndex, liveResult) {
      if (!tutorial || !tutorial.active) return '';
      const recommended = String(((tutorial.recommended_actions || [])[roundIndex]) || '').toLowerCase();
      const activeAbility = (liveResult && liveResult.interactive_active_ability) || {};
      const items = [
        { key: 'guard', label: 'Блок', cost: 1 },
        { key: 'burst', label: 'Натиск', cost: 2 },
        { key: 'ability', label: activeAbility.name || 'Способность', cost: Number(activeAbility.cost || 3) || 3 },
      ];
      return `
        <div class="tutorial-action-legend">
          ${items.map((item) => `
            <span class="tutorial-action-chip ${recommended === item.key ? 'recommended' : ''}">
              <strong>${item.label}</strong>
              <span>${item.cost} маны</span>
            </span>
          `).join('')}
        </div>
      `;
    }

    function applyTutorialVisualFocus(result) {
      const tutorial = result && result.tutorial;
      if (!tutorial || !tutorial.active) return;
      const roundIndex = Number(result.interactive_round_index || 0);
      const currentTip = tutorial.current_tip || ((tutorial.tips || [])[Math.min(roundIndex, Math.max((tutorial.tips || []).length - 1, 0))]);
      if (!currentTip) return;
      const focus = currentTip.focus || '';
      const recommended = ((tutorial.recommended_actions || [])[roundIndex]) || '';
      const activePlayerSlot = Number((result.player_cards || [])[Math.min(roundIndex, Math.max((result.player_cards || []).length - 1, 0))]?.slot || 0);
      const featuredSlot = Number(result.player_featured_card?.slot || result.selected_slot || 0);
      if (focus === 'order' && activePlayerSlot) {
        const slotCard = battleResult.querySelector(`.arena-rail.player .arena-slot-card[data-slot="${activePlayerSlot}"]`);
        if (slotCard) slotCard.classList.add('tutorial-focus');
        const lanePath = battleResult.querySelectorAll('.arena-route-path')[Math.max(0, roundIndex)];
        if (lanePath) lanePath.classList.add('tutorial-focus');
      }
      if (focus === 'featured' && featuredSlot) {
        const featuredCard = battleResult.querySelector(`.arena-rail.player .arena-slot-card[data-slot="${featuredSlot}"]`);
        if (featuredCard) featuredCard.classList.add('tutorial-focus');
      }
      if ((focus === 'action' || focus === 'featured') && recommended) {
        const actionBtn = battleResult.querySelector(`.interactive-action-btn[data-action-key="${recommended}"]`);
        if (actionBtn) actionBtn.classList.add('tutorial-focus');
      }
      if (recommended === 'burst' || recommended === 'guard') {
        const manaPill = battleResult.querySelector('.arena-resource-pill.mana');
        if (manaPill) manaPill.classList.add('tutorial-focus');
      }
      if (recommended === 'ability') {
        const abilityPill = battleResult.querySelector('.arena-resource-pill.ability');
        const cooldownPill = battleResult.querySelector('.arena-resource-pill.cooldown');
        if (abilityPill) abilityPill.classList.add('tutorial-focus');
        if (cooldownPill) cooldownPill.classList.add('tutorial-focus');
      }
    }

    function renderIdentityPanel() {
      if (!profileIdentityPanel) return;
      const profile = state.socialData && state.socialData.profile;
      if (!state.wallet || !profile) {
        profileIdentityPanel.innerHTML = '<div class="user-item muted">Подключи кошелёк, чтобы настроить ник и профиль.</div>';
        return;
      }
      const rewards = (state.playerProfile && state.playerProfile.rewards) || {};
      const cosmetics = Array.isArray(rewards.cosmetics) ? rewards.cosmetics : [];
      const equipped = rewards.equipped_cosmetics || {};
      const guildItems = cosmetics.filter((item) => item.type === 'guild');
      const profileBannerKey = profile.profile_banner_key || ((equipped.guild || {}).key) || '';
      const currentDomain = state.selectedDomain || profile.domain || (state.playerProfile && state.playerProfile.current_domain) || '';
      const analytics = profile.analytics || {};
      const actionRates = analytics.action_rates || {};
      const behaviorCards = [
        `Winrate ${(Number(analytics.win_rate || 0) * 100).toFixed(0)}%`,
        `Натиск ${(Number(actionRates.burst || 0) * 100).toFixed(0)}%`,
        `Блок ${(Number(actionRates.guard || 0) * 100).toFixed(0)}%`,
        `Способность ${(Number(actionRates.ability || 0) * 100).toFixed(0)}%`,
      ].map((item) => `<span class="summary-chip">${escapeHtml(item)}</span>`).join('');
      const currentTab = state.profileTab === 'preferences' ? 'preferences' : 'overview';
      const profileSummaryChips = [
        profile.profile_title ? `Титул: ${profile.profile_title}` : 'Титул не задан',
        currentDomain ? `Домен: ${currentDomain}.ton` : 'Домен не выбран',
        `Способность: ${profileAbilityMeta(profile.favorite_ability || '').label}`,
        `Стиль: ${profilePlayStyleMeta(profile.play_style || '').label}`,
        `Стратегия: ${strategyMeta(profile.favorite_strategy || '').label}`,
        `Роль: ${profileRoleMeta(profile.favorite_role || '')}`,
      ].map((item) => `<span class="summary-chip">${escapeHtml(item)}</span>`).join('');
      const overviewCard = renderCompactPlayerCard(
        {
          ...profile,
          wallet: state.wallet,
          current_domain: currentDomain || profile.current_domain || profile.domain || '',
          equipped_cosmetics: equipped,
          selected_gift: profile.selected_gift || null,
          profile_banner_key: profileBannerKey,
          display_name: profile.display_name || profile.nickname || shortAddress(state.wallet),
        },
        {
          className: 'profile-preview',
          actionsHtml: '',
        },
      );
      profileIdentityPanel.innerHTML = `
        <div class="user-item">
          <strong>Профиль игрока</strong>
          <div class="actions" style="margin-top:12px; gap:10px; flex-wrap:wrap;">
            <button type="button" class="${currentTab === 'overview' ? '' : 'secondary'} profile-tab-btn" data-profile-tab="overview">Обзор</button>
            <button type="button" class="${currentTab === 'preferences' ? '' : 'secondary'} profile-tab-btn" data-profile-tab="preferences">Предпочтения</button>
          </div>
          ${currentTab === 'overview' ? `
            <div style="margin-top:14px; display:grid; gap:14px;">
              ${overviewCard}
              <div class="row" style="margin-top:4px;">
                <input id="profile-nickname-input" value="${escapeHtml(profile.nickname || '')}" maxlength="24" placeholder="Ник / имя для матчей">
                <input id="profile-title-input" value="${escapeHtml(profile.profile_title || '')}" maxlength="40" placeholder="Титул профиля">
              </div>
              <div class="row">
                <input id="profile-bio-input" value="${escapeHtml(profile.bio || '')}" maxlength="160" placeholder="Короткое описание профиля">
              </div>
            </div>
          ` : ''}
          ${currentTab === 'preferences' ? `
            <div style="margin-top:14px; display:grid; gap:14px;">
              <div class="summary-chip-row">${profileSummaryChips}</div>
              <div class="summary-chip-row">${behaviorCards}</div>
              <div class="row">
                <select id="profile-banner-select">
                  <option value="">Профильный баннер из боя</option>
                  ${guildItems.map((item) => `<option value="${escapeHtml(item.key)}"${profileBannerKey === item.key ? ' selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}
                </select>
              </div>
              <div class="tiny">Любимая способность, стиль игры, стратегия и роль теперь определяются автоматически по истории матчей игрока. Здесь настраиваются только публичные элементы профиля.</div>
              <div class="summary-chip-row">
                <span class="summary-chip">${escapeHtml(profileAbilityMeta(profile.favorite_ability || '').description)}</span>
                <span class="summary-chip">${escapeHtml(profilePlayStyleMeta(profile.play_style || '').description)}</span>
                <span class="summary-chip">${escapeHtml(strategyMeta(profile.favorite_strategy || 'balanced').description)}</span>
                <span class="summary-chip">${escapeHtml(profileRoleMeta(profile.favorite_role || ''))}</span>
              </div>
            </div>
          ` : ''}
          <div class="actions" style="margin-top:14px;">
            <button id="save-profile-btn">Сохранить профиль</button>
            <button class="secondary" id="share-last-result-btn"${state.lastResult ? '' : ' disabled'}>Поделиться последним матчем</button>
          </div>
        </div>
      `;
      profileIdentityPanel.querySelectorAll('.profile-tab-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          state.profileTab = btn.dataset.profileTab || 'overview';
          renderIdentityPanel();
        });
      });
      const saveBtn = document.getElementById('save-profile-btn');
      const shareBtn = document.getElementById('share-last-result-btn');
      if (saveBtn) bindFunctionalControl(saveBtn, saveProfileIdentity);
      if (shareBtn) bindFunctionalControl(shareBtn, shareLastResultToTelegram);
    }

    function renderSocialPanel() {
      if (!socialPanel) return;
      const social = state.socialData;
      if (!state.wallet || !social) {
        socialPanel.innerHTML = '<div class="user-item muted">Подключи кошелёк, чтобы увидеть друзей, заявки и лобби.</div>';
        renderSocialGuildBadges();
        return;
      }
      const friends = renderCompactPlayerGrid(
        social.friends || [],
        (item) => [
          compactActionButton('Дуэль', {'social-action': 'duel', reference: duelReferenceForPlayer(item)}),
          compactActionButton('Убрать', {'social-action': 'remove-friend', reference: item.wallet}),
          compactActionButton('Блок', {'social-action': 'block', reference: item.wallet}),
        ].join(''),
        '<div class="user-item muted">Друзей пока нет.</div>',
      );
      const incoming = renderCompactPlayerGrid(
        social.incoming_requests || [],
        (item) => [
          compactActionButton('Принять', {'social-action': 'accept-friend', 'request-id': item.id}, false),
          compactActionButton('Отклонить', {'social-action': 'decline-friend', 'request-id': item.id}),
        ].join(''),
        '<div class="user-item muted">Новых заявок нет.</div>',
      );
      const incomingDuels = (social.incoming_duel_invites || []).map((item) => renderCompactPlayerCard({
        wallet: item.inviter_wallet,
        display_name: item.inviter_name || shortAddress(item.inviter_wallet),
        current_domain: item.inviter_domain || '',
        rating: item.inviter_rating || 1000,
        games_played: item.inviter_games_played || 0,
        profile_title: `Вызов • ${Number(item.timeout_seconds || 30)} сек`,
        bio: `${item.inviter_domain || '---'}.ton vs ${item.invitee_domain || '---'}.ton`,
        equipped_cosmetics: item.inviter_equipped_cosmetics || {},
        selected_gift: item.inviter_selected_gift || null,
        profile_banner_key: item.inviter_profile_banner_key || '',
        play_style: item.inviter_play_style || '',
        favorite_ability: item.inviter_favorite_ability || '',
        favorite_role: item.inviter_favorite_role || '',
      }, {
        actionsHtml: [
          compactActionButton('Принять', {'social-action': 'accept-duel', 'invite-id': item.id}, false),
          compactActionButton('Отклонить', {'social-action': 'decline-duel', 'invite-id': item.id}),
        ].join(''),
      })).join('') || '<div class="user-item muted">Входящих дуэлей нет.</div>';
      const outgoingDuels = (social.outgoing_duel_invites || []).map((item) => renderCompactPlayerCard({
        wallet: item.invitee_wallet,
        display_name: item.invitee_name || shortAddress(item.invitee_wallet),
        current_domain: item.invitee_domain || '',
        rating: item.invitee_rating || 1000,
        games_played: item.invitee_games_played || 0,
        profile_title: 'Исходящая дуэль',
        bio: `${item.inviter_domain || '---'}.ton vs ${item.invitee_domain || '---'}.ton`,
        equipped_cosmetics: item.invitee_equipped_cosmetics || {},
        selected_gift: item.invitee_selected_gift || null,
        profile_banner_key: item.invitee_profile_banner_key || '',
        play_style: item.invitee_play_style || '',
        favorite_ability: item.invitee_favorite_ability || '',
        favorite_role: item.invitee_favorite_role || '',
      }, {
        actionsHtml: compactActionButton('Проверить статус', {'social-action': 'open-duel', 'invite-id': item.id}),
      })).join('') || '<div class="user-item muted">Исходящих дуэлей нет.</div>';
      const suggested = renderCompactPlayerGrid(
        (social.suggested_players || []).slice(0, 6),
        (item) => [
          compactActionButton('В друзья', {'social-action': 'request-friend', reference: item.wallet}),
          compactActionButton('Дуэль', {'social-action': 'duel', reference: duelReferenceForPlayer(item)}),
        ].join(''),
        '<div class="user-item muted">Рекомендации появятся, когда в игре будет больше активных игроков.</div>',
      );
      const lobby = (social.lobby_messages || []).map((item) => `
        <div class="user-item">
          <strong>${escapeHtml(item.display_name)}</strong>
          <div class="tiny">${escapeHtml(item.message)}</div>
          <div class="actions" style="margin-top:8px;">
            <button class="secondary" data-social-action="report" data-reference="${escapeHtml(item.wallet)}" data-scope="lobby">Пожаловаться</button>
          </div>
        </div>
      `).join('') || '<div class="user-item muted">Лобби пустое.</div>';
      socialPanel.innerHTML = `
        <div class="user-item">
          <strong>Быстрые цифры</strong>
          <div class="tiny">Друзей: ${social.friend_count || 0} • Входящих: ${(social.incoming_requests || []).length} • Исходящих: ${(social.outgoing_requests || []).length}</div>
          <div class="summary-chip-row">
            <span class="summary-chip">Друзья: ${social.friend_count || 0}</span>
            <span class="summary-chip">Входящие: ${(social.incoming_requests || []).length}</span>
            <span class="summary-chip">Дуэли: ${(social.incoming_duel_invites || []).length}</span>
            <span class="summary-chip">Лобби: ${(social.lobby_messages || []).length}</span>
          </div>
        </div>
        <h4 style="margin:14px 0 8px;">Друзья</h4>
        <div class="catalog-grid">${friends}</div>
        <h4 style="margin:18px 0 8px;">Входящие заявки</h4>
        <div class="catalog-grid">${incoming}</div>
        <h4 style="margin:18px 0 8px;">Входящие дуэли</h4>
        <div class="catalog-grid">${incomingDuels}</div>
        <h4 style="margin:18px 0 8px;">Исходящие дуэли</h4>
        <div class="catalog-grid">${outgoingDuels}</div>
        <h4 style="margin:18px 0 8px;">Кого добавить</h4>
        <div class="catalog-grid">${suggested}</div>
        <h4 style="margin:18px 0 8px;">Лобби чат</h4>
        <div class="row" style="margin-bottom:10px;">
          <input id="lobby-message-input" maxlength="240" placeholder="Сообщение в общее лобби">
          <button id="send-lobby-message-btn">Отправить</button>
        </div>
        <div class="deck-list">${lobby}</div>
      `;
      const lobbyBtn = document.getElementById('send-lobby-message-btn');
      if (lobbyBtn) bindFunctionalControl(lobbyBtn, sendLobbyMessage);
      renderSocialGuildBadges();
    }

    function renderGuildPanel() {
      if (!guildPanel) return;
      const data = state.guildData;
      if (!state.wallet || !data) {
        guildPanel.innerHTML = '<div class="user-item muted">Подключи кошелёк, чтобы создать клан или вступить в существующий.</div>';
        renderSocialGuildBadges();
        return;
      }
      const current = data.current_guild;
      const invites = (data.pending_invites || []).map((item) => `
        <div class="user-item">
          <strong>${escapeHtml(item.guild_name)}</strong>
          <div class="tiny">Инвайт от ${escapeHtml(item.inviter_name)}</div>
          <div class="actions" style="margin-top:10px;">
            <button data-guild-action="accept-invite" data-invite-id="${escapeHtml(item.id)}">Вступить</button>
            <button class="secondary" data-guild-action="decline-invite" data-invite-id="${escapeHtml(item.id)}">Отклонить</button>
          </div>
        </div>
      `).join('');
      const recommended = (data.recommended_guilds || []).slice(0, 6).map((item) => `
        <div class="user-item">
          <strong>${escapeHtml(item.name)}</strong>
          <div class="tiny">${item.domain_identity ? `${escapeHtml(item.domain_identity)}.ton` : 'без доменного тега'} • участников ${item.member_count}</div>
          <div class="tiny">${escapeHtml(item.description || 'Открытый клан')}</div>
          <div class="actions" style="margin-top:10px;">
            <button class="secondary" data-guild-action="apply" data-guild-id="${escapeHtml(item.id)}">Подать заявку</button>
          </div>
        </div>
      `).join('') || '<div class="user-item muted">Открытых кланов пока нет.</div>';
      if (!current) {
        const firstRecommended = (data.recommended_guilds || [])[0];
        guildPanel.innerHTML = `
          ${firstRecommended ? `
            <div class="user-item">
              <strong>Быстрый вход в рекомендованный клан</strong>
              <div class="tiny">${escapeHtml(firstRecommended.name)} • участников ${Number(firstRecommended.member_count || 0)} • язык ${escapeHtml(firstRecommended.language || 'ru')}</div>
              <div class="tiny">${escapeHtml(firstRecommended.description || 'Открытый активный клан')}</div>
              <div class="actions" style="margin-top:10px;">
                <button data-guild-action="apply" data-guild-id="${escapeHtml(firstRecommended.id)}">Вступить в рекомендованный клан</button>
              </div>
            </div>
          ` : ''}
          <div class="user-item">
            <strong>Создать клан</strong>
            <div class="row" style="margin-top:10px;">
              <input id="guild-name-input" maxlength="40" placeholder="Название клана">
              <input id="guild-language-input" maxlength="12" value="ru" placeholder="Язык">
            </div>
            <div class="row" style="margin-top:10px;">
              <input id="guild-description-input" maxlength="220" placeholder="Описание, цели, стиль игры">
            </div>
            <div class="actions" style="margin-top:10px;">
              <button id="create-guild-btn">Создать клан</button>
            </div>
          </div>
          ${(invites || '') ? `<h4 style="margin:18px 0 8px;">Инвайты</h4><div class="catalog-grid">${invites}</div>` : ''}
          <h4 style="margin:18px 0 8px;">Рекомендованные кланы</h4>
          <div class="catalog-grid">${recommended}</div>
        `;
        const createGuildBtn = document.getElementById('create-guild-btn');
        if (createGuildBtn) bindFunctionalControl(createGuildBtn, createGuildFromUI);
        renderSocialGuildBadges();
        return;
      }
      const members = renderCompactPlayerGrid(
        current.members || [],
        (item) => [
          compactActionButton('Дуэль', {'social-action': 'duel', reference: duelReferenceForPlayer(item)}),
          (current.viewer_role === 'owner' && item.role !== 'owner')
            ? compactActionButton(
                item.role === 'officer' ? 'Снять офицера' : 'Сделать офицером',
                {
                  'guild-action': 'toggle-role',
                  'guild-id': current.id,
                  'target-wallet': item.wallet,
                  'next-role': item.role === 'officer' ? 'member' : 'officer',
                },
              )
            : '',
        ].filter(Boolean).join(''),
        '<div class="user-item muted">Состав пока пуст.</div>',
      );
      const chat = (current.chat || []).map((item) => `
        <div class="user-item">
          <strong>${escapeHtml(item.display_name)}</strong>
          <div class="tiny">${escapeHtml(item.message)}</div>
          <div class="actions" style="margin-top:8px;">
            <button class="secondary" data-social-action="report" data-reference="${escapeHtml(item.wallet)}" data-scope="guild">Пожаловаться</button>
          </div>
        </div>
      `).join('') || '<div class="user-item muted">Чат пуст.</div>';
      const announcements = (current.announcements || []).map((item) => `
        <div class="user-item">
          <strong>${escapeHtml(item.display_name)}</strong>
          <div class="tiny">${escapeHtml(item.message)}</div>
        </div>
      `).join('') || '<div class="user-item muted">Объявлений пока нет.</div>';
      const requests = renderCompactPlayerGrid(
        current.pending_requests || [],
        (item) => [
          compactActionButton('Принять', {'guild-action': 'accept-request', 'request-id': item.id}, false),
          compactActionButton('Отклонить', {'guild-action': 'decline-request', 'request-id': item.id}),
        ].join(''),
        '',
      );
      const todayHelp = (current.goals && current.goals.today_help) || [];
      const todayActionButtons = [];
      if (todayHelp.some((item) => /побед|матч|бой/i.test(item))) {
        todayActionButtons.push('<button id="guild-help-battle-btn">Играть матч</button>');
      }
      if (todayHelp.some((item) => /пак|сундук/i.test(item))) {
        todayActionButtons.push('<button class="secondary" id="guild-help-pack-btn">Открыть пак</button>');
      }
      todayActionButtons.push('<button class="secondary" id="guild-help-profile-btn">К профилю</button>');
      guildPanel.innerHTML = `
        <div class="user-item">
          <strong>${escapeHtml(current.name)}</strong>
          <div class="tiny">${current.domain_identity ? `${escapeHtml(current.domain_identity)}.ton` : 'без доменного тега'} • роль ${escapeHtml(current.viewer_role || 'member')} • участников ${current.member_count}</div>
          <div class="tiny">${escapeHtml(current.description || 'Описание не заполнено')}</div>
          <div class="tiny">Недельные победы: ${current.goals.weekly_wins}/${current.goals.weekly_win_target} • Паки: ${current.goals.weekly_packs}/${current.goals.weekly_pack_target} • Сезон: ${current.goals.season_points}</div>
          <div class="tiny">Сегодня полезно клану: ${(current.goals.today_help || []).join(' • ')}</div>
          <div class="summary-chip-row">
            <span class="summary-chip">Инвайты: ${(data.pending_invites || []).length}</span>
            <span class="summary-chip">Заявки: ${(current.pending_requests || []).length}</span>
            <span class="summary-chip">Чат: ${(current.chat || []).length}</span>
          </div>
          <div class="actions" style="margin-top:10px;">${todayActionButtons.join('')}<button class="secondary" id="guild-weekly-reward-btn"${current.goals.weekly_reward_ready ? '' : ' disabled'}>Награда недели</button></div>
        </div>
        <div class="catalog-grid" style="margin:14px 0;">
          <article class="catalog-card skill-card">
            <div class="catalog-kicker">Клановая война</div>
            <strong>Война недели</strong>
            <div class="tiny">Счёт: ${current.goals.war_score}/${current.goals.war_target}</div>
            <div class="tiny">Победы дают x4, открытые паки x3, сезонные очки тоже входят в войну.</div>
            <div class="tiny">${current.goals.war_score >= current.goals.war_target ? 'Цель войны выполнена' : `До цели осталось ${Math.max(0, Number(current.goals.war_target || 0) - Number(current.goals.war_score || 0))}`}</div>
          </article>
          <article class="catalog-card skill-card">
            <div class="catalog-kicker">Клановая награда</div>
            <strong>Недельный сундук</strong>
            <div class="tiny">Осколки +5 • Редкий токен +1</div>
            <div class="tiny">${current.goals.war_score >= current.goals.war_target ? 'За выполненную войну дополнительно Lucky +1 и баннер недели.' : 'Lucky +1 и баннер недели даются только за выполненную войну.'}</div>
            <div class="tiny">${current.goals.weekly_reward_ready ? 'Награда уже доступна' : 'Награда пока закрыта'}</div>
          </article>
        </div>
        <h4 style="margin:18px 0 8px;">Клановые задания</h4>
        <div class="catalog-grid">
          ${(current.goals.weekly_quests || []).map((quest) => `
            <article class="catalog-card skill-card">
              <div class="catalog-kicker">Задание</div>
              <strong>${escapeHtml(quest.label || 'Цель')}</strong>
              <div class="tiny">Прогресс: ${Number(quest.progress || 0)}/${Number(quest.target || 0)}</div>
              <div class="tiny">Награда: ${escapeHtml(quest.reward || 'награда')}</div>
            </article>
          `).join('')}
        </div>
        <h4 style="margin:18px 0 8px;">Объявления</h4>
        <div class="deck-list">${announcements}</div>
        <div class="row" style="margin:10px 0;">
          <input id="guild-announcement-input" maxlength="220" placeholder="Новое объявление для клана">
          <button id="send-guild-announcement-btn"${current.viewer_role === 'member' ? ' disabled' : ''}>Объявить</button>
        </div>
        <h4 style="margin:18px 0 8px;">Состав</h4>
        <div class="catalog-grid">${members}</div>
        ${requests ? `<h4 style="margin:18px 0 8px;">Заявки</h4><div class="catalog-grid">${requests}</div>` : ''}
        <h4 style="margin:18px 0 8px;">Клановый чат</h4>
        <div class="row" style="margin-bottom:10px;">
          <input id="guild-chat-input" maxlength="240" placeholder="Сообщение в клановый чат">
          <button id="send-guild-chat-btn">Отправить</button>
        </div>
        <div class="deck-list">${chat}</div>
        <div class="row" style="margin-top:10px;">
          <input id="guild-invite-reference-input" maxlength="96" placeholder="Кошелёк или 1234.ton для инвайта">
          <button id="send-guild-invite-btn"${current.viewer_role === 'member' ? ' disabled' : ''}>Инвайт</button>
        </div>
      `;
      const chatBtn = document.getElementById('send-guild-chat-btn');
      const announcementBtn = document.getElementById('send-guild-announcement-btn');
      const inviteBtn = document.getElementById('send-guild-invite-btn');
      const guildHelpBattleBtn = document.getElementById('guild-help-battle-btn');
      const guildHelpPackBtn = document.getElementById('guild-help-pack-btn');
      const guildHelpProfileBtn = document.getElementById('guild-help-profile-btn');
      const guildWeeklyRewardBtn = document.getElementById('guild-weekly-reward-btn');
      if (chatBtn) bindFunctionalControl(chatBtn, sendGuildChatMessage);
      if (announcementBtn && !announcementBtn.disabled) bindFunctionalControl(announcementBtn, sendGuildAnnouncement);
      if (inviteBtn && !inviteBtn.disabled) bindFunctionalControl(inviteBtn, sendGuildInvite);
      if (guildHelpBattleBtn) bindFunctionalControl(guildHelpBattleBtn, () => switchView('modes'));
      if (guildHelpPackBtn) bindFunctionalControl(guildHelpPackBtn, () => switchView('pack'));
      if (guildHelpProfileBtn) bindFunctionalControl(guildHelpProfileBtn, () => switchView('profile'));
      if (guildWeeklyRewardBtn && !guildWeeklyRewardBtn.disabled) bindFunctionalControl(guildWeeklyRewardBtn, claimGuildWeeklyReward);
      renderSocialGuildBadges();
    }

    function api(path, options = {}) {
      const config = {
        method: options.method || 'GET',
        headers: {'Content-Type': 'application/json'},
      };
      if (options.body) {
        config.body = JSON.stringify(options.body);
      }
      return fetch(path, config).then(async (response) => {
        const rawText = await response.text().catch(() => '');
        let data = {};
        if (rawText) {
          try {
            data = JSON.parse(rawText);
          } catch (_) {
            data = {};
          }
        }
        if (!response.ok) {
          const fallback = rawText && rawText.trim() ? rawText.trim() : `HTTP ${response.status}`;
          throw new Error(data.error || data.detail || data.message || fallback || 'Request failed');
        }
        return data;
      });
    }

    function loadUsageMap() {
      try {
        return JSON.parse(window.localStorage.getItem(usageStorageKey) || '{}') || {};
      } catch (_) {
        return {};
      }
    }

    function saveUsageMap(map) {
      try {
        window.localStorage.setItem(usageStorageKey, JSON.stringify(map));
      } catch (_) {
      }
    }

    function bumpUsage(key) {
      const usage = loadUsageMap();
      usage[key] = Number(usage[key] || 0) + 1;
      saveUsageMap(usage);
      return usage[key];
    }

    function mostUsedMode() {
      const usage = loadUsageMap();
      const modes = ['ranked', 'casual', 'bot'];
      const sorted = modes
        .map((mode) => ({ mode, count: Number(usage[`mode:${mode}`] || 0) }))
        .sort((a, b) => b.count - a.count);
      return sorted[0] && sorted[0].count > 0 ? sorted[0].mode : '';
    }

    function softCameraFocus(target, block = 'center') {
      if (!target) return;
      requestAnimationFrame(() => {
        target.scrollIntoView({ behavior: 'smooth', block, inline: 'nearest' });
      });
    }

    function refreshModeUsageUI() {
      const topMode = mostUsedMode();
      document.querySelectorAll('[data-mode-card]').forEach((card) => {
        const preferred = topMode && card.dataset.modeCard === topMode;
        card.classList.toggle('preferred-mode', preferred);
        card.dataset.usageLabel = preferred ? 'Чаще играешь' : '';
      });
      return topMode;
    }

    function syncModeGridVisualState() {
      const modeGrid = document.querySelector('.mode-grid');
      if (!modeGrid) return;
      modeGrid.classList.toggle('matchmaking-live', Boolean(state.matchmakingMode));
    }

    function switchView(name) {
      if (name === 'wallet') {
        name = 'profile';
      }
      if (name !== 'modes' && name !== 'battleflow') {
        resetBattleStage();
      }
      resetHorizontalViewportDrift();
      syncTmaMode();
      syncTmaViewport();
      if (name !== 'modes') {
        resetModeChoice('');
      }
      document.querySelectorAll('.view').forEach((view) => {
        view.classList.toggle('active', view.id === `view-${name}`);
      });
      document.querySelectorAll('[data-step-chip]').forEach((chip) => {
        chip.classList.toggle('active', chip.dataset.stepChip === name);
      });
      document.querySelectorAll('.mobile-nav button').forEach((button) => {
        button.classList.toggle('active', button.id === `nav-${name}`);
      });
      document.querySelectorAll('.top-app-nav-link').forEach((button) => {
        button.classList.toggle('active', button.id === `top-nav-${name}`);
      });
      if (name === 'modes') {
        const preferredMode = refreshModeUsageUI();
        if (preferredMode) {
          const preferredCard = document.querySelector(`[data-mode-card="${preferredMode}"]`);
          softCameraFocus(preferredCard);
        }
      }
    }

    function setMascotOpen(open) {
      if (!mascotWidget) return;
      mascotWidget.classList.toggle('open', Boolean(open));
    }

    function mascotHintText() {
      if (!state.wallet) {
        return 'Сначала подключи кошелёк и проверь домены.';
      }
      if (!state.selectedDomain) {
        return 'Выбери домен и переходи к картам или в бой.';
      }
      if (state.matchmakingMode) {
        return 'Сейчас идёт поиск матча. Можно открыть игру и следить за статусом.';
      }
      return 'Быстрый доступ к профилю, картам, бою и гайду.';
    }

    function mountWalletIntoProfile() {
      const walletView = document.getElementById('view-wallet');
      if (!walletView || !profileWalletHub || walletView.dataset.movedToProfile === '1') {
        return;
      }
      const fragment = document.createDocumentFragment();
      Array.from(walletView.childNodes).forEach((node) => {
        fragment.appendChild(node);
      });
      profileWalletHub.appendChild(fragment);
      walletView.dataset.movedToProfile = '1';
      walletView.style.display = 'none';
      walletView.classList.remove('active');
    }

    function animateModeChoice(modeName) {
      const modeGrid = document.querySelector('.mode-grid');
      if (modeGrid) {
        modeGrid.classList.add('mode-focus');
      }
      document.querySelectorAll('[data-mode-card]').forEach((card) => {
        card.classList.toggle('active-mode', card.dataset.modeCard === modeName);
      });
      const activeCard = document.querySelector(`[data-mode-card="${modeName}"]`);
      softCameraFocus(activeCard);
      syncModeGridVisualState();
      window.clearTimeout(modeFocusTimer);
      modeFocusTimer = window.setTimeout(() => {
        if (modeGrid) {
          modeGrid.classList.remove('mode-focus');
        }
      }, 2200);
    }

    function resetModeChoice(message = '') {
      const modeGrid = document.querySelector('.mode-grid');
      if (modeGrid) {
        modeGrid.classList.remove('mode-focus');
      }
      document.querySelectorAll('[data-mode-card]').forEach((card) => {
        card.classList.remove('active-mode');
      });
      if (teamPanel) {
        teamPanel.style.display = 'none';
      }
      window.clearTimeout(modeFocusTimer);
      syncModeGridVisualState();
      if (message) {
        matchmakingStatus.textContent = message;
      }
    }

    function renderLeaderBoard(items) {
      const emptyMarkup = '<div class="leaderboard-item muted">Рейтинг появится после первых матчей.</div>';
      if (!items.length) {
        leaderboard.innerHTML = emptyMarkup;
        mobileLeaderboard.innerHTML = emptyMarkup;
        return;
      }
      const markup = items.map((item, index) => `
        <div class="leaderboard-item" data-open-profile-wallet="${escapeHtml(item.wallet)}" style="cursor:pointer;">
          <div class="team-line"><strong>#${index + 1} ${shortAddress(item.wallet)}</strong><strong>${item.rating}</strong></div>
          <div class="tiny">Матчей: ${item.games_played} • Побед: ${item.ranked_wins} • Лучший домен: ${item.best_domain || '-'}</div>
        </div>
      `).join('');
      leaderboard.innerHTML = markup;
      mobileLeaderboard.innerHTML = markup;
    }

    async function fillOpponent(reference) {
      await prepareFunctionalInteraction();
      document.getElementById('opponent-wallet').value = reference;
      switchView('modes');
      updateButtons();
    }

    function renderActiveUsers(items) {
      state.activeUsers = items;
      if (!items.length) {
        activeUsersList.innerHTML = '<div class="user-item muted">Активные игроки появятся здесь после входа в игру.</div>';
        return;
      }
      activeUsersList.innerHTML = items.map((item) => renderCompactPlayerCard(item, {
        actionsHtml: [
          `<div class="tiny" style="width:100%;">Прокачка (сред.): атака ${escapeHtml(String(item.average_attack || 0))} • защита ${escapeHtml(String(item.average_defense || 0))}</div>`,
          compactActionButton('В друзья', {'social-action': 'request-friend', reference: item.wallet}),
          compactActionButton('Дуэль', {'social-action': 'duel', reference: duelReferenceForPlayer(item)}),
        ].join(''),
      })).join('');
    }

    function renderDeck(data) {
      const emptyMarkup = '<div class="user-item muted">Сначала выбери домен и открой колоду.</div>';
      if (!data) {
        deckView.innerHTML = emptyMarkup;
        mobileDeckView.innerHTML = emptyMarkup;
        return;
      }
      const meta = (data.deck && data.deck.domain_metadata) || {};
      const markup = `
        <div class="user-item">
          <strong>${data.domain}.ton</strong>
          <div class="tiny">Редкость: ${meta.rarityLabel || '-'} • Тир: ${meta.tierLabel || '-'}</div>
          <div class="tiny">Счёт: ${meta.score || '-'} • Роль/класс: ${meta.role ? `${meta.role} / ${meta.class}` : '-'}</div>
          <div class="tiny">Бонус 10K Club: +${meta.bonusScore || 0} • База: ${meta.baseScore || 2500}</div>
          <div class="tiny">Атомарные паттерны: ${(meta.atomicPatterns && meta.atomicPatterns.length) ? meta.atomicPatterns.join(', ') : 'нет'}</div>
          <div class="tiny">Суперпаттерн: ${meta.superPattern || 'нет'} • Уровень: ${meta.level || 1}</div>
          <div class="tiny">Пассивная: ${meta.passiveAbility ? `${meta.passiveAbility.name} • шанс ${(Number(meta.passiveAbility.probability || 0) * 100).toFixed(0)}%` : '-'}</div>
          <div class="tiny">Активная: ${meta.activeAbility ? `${meta.activeAbility.name} • цена ${meta.activeAbility.cost} • кд ${meta.activeAbility.cooldown} • заряды ${meta.activeAbility.charges} • шанс ${(Number(meta.activeAbility.probability || 0) * 100).toFixed(0)}%` : '-'}</div>
          <div class="tiny">Синергии: ${data.deck.synergies && data.deck.synergies.labels && data.deck.synergies.labels.length ? data.deck.synergies.labels.join(' • ') : 'нет'}</div>
          <div class="tiny">Winrate домена: ${meta.totalMatches ? `${Math.round((meta.winRate || 0) * 100)}% из ${meta.totalMatches}` : 'нет матчей'}</div>
          <div class="tiny">Свободный пул дисциплин: ${data.deck.discipline_pool || 0}</div>
          <div class="tiny">Вклад карт в колоду: ${data.deck.total_score}</div>
        </div>
        ${data.deck.cards.map((card) => `
          <div class="user-item">
            <strong>${card.title}</strong>
            <div class="tiny">Слот ${card.slot} • ${card.rarity}</div>
            <div class="tiny">Базовая сила: ${card.pool_value || card.base_power || 0}</div>
            <div class="tiny">Скилл: ${card.skill_name || '-'} </div>
            <div class="tiny">${card.skill_description || card.ability || ''}</div>
          </div>
        `).join('')}
      `;
      deckView.innerHTML = markup;
      mobileDeckView.innerHTML = markup;
    }

    function renderDisciplineBuild(build) {
      state.disciplineBuild = build;
      const points = (build && build.points) || {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0};
      buildAttack.value = points.attack || 0;
      buildDefense.value = points.defense || 0;
      buildLuck.value = points.luck || 0;
      buildSpeed.value = points.speed || 0;
      buildMagic.value = points.magic || 0;
      const pool = Number(build && build.pool ? build.pool : 0);
      const spent = Number(points.attack || 0) + Number(points.defense || 0) + Number(points.luck || 0) + Number(points.speed || 0) + Number(points.magic || 0);
      buildStatus.textContent = `Пул: ${pool} • Потрачено: ${spent} • Остаток: ${Math.max(0, pool - spent)}`;
      saveBuildBtn.disabled = !(state.wallet && state.selectedDomain);
    }

    function collectBuildPoints() {
      return {
        attack: Number(buildAttack.value || 0),
        defense: Number(buildDefense.value || 0),
        luck: Number(buildLuck.value || 0),
        speed: Number(buildSpeed.value || 0),
        magic: Number(buildMagic.value || 0),
      };
    }

    async function loadDisciplineBuild() {
      if (!state.wallet || !state.selectedDomain) {
        renderDisciplineBuild({pool: 0, points: {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0}});
        return;
      }
      try {
        const data = await api(`/api/deck-build?wallet=${encodeURIComponent(state.wallet)}&domain=${encodeURIComponent(state.selectedDomain)}`);
        renderDisciplineBuild(data.build);
      } catch (error) {
        buildStatus.textContent = error.message;
      }
    }

    async function saveDisciplineBuild() {
      if (!state.wallet || !state.selectedDomain) return;
      try {
        const data = await api('/api/deck-build', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            points: collectBuildPoints()
          }
        });
        renderDisciplineBuild(data.build);
        buildStatus.textContent = `Прокачка сохранена. Пул: ${data.build.pool}.`;
      } catch (error) {
        buildStatus.textContent = error.message;
      }
    }

    async function shuffleDeck() {
      if (!state.wallet || !state.selectedDomain || !state.cards.length) return;
      try {
        setStatus(document.getElementById('pack-status'), 'Перемешиваем порядок карт для стратегии 5 на 5...', 'warning');
        const data = await api('/api/deck/shuffle', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain
          }
        });
        state.cards = data.cards || [];
        await renderPack(state.cards, data.total_score || 0);
        refreshOneCardSelector();
        renderDeck({ wallet: state.wallet, domain: data.domain, deck: data.deck });
        setStatus(document.getElementById('pack-status'), 'Колода перемешана. Новый порядок карт сохранен.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    function renderProfile() {
      const rewards = (state.playerProfile && state.playerProfile.rewards) || {};
      walletBadge.textContent = state.wallet ? `Подключён: ${shortAddress(state.wallet)}` : 'Кошелёк не подключен';
      currencyBadge.textContent = state.playerProfile && state.playerProfile.rewards
        ? `Осколки: ${rewards.pack_shards || 0} • Редкие: ${rewards.rare_tokens || 0} • Lucky: ${rewards.lucky_tokens || 0}`
        : 'Осколки: 0 • Редкие: 0 • Lucky: 0';
      if (walletQuickCurrency) {
        walletQuickCurrency.innerHTML = `
          <span class="wallet-currency-chip">💠 ${Number(rewards.pack_shards || 0)}</span>
          <span class="wallet-currency-chip">🎟️ ${Number(rewards.rare_tokens || 0)}</span>
          <span class="wallet-currency-chip">✨ ${Number(rewards.lucky_tokens || 0)}</span>
        `;
      }
      if (globalCurrencyShards) globalCurrencyShards.textContent = Number(rewards.pack_shards || 0);
      if (globalCurrencyRare) globalCurrencyRare.textContent = Number(rewards.rare_tokens || 0);
      if (globalCurrencyLucky) globalCurrencyLucky.textContent = Number(rewards.lucky_tokens || 0);
      walletQuickWallet.textContent = state.wallet ? shortAddress(state.wallet) : 'Не подключен';
      walletQuickDomain.textContent = state.selectedDomain ? `${state.selectedDomain}.ton` : 'Не выбран';
      profileWallet.textContent = state.wallet ? shortAddress(state.wallet) : '-';
      profileDomain.textContent = state.selectedDomain ? `${state.selectedDomain}.ton` : '-';
      selectedDomainLabel.textContent = state.selectedDomain ? `Домен: ${state.selectedDomain}.ton` : 'Домен не выбран';

      if (state.playerProfile) {
        profileRating.textContent = state.playerProfile.rating;
        profileGames.textContent = state.playerProfile.games_played;
        showDeckBtn.disabled = !(state.playerProfile.current_domain || state.playerProfile.best_domain);
      } else {
        profileRating.textContent = '1000';
        profileGames.textContent = '0';
        showDeckBtn.disabled = true;
      }

      mobileProfileSummary.innerHTML = `
        <div class="user-item">
          <strong>${state.selectedDomain ? `${state.selectedDomain}.ton` : 'Профиль игрока'}</strong>
          <div class="tiny">Кошелёк: ${state.wallet ? shortAddress(state.wallet) : '-'}</div>
          <div class="tiny">Активный домен: ${state.selectedDomain ? `${state.selectedDomain}.ton` : '-'}</div>
          <div class="tiny">Титул: ${state.playerProfile && state.playerProfile.profile_title ? escapeHtml(state.playerProfile.profile_title) : '-'}</div>
          <div class="tiny">Рейтинг: ${profileRating.textContent} • Матчей: ${profileGames.textContent}</div>
          <div class="tiny">Стиль: ${escapeHtml(profilePlayStyleMeta((state.playerProfile && state.playerProfile.play_style) || '').label)} • Способность: ${escapeHtml(profileAbilityMeta((state.playerProfile && state.playerProfile.favorite_ability) || '').label)}</div>
          <div class="tiny">Награды: ${state.playerProfile && state.playerProfile.rewards ? `осколки ${state.playerProfile.rewards.pack_shards} • редкие ${state.playerProfile.rewards.rare_tokens} • lucky ${state.playerProfile.rewards.lucky_tokens}` : '-'}</div>
          <div class="tiny">Сезон: ${state.playerProfile && state.playerProfile.rewards ? `ур. ${state.playerProfile.rewards.season_level} • ${state.playerProfile.rewards.season_points}/${state.playerProfile.rewards.season_target}` : '-'}</div>
          <div class="tiny">Синергии: ${state.playerProfile && state.playerProfile.synergies && state.playerProfile.synergies.labels && state.playerProfile.synergies.labels.length ? state.playerProfile.synergies.labels.join(' • ') : 'нет'}</div>
        </div>
      `;
      document.getElementById('mobile-show-deck-btn').disabled = showDeckBtn.disabled;
      renderTelegramLinkPanel();
      renderRewardsPanels();
      renderPackEconomy();
      renderIdentityPanel();
      renderCosmeticsPanel();
      renderFaqPanel();
      renderSocialPanel();
      renderGuildPanel();
      renderTutorialPanel();
      renderClanSeasonHub();
    }

    function telegramLinkTitle() {
      const telegram = state.playerProfile && state.playerProfile.telegram;
      if (!telegram) {
        return state.wallet ? 'Не привязан' : 'Сначала подключи кошелёк';
      }
      if (telegram.username) {
        return `Привязан: @${telegram.username}`;
      }
      if (telegram.first_name) {
        return `Привязан: ${telegram.first_name}`;
      }
      return 'Telegram привязан';
    }

    function mountTelegramLoginWidget() {
      if (!telegramLoginWidget) return;
      const signature = state.wallet ? `${state.wallet}:${telegramLinkTitle()}` : '';
      if (state.telegramWidgetSignature === signature && telegramLoginWidget.childElementCount) {
        return;
      }
      state.telegramWidgetSignature = signature;
      telegramLoginWidget.innerHTML = '';
      if (!telegramBotUsername) {
        telegramLoginWidget.innerHTML = '<div class="tiny" style="color: var(--warning);">TG_BOT_USERNAME не настроен на сервере.</div>';
        return;
      }
      if (!state.wallet) {
        telegramLoginWidget.innerHTML = '<div class="tiny" style="color: var(--muted);">Сначала подключи TON-кошелёк, потом привяжи Telegram.</div>';
        return;
      }
      const script = document.createElement('script');
      script.async = true;
      script.src = 'https://telegram.org/js/telegram-widget.js?22';
      script.setAttribute('data-telegram-login', telegramBotUsername);
      script.setAttribute('data-size', 'large');
      script.setAttribute('data-radius', '12');
      script.setAttribute('data-request-access', 'write');
      script.setAttribute('data-userpic', 'false');
      script.setAttribute('data-lang', 'ru');
      script.setAttribute('data-onauth', 'window.onTelegramSiteAuth(user)');
      telegramLoginWidget.appendChild(script);
    }

    function renderTelegramLinkPanel() {
      if (!telegramLinkSummary || !telegramLoginWidget) return;
      const tma = isTelegramMiniApp();
      telegramLinkSummary.textContent = telegramLinkTitle();
      if (!state.wallet) {
        setStatus(telegramLinkStatus, 'Telegram можно привязать после подключения кошелька.', 'warning');
      } else if (state.playerProfile && state.playerProfile.telegram_linked) {
        setStatus(telegramLinkStatus, 'Telegram привязан. Уведомления по бою и наградам можно отправлять напрямую.', 'success');
      } else {
        setStatus(telegramLinkStatus, tma
          ? 'В mini app Telegram можно привязать без отдельного логина. Нажми кнопку ниже, чтобы включить уведомления.'
          : 'Нажми кнопку Telegram ниже, чтобы привязать аккаунт к текущему кошельку.', 'warning');
      }
      if (telegramMiniappLinkBtn) {
        telegramMiniappLinkBtn.style.display = tma ? 'inline-flex' : 'none';
        telegramMiniappLinkBtn.disabled = !state.wallet || Boolean(state.playerProfile && state.playerProfile.telegram_linked);
        telegramMiniappLinkBtn.textContent = state.playerProfile && state.playerProfile.telegram_linked
          ? 'Telegram уже привязан'
          : 'Включить уведомления Telegram в mini app';
      }
      telegramLoginWidget.style.display = tma ? 'none' : 'flex';
      if (!tma) {
        mountTelegramLoginWidget();
      } else {
        telegramLoginWidget.innerHTML = '';
      }
    }

    function renderOwnedDecks(decks, currentDomain) {
      state.ownedDecks = decks || [];
      if (!state.ownedDecks.length) {
        ownedDecksList.innerHTML = '<div class="user-item muted">Сначала проверь домены кошелька.</div>';
        walletOwnedDecksList.innerHTML = '<div class="user-item muted">Сначала проверь домены кошелька.</div>';
        return;
      }
      const markup = state.ownedDecks.map((item) => `
        <div class="user-item wallet-domain-card">
          <strong>${item.domain}.ton ${item.is_active || currentDomain === item.domain ? '(активная)' : ''}</strong>
          <div class="wallet-domain-stats">
            <span class="wallet-domain-chip">Редкость: ${item.rarity || '-'}</span>
            <span class="wallet-domain-chip">Тир: ${item.tier || '-'}</span>
            <span class="wallet-domain-chip">Удача: ${item.luck || 0}</span>
            <span class="wallet-domain-chip">Пул: ${(item.metadata && item.metadata.score) || item.deck.discipline_pool || 0}</span>
          </div>
          <div class="wallet-domain-mainline">Вклад карт: ${item.deck.total_score} • ${item.deck.cards && item.deck.cards.length ? `карт: ${item.deck.cards.length}` : 'колода еще не открыта'}</div>
          <div class="tiny">Роль / класс: ${item.metadata && item.metadata.role ? `${item.metadata.role} / ${item.metadata.class}` : '-'}</div>
          <div class="tiny">Пассивная: ${item.metadata && item.metadata.passiveAbility ? item.metadata.passiveAbility.name : '-'} • Активная: ${item.metadata && item.metadata.activeAbility ? item.metadata.activeAbility.name : '-'}</div>
          <div class="tiny">Синергии: ${item.deck && item.deck.synergies && item.deck.synergies.labels && item.deck.synergies.labels.length ? item.deck.synergies.labels.join(' • ') : 'нет'}</div>
          <div class="actions" style="margin-top:10px;">
            <button class="secondary wallet-domain-action" data-domain-action="${item.domain}">Играть этим доменом</button>
          </div>
        </div>
      `).join('');
      ownedDecksList.innerHTML = markup;
      walletOwnedDecksList.innerHTML = markup;
    }

    function preferredDeckDomain(decks, currentDomain = null) {
      const items = Array.isArray(decks) ? decks : [];
      if (!items.length) return null;
      const explicitActive = items.find((item) => item.domain === currentDomain || item.is_active);
      if (explicitActive) return explicitActive.domain;
      const openedDeck = items.find((item) => item.deck && Array.isArray(item.deck.cards) && item.deck.cards.length === 5);
      return openedDeck ? openedDeck.domain : items[0].domain;
    }

    function renderGlobalPlayers(items) {
      state.allPlayers = items || [];
      const emptyMarkup = '<div class="user-item muted">Игроки появятся после первого входа.</div>';
      if (!state.allPlayers.length) {
        globalPlayersList.innerHTML = emptyMarkup;
        mobileGlobalPlayersList.innerHTML = emptyMarkup;
        return;
      }
      const markup = state.allPlayers.map((player, index) => renderCompactPlayerCard(player, {
        actionsHtml: [
          `<div class="tiny" style="width:100%;">#${index + 1} • рейтинг ${escapeHtml(String(player.rating || 1000))} • матчей ${escapeHtml(String(player.games_played || 0))}</div>`,
          compactActionButton('В друзья', {'social-action': 'request-friend', reference: player.wallet}),
          compactActionButton('Дуэль', {'social-action': 'duel', reference: duelReferenceForPlayer(player)}),
        ].join(''),
      })).join('');
      globalPlayersList.innerHTML = markup;
      mobileGlobalPlayersList.innerHTML = markup;
    }

    function renderClanSeasonHub() {
      if (!achievementsList) return;
      if (!state.wallet) {
        achievementsList.innerHTML = '<div class="user-item muted">Подключи кошелёк, чтобы открыть сезонный пропуск.</div>';
        return;
      }
      const rewards = (state.playerProfile && state.playerProfile.rewards) || {};
      const track = Array.isArray(rewards.season_pass_track) ? rewards.season_pass_track : [];
      const seasonTasks = Array.isArray(rewards.season_tasks) ? rewards.season_tasks : [];
      const rewardTone = (text) => {
        const lower = String(text || '').toLowerCase();
        if (lower.includes('арена')) return 'radial-gradient(circle at top, rgba(69,215,255,0.2), rgba(13,22,37,0.94) 62%)';
        if (lower.includes('рубаш')) return 'radial-gradient(circle at top, rgba(255,211,110,0.18), rgba(13,22,37,0.94) 62%)';
        if (lower.includes('рамк')) return 'radial-gradient(circle at top, rgba(83,246,184,0.18), rgba(13,22,37,0.94) 62%)';
        if (lower.includes('титул') || lower.includes('баннер')) return 'radial-gradient(circle at top, rgba(255,122,134,0.2), rgba(13,22,37,0.94) 62%)';
        if (lower.includes('косметический пак')) return 'radial-gradient(circle at top, rgba(145,112,255,0.22), rgba(13,22,37,0.94) 62%)';
        if (lower.includes('оскол')) return 'radial-gradient(circle at top, rgba(69,215,255,0.16), rgba(13,22,37,0.94) 62%)';
        if (lower.includes('редк')) return 'radial-gradient(circle at top, rgba(255,122,134,0.16), rgba(13,22,37,0.94) 62%)';
        if (lower.includes('lucky')) return 'radial-gradient(circle at top, rgba(255,211,110,0.18), rgba(13,22,37,0.94) 62%)';
        return 'radial-gradient(circle at top, rgba(121,217,255,0.12), rgba(13,22,37,0.94) 62%)';
      };
      const premiumRow = track.map((item, index) => `
        <article class="catalog-card skill-card season-pass-stage-card${index === 0 ? ' is-active' : ''}" data-pass-card-index="${index}" style="padding:12px; min-height:112px; display:grid; gap:8px; align-content:start; background:${rewardTone(item.premium)}; border-color:rgba(255, 211, 110, 0.28); min-width:220px;">
          <div class="catalog-kicker">Премиум • ур. ${item.level}</div>
          <strong>${item.premium ? escapeHtml(item.premium) : 'Нет награды'}</strong>
          <div class="tiny">${item.premium_claimed ? 'Получено' : (item.premium_claimable ? 'Можно забрать' : (item.premium_ready ? 'Доступно' : 'Закрыто'))}</div>
          <div class="actions" style="margin-top:auto;">
            <button type="button" class="secondary season-pass-claim-btn" data-pass-claim="premium" data-level="${item.level}"${item.premium_claimable ? '' : ' disabled'}>${item.premium_claimed ? 'Получено' : 'Забрать'}</button>
          </div>
        </article>
      `).join('');
      const freeRow = track.map((item, index) => `
        <article class="catalog-card skill-card season-pass-stage-card${index === 0 ? ' is-active' : ''}" data-pass-card-index="${index}" style="padding:12px; min-height:112px; display:grid; gap:8px; align-content:start; background:${rewardTone(item.free)}; min-width:220px;">
          <div class="catalog-kicker">Бесплатно • ур. ${item.level}</div>
          <strong>${item.free ? escapeHtml(item.free) : 'Нет награды'}</strong>
          <div class="tiny">${item.free_claimed ? 'Получено' : (item.free_claimable ? 'Можно забрать' : (item.free_ready ? 'Доступно' : 'Закрыто'))}</div>
          <div class="actions" style="margin-top:auto;">
            <button type="button" class="secondary season-pass-claim-btn" data-pass-claim="free" data-level="${item.level}"${item.free_claimable ? '' : ' disabled'}>${item.free_claimed ? 'Получено' : 'Забрать'}</button>
          </div>
        </article>
      `).join('');
      const passMarkup = `
        <div class="user-item">
          <strong>Сезонный пропуск</strong>
          <div class="tiny">Статус: ${rewards.premium_pass_active ? 'Премиум активен' : 'Бесплатный трек'} • сезон ${Number(rewards.season_level || 1)} • ${Number(rewards.season_points || 0)}/${Number(rewards.season_target || 16)} очков</div>
          <div class="tiny">Сверху премиум-линия, снизу бесплатная. На одном уровне могут открываться обе награды или только одна из них.</div>
          ${seasonTasks.length ? `
            <div class="catalog-grid" style="margin-top:12px;">
              ${seasonTasks.map((task) => `
                <article class="catalog-card skill-card" style="padding:12px; min-height:112px; display:grid; gap:8px; align-content:start; background:radial-gradient(circle at top, rgba(83,246,184,0.12), rgba(13,22,37,0.94) 62%);">
                  <div class="catalog-kicker">Сложное задание дня</div>
                  <strong>${escapeHtml(task.label)}</strong>
                  <div class="tiny">Прогресс: ${Number(task.progress || 0)}/${Number(task.target || 0)}</div>
                  <div class="tiny">Крупная награда: +${Number(task.reward_points || 0)} очков пропуска</div>
                  <div class="actions" style="margin-top:auto;">
                    <button type="button" class="secondary season-task-claim-btn" data-task-key="${escapeHtml(task.key)}"${task.claimable ? '' : ' disabled'}>${task.claimed ? 'Получено' : (task.claimable ? 'Забрать' : 'Выполняется')}</button>
                  </div>
                </article>
              `).join('')}
            </div>
          ` : ''}
          <div style="display:flex; align-items:center; gap:10px; margin-top:12px; flex-wrap:wrap;">
            <button type="button" id="season-pass-prev-btn" style="min-width:110px; min-height:40px; border-radius:12px; border:1px solid rgba(121,217,255,0.24); background:rgba(10,23,40,0.9); color:#eef6ff; font-weight:800; cursor:pointer;">← Назад</button>
            <span id="season-pass-level-label" style="display:inline-flex; align-items:center; min-height:40px; padding:0 14px; border-radius:999px; border:1px solid rgba(121,217,255,0.22); background:rgba(10,23,40,0.78); color:#eef6ff; font-size:12px; font-weight:700; letter-spacing:0.04em; text-transform:uppercase;">Уровень 1 / ${track.length}</span>
            <button type="button" id="season-pass-next-btn" style="min-width:110px; min-height:40px; border-radius:12px; border:1px solid rgba(121,217,255,0.24); background:rgba(10,23,40,0.9); color:#eef6ff; font-weight:800; cursor:pointer;">Вперёд →</button>
          </div>
          <div class="season-pass-board" style="margin-top:10px; display:grid; gap:14px;">
            <div>
              <div class="tiny" style="margin:0 0 8px; color:#ffe3a1;">Премиум</div>
              <div class="season-pass-stage" data-pass-stage="premium">
                ${premiumRow}
              </div>
            </div>
            <div>
              <div class="tiny" style="margin:0 0 8px;">Бесплатно</div>
              <div class="season-pass-stage" data-pass-stage="free">
                ${freeRow}
              </div>
            </div>
          </div>
          <div class="actions" style="margin-top:10px;">
            <button id="buy-season-pass-btn"${rewards.premium_pass_active ? ' disabled' : ''}>Купить премиум-пропуск за 1.49 TON</button>
          </div>
        </div>
      `;
      achievementsList.innerHTML = passMarkup;
      achievementsList.querySelectorAll('.season-pass-claim-btn').forEach((button) => {
        if (button.disabled) return;
        bindFunctionalControl(button, () => claimSeasonPassReward(button.dataset.level, button.dataset.passClaim));
      });
      achievementsList.querySelectorAll('.season-task-claim-btn').forEach((button) => {
        if (button.disabled) return;
        bindFunctionalControl(button, () => claimSeasonTaskReward(button.dataset.taskKey));
      });
      const passLevelLabel = document.getElementById('season-pass-level-label');
      const passPrevBtn = document.getElementById('season-pass-prev-btn');
      const passNextBtn = document.getElementById('season-pass-next-btn');
      const showPassLevel = (index) => {
        const boundedIndex = Math.max(0, Math.min(track.length - 1, Number(index || 0)));
        ['premium', 'free'].forEach((target) => {
          const stage = achievementsList.querySelector(`.season-pass-stage[data-pass-stage="${target}"]`);
          if (!stage) return;
          stage.querySelectorAll('.season-pass-stage-card').forEach((card) => {
            const active = Number(card.dataset.passCardIndex || 0) === boundedIndex;
            card.classList.toggle('is-active', active);
            card.style.display = active ? 'grid' : 'none';
          });
        });
        if (passLevelLabel) passLevelLabel.textContent = `Уровень ${boundedIndex + 1} / ${track.length}`;
        if (passPrevBtn) passPrevBtn.disabled = boundedIndex <= 0;
        if (passNextBtn) passNextBtn.disabled = boundedIndex >= track.length - 1;
        state.seasonPassLevelIndex = boundedIndex;
      };
      window.jumpSeasonPassLevel = function jumpSeasonPassLevel(levelValue) {
        const next = Math.max(0, Math.min(track.length - 1, Number(levelValue || 1) - 1));
        showPassLevel(next);
      };
      if (passPrevBtn) {
        bindFunctionalControl(passPrevBtn, () => showPassLevel((state.seasonPassLevelIndex || 0) - 1));
      }
      if (passNextBtn) {
        bindFunctionalControl(passNextBtn, () => showPassLevel((state.seasonPassLevelIndex || 0) + 1));
      }
      showPassLevel(Math.max(0, Math.min(track.length - 1, Number((state.seasonPassLevelIndex || 0)))));
      const buySeasonPassBtn = document.getElementById('buy-season-pass-btn');
      if (buySeasonPassBtn && !buySeasonPassBtn.disabled) bindFunctionalControl(buySeasonPassBtn, buySeasonPassWithTon);
    }

    const GIFT_THEMES = {
      black: { name: 'Black', emoji: '♠️', base: '#020202', secondary: '#090909', accent: '#5E616B', glow: 'rgba(94,97,107,0.22)', text: '#F2F2F2', motif: 'stripes' },
      onyx_black: { name: 'Onyx Black', emoji: '🕷️', base: '#0B0E14', secondary: '#171D27', accent: '#9BB0D2', glow: 'rgba(155,176,210,0.26)', text: '#F2F7FF', motif: 'web' },
      gunmetal: { name: 'Gunmetal', emoji: '🛠️', base: '#1A2432', secondary: '#2A3C56', accent: '#9BB0CC', glow: 'rgba(155,176,204,0.26)', text: '#EEF5FF', motif: 'grid' },
      ivory_white: { name: 'Ivory White', emoji: '🕊️', base: '#F4EFE4', secondary: '#E0D5C1', accent: '#BDAA87', glow: 'rgba(189,170,135,0.26)', text: '#1A1A1A', motif: 'petals' },
      platinum: { name: 'Platinum', emoji: '⚪', base: '#CED2D8', secondary: '#B5BCC7', accent: '#8E97A6', glow: 'rgba(142,151,166,0.24)', text: '#0D1320', motif: 'grid' },
      midnight_blue: { name: 'Midnight Blue', emoji: '🌙', base: '#132342', secondary: '#1D3361', accent: '#7FA8FF', glow: 'rgba(127,168,255,0.26)', text: '#F1F6FF', motif: 'stars' },
      rifle_green: { name: 'Rifle Green', emoji: '🎯', base: '#414833', secondary: '#58634A', accent: '#B6C58F', glow: 'rgba(182,197,143,0.24)', text: '#F3F9E7', motif: 'leaf' },
      fire_engine: { name: 'Fire Engine', emoji: '🔥', base: '#7F111B', secondary: '#B31A29', accent: '#FF8B83', glow: 'rgba(255,139,131,0.28)', text: '#FFF5F5', motif: 'sparks' },
      deep_cyan: { name: 'Deep Cyan', emoji: '🌊', base: '#0E5560', secondary: '#0F7B88', accent: '#7DEBFF', glow: 'rgba(125,235,255,0.28)', text: '#EDFFFF', motif: 'waves' },
      khaki_green: { name: 'Khaki Green', emoji: '🌿', base: '#465236', secondary: '#67784A', accent: '#C8D89A', glow: 'rgba(200,216,154,0.26)', text: '#F2F8E6', motif: 'leaf' },
      emerald: { name: 'Emerald', emoji: '🍀', base: '#1A5C3F', secondary: '#23835A', accent: '#8BDFB5', glow: 'rgba(139,223,181,0.28)', text: '#F2FFF7', motif: 'leaf' },
      tactical_pine: { name: 'Tactical Pine', emoji: '🌲', base: '#1E2E24', secondary: '#2B4637', accent: '#8EB99E', glow: 'rgba(142,185,158,0.25)', text: '#EEFFF5', motif: 'leaf' },
      ranger_green: { name: 'Ranger Green', emoji: '🪖', base: '#2C3B2A', secondary: '#40533E', accent: '#A6C39F', glow: 'rgba(166,195,159,0.25)', text: '#F0F8EB', motif: 'grid' },
      moonstone: { name: 'Moonstone', emoji: '🌘', base: '#4E5D70', secondary: '#67798E', accent: '#B7C8DD', glow: 'rgba(183,200,221,0.27)', text: '#F4F8FF', motif: 'stars' },
      cobalt_blue: { name: 'Cobalt Blue', emoji: '🔷', base: '#163D88', secondary: '#2358B3', accent: '#77B4FF', glow: 'rgba(119,180,255,0.28)', text: '#F1F7FF', motif: 'grid' },
      satin_gold: { name: 'Satin Gold', emoji: '✨', base: '#8B6D1B', secondary: '#BF9830', accent: '#FFE08A', glow: 'rgba(255,224,138,0.3)', text: '#FFF7DE', motif: 'gems' },
      old_gold: { name: 'Old Gold', emoji: '👑', base: '#6C5520', secondary: '#8E7330', accent: '#D5BA63', glow: 'rgba(213,186,99,0.28)', text: '#FFF6DD', motif: 'crown' },
      copper: { name: 'Copper', emoji: '🪙', base: '#7A4A2D', secondary: '#A1623E', accent: '#E2AA84', glow: 'rgba(226,170,132,0.28)', text: '#FFF1E8', motif: 'stripes' },
      neon_blue: { name: 'Neon Blue', emoji: '💠', base: '#0E2F7B', secondary: '#1747B7', accent: '#6CD8FF', glow: 'rgba(108,216,255,0.3)', text: '#F1F9FF', motif: 'grid' },
      raspberry: { name: 'Raspberry', emoji: '🍇', base: '#5A1A3D', secondary: '#7A2A57', accent: '#F59BD0', glow: 'rgba(245,155,208,0.28)', text: '#FFF2FA', motif: 'sparks' },
    };
    const COSMETIC_ASSET_VERSION = '20260401c';
    function escapeSvg(text) {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function svgDataUrl(svg) {
      const safeSvg = String(svg || '');
      try {
        return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(safeSvg)))}`;
      } catch (_) {
        return `data:image/svg+xml;utf8,${encodeURIComponent(safeSvg)}`;
      }
    }

    function themeSlugFromKey(key) {
      const safeKey = String(key || '').toLowerCase();
      return Object.keys(GIFT_THEMES).find((slug) => safeKey.includes(slug)) || 'black';
    }

    function cosmeticTheme(type, key) {
      return GIFT_THEMES[themeSlugFromKey(key)] || GIFT_THEMES.black;
    }

    const COSMETIC_RARITY_ORDER = ['basic', 'rare', 'epic', 'mythic', 'legendary'];
    const COSMETIC_RARITY_LABELS = {
      basic: 'Basic',
      rare: 'Rare',
      epic: 'Epic',
      mythic: 'Mythic',
      legendary: 'Legendary',
    };
    const COSMETIC_RARITY_WEIGHTS = {
      basic: 32,
      rare: 27,
      epic: 20,
      mythic: 13,
      legendary: 8,
    };
    let rouletteAudioCtx = null;

    function cosmeticRarityKey(item) {
      const key = String((item || {}).rarity_key || 'basic').toLowerCase();
      return COSMETIC_RARITY_ORDER.includes(key) ? key : 'basic';
    }

    function cosmeticRarityLabel(item) {
      const key = cosmeticRarityKey(item);
      return COSMETIC_RARITY_LABELS[key] || 'Basic';
    }

    function cosmeticTypeIcon(item) {
      const type = String((item || {}).type || '').toLowerCase();
      if (type === 'emoji') return item.emoji || '•';
      if (type === 'frame') return '🖼️';
      if (type === 'cardback') return '🃏';
      if (type === 'arena') return '🏟️';
      if (type === 'guild') return '🏳️';
      return '✨';
    }

    function cosmeticTypeLabelRu(type) {
      const key = String(type || '').toLowerCase();
      if (key === 'frame') return 'Рамка';
      if (key === 'cardback') return 'Рубашка';
      if (key === 'arena') return 'Арена';
      if (key === 'guild') return 'Баннер';
      if (key === 'emoji') return 'Эмодзи';
      return 'Косметика';
    }

    function ensureRouletteAudioContext() {
      if (rouletteAudioCtx) return rouletteAudioCtx;
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      rouletteAudioCtx = new Ctx();
      return rouletteAudioCtx;
    }

    async function resumeRouletteAudioContext() {
      const ctx = ensureRouletteAudioContext();
      if (!ctx) return null;
      if (ctx.state === 'suspended') {
        try {
          await ctx.resume();
        } catch (_) {}
      }
      return ctx;
    }

    function playRouletteTickSound(power = 0.55, pitch = 980) {
      const ctx = ensureRouletteAudioContext();
      if (!ctx) return;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const filter = ctx.createBiquadFilter();
      filter.type = 'highpass';
      filter.frequency.setValueAtTime(420, now);
      osc.type = 'square';
      osc.frequency.setValueAtTime(Math.max(240, pitch), now);
      osc.frequency.exponentialRampToValueAtTime(Math.max(180, pitch * 0.72), now + 0.042);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(Math.max(0.01, 0.032 * power), now + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.055);
      osc.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.06);
    }

    function playRouletteDropSound() {
      const ctx = ensureRouletteAudioContext();
      if (!ctx) return;
      const now = ctx.currentTime;

      const hitOsc = ctx.createOscillator();
      const hitGain = ctx.createGain();
      hitOsc.type = 'triangle';
      hitOsc.frequency.setValueAtTime(182, now);
      hitOsc.frequency.exponentialRampToValueAtTime(84, now + 0.15);
      hitGain.gain.setValueAtTime(0.0001, now);
      hitGain.gain.exponentialRampToValueAtTime(0.09, now + 0.01);
      hitGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.17);
      hitOsc.connect(hitGain);
      hitGain.connect(ctx.destination);
      hitOsc.start(now);
      hitOsc.stop(now + 0.2);

      const shineOsc = ctx.createOscillator();
      const shineGain = ctx.createGain();
      const shineFilter = ctx.createBiquadFilter();
      shineFilter.type = 'bandpass';
      shineFilter.frequency.setValueAtTime(1650, now);
      shineOsc.type = 'sine';
      shineOsc.frequency.setValueAtTime(1180, now + 0.01);
      shineOsc.frequency.exponentialRampToValueAtTime(540, now + 0.24);
      shineGain.gain.setValueAtTime(0.0001, now + 0.01);
      shineGain.gain.exponentialRampToValueAtTime(0.055, now + 0.03);
      shineGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.26);
      shineOsc.connect(shineFilter);
      shineFilter.connect(shineGain);
      shineGain.connect(ctx.destination);
      shineOsc.start(now + 0.01);
      shineOsc.stop(now + 0.28);
    }

    async function runRouletteTickSequence(totalDistancePx, stepPx) {
      const safeStep = Math.max(1, Number(stepPx || 1));
      const totalTicks = Math.max(18, Math.min(120, Math.floor(totalDistancePx / safeStep) + 6));
      const phase1Ticks = Math.max(8, Math.floor(totalTicks * 0.55));
      const phase2Ticks = Math.max(6, Math.floor(totalTicks * 0.35));
      const phase3Ticks = Math.max(2, totalTicks - phase1Ticks - phase2Ticks);
      const p1Interval = 2240 / phase1Ticks;
      const p2Interval = 2090 / phase2Ticks;
      const p3Interval = 380 / phase3Ticks;

      for (let i = 0; i < phase1Ticks; i += 1) {
        const t = i / Math.max(1, phase1Ticks - 1);
        playRouletteTickSound(0.62, 1450 - t * 520);
        await sleep(p1Interval);
      }
      for (let i = 0; i < phase2Ticks; i += 1) {
        const t = i / Math.max(1, phase2Ticks - 1);
        playRouletteTickSound(0.56, 910 - t * 370);
        await sleep(p2Interval);
      }
      for (let i = 0; i < phase3Ticks; i += 1) {
        const t = i / Math.max(1, phase3Ticks - 1);
        playRouletteTickSound(0.5, 520 - t * 120);
        await sleep(p3Interval);
      }
    }

    function cosmeticEmojiSymbol(cosmetics) {
      if (!cosmetics || !cosmetics.emoji) return '';
      return String(cosmetics.emoji.emoji || '•').trim();
    }

    function cosmeticEmojiBadge(cosmetics) {
      const emoji = cosmeticEmojiSymbol(cosmetics);
      if (!emoji) return '';
      return `<div class="arena-card-emoji">${escapeHtml(emoji)}</div>`;
    }

    function chooseWeightedCosmeticRarity(availableRarities) {
      const weights = availableRarities.map((key) => Number(COSMETIC_RARITY_WEIGHTS[key] || 0));
      const total = weights.reduce((sum, value) => sum + value, 0);
      if (!total) return availableRarities[Math.floor(Math.random() * availableRarities.length)] || 'basic';
      let cursor = Math.random() * total;
      for (let i = 0; i < availableRarities.length; i += 1) {
        cursor -= weights[i];
        if (cursor <= 0) return availableRarities[i];
      }
      return availableRarities[availableRarities.length - 1] || 'basic';
    }

    function drawRouletteCosmetic(catalog, forced = null) {
      if (forced) return forced;
      if (!Array.isArray(catalog) || !catalog.length) return null;
      const byRarity = {};
      catalog.forEach((item) => {
        const rarity = cosmeticRarityKey(item);
        if (!byRarity[rarity]) byRarity[rarity] = [];
        byRarity[rarity].push(item);
      });
      const rarities = COSMETIC_RARITY_ORDER.filter((key) => byRarity[key] && byRarity[key].length);
      if (!rarities.length) return catalog[Math.floor(Math.random() * catalog.length)];
      const rarity = chooseWeightedCosmeticRarity(rarities);
      const pool = byRarity[rarity] || catalog;
      const weighted = pool.map((item) => ({
        item,
        weight: Math.max(0.01, Number(item && item.drop_weight ? item.drop_weight : 1)),
      }));
      const total = weighted.reduce((sum, entry) => sum + entry.weight, 0);
      if (!total) return pool[Math.floor(Math.random() * pool.length)] || catalog[0];
      let cursor = Math.random() * total;
      for (const entry of weighted) {
        cursor -= entry.weight;
        if (cursor <= 0) return entry.item;
      }
      return weighted[weighted.length - 1].item;
    }

    function hexToRgba(hex, alpha) {
      const value = String(hex || '').replace('#', '').trim();
      const normalized = value.length === 3
        ? value.split('').map((chunk) => chunk + chunk).join('')
        : value;
      if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
        return `rgba(69,215,255,${alpha})`;
      }
      const intValue = parseInt(normalized, 16);
      const r = (intValue >> 16) & 255;
      const g = (intValue >> 8) & 255;
      const b = intValue & 255;
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    function battleArenaUiStyle(cosmetics) {
      const arenaKey = (((cosmetics || {}).arena || {}).key || '');
      const theme = cosmeticTheme('arena', arenaKey);
      const isIvory = themeSlugFromKey(arenaKey) === 'ivory_white';
      const text = isIvory ? '#141414' : (theme.text || '#f4fbff');
      const chipText = isIvory ? '#241a10' : '#fff1b8';
      return [
        `--arena-ui-base:${hexToRgba(theme.base, isIvory ? 0.82 : 0.9)}`,
        `--arena-ui-secondary:${hexToRgba(theme.secondary, isIvory ? 0.76 : 0.92)}`,
        `--arena-ui-accent:${theme.accent}`,
        `--arena-ui-accent-soft:${hexToRgba(theme.accent, isIvory ? 0.14 : 0.2)}`,
        `--arena-ui-accent-border:${hexToRgba(theme.accent, isIvory ? 0.34 : 0.38)}`,
        `--arena-ui-text:${text}`,
        `--arena-ui-chip-bg:${hexToRgba(theme.accent, isIvory ? 0.18 : 0.16)}`,
        `--arena-ui-chip-border:${hexToRgba(theme.accent, isIvory ? 0.42 : 0.38)}`,
        `--arena-ui-chip-text:${chipText}`,
        `--arena-overlay-text:${isIvory ? '#111111' : '#ffffff'}`,
        `--arena-overlay-muted:${isIvory ? 'rgba(17,17,17,0.78)' : 'rgba(255,255,255,0.76)'}`,
        `--arena-route-main:${isIvory ? 'rgba(17,17,17,0.74)' : 'rgba(255,255,255,0.72)'}`,
        `--arena-route-alt:${isIvory ? 'rgba(17,17,17,0.54)' : 'rgba(255,255,255,0.52)'}`,
        `--arena-route-active:${isIvory ? '#111111' : '#ffffff'}`,
        `--arena-state-bg:${isIvory ? 'rgba(17,17,17,0.07)' : 'rgba(255,255,255,0.06)'}`,
        `--arena-state-border:${isIvory ? 'rgba(17,17,17,0.18)' : 'rgba(255,255,255,0.16)'}`,
      ].join(';');
    }

    function monogramPatternSurface(emoji, theme, mode = 'cardback') {
      const symbol = String(emoji || '').trim();
      if (!symbol) return '';
      const tileSize = mode === 'arena' ? 170 : (mode === 'guild' ? 78 : 62);
      const fontSize = mode === 'arena' ? 38 : (mode === 'guild' ? 24 : 20);
      const opacity = mode === 'arena' ? 0.2 : (mode === 'guild' ? 0.34 : 0.3);
      const fill = (theme && theme.text) ? theme.text : '#f2f8ff';
      const stroke = (theme && theme.accent) ? theme.accent : '#7ddfff';
      const svg = `
        <svg width="240" height="240" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg">
          <g fill="${fill}" fill-opacity="${opacity}" stroke="${stroke}" stroke-opacity="${Math.max(0.12, opacity * 0.55)}" stroke-width="1.2" paint-order="stroke fill" font-size="${fontSize}" text-anchor="middle" dominant-baseline="middle">
            <text x="40" y="40">${escapeSvg(symbol)}</text>
            <text x="120" y="40">${escapeSvg(symbol)}</text>
            <text x="200" y="40">${escapeSvg(symbol)}</text>
            <text x="40" y="120">${escapeSvg(symbol)}</text>
            <text x="120" y="120">${escapeSvg(symbol)}</text>
            <text x="200" y="120">${escapeSvg(symbol)}</text>
            <text x="40" y="200">${escapeSvg(symbol)}</text>
            <text x="120" y="200">${escapeSvg(symbol)}</text>
            <text x="200" y="200">${escapeSvg(symbol)}</text>
          </g>
        </svg>
      `;
      return `url(${svgDataUrl(svg)}) center/${tileSize}px ${tileSize}px repeat`;
    }

    function giftCardbackSurface(key, emoji = '') {
      const theme = cosmeticTheme('cardback', key);
      const safeKey = String(key || '').toLowerCase();
      if (safeKey.includes('stock_plain')) {
        return [
          'repeating-linear-gradient(135deg, rgba(154,164,181,0.2) 0 10px, rgba(154,164,181,0) 10px 20px)',
          'linear-gradient(180deg, rgba(60,68,82,0.98), rgba(38,44,56,0.98))',
        ].join(', ');
      }
      const layers = [];
      if (safeKey.includes('onyx_black')) {
        layers.push('radial-gradient(circle at 22% 18%, rgba(162, 186, 224, 0.24), transparent 42%)');
        layers.push('radial-gradient(circle at 78% 82%, rgba(148, 169, 201, 0.18), transparent 44%)');
      } else if (safeKey.includes('black')) {
        layers.push('repeating-linear-gradient(135deg, rgba(162, 169, 182, 0.08) 0 7px, rgba(162, 169, 182, 0) 7px 15px)');
      }
      const pattern = monogramPatternSurface(emoji, theme, 'cardback');
      if (pattern) layers.push(pattern);
      layers.push(`radial-gradient(circle at 50% 6%, ${hexToRgba(theme.accent, 0.2)}, transparent 46%)`);
      layers.push(`linear-gradient(180deg, ${hexToRgba(theme.base, 0.96)}, ${hexToRgba(theme.secondary, 0.98)})`);
      return layers.join(', ');
    }

    function giftArenaSurface(key, emoji = '') {
      const theme = cosmeticTheme('arena', key);
      const safeKey = String(key || '').toLowerCase();
      if (safeKey.includes('stock_grid')) {
        return [
          'repeating-linear-gradient(0deg, rgba(143,155,175,0.16) 0 1px, rgba(0,0,0,0) 1px 42px)',
          'repeating-linear-gradient(90deg, rgba(143,155,175,0.16) 0 1px, rgba(0,0,0,0) 1px 42px)',
          'linear-gradient(180deg, rgba(53,61,75,0.96), rgba(34,40,50,0.98))',
        ].join(', ');
      }
      const layers = [];
      if (safeKey.includes('onyx_black')) {
        layers.push('radial-gradient(circle at 50% 50%, rgba(142, 176, 228, 0.18), rgba(0,0,0,0) 58%)');
        layers.push('repeating-radial-gradient(circle at 50% 50%, rgba(136, 164, 208, 0.14) 0 2px, rgba(0,0,0,0) 2px 34px)');
      } else if (safeKey.includes('black')) {
        layers.push('repeating-linear-gradient(135deg, rgba(150, 154, 165, 0.12) 0 2px, rgba(0,0,0,0) 2px 24px)');
        layers.push('radial-gradient(circle at 50% 50%, rgba(120, 126, 138, 0.08), rgba(0,0,0,0) 62%)');
      }
      const pattern = monogramPatternSurface(emoji, theme, 'arena');
      if (pattern) layers.push(pattern);
      layers.push(`radial-gradient(circle at 50% 45%, ${hexToRgba(theme.accent, 0.14)}, transparent 62%)`);
      layers.push(`linear-gradient(180deg, ${hexToRgba(theme.secondary, 0.9)}, ${hexToRgba(theme.base, 0.94)})`);
      return layers.join(', ');
    }

    function giftGuildSurface(key, emoji = '') {
      const theme = cosmeticTheme('guild', key);
      const safeKey = String(key || '').toLowerCase();
      if (safeKey.includes('stock_plain')) {
        return [
          'repeating-linear-gradient(90deg, rgba(165,176,196,0.14) 0 1px, rgba(0,0,0,0) 1px 16px)',
          'linear-gradient(180deg, rgba(56,64,78,0.96), rgba(37,43,55,0.98))',
        ].join(', ');
      }
      const layers = [];
      const pattern = monogramPatternSurface(emoji, theme, 'guild');
      if (pattern) layers.push(pattern);
      layers.push(`linear-gradient(90deg, ${hexToRgba(theme.base, 0.95)}, ${hexToRgba(theme.secondary, 0.95)})`);
      return layers.join(', ');
    }

    function giftThemePattern(theme) {
      const accent = theme.accent;
      switch (theme.motif) {
        case 'web':
          return `
            <g opacity="0.18" stroke="${accent}" stroke-width="2.5" fill="none">
              <circle cx="256" cy="384" r="148"/><circle cx="256" cy="384" r="108"/><circle cx="256" cy="384" r="68"/>
              <path d="M256 236V532M108 384H404M152 280L360 488M360 280L152 488"/>
            </g>
          `;
        case 'petals':
          return `
            <g opacity="0.2" fill="${accent}">
              <ellipse cx="256" cy="250" rx="42" ry="86"/><ellipse cx="256" cy="518" rx="42" ry="86"/>
              <ellipse cx="122" cy="384" rx="42" ry="86" transform="rotate(90 122 384)"/>
              <ellipse cx="390" cy="384" rx="42" ry="86" transform="rotate(90 390 384)"/>
            </g>
          `;
        case 'stars':
          return `
            <g opacity="0.18" fill="${accent}">
              <circle cx="110" cy="166" r="8"/><circle cx="390" cy="210" r="6"/><circle cx="158" cy="560" r="7"/><circle cx="360" cy="596" r="9"/>
              <path d="M256 118 268 144 296 148 274 166 280 194 256 180 232 194 238 166 216 148 244 144Z"/>
            </g>
          `;
        case 'sparks':
          return `
            <g opacity="0.18" fill="${accent}">
              <rect x="98" y="182" width="18" height="106" rx="9" transform="rotate(28 98 182)"/>
              <rect x="322" y="126" width="18" height="138" rx="9" transform="rotate(18 322 126)"/>
              <rect x="366" y="466" width="18" height="118" rx="9" transform="rotate(-24 366 466)"/>
              <rect x="144" y="512" width="18" height="92" rx="9" transform="rotate(-18 144 512)"/>
            </g>
          `;
        case 'waves':
          return `
            <g opacity="0.18" stroke="${accent}" stroke-width="8" fill="none" stroke-linecap="round">
              <path d="M60 230c52-28 92-28 144 0s92 28 144 0 92-28 144 0"/>
              <path d="M40 384c60 34 104 34 164 0s104-34 164 0 104 34 164 0"/>
              <path d="M60 540c52-28 92-28 144 0s92 28 144 0 92-28 144 0"/>
            </g>
          `;
        case 'leaf':
          return `
            <g opacity="0.18" fill="${accent}">
              <path d="M138 182c62 4 106 46 110 114-60-4-106-44-110-114Z"/>
              <path d="M374 478c-62-4-106-46-110-114 60 4 106 44 110 114Z"/>
              <path d="M136 560c52-30 116-26 164 12-54 30-116 26-164-12Z"/>
            </g>
          `;
        case 'gems':
          return `
            <g opacity="0.18" fill="${accent}">
              <path d="M256 156 304 208 256 260 208 208Z"/>
              <path d="M132 386 168 424 132 462 96 424Z"/>
              <path d="M380 386 416 424 380 462 344 424Z"/>
              <path d="M256 568 304 620 256 672 208 620Z"/>
            </g>
          `;
        case 'crown':
          return `
            <g opacity="0.18" fill="${accent}">
              <path d="M130 224 194 274 256 188 318 274 382 224 356 344H156Z"/>
              <circle cx="194" cy="260" r="10"/><circle cx="256" cy="176" r="10"/><circle cx="318" cy="260" r="10"/>
            </g>
          `;
        case 'grid':
          return `
            <g opacity="0.16" stroke="${accent}" stroke-width="3">
              <path d="M104 124V644M184 124V644M264 124V644M344 124V644M424 124V644"/>
              <path d="M88 180H440M88 276H440M88 372H440M88 468H440M88 564H440"/>
            </g>
          `;
        case 'stripes':
        default:
          return `
            <g opacity="0.18" fill="${accent}">
              <rect x="84" y="152" width="48" height="464" rx="12" transform="rotate(24 84 152)"/>
              <rect x="208" y="120" width="48" height="528" rx="12" transform="rotate(24 208 120)"/>
              <rect x="332" y="88" width="48" height="528" rx="12" transform="rotate(24 332 88)"/>
            </g>
          `;
      }
    }

    function cosmeticAssetUrl(type, key) {
      const theme = cosmeticTheme(type, key);
      if (!theme) return '';
      if (type === 'cardback') {
        return `/static/cosmetics/cardbacks/generated/${themeSlugFromKey(key)}.svg?v=${COSMETIC_ASSET_VERSION}`;
      }
      if (type === 'frame') {
        return svgDataUrl(`
          <svg width="512" height="768" viewBox="0 0 512 768" xmlns="http://www.w3.org/2000/svg">
            <rect x="12" y="12" width="488" height="744" rx="42" stroke="${theme.accent}" stroke-width="16"/>
            <rect x="28" y="28" width="456" height="712" rx="30" stroke="${theme.secondary}" stroke-width="6"/>
            <circle cx="96" cy="96" r="20" fill="${theme.accent}" fill-opacity="0.55"/>
            <circle cx="416" cy="672" r="20" fill="${theme.accent}" fill-opacity="0.55"/>
          </svg>
        `);
      }
      if (type === 'arena') {
        return `/static/cosmetics/arenas/generated/${themeSlugFromKey(key)}.svg?v=${COSMETIC_ASSET_VERSION}`;
      }
      if (type === 'guild') {
        return `${svgDataUrl(`
          <svg width="512" height="256" viewBox="0 0 512 256" xmlns="http://www.w3.org/2000/svg">
            <rect width="512" height="256" rx="26" fill="${theme.base}"/>
            <rect x="14" y="14" width="484" height="228" rx="20" fill="${theme.secondary}" stroke="${theme.accent}" stroke-width="4"/>
            <path d="M76 54H436V136L256 208L76 136Z" fill="${theme.accent}" fill-opacity="0.22"/>
            <text x="256" y="154" text-anchor="middle" font-size="68" fill="${theme.text}" stroke="${theme.accent}" stroke-opacity="0.36" stroke-width="3" paint-order="stroke fill">${escapeSvg(theme.emoji)}</text>
          </svg>
        `)}#v=${COSMETIC_ASSET_VERSION}`;
      }
      return '';
    }

    function renderCosmeticsPanel() {
      if (!profileCosmeticsPanel) return;
      const rewards = (state.playerProfile && state.playerProfile.rewards) || {};
      const cosmetics = Array.isArray(rewards.cosmetics) ? rewards.cosmetics : [];
      const cosmeticCatalog = Array.isArray(rewards.cosmetic_catalog) ? rewards.cosmetic_catalog : [];
      const inventoryByKey = Object.fromEntries(cosmetics.map((item) => [item.key, item]));
      if (!state.wallet) {
        profileCosmeticsPanel.innerHTML = '<div class="user-item muted">Подключи кошелёк, чтобы видеть косметику и её превью.</div>';
        return;
      }
      if (!cosmeticCatalog.length) {
        profileCosmeticsPanel.innerHTML = '<div class="user-item muted">Каталог косметики пока недоступен.</div>';
        return;
      }
      const unlockedKeys = new Set(cosmetics.map((item) => item.key));
      const catalogByType = cosmeticCatalog.reduce((acc, item) => {
        const key = item.type || 'other';
        if (!acc[key]) acc[key] = [];
        acc[key].push(item);
        return acc;
      }, {});
      const equipped = rewards.equipped_cosmetics || {};
      const featuredArena = (catalogByType.arena || []).find((item) => item.key === (equipped.arena && equipped.arena.key)) || cosmetics.find((item) => item.type === 'arena') || (catalogByType.arena || [])[0] || cosmeticCatalog[0];
      const featuredFrame = (catalogByType.frame || []).find((item) => item.key === (equipped.frame && equipped.frame.key)) || cosmetics.find((item) => item.type === 'frame') || (catalogByType.frame || [])[0] || null;
      const featuredBack = (catalogByType.cardback || []).find((item) => item.key === (equipped.cardback && equipped.cardback.key)) || cosmetics.find((item) => item.type === 'cardback') || (catalogByType.cardback || [])[0] || null;
      const featuredGuild = (catalogByType.guild || []).find((item) => item.key === (equipped.guild && equipped.guild.key)) || cosmetics.find((item) => item.type === 'guild') || (catalogByType.guild || [])[0] || null;
      const featuredEmoji = (catalogByType.emoji || []).find((item) => item.key === (equipped.emoji && equipped.emoji.key)) || cosmetics.find((item) => item.type === 'emoji') || (catalogByType.emoji || [])[0] || null;
      const compactPreview = document.body.classList.contains('tma-app') || window.innerWidth <= 760;
      const featuredEmojiValue = featuredEmoji ? (featuredEmoji.emoji || '') : '';
      const frameAsset = cosmeticAssetUrl('frame', featuredFrame && featuredFrame.key);
      const visibleCatalogByType = Object.fromEntries(Object.entries(catalogByType).map(([type, items]) => [
        type,
        state.showAllCosmetics ? items : items.filter((item) => unlockedKeys.has(item.key)),
      ]));
      const typeLabel = {
        frame: 'Рамки',
        arena: 'Арены',
        cardback: 'Рубашки',
        guild: 'Клановые баннеры',
        emoji: 'Emoji-монограммы',
      };
      const previewMetaMarkup = [
        `Арена: ${featuredArena ? escapeHtml(featuredArena.name) : 'стандарт'}`,
        `Рамка: ${featuredFrame ? escapeHtml(featuredFrame.name) : 'стандарт'}`,
        `Рубашка: ${featuredBack ? escapeHtml(featuredBack.name) : 'стандарт'}`,
        `Баннер: ${featuredGuild ? escapeHtml(featuredGuild.name) : 'стандарт'}`,
        `Монограмма: ${featuredEmoji ? escapeHtml((featuredEmoji.emoji || '•') + ' ' + featuredEmoji.name) : 'стандарт'}`
      ].map((text) => `<div class="summary-chip">${text}</div>`).join('');
      profileCosmeticsPanel.innerHTML = `
        <div class="user-item" style="margin-bottom:14px;">
          <strong>Предпросмотр</strong>
          <div style="margin-top:10px; border-radius:18px; padding:18px; display:grid; grid-template-columns:${compactPreview ? '1fr' : 'minmax(180px, 240px) minmax(0, 1fr)'}; gap:22px; align-items:center; overflow:hidden; background:${giftArenaSurface(featuredArena && featuredArena.key, featuredEmojiValue)};">
            <div style="position:relative; width:190px; height:220px; margin:0 auto;">
              ${featuredGuild ? `<div style="position:absolute; left:50%; top:22px; transform:translateX(-50%); width:110px; height:64px; border-radius:10px; border:1px solid rgba(255,255,255,0.24); background:${giftGuildSurface(featuredGuild.key, featuredEmojiValue)}; opacity:0.98; z-index:1; pointer-events:none;"></div>` : ''}
              <div style="position:absolute; left:35px; top:48px; width:120px; height:168px; border-radius:18px; background:${giftCardbackSurface(featuredBack && featuredBack.key, featuredEmojiValue)}; border:1px solid rgba(121,217,255,0.18); box-shadow:0 20px 36px rgba(0,0,0,0.28); z-index:2;"></div>
              ${featuredFrame ? `<img src="${frameAsset}" alt="" style="position:absolute; left:27px; top:40px; width:136px; height:184px; object-fit:contain; z-index:3; pointer-events:none;">` : ''}
            </div>
            <div style="display:grid; gap:12px; align-content:center; min-width:0;">
              <div class="summary-chip-row">${previewMetaMarkup}</div>
              <div class="tiny">Открыто: ${cosmetics.length} • Всего вариантов: ${cosmeticCatalog.length}</div>
              <div class="tiny">Ниже показан полный каталог косметики по категориям. Закрытые варианты отображаются отдельно от уже открытых.</div>
              <div class="actions" style="margin-top:8px;">
                <button type="button" class="secondary" id="toggle-cosmetics-catalog-btn">${state.showAllCosmetics ? 'Показать только открытое' : 'Посмотреть все виды кастомизации'}</button>
              </div>
            </div>
          </div>
        </div>
        ${Object.entries(visibleCatalogByType).filter(([, items]) => items.length).map(([type, items]) => `
          <div class="user-item" style="margin-bottom:14px;">
            <strong>${typeLabel[type] || type}</strong>
            <div class="catalog-grid" style="margin-top:12px;">
              ${items.map((item) => {
                const unlocked = unlockedKeys.has(item.key);
                const equippedNow = equipped[type] && equipped[type].key === item.key;
                const ownedMeta = inventoryByKey[item.key] || null;
                const itemFrameAsset = cosmeticAssetUrl('frame', item.key);
                const itemEmoji = type === 'emoji' ? (item.emoji || '') : featuredEmojiValue;
                const rarity = String(item.rarity_key || 'basic').toLowerCase();
                return `
                  <article class="catalog-card skill-card ${rarity}" style="padding:14px; opacity:${unlocked ? '1' : '0.62'};">
                    <div class="catalog-kicker">${escapeHtml(typeLabel[type] || type)}</div>
                    <strong>${escapeHtml(item.name)}</strong>
                    <div class="tiny">${rarity.toUpperCase()}</div>
                    <div class="tiny" style="margin-top:6px;">${equippedNow ? 'Выбрано' : (unlocked ? 'Открыто' : 'Закрыто')}</div>
                      <div style="margin-top:10px; border-radius:14px; min-height:96px; padding:12px; position:relative; overflow:hidden; background:${type === 'arena' ? giftArenaSurface(item.key, itemEmoji) : type === 'cardback' ? giftCardbackSurface(item.key, itemEmoji) : type === 'guild' ? giftGuildSurface(item.key, itemEmoji) : 'linear-gradient(180deg, rgba(69,215,255,0.12), rgba(8,20,36,0.92))'};">
                      <div style="position:absolute; inset:12px; border-radius:12px; border:${type === 'frame' ? '1px solid rgba(83,246,184,0.32)' : '1px solid rgba(121,217,255,0.18)'};"></div>
                      ${type === 'frame' && itemFrameAsset ? `<img src="${itemFrameAsset}" alt="" style="position:absolute; inset:6px; width:calc(100% - 12px); height:calc(100% - 12px); object-fit:contain;">` : ''}
                      ${type === 'emoji' ? `<div style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:34px;">${escapeHtml(item.emoji || '•')}</div>` : ''}
                      <div style="position:absolute; left:18px; bottom:16px; font-size:11px; color:rgba(213,235,255,0.86);">${escapeHtml(item.name)}</div>
                    </div>
                    <div class="actions" style="margin-top:10px;">
                      <button type="button" class="secondary equip-cosmetic-btn" data-cosmetic-key="${escapeHtml(item.key)}"${!unlocked || equippedNow ? ' disabled' : ''}>${equippedNow ? 'Выбрано' : (unlocked ? 'Выбрать' : 'Закрыто')}</button>
                    </div>
                  </article>
                `;
              }).join('')}
            </div>
          </div>
        `).join('')}
      `;
      const toggleBtn = document.getElementById('toggle-cosmetics-catalog-btn');
      if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
          state.showAllCosmetics = !state.showAllCosmetics;
          renderCosmeticsPanel();
        });
      }
      profileCosmeticsPanel.querySelectorAll('.equip-cosmetic-btn').forEach((button) => {
        bindFunctionalControl(button, () => equipCosmeticChoice(button.dataset.cosmeticKey));
      });
    }

    async function equipCosmeticChoice(cosmeticKey) {
      if (!state.wallet || !cosmeticKey) return;
      const data = await api('/api/cosmetics/equip', {
        method: 'POST',
        body: { wallet: state.wallet, cosmetic_key: cosmeticKey }
      });
      state.playerProfile = data.player || state.playerProfile;
      renderProfile();
    }

    async function claimSeasonPassReward(level, tier) {
      if (!state.wallet || !level || !tier) return;
      const data = await api('/api/rewards/season-pass-claim', {
        method: 'POST',
        body: { wallet: state.wallet, level: Number(level), tier }
      });
      if (state.playerProfile) {
        state.playerProfile.rewards = data.rewards || state.playerProfile.rewards;
      }
      renderProfile();
      if (typeof renderWalletPanel === 'function') renderWalletPanel();
    }

    async function claimSeasonTaskReward(taskKey) {
      if (!state.wallet || !taskKey) return;
      try {
        const data = await api('/api/rewards/season-task', {
          method: 'POST',
          body: { wallet: state.wallet, task_key: taskKey }
        });
        if (state.playerProfile) {
          state.playerProfile.rewards = data.rewards || state.playerProfile.rewards;
        }
        renderProfile();
        if (typeof renderWalletPanel === 'function') renderWalletPanel();
        setStatus(document.getElementById('pack-status'), 'Очки пропуска за задание получены.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    function renderFaqPanel() {
      if (!faqPanel) return;
      const faqItems = [
        {
          title: 'Как работают домены 10K Club',
          body: 'Сила домена берётся из индекса 10K Club: тир, паттерны, score и бонусы. Редкий домен помогает, но бой всё равно решают выбор действия, энергия, стратегия и RNG.'
        },
        {
          title: 'Что дают Натиск, Блок и Способность',
          body: 'Натиск стоит 2 энергии и лучше раскрывает агрессию. Блок стоит 1 энергию и помогает пережить сильный раунд соперника. Способность стоит 3 энергии, имеет КД и заряды, поэтому её выгодно прожимать в ключевой момент.'
        },
        {
          title: 'Как работают паки',
          body: 'Бесплатные и reward-паки дают карты и валюту. Редкость идёт по порядку: Basic, Rare, Epic, Mythic, Legendary.'
        },
        {
          title: 'Что даёт сезонный пропуск',
          body: 'Верхняя линия — премиум, нижняя — бесплатная. В пропуске 16 уровней. Бесплатные награды идут реже, а премиум чаще даёт валюту и косметические паки. Дополнительно есть ежедневные задания пропуска на быстрый прогресс.'
        },
        {
          title: 'Как работают кланы и войны',
          body: 'Клан даёт недельные задания, войну недели, общий сезонный счёт и сундук награды. Чем больше активность клана в боях и заданиях, тем выше общая награда недели.'
        },
        {
          title: 'Как работает косметика',
          body: 'Косметика видна всем игрокам: рубашка, рамка, арена и клановый баннер применяются в превью и в бою. Сначала показываются открытые предметы, остальное открывается по кнопке просмотра полного каталога.'
        }
      ];
      faqPanel.innerHTML = faqItems.map((item) => `
        <div class="user-item">
          <strong>${item.title}</strong>
          <div class="tiny" style="margin-top:8px;">${item.body}</div>
        </div>
      `).join('');
    }

    function renderCardCatalog(cards, skills = []) {
      state.cardCatalog = cards || [];
      if (!state.cardCatalog.length) {
        cardCatalogList.innerHTML = '<div class="user-item muted">Каталог карт загружается...</div>';
        return;
      }
      const packGuide = (state.packTypes || []).length
        ? `
          <div class="panel" style="margin-bottom:14px; padding:16px;">
            <h3 style="margin-bottom:10px;">Типы паков и гарантия</h3>
            <div class="catalog-grid">
              ${state.packTypes.map((pack) => `
                <article class="catalog-card skill-card">
                  <div class="catalog-kicker">Пак</div>
                  <strong>${pack.label}</strong>
                  <div class="tiny">Карт: ${pack.count} • Стоимость: ${packCostText(pack.costs || {})}</div>
                  <div class="tiny">Шансы: ${Object.entries(pack.weights || {}).map(([key, value]) => `${key} ${value}%`).join(' • ')}</div>
                  <div class="tiny">Lucky-бонус: ${pack.lucky_bonus ? 'есть' : 'нет'} • гарантия после ${state.packPityThreshold} паков без легендарки</div>
                </article>
              `).join('')}
              <article class="catalog-card skill-card" style="border-color:rgba(174,126,255,0.28); background:radial-gradient(circle at top, rgba(145,112,255,0.18), rgba(13,22,37,0.94) 66%);">
                <div class="catalog-kicker">Пак</div>
                <strong>Косметический пак</strong>
                <div class="tiny">Содержимое: 1 случайный косметический предмет</div>
                <div class="tiny">Редкости: Basic 32% • Rare 27% • Epic 20% • Mythic 13% • Legendary 8%</div>
                <div class="tiny">Источник: только из премиум-пропуска</div>
              </article>
            </div>
          </div>
        `
        : '';
      const tacticalGuide = (skills || []).length
        ? `
          <div class="panel" style="margin-bottom:14px; padding:16px;">
            <h3 style="margin-bottom:10px;">Все стратегические карты</h3>
            <div class="tiny" style="margin-bottom:12px;">Это полный набор стратегических эффектов, который может выпасть на карту в бою.</div>
            <div class="catalog-grid">
              ${skills.map((skill) => `
                <article class="catalog-card skill-card">
                  <div class="catalog-kicker">Стратегическая карта</div>
                  <strong>${skill.name}</strong>
                  <div class="tiny">${skill.description}</div>
                  <div class="tiny" style="margin-top:8px;">Сильнее всего: ${skill.strong_against}</div>
                  <div class="tiny" style="margin-top:8px;">Может появиться на любой карте колоды как её стратегический эффект.</div>
                </article>
              `).join('')}
            </div>
          </div>
          <div class="panel" style="margin-bottom:14px; padding:16px;">
            <h3 style="margin-bottom:10px;">Когда выгоден Натиск и Блок</h3>
            <div class="catalog-grid">
              <article class="catalog-card skill-card">
                <div class="catalog-kicker">Выбор в бою</div>
                <strong>Натиск</strong>
                <div class="tiny">Выгоден, когда хочешь продавить раунд силой и поймать соперника на пассивной игре.</div>
                <div class="tiny" style="margin-top:8px;">Лучше всего: когда твоя карта сильнее по темпу, нужно добить перевес или закончить серию в свою пользу.</div>
              </article>
              <article class="catalog-card skill-card">
                <div class="catalog-kicker">Выбор в бою</div>
                <strong>Блок</strong>
                <div class="tiny">Выгоден, когда ждёшь агрессию соперника и хочешь пережить его сильный заход.</div>
                <div class="tiny" style="margin-top:8px;">Лучше всего: когда раунд надо стабилизировать, у соперника выглядит очевидный пуш или нужно сохранить преимущество.</div>
              </article>
            </div>
          </div>
        `
        : '';
      cardCatalogList.innerHTML = `
        ${packGuide}
        ${tacticalGuide}
        <div class="catalog-grid">
          ${state.cardCatalog.map((card) => `
            <article class="catalog-card ${card.rarity}">
              <strong>${card.id.toUpperCase()} • ${card.title}</strong>
              <div class="tiny">Редкость: ${card.rarity_label}</div>
              <div class="tiny">Базовая сила: ${card.pool_min}-${card.pool_max}</div>
              <div class="tiny">Скиллы в бою распределяются по картам при открытии пака.</div>
            </article>
          `).join('')}
        </div>
      `;
    }

    function refreshOneCardSelector() {
      if (oneCardSlot) {
        oneCardSlot.innerHTML = '<option value="">Выбери карту для режима одной карты</option>';
      }
      if (!state.cards.length) {
        battleCardSlot.innerHTML = '<option value="">Выбери тактическую карту на матч</option>';
        state.selectedBattleSlot = null;
        return;
      }
      if (oneCardSlot) {
        oneCardSlot.innerHTML += state.cards.map((card) => `
          <option value="${card.slot}">Слот ${card.slot}: ${card.title} (${card.pool_value || card.score || 0})</option>
        `).join('');
      }
      battleCardSlot.innerHTML = '<option value="">Выбери тактическую карту на матч</option>' + state.cards.map((card) => `
        <option value="${card.slot}">Слот ${card.slot}: ${card.title} • ${card.skill_name || 'скилл'} </option>
      `).join('');
      if (!state.selectedBattleSlot || !state.cards.some((card) => Number(card.slot) === Number(state.selectedBattleSlot))) {
        state.selectedBattleSlot = state.cards[0].slot;
      }
      battleCardSlot.value = String(state.selectedBattleSlot);
    }

    function updateButtons() {
      const connected = Boolean(state.wallet);
      const hasDomain = Boolean(state.selectedDomain);
      const hasCards = state.cards.length === 5;
      const searching = Boolean(state.matchmakingMode);
      const selectedPack = state.selectedPackType || 'common';
      const selectedPackMeta = packTypeMeta(selectedPack);
      const connectWalletBtn = document.getElementById('connect-wallet-btn');
      if (connectWalletBtn) {
        connectWalletBtn.disabled = false;
        connectWalletBtn.textContent = connected ? 'Кошелёк подключён' : 'Подключить кошелёк';
      }
      document.getElementById('check-domains-btn').disabled = false;
      document.getElementById('shuffle-deck-btn').disabled = !(connected && hasDomain && hasCards);
      document.getElementById('open-pack-btn').disabled = !(connected && hasDomain) || selectedPack !== 'common';
      document.getElementById('open-pack-btn').textContent = selectedPack === 'common' ? 'Открыть ежедневный пак' : 'Ежедневный пак: только Common';
      buyPackBtn.disabled = !(connected && tonConnectUI) || Boolean(state.playerProfile && state.playerProfile.rewards && state.playerProfile.rewards.premium_pass_active);
      buyPackBtn.textContent = state.playerProfile && state.playerProfile.rewards && state.playerProfile.rewards.premium_pass_active
        ? 'Премиум-пропуск активен'
        : 'Купить премиум-пропуск за 1.49 TON';
      if (walletTechStatus) {
        const tonUiLoaded = Boolean(window.TON_CONNECT_UI && window.TON_CONNECT_UI.TonConnectUI);
        const tonUiCreated = Boolean(tonConnectUI);
        const tonAccount = Boolean(tonConnectUI && tonConnectUI.account && tonConnectUI.account.address);
        walletTechStatus.textContent = `TonConnect: script ${tonUiLoaded ? 'ok' : 'x'} • ui ${tonUiCreated ? 'ok' : 'x'} • account ${tonAccount ? 'ok' : 'x'}`;
      }
      document.getElementById('continue-to-modes-btn').disabled = !hasCards;
      document.getElementById('play-ranked-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('play-casual-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('play-bot-btn').disabled = !(connected && hasCards) || searching;
      const duelInput = document.getElementById('opponent-wallet');
      const duelButton = document.getElementById('play-duel-btn');
      if (duelButton) {
        duelButton.disabled = !(connected && hasCards && duelInput && duelInput.value.trim()) || searching;
      }
      if (playOnecardBtn && oneCardSlot) {
        playOnecardBtn.disabled = !(connected && hasCards && oneCardSlot.value) || searching;
      }
      if (createRoomBtn) {
        createRoomBtn.disabled = !(connected && hasCards) || searching;
      }
      if (joinRoomBtn) {
        joinRoomBtn.disabled = !(connected && hasCards) || searching;
      }
      refreshAchievementsBtn.disabled = !connected;
      cancelMatchmakingBtn.disabled = !searching;
      saveBuildBtn.disabled = !(connected && hasDomain);
      walletOpenPackBtn.disabled = !(connected && hasDomain);
      renderPackEconomy();
      renderPackTypePicker();
      updatePreviousDeckRestoreButton();
    }

    function renderDomains(domains) {
      const container = document.getElementById('domains-list');
      if (!domains.length) {
        container.innerHTML = '';
        marketplacesBox.style.display = state.domainsChecked ? 'block' : 'none';
        marketplacesLinks.innerHTML = marketplaceLinks.map((item) => `
          <a class="market-link" href="${item.url}" target="_blank" rel="noopener">${item.label}</a>
        `).join('');
        return;
      }

      marketplacesBox.style.display = 'none';
      container.innerHTML = domains.map((domain) => `
        <div class="domain-card user-item wallet-domain-card ${state.selectedDomain === domain.domain ? 'selected' : ''}">
          <h3>${domain.domain}.ton ${domain.is_guest ? '• гостевой' : ''}</h3>
          <div class="wallet-domain-stats">
            <span class="wallet-domain-chip">Источник: ${domain.source_label}</span>
            <span class="wallet-domain-chip">Редкость: ${domain.rarity || '-'}</span>
            <span class="wallet-domain-chip">Тир: ${domain.tier || '-'}</span>
            <span class="wallet-domain-chip">Удача: ${domain.luck || 0}</span>
          </div>
          <div class="wallet-domain-mainline">Счёт домена: ${domain.score} • DNS: ${domain.is_guest ? 'гостевой режим' : (domain.domain_exists ? 'активен' : 'не подтверждён')}</div>
          <details class="wallet-domain-more">
            <summary>Подробнее</summary>
            <div class="tiny">Паттерны: ${domain.patterns.length ? domain.patterns.join(', ') : 'базовый 10K домен'}</div>
            <div class="tiny">Спецколлекции: ${domain.special_collections && domain.special_collections.length ? domain.special_collections.join(', ') : 'нет'}</div>
            <div class="tiny">Роль / класс: ${domain.metadata && domain.metadata.role ? `${domain.metadata.role} / ${domain.metadata.class}` : '-'}</div>
            <div class="tiny">Пассивная: ${domain.metadata && domain.metadata.passiveAbility ? domain.metadata.passiveAbility.name : '-'}</div>
            <div class="tiny">Активная: ${domain.metadata && domain.metadata.activeAbility ? domain.metadata.activeAbility.name : '-'}</div>
            <div class="tiny">Уровень / опыт: ${domain.metadata ? `${domain.metadata.level} / ${domain.metadata.experience}` : '-'}</div>
          </details>
          <button class="wallet-domain-action" data-domain-action="${domain.domain}">${state.selectedDomain === domain.domain ? 'Открыть колоду' : 'Выбрать домен'}</button>
        </div>
      `).join('');
    }

    window.selectDomain = async function selectDomain(domain) {
      await selectDeckDomain(domain);
    };

    function sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function nextFrame() {
      return new Promise((resolve) => requestAnimationFrame(() => resolve()));
    }

    function animateElement(element, keyframes, options) {
      return new Promise((resolve) => {
        const animation = element.animate(keyframes, options);
        animation.addEventListener('finish', resolve, { once: true });
      });
    }

    async function playPackSequence() {
      const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const targets = Array.from(packCards.querySelectorAll('.game-card'));
      if (!targets.length || prefersReduced) {
        packCards.classList.remove('sequence-prep');
        requestAnimationFrame(() => packCards.classList.add('reveal'));
        return;
      }

      const layer = document.createElement('div');
      layer.className = 'pack-sequence-layer';
      document.body.appendChild(layer);

      const packRect = foilPack.getBoundingClientRect();
      const startX = packRect.left + packRect.width * 0.5;
      const startY = packRect.top + packRect.height * 0.17;
      const centerX = window.innerWidth * 0.5;
      const centerY = window.innerHeight * 0.5;

      for (const [index, target] of targets.entries()) {
        const preview = document.createElement('article');
        preview.className = 'pack-preview-card';
        const previewCard = document.createElement('article');
        previewCard.className = 'game-card';
        previewCard.innerHTML = target.innerHTML;
        preview.appendChild(previewCard);
        preview.style.left = `${startX}px`;
        preview.style.top = `${startY}px`;
        preview.style.transform = 'perspective(1400px) translate(-50%, -50%) rotateY(0deg) scale(1)';
        preview.style.opacity = '1';
        layer.appendChild(preview);

        await nextFrame();
        preview.classList.add('focused');
        layer.classList.add('dimmed');
        await animateElement(preview, [
          {
            left: `${startX}px`,
            top: `${startY}px`,
            opacity: 0,
            transform: `perspective(1400px) translate(-50%, -50%) rotateY(${index % 2 === 0 ? 220 : -220}deg) scale(0.2)`
          },
          {
            left: `${centerX}px`,
            top: `${centerY}px`,
            opacity: 1,
            transform: 'perspective(1400px) translate(-50%, -50%) rotateY(0deg) scale(1.02)'
          }
        ], {
          duration: 900,
          easing: 'cubic-bezier(.16,.84,.2,1)',
          fill: 'forwards'
        });

        preview.style.left = `${centerX}px`;
        preview.style.top = `${centerY}px`;
        preview.style.opacity = '1';
        preview.style.transform = 'perspective(1400px) translate(-50%, -50%) rotateY(0deg) scale(1.02)';

        await sleep(1000);

        const rect = target.getBoundingClientRect();
        const targetX = rect.left + rect.width / 2;
        const targetY = rect.top + rect.height / 2;
        await animateElement(preview, [
          {
            left: `${centerX}px`,
            top: `${centerY}px`,
            opacity: 1,
            transform: 'perspective(1400px) translate(-50%, -50%) rotateY(0deg) scale(1.02)'
          },
          {
            left: `${targetX}px`,
            top: `${targetY}px`,
            opacity: 0.94,
            transform: `perspective(1400px) translate(-50%, -50%) rotateY(${index % 2 === 0 ? -180 : 180}deg) scale(0.44)`
          }
        ], {
          duration: 620,
          easing: 'cubic-bezier(.16,.84,.2,1)',
          fill: 'forwards'
        });

        target.classList.add('sequence-visible');
        preview.remove();
      }

      layer.classList.remove('dimmed');
      layer.remove();
      packCards.classList.remove('sequence-prep');
      packCards.classList.add('reveal');
    }

    async function renderPack(cards, total, cinematic = true) {
      const rarityOrderIndex = { basic: 0, rare: 1, epic: 2, mythic: 3, legendary: 4 };
      const orderedCards = [...cards].sort((a, b) => {
        const aRank = rarityOrderIndex[String(a.rarity_key || '').toLowerCase()] ?? 0;
        const bRank = rarityOrderIndex[String(b.rarity_key || '').toLowerCase()] ?? 0;
        if (aRank !== bRank) return aRank - bRank;
        return Number(a.slot || 0) - Number(b.slot || 0);
      });
      packCards.classList.remove('reveal', 'pack-emerge', 'sequence-prep');
      packCards.innerHTML = orderedCards.map((card) => `
        <article class="game-card">
          <div class="tiny">${card.rarity}</div>
          <h3>${card.title}</h3>
          <p>${card.domain}.ton • слот ${card.slot}</p>
          <div class="team-line"><span>Базовая сила</span><strong>${card.pool_value || card.base_power || 0}</strong></div>
          <div class="team-line"><span>Скилл</span><strong>${card.skill_name || '-'}</strong></div>
          <p>${card.ability}</p>
        </article>
      `).join('');
      packScoreLabel.textContent = `Вклад карт: ${total}`;
      refreshOneCardSelector();
      if (cinematic) {
        packCards.classList.add('sequence-prep');
        await playPackSequence();
      } else {
        packCards.classList.add('reveal');
      }
    }

    function showdownDeckMarkup(cards, fallbackCard) {
      const normalized = Array.isArray(cards) && cards.length
        ? cards
        : (fallbackCard ? [fallbackCard] : []);
      if (!normalized.length) {
        return '<div class="tiny">Колода недоступна</div>';
      }
      return normalized.map((card, index) => `
        <div class="showdown-card">
          <strong>${index + 1}. ${card.title || 'Карта'}</strong>
          <div class="tiny">${card.rarity || '-'}</div>
          <div class="tiny">Базовая сила: ${card.pool_value ?? card.base_power ?? card.score ?? 0}</div>
          <div class="tiny">Скилл: ${card.skill_name || '-'}</div>
        </div>
      `).join('');
    }

    function arenaDeckMarkup(cards, fallbackCard, side = 'player', activeSlot = null, featuredSlot = null, cosmetics = null) {
      const normalized = Array.isArray(cards) && cards.length
        ? cards
        : (fallbackCard ? [fallbackCard] : []);
      if (!normalized.length) {
        return '<div class="tiny">Колода недоступна</div>';
      }
      return normalized.map((card, index) => {
        const slot = Number(card.slot || index + 1);
        const isActive = Number(activeSlot || 0) === slot;
        const isFeatured = Number(featuredSlot || 0) === slot;
        return `
          <div class="arena-slot-card ${side === 'enemy' ? 'enemy-card' : 'player-card'} ${isActive ? 'active-slot' : ''} ${isFeatured ? 'featured-slot' : ''}" data-slot="${slot}" data-side="${side}" style="${battleCardStyle(cosmetics, side)}">
            <strong>${slot}. ${card.title || 'Карта'}</strong>
            <div class="arena-slot-meta">${card.rarity || '-'}</div>
            <div class="arena-slot-meta">Базовая сила: ${card.pool_value ?? card.base_power ?? card.score ?? 0}</div>
            <div class="arena-slot-meta">${card.skill_name || '-'}</div>
          </div>
        `;
      }).join('');
    }

    function battleArenaBackground(cosmetics) {
      const arenaKey = (((cosmetics || {}).arena || {}).key || '');
      const emoji = cosmeticEmojiSymbol(cosmetics);
      return giftArenaSurface(arenaKey, emoji);
    }

    function battleCardStyle(cosmetics, side = 'player') {
      const frameKey = (((cosmetics || {}).frame || {}).key || '');
      const backKey = (((cosmetics || {}).cardback || {}).key || '');
      const frameAsset = cosmeticAssetUrl('frame', frameKey);
      const backAsset = cosmeticAssetUrl('cardback', backKey);
      let border = side === 'player' ? 'rgba(83,246,184,0.34)' : 'rgba(255,122,134,0.3)';
      let glow = side === 'player' ? 'rgba(83,246,184,0.18)' : 'rgba(255,122,134,0.16)';
      if (frameKey.includes('stock')) {
        border = 'rgba(126, 137, 156, 0.46)';
        glow = 'rgba(94, 104, 122, 0.22)';
      }
      if (frameKey.includes('gold') || frameKey.includes('solar')) border = 'rgba(255,211,110,0.42)';
      if (frameKey.includes('void') || frameKey.includes('obsidian')) border = 'rgba(174,126,255,0.38)';
      if (frameKey.includes('crimson')) border = 'rgba(255,122,134,0.42)';
      if (backKey.includes('gold') || backKey.includes('script')) {
        glow = 'rgba(255,211,110,0.24)';
      } else if (backKey.includes('raspberry')) {
        glow = 'rgba(245, 155, 208, 0.24)';
      } else if (backKey.includes('chrome')) {
        glow = 'rgba(125, 225, 255, 0.22)';
      } else if (backKey.includes('frost')) {
        glow = 'rgba(191, 231, 255, 0.2)';
      } else if (backKey.includes('ember')) {
        glow = 'rgba(255, 138, 92, 0.22)';
      } else if (backKey.includes('emerald')) {
        glow = 'rgba(83,246,184,0.24)';
      } else if (backKey.includes('void')) {
        glow = 'rgba(174,126,255,0.24)';
      } else if (backKey.includes('glitch') || backKey.includes('signal')) {
        glow = 'rgba(188,126,255,0.24)';
      } else if (backKey.includes('tactical') || backKey.includes('black')) {
        glow = 'rgba(255,186,108,0.18)';
      }
      const base = giftCardbackSurface(backKey, cosmeticEmojiSymbol(cosmetics));
      const frameLayer = frameAsset ? `, url(${frameAsset}) center/100% 100% no-repeat` : '';
      return `border-color:${border}; background:${base}${frameLayer}; box-shadow:0 0 0 1px ${border}, 0 16px 32px ${glow}, inset 0 0 0 1px rgba(255,255,255,0.03); filter:saturate(1.12) contrast(1.04);`;
    }

    window.scrollSeasonPassTrack = function scrollSeasonPassTrack(target, dir) {
      const scroller = achievementsList ? achievementsList.querySelector(`.season-pass-scroll[data-pass-track="${target}"]`) : null;
      if (!scroller || !dir) return;
      const track = scroller.querySelector('.season-pass-track');
      const firstCard = track ? track.firstElementChild : null;
      const gap = track ? parseFloat(window.getComputedStyle(track).columnGap || window.getComputedStyle(track).gap || '12') : 12;
      const cardWidth = firstCard ? firstCard.getBoundingClientRect().width : 0;
      const step = Math.max(cardWidth + gap, Math.floor(scroller.clientWidth * 0.92), 220);
      const maxLeft = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
      const nextLeft = Math.max(0, Math.min(maxLeft, scroller.scrollLeft + Number(dir) * step));
      if (typeof scroller.scrollTo === 'function') {
        scroller.scrollTo({ left: nextLeft, behavior: 'smooth' });
      } else {
        scroller.scrollLeft = nextLeft;
      }
    };

    window.syncSeasonPassFromSlider = function syncSeasonPassFromSlider(slider) {
      if (!slider) return;
      const target = slider.dataset.passSlider;
      const scroller = document.querySelector(`.season-pass-scroll[data-pass-track="${target}"]`);
      if (!scroller) return;
      const maxLeft = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
      const ratio = Math.max(0, Math.min(100, Number(slider.value || 0))) / 100;
      const nextLeft = Math.max(0, Math.min(maxLeft, ratio * maxLeft));
      scroller.scrollLeft = nextLeft;
    };

    function battleTrailStyle(cosmetics) {
      const frameKey = (((cosmetics || {}).frame || {}).key || '');
      const backKey = (((cosmetics || {}).cardback || {}).key || '');
      const arenaKey = (((cosmetics || {}).arena || {}).key || '');
      const theme = cosmeticTheme('frame', frameKey || backKey || arenaKey);
      return theme && theme.glow ? theme.glow.replace(/0\\.\\d+\\)/, '0.78)') : 'rgba(188,126,255,0.78)';
    }

    async function syncSoloBattleState(sessionId) {
      if (!sessionId || !state.wallet) {
        return null;
      }
      const data = await api(`/api/solo-battle/status?wallet=${encodeURIComponent(state.wallet)}&session_id=${encodeURIComponent(sessionId)}`);
      return data.result || null;
    }

    function actionStickerSvg(actionKey) {
      if (actionKey === 'burst') {
        return `<span aria-hidden="true">⚔️</span>`;
      }
      if (actionKey === 'ability') {
        return `
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path fill="currentColor" d="M12 2.5 14.4 8l5.9.5-4.5 3.8 1.4 5.7L12 15l-5.2 3 1.4-5.7-4.5-3.8L9.6 8z"/>
          </svg>
        `;
      }
      return `
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path fill="currentColor" d="M12 2 19 5v6.2c0 5.2-3.2 9.4-7 10.8-3.8-1.4-7-5.6-7-10.8V5zm0 3.1L7.4 7v4.1c0 3.6 2 6.7 4.6 8 2.6-1.3 4.6-4.4 4.6-8V7z"/>
        </svg>
      `;
    }

    async function playRoundClashReveal(currentResult, nextResult, playerActionKey) {
      const activeLane = battleResult.querySelector('.arena-round-choice-slot.active');
      const arenaCore = battleResult.querySelector('.arena-core');
      if (!activeLane || !arenaCore) {
        return;
      }
      const currentRoundIndex = Number(currentResult && currentResult.interactive_round_index || 0);
      const playerCard = (currentResult.player_cards || [])[currentRoundIndex];
      const opponentCard = (currentResult.opponent_cards || [])[currentRoundIndex];
      const latestRound = Array.isArray(nextResult && nextResult.rounds) && nextResult.rounds.length
        ? nextResult.rounds[nextResult.rounds.length - 1]
        : null;
      if (!playerCard || !opponentCard || !latestRound) {
        return;
      }
      const opponentActionKey = latestRound.opponent_action || 'guard';
      const resultKey = latestRound.winner === 'player' ? 'win' : (latestRound.winner === 'opponent' ? 'lose' : 'draw');
      const laneRect = activeLane.getBoundingClientRect();
      const coreRect = arenaCore.getBoundingClientRect();
      const arenaShell = battleResult.querySelector('.arena-shell');
      const laneCenter = laneRect.left + laneRect.width / 2 - coreRect.left;
      const playerActiveSlot = Number(playerCard.slot || currentRoundIndex + 1);
      const opponentActiveSlot = Number(opponentCard.slot || currentRoundIndex + 1);
      const playerSource = battleResult.querySelector(`.arena-rail.player .arena-slot-card[data-slot="${playerActiveSlot}"].active-slot`) ||
        battleResult.querySelector(`.arena-rail.player .arena-slot-card[data-slot="${playerActiveSlot}"]`) ||
        battleResult.querySelector('.arena-rail.player .arena-slot-card.active-slot') ||
        battleResult.querySelector('.arena-rail.player .arena-slot-card');
      const enemySource = battleResult.querySelector(`.arena-rail.enemy .arena-slot-card[data-slot="${opponentActiveSlot}"].active-slot`) ||
        battleResult.querySelector(`.arena-rail.enemy .arena-slot-card[data-slot="${opponentActiveSlot}"]`) ||
        battleResult.querySelector('.arena-rail.enemy .arena-slot-card.active-slot') ||
        battleResult.querySelector('.arena-rail.enemy .arena-slot-card');
      if (!playerSource || !enemySource) {
        return;
      }
      const playerRect = playerSource.getBoundingClientRect();
      const enemyRect = enemySource.getBoundingClientRect();
      const compactClash = document.body.classList.contains('tma-app') || window.innerWidth <= 700;
      const playerCosmetics = (currentResult && currentResult.player_cosmetics) || {};
      const opponentCosmetics = (currentResult && currentResult.opponent_cosmetics) || {};
      const clashCardWidth = compactClash ? 56 : 138;
      const clashCardHeight = compactClash ? 82 : 196;
      const clashGap = compactClash ? 12 : 22;
      const clashLanePadding = compactClash ? 6 : 10;
      const laneTop = compactClash ? 18 : 24;
      const laneHeight = Math.max(140, coreRect.height - (compactClash ? 36 : 48));
      const laneTopBound = laneTop + (compactClash ? 6 : 10);
      const laneBottomBound = laneTop + laneHeight - (compactClash ? 6 : 10);
      const laneCenterY = laneTop + laneHeight / 2;
      const laneTargetLeft = Math.max(
        clashLanePadding,
        Math.min(laneCenter - clashCardWidth / 2, coreRect.width - clashCardWidth - clashLanePadding)
      );
      const playerTargetLeft = laneTargetLeft;
      const enemyTargetLeft = laneTargetLeft;
      let enemyTargetTop = laneCenterY - clashCardHeight;
      let playerTargetTop = laneCenterY;
      enemyTargetTop = Math.max(laneTopBound, enemyTargetTop);
      playerTargetTop = Math.min(laneBottomBound - clashCardHeight, playerTargetTop);
      if (playerTargetTop <= enemyTargetTop + clashCardHeight + clashGap) {
        enemyTargetTop = Math.max(laneTopBound, laneCenterY - clashCardHeight - clashGap);
        playerTargetTop = Math.min(laneBottomBound - clashCardHeight, laneCenterY);
      }
      if (playerTargetTop < enemyTargetTop) {
        const correctedEnemyTop = Math.max(laneTopBound, Math.min(enemyTargetTop, playerTargetTop));
        const correctedPlayerTop = Math.min(
          laneBottomBound - clashCardHeight,
          Math.max(playerTargetTop, correctedEnemyTop + clashCardHeight + Math.max(8, clashGap))
        );
        enemyTargetTop = correctedEnemyTop;
        playerTargetTop = correctedPlayerTop;
      }
      const playerAttack = playerActionKey === 'burst';
      const enemyAttack = opponentActionKey === 'burst';
      const playerPrepTop = playerAttack ? playerTargetTop - (compactClash ? 8 : 12) : playerTargetTop;
      const enemyPrepTop = enemyAttack ? enemyTargetTop + (compactClash ? 8 : 12) : enemyTargetTop;
      const enemyImpactTop = Math.max(laneTopBound, enemyTargetTop + (enemyAttack ? 8 : 4));
      const playerImpactTop = Math.min(laneBottomBound - clashCardHeight, playerTargetTop - (playerAttack ? 8 : 4));
      const playerImpactScale = playerAttack ? (compactClash ? 1.03 : 1.08) : 1.01;
      const enemyImpactScale = enemyAttack ? (compactClash ? 1.03 : 1.08) : 1.01;
      const playerImpactRotate = playerAttack ? '-8deg' : '2deg';
      const enemyImpactRotate = enemyAttack ? '8deg' : '-2deg';
      const playerRecoilY = playerAttack ? playerImpactTop + (compactClash ? 8 : 8) : playerTargetTop;
      const enemyRecoilY = enemyAttack ? enemyImpactTop - (compactClash ? 8 : 8) : enemyTargetTop;
      const playerRecoilScale = playerAttack ? 1.02 : 1;
      const enemyRecoilScale = enemyAttack ? 1.02 : 1;
      const impactCenterY = laneCenterY;
      const laneReveal = document.createElement('div');
      laneReveal.className = 'arena-lane-clash';
      laneReveal.style.setProperty('--clash-card-width', `${clashCardWidth}px`);
      laneReveal.style.setProperty('--clash-card-height', `${clashCardHeight}px`);
      activeLane.classList.add('clash-resolving');
      arenaCore.classList.add('clash-live');
      if (arenaShell) {
        arenaShell.classList.add('clash-live');
        arenaShell.classList.add('lane-clash-live');
      }
      const playerSourceVisibility = playerSource.style.visibility;
      const playerSourceOpacity = playerSource.style.opacity;
      const enemySourceVisibility = enemySource.style.visibility;
      const enemySourceOpacity = enemySource.style.opacity;
      const playerClone = playerSource.cloneNode(true);
      playerClone.className = `${playerClone.className} arena-lane-card player ${playerActionKey}`.trim();
      playerClone.classList.add('simplified');
      playerClone.innerHTML = '';
      playerClone.style.visibility = 'visible';
      playerClone.style.opacity = '1';
      playerClone.style.left = `${playerRect.left - coreRect.left}px`;
      const playerStartTop = compactClash
        ? Math.max(laneBottomBound - clashCardHeight, laneTop + laneHeight + 4)
        : Math.max(coreRect.height + 8, playerRect.top - coreRect.top);
      const enemyStartTop = compactClash
        ? Math.min(laneTopBound - clashCardHeight - 4, laneTop - clashCardHeight - 4)
        : Math.min(-clashCardHeight - 8, enemyRect.top - coreRect.top);
      playerClone.style.top = `${playerStartTop}px`;
      playerClone.style.width = `${clashCardWidth}px`;
      playerClone.style.height = `${clashCardHeight}px`;
      playerClone.style.cssText += `;${battleCardStyle(playerCosmetics, 'player')}`;
      playerClone.style.zIndex = '3';
      playerClone.insertAdjacentHTML('beforeend', `<div class="arena-action-sticker ${playerActionKey}">${actionStickerSvg(playerActionKey)}</div>`);
      const enemyClone = enemySource.cloneNode(true);
      enemyClone.className = `${enemyClone.className} arena-lane-card enemy ${opponentActionKey}`.trim();
      enemyClone.classList.add('simplified');
      enemyClone.innerHTML = '';
      enemyClone.style.visibility = 'visible';
      enemyClone.style.opacity = '1';
      enemyClone.style.left = `${enemyRect.left - coreRect.left}px`;
      enemyClone.style.top = `${enemyStartTop}px`;
      enemyClone.style.width = `${clashCardWidth}px`;
      enemyClone.style.height = `${clashCardHeight}px`;
      enemyClone.style.cssText += `;${battleCardStyle(opponentCosmetics, 'enemy')}`;
      enemyClone.style.zIndex = '2';
      enemyClone.insertAdjacentHTML('beforeend', `<div class="arena-action-sticker ${opponentActionKey}">${actionStickerSvg(opponentActionKey)}</div>`);
      playerSource.style.visibility = 'hidden';
      playerSource.style.opacity = '0';
      enemySource.style.visibility = 'hidden';
      enemySource.style.opacity = '0';
      const impactNode = document.createElement('div');
      impactNode.className = `arena-lane-impact ${resultKey}`;
      impactNode.style.left = `${laneTargetLeft + clashCardWidth / 2}px`;
      impactNode.style.top = `${impactCenterY}px`;
      impactNode.style.boxShadow = `0 0 0 18px ${battleTrailStyle(playerCosmetics)}22, 0 0 48px ${battleTrailStyle(playerCosmetics)}55`;
      impactNode.style.backgroundImage = 'radial-gradient(circle, rgba(216, 228, 255, 0.22), rgba(216, 228, 255, 0.02) 68%)';
      laneReveal.appendChild(playerClone);
      laneReveal.appendChild(enemyClone);
      laneReveal.appendChild(impactNode);
      arenaCore.appendChild(laneReveal);
      requestAnimationFrame(() => laneReveal.classList.add('visible'));
      const playerStartLeft = playerRect.left - coreRect.left;
      const enemyStartLeft = enemyRect.left - coreRect.left;
      playerClone.animate([
        { opacity: 0.96, transform: 'translate3d(0, 0, 0) scale(1)' },
        { opacity: 1, transform: `translate3d(${playerTargetLeft - playerStartLeft}px, ${playerPrepTop - playerStartTop}px, 0) scale(1.02)` },
        { opacity: 1, transform: `translate3d(${playerTargetLeft - playerStartLeft}px, ${playerImpactTop - playerStartTop}px, 0) rotate(${playerImpactRotate}) scale(${playerImpactScale})` },
        { opacity: 1, transform: `translate3d(${playerTargetLeft - playerStartLeft}px, ${playerRecoilY - playerStartTop}px, 0) rotate(0deg) scale(${playerRecoilScale})` }
      ], { duration: 700, easing: 'cubic-bezier(.16,.84,.2,1)', fill: 'forwards' });
      enemyClone.animate([
        { opacity: 0.96, transform: 'translate3d(0, 0, 0) scale(1)' },
        { opacity: 1, transform: `translate3d(${enemyTargetLeft - enemyStartLeft}px, ${enemyPrepTop - enemyStartTop}px, 0) scale(1.02)` },
        { opacity: 1, transform: `translate3d(${enemyTargetLeft - enemyStartLeft}px, ${enemyImpactTop - enemyStartTop}px, 0) rotate(${enemyImpactRotate}) scale(${enemyImpactScale})` },
        { opacity: 1, transform: `translate3d(${enemyTargetLeft - enemyStartLeft}px, ${enemyRecoilY - enemyStartTop}px, 0) rotate(0deg) scale(${enemyRecoilScale})` }
      ], { duration: 700, easing: 'cubic-bezier(.16,.84,.2,1)', fill: 'forwards' });
      window.setTimeout(() => impactNode.classList.add('visible'), 360);
      await sleep(700);
      playBattleFx(resultKey, 'round', impactNode);
      await sleep(620);
      laneReveal.classList.add('resolving');
      await sleep(260);
      laneReveal.remove();
      playerSource.style.visibility = playerSourceVisibility;
      playerSource.style.opacity = playerSourceOpacity;
      enemySource.style.visibility = enemySourceVisibility;
      enemySource.style.opacity = enemySourceOpacity;
      activeLane.classList.remove('clash-resolving');
      arenaCore.classList.remove('clash-live');
      if (arenaShell) {
        arenaShell.classList.remove('clash-live');
        arenaShell.classList.remove('lane-clash-live');
      }
    }

    async function handleInteractiveBattleChoice(actionKey, event = null, byTimeout = false) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      if (state.interactiveActionInFlight) {
        return;
      }
      const liveResult = state.lastResult || {};
      const sessionId = liveResult.interactive_session_id;
      const actionPanel = battleResult.querySelector('#interactive-battle-panel');
      const interactiveBattleStatus = battleResult.querySelector('#interactive-battle-status');
      const interactiveTimer = battleResult.querySelector('#interactive-timer');
      const interactiveActionButtons = Array.from(battleResult.querySelectorAll('.interactive-action-btn'));
      const activeButton = event && event.currentTarget ? event.currentTarget : interactiveActionButtons.find((node) => node.dataset.actionKey === actionKey);
      if (!sessionId || !state.wallet) {
        if (interactiveBattleStatus) {
          interactiveBattleStatus.textContent = 'Сессия боя потеряна. Обнови матч.';
        }
        return;
      }

      state.interactiveActionInFlight = true;
      queueTmaModeSync();
      clearInteractiveChoiceTimer();
      interactiveActionButtons.forEach((node) => {
        node.disabled = true;
        node.classList.remove('choice-ready');
      });
      if (activeButton) {
        activeButton.classList.add('choice-picked');
      }
      if (interactiveBattleStatus) {
        const meta = actionRuleMeta(actionKey);
        interactiveBattleStatus.textContent = byTimeout
          ? `Время вышло. Автовыбор: ${meta.ruLabel}.`
          : `Ты выбираешь: ${meta.ruLabel}.`;
      }
      await sleep(180);
      try {
        const data = await api('/api/solo-battle/action', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            session_id: sessionId,
            action: actionKey
          }
        });
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
        }
        const nextResult = data.result || {};
        await playRoundClashReveal(liveResult, nextResult, actionKey);
        nextResult.autostart_battle = true;
        state.lastResult = nextResult;
        state.interactiveActionInFlight = false;
        renderBattleResult(nextResult);
      } catch (error) {
        try {
          const synced = await syncSoloBattleState(sessionId);
          if (synced) {
            synced.autostart_battle = true;
            state.lastResult = synced;
            state.interactiveActionInFlight = false;
            renderBattleResult(synced);
            return;
          }
        } catch (syncError) {
          if (interactiveBattleStatus) {
            interactiveBattleStatus.textContent = syncError.message || error.message;
          }
        }
        interactiveActionButtons.forEach((node) => {
          node.disabled = false;
          node.classList.remove('choice-picked');
        });
        if (interactiveBattleStatus) {
          interactiveBattleStatus.textContent = error.message;
        }
        state.interactiveActionInFlight = false;
        startInteractiveChoiceTimer(interactiveTimer, () => handleInteractiveBattleChoice('guard', null, true), 350);
      }
    }

    function battleFlowRoundsMarkup(result) {
      const rounds = Array.isArray(result && result.rounds) ? result.rounds : [];
      if (!rounds.length) {
        return '<div class="tiny">Подробный ход боя пока недоступен.</div>';
      }
      const reasonChip = (label, value, kind = '') => {
        if (!value) return '';
        return `<span class="arena-decision-chip ${kind}">${label}: ${value}</span>`;
      };
      return `
        <div class="discipline-list">
          ${rounds.map((round, index) => {
            const roundClass = round.winner === 'player' ? 'win' : (round.winner === 'opponent' ? 'lose' : 'draw');
            const marker = round.winner === 'player' ? 'WIN' : (round.winner === 'opponent' ? 'LOSE' : 'DRAW');
            const whyLabel = round.winner === 'player' ? 'Почему победа' : (round.winner === 'opponent' ? 'Почему поражение' : 'Почему ничья');
            const playerCardTitle = round.player_card?.title || 'Твоя карта';
            const opponentCardTitle = round.opponent_card?.title || 'Карта соперника';
            const playerSlot = round.player_card?.slot || '-';
            const opponentSlot = round.opponent_card?.slot || '-';
            const playerStrategy = strategyMeta(round.player_strategy_key || 'balanced');
            const opponentStrategy = strategyMeta(round.opponent_strategy_key || 'balanced');
            const playerAction = actionRuleMeta(round.player_action || 'channel');
            const opponentAction = actionRuleMeta(round.opponent_action || 'channel');
            const playerActionClass = round.player_action || 'channel';
            const opponentActionClass = round.opponent_action || 'channel';
            const reasons = [
              round.player_action_note,
              round.player_domain_note,
              round.player_strategy_note,
              round.player_skill_note,
            ].filter(Boolean);
            const impactParts = [
              `база ${round.player_value || 0}/${round.opponent_value || 0}`,
              `прокачка ${round.player_boost || 0}/${round.opponent_boost || 0}`,
              `действие ${round.player_action_bonus || 0}/${round.opponent_action_bonus || 0}`,
              `стратегия ${round.player_strategy_bonus || 0}/${round.opponent_strategy_bonus || 0}`,
              `навык ${round.player_skill_bonus || 0}/${round.opponent_skill_bonus || 0}`,
              `домен ${round.player_domain_bonus || 0}/${round.opponent_domain_bonus || 0}`,
              `удача ${round.player_roll_bonus || 0}/${round.opponent_roll_bonus || 0}`,
            ];
            const playerFormula = [
              round.player_value || 0,
              round.player_boost || 0,
              round.player_action_bonus || 0,
              round.player_strategy_bonus || 0,
              round.player_skill_bonus || 0,
              round.player_featured_bonus || 0,
              round.player_domain_bonus || 0,
              round.player_roll_bonus || 0,
              round.player_swing || 0,
            ];
            const opponentFormula = [
              round.opponent_value || 0,
              round.opponent_boost || 0,
              round.opponent_action_bonus || 0,
              round.opponent_strategy_bonus || 0,
              round.opponent_skill_bonus || 0,
              round.opponent_featured_bonus || 0,
              round.opponent_domain_bonus || 0,
              round.opponent_roll_bonus || 0,
              round.opponent_swing || 0,
            ];
            const delay = index * 120;
            return `
              <div class="discipline-row round-clash ${roundClass} visible" style="animation-delay:${delay}ms;">
                <div class="arena-decision-roundline">
                  <strong>${round.label}</strong>
                  <span class="arena-decision-score">${round.player_total} : ${round.opponent_total} • ${marker}</span>
                </div>
                <div class="arena-clash-lane">
                  <div class="arena-clash-card player">
                    <div class="arena-clash-slot">Слот ${playerSlot}</div>
                    <div class="arena-clash-title">${playerCardTitle}</div>
                    <div class="arena-clash-meta">Твой ход: ${playerAction.ruLabel}</div>
                  </div>
                  <div class="arena-clash-versus">
                    <div class="arena-clash-badge">${playerAction.ruLabel} / ${opponentAction.ruLabel}</div>
                    <div class="arena-clash-winner">${marker}</div>
                  </div>
                  <div class="arena-clash-card enemy">
                    <div class="arena-clash-slot">Слот ${opponentSlot}</div>
                    <div class="arena-clash-title">${opponentCardTitle}</div>
                    <div class="arena-clash-meta">Ход соперника: ${opponentAction.ruLabel}</div>
                  </div>
                </div>
                <div class="arena-decision-chips">
                  <span class="arena-decision-chip featured" style="animation-delay:${delay + 20}ms;">Прокачка дисциплин: +${round.player_boost || 0} / +${round.opponent_boost || 0}</span>
                  <span class="arena-decision-chip action player ${playerActionClass}" style="animation-delay:${delay + 40}ms;">Твой выбор: ${playerAction.ruLabel}</span>
                  <span class="arena-decision-chip action enemy ${opponentActionClass}" style="animation-delay:${delay + 90}ms;">Соперник: ${opponentAction.ruLabel}</span>
                  <span class="arena-decision-chip strategy" style="animation-delay:${delay + 140}ms;">Стратегия: ${playerStrategy.label} / ${opponentStrategy.label}</span>
                  <span class="arena-decision-chip featured" style="animation-delay:${delay + 190}ms;">Тактическая карта: +${round.player_featured_bonus || 0} / +${round.opponent_featured_bonus || 0}</span>
                  <span class="arena-decision-chip outcome" style="animation-delay:${delay + 240}ms;">Итог раунда: ${marker}</span>
                  ${reasonChip(whyLabel, reasons.join(' • ') || 'Разница получилась из базовой силы, выбора действия и броска удачи.', 'outcome')}
                  ${reasonChip('Откуда перевес', impactParts.join(' • '), 'strategy')}
                  ${reasonChip('Формула игрока', `${playerFormula.join(' + ')} = ${round.player_total || 0}`, 'featured')}
                  ${reasonChip('Формула соперника', `${opponentFormula.join(' + ')} = ${round.opponent_total || 0}`, 'featured')}
                  ${(round.player_crit || round.opponent_crit) ? `<span class="arena-decision-chip outcome">${round.player_crit ? 'Твой crit' : ''}${round.player_crit && round.opponent_crit ? ' / ' : ''}${round.opponent_crit ? 'Crit соперника' : ''}</span>` : ''}
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    function renderBattleFlowView(result) {
      if (!battleFlowView) return;
      const safeResult = result || state.lastResult || {};
      const opponentLabel = safeResult.opponent_domain ? `${safeResult.opponent_domain}.ton` : 'бот';
      battleFlowView.innerHTML = `
        <div class="battleflow-shell">
          <div class="battleflow-summary">
            <div class="tiny"><strong>${safeResult.player_domain || '-'}.ton</strong> vs <strong>${opponentLabel}</strong></div>
            <div class="showdown-score">
              <span>${safeResult.player_score ?? 0}</span>
              <span>:</span>
              <span>${safeResult.opponent_score ?? 0}</span>
            </div>
          </div>
          ${battleFlowRoundsMarkup(safeResult)}
          <div class="actions">
            <button class="secondary" onclick="switchView('modes')">Назад к режимам</button>
          </div>
        </div>
      `;
    }

    function revealDisciplineRows(startDelay = 0, stepMs = 1000) {
      const rows = battleResult.querySelectorAll('.discipline-row');
      if (!rows.length) {
        return 0;
      }
      rows.forEach((row, index) => {
        const delay = startDelay + index * stepMs;
        setTimeout(() => {
          row.classList.add('visible');
        }, delay);
      });
      return startDelay + (rows.length - 1) * stepMs;
    }

    function playFinalClimax(resultKey, resultLabel) {
      const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const rows = Array.from(battleResult.querySelectorAll('.discipline-row'));
      if (prefersReduced) {
        return Promise.resolve();
      }
      return new Promise((resolve) => {
        const layer = document.createElement('div');
        layer.className = 'final-climax';
        const chips = rows.map((row, index) => {
          const chip = document.createElement('div');
          const rowClass = row.classList.contains('win') ? 'win' : (row.classList.contains('lose') ? 'lose' : 'draw');
          chip.className = `final-chip ${rowClass}`;
          const title = row.querySelector('span') ? row.querySelector('span').textContent.split(':')[0] : `Раунд ${index + 1}`;
          const score = row.querySelectorAll('span')[1] ? row.querySelectorAll('span')[1].textContent : '';
          chip.textContent = `${title} • ${score}`;
          const fromLeft = index % 2 === 0;
          chip.style.left = fromLeft ? '12%' : '88%';
          chip.style.top = `${18 + index * 12}%`;
          chip.style.opacity = '1';
          layer.appendChild(chip);
          return chip;
        });
        const core = document.createElement('div');
        core.className = `final-core ${resultKey}`;
        core.innerHTML = `
          <div class="final-boom"></div>
          <div class="final-label">${resultKey === 'draw' ? 'DRAW' : (resultKey === 'win' ? 'WIN' : 'LOSE')}</div>
          <div class="final-sub">${resultLabel || ''}</div>
          <div class="final-buttons">
            <button class="secondary" onclick="viewBattleFlow()">Смотреть ход боя</button>
            ${state.lastResult && state.lastResult.opponent_wallet && state.lastResult.opponent_wallet !== 'bot' ? '<button class="secondary" onclick="rematchLastOpponent()">Рематч</button>' : ''}
            <button onclick="repeatLastMode()">Играть ещё раз</button>
            <button class="secondary" onclick="openModes()">К режимам</button>
          </div>
        `;
        layer.appendChild(core);
        document.body.appendChild(layer);
        requestAnimationFrame(() => {
          layer.classList.add('shake');
          battleResult.classList.add('battle-live');
          setTimeout(() => battleResult.classList.remove('battle-live'), 980);
          if (chips.length) {
            chips.forEach((chip, index) => {
              setTimeout(() => {
                chip.classList.add('fly');
                playBattleFx(resultKey, 'round');
              }, index * 80);
            });
          } else {
            playBattleFx(resultKey, 'round', battleResult.querySelector('.arena-score-card'));
          }
        });
        setTimeout(() => {
          core.classList.add('visible');
          playBattleFx(resultKey, 'finish', battleResult.querySelector('.arena-score-card'));
        }, chips.length ? 860 : 180);
        setTimeout(() => {
          resolve();
        }, chips.length ? 2140 : 1480);
      });
    }

    function clearFinalClimax() {
      document.querySelectorAll('.final-climax').forEach((node) => node.remove());
    }

    function playBattleFx(resultKey = 'draw', phase = 'start', anchorNode = null) {
      const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (prefersReduced) return;

      const layer = document.createElement('div');
      layer.className = 'battle-fx-layer';
      let fxX = 50;
      let fxY = 52;
      if (anchorNode) {
        const rect = anchorNode.getBoundingClientRect();
        const x = ((rect.left + rect.width / 2) / window.innerWidth) * 100;
        const y = ((rect.top + rect.height / 2) / window.innerHeight) * 100;
        fxX = Math.max(8, Math.min(92, x));
        fxY = Math.max(8, Math.min(92, y));
      }
      layer.style.setProperty('--fx-x', `${fxX.toFixed(2)}%`);
      layer.style.setProperty('--fx-y', `${fxY.toFixed(2)}%`);

      const flash = document.createElement('div');
      flash.className = 'battle-flash';
      flash.style.background = `radial-gradient(circle at ${fxX.toFixed(2)}% ${fxY.toFixed(2)}%, rgba(255, 255, 255, 0.56), rgba(69, 215, 255, 0.18) 35%, transparent 65%)`;
      if (resultKey === 'lose') {
        flash.style.background = `radial-gradient(circle at ${fxX.toFixed(2)}% ${fxY.toFixed(2)}%, rgba(255,255,255,0.52), rgba(255,122,134,0.2) 35%, transparent 65%)`;
      } else if (resultKey === 'draw') {
        flash.style.background = `radial-gradient(circle at ${fxX.toFixed(2)}% ${fxY.toFixed(2)}%, rgba(255,255,255,0.5), rgba(255,211,110,0.2) 35%, transparent 65%)`;
      }
      layer.appendChild(flash);

      const ring = document.createElement('div');
      ring.className = 'battle-ring';
      if (resultKey === 'lose') {
        ring.style.borderColor = 'rgba(255, 122, 134, 0.75)';
        ring.style.boxShadow = '0 0 22px rgba(255, 122, 134, 0.4)';
      } else if (resultKey === 'draw') {
        ring.style.borderColor = 'rgba(255, 211, 110, 0.75)';
        ring.style.boxShadow = '0 0 22px rgba(255, 211, 110, 0.4)';
      }
      layer.appendChild(ring);

      const particleCount = phase === 'finish' ? 58 : (phase === 'round' ? 26 : 34);
      for (let i = 0; i < particleCount; i += 1) {
        const piece = document.createElement('div');
        piece.className = 'battle-particle';
        const angle = Math.random() * Math.PI * 2;
        const base = phase === 'finish' ? 240 : (phase === 'round' ? 110 : 170);
        const spread = phase === 'finish' ? 220 : (phase === 'round' ? 90 : 130);
        const dist = base + Math.random() * spread;
        const tx = Math.cos(angle) * dist;
        const ty = Math.sin(angle) * dist;
        const rotation = `${Math.floor(Math.random() * 360)}deg`;
        const duration = `${phase === 'round' ? 460 + Math.random() * 420 : 580 + Math.random() * 760}ms`;
        const delay = `${Math.random() * (phase === 'finish' ? 240 : (phase === 'round' ? 80 : 120))}ms`;
        if (resultKey === 'lose') {
          piece.style.background = 'linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,122,134,0.82))';
        } else if (resultKey === 'draw') {
          piece.style.background = 'linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,211,110,0.82))';
        }
        piece.style.setProperty('--tx', `${tx.toFixed(1)}px`);
        piece.style.setProperty('--ty', `${ty.toFixed(1)}px`);
        piece.style.setProperty('--rot', rotation);
        piece.style.setProperty('--dur', duration);
        piece.style.setProperty('--delay', delay);
        layer.appendChild(piece);
      }

      document.body.appendChild(layer);
      setTimeout(() => layer.remove(), phase === 'finish' ? 1900 : (phase === 'round' ? 980 : 1300));
    }

    function showMatchIntro(title) {
      clearInteractiveChoiceTimer();
      clearBattleAutostartTimer();
      clearFinalClimax();
      battleResult.className = 'result-box duel-anim showdown-fullscreen';
      battleResult.style.display = 'block';
      document.body.classList.add('showdown-open');
      battleResult.scrollTop = 0;
      battleResult.innerHTML = `
        <section class="showdown-center">
          <h3>${title}</h3>
          <div class="showdown-score"><span>?</span><span>:</span><span>?</span></div>
          <p class="muted">Подготавливаем колоды и дисциплины. Сейчас начнётся разбор по раундам.</p>
        </section>
      `;
    }

    function setBattleLaunchInFlight(active) {
      state.battleLaunchInFlight = Boolean(active);
      battleResult.querySelectorAll('.result-actions button').forEach((button) => {
        if ((button.textContent || '').includes('Играть ещё раз')) {
          button.disabled = Boolean(active);
          button.style.pointerEvents = active ? 'none' : '';
          button.style.opacity = active ? '0.6' : '';
        }
      });
    }

    function resetBattleStage() {
      clearInteractiveChoiceTimer();
      clearBattleAutostartTimer();
      clearFinalClimax();
      battleResult.className = 'result-box';
      battleResult.style.display = 'none';
      battleResult.innerHTML = '';
      inviteResult.className = 'result-box';
      inviteResult.style.display = 'none';
      inviteResult.innerHTML = '';
      document.body.classList.remove('showdown-open');
      document.querySelectorAll('.battle-fx-layer').forEach((node) => node.remove());
    }

    function renderBattleResult(result) {
      clearInteractiveChoiceTimer();
      clearBattleAutostartTimer();
      setBattleLaunchInFlight(false);
      state.lastReplayTapAt = 0;
      battleResult.className = 'result-box';
      battleResult.style.display = 'block';
      battleResult.classList.add('duel-anim');
      if (result.kind === 'team') {
        document.body.classList.remove('showdown-open');
        battleResult.innerHTML = `
          <h3>Командный матч завершён</h3>
          <div class="team-line"><strong>${result.teams[0].name}</strong><strong>${result.teams[0].score}</strong></div>
          <div class="team-line"><strong>${result.teams[1].name}</strong><strong>${result.teams[1].score}</strong></div>
          <p class="muted">Победитель: ${result.winner}</p>
          ${result.teams.map((team) => `
            <div style="margin-top:12px;">
              <strong>${team.name}</strong>
              ${team.players.map((player) => `
                <div class="team-line tiny"><span>${player.username} • ${player.domain}.ton</span><strong>${player.deck_score}</strong></div>
              `).join('')}
            </div>
          `).join('')}
          <div class="result-actions">
            <button class="secondary" onclick="viewBattleFlow()">Смотреть ход боя</button>
            <button onclick="repeatLastMode()">Играть ещё раз</button>
            <button class="secondary" onclick="openModes()">К режимам</button>
          </div>
        `;
      } else {
        const ratingLine = result.rating_after !== undefined
          ? `<div class="team-line"><span>Рейтинг</span><strong>${result.rating_before} → ${result.rating_after}</strong></div>`
          : '';
        const opponentLabel = result.opponent_domain ? `${result.opponent_domain}.ton` : 'бот';
        const resultKey = result.result || (result.result_label === 'Победа' ? 'win' : (result.result_label === 'Поражение' ? 'lose' : 'draw'));
        const selectedStrategy = strategyMeta(result.strategy_key || 'balanced');
        const totalRounds = result.interactive_total_rounds || 5;
        const activeRoundNumber = Math.min((result.interactive_round_index || 0) + 1, totalRounds);
        const compactArena = window.innerWidth <= 920;
        const arenaLanes = compactArena
          ? [
              { percent: 16, x: 160 },
              { percent: 33, x: 330 },
              { percent: 50, x: 500 },
              { percent: 67, x: 670 },
              { percent: 84, x: 840 },
            ]
          : [
              { percent: 10, x: 100 },
              { percent: 30, x: 300 },
              { percent: 50, x: 500 },
              { percent: 70, x: 700 },
              { percent: 90, x: 900 },
            ];
        const interactiveActionKeys = result.interactive_available_actions || ['burst', 'guard'];
        const activeAbilityName = result.interactive_active_ability && result.interactive_active_ability.name ? result.interactive_active_ability.name : 'Базовый режим';
        const activeAbilityCooldownMax = Math.max(1, Number((result.interactive_active_ability && result.interactive_active_ability.cooldown) || 0) || 1);
        const activeAbilityChargesMax = Math.max(1, Number((result.interactive_active_ability && result.interactive_active_ability.charges) || 0) || 1);
        const activeAbilityCooldownNow = Number((result.interactive_ability_state && result.interactive_ability_state.cooldown_remaining) || 0);
        const activeAbilityChargesNow = Number((result.interactive_ability_state && result.interactive_ability_state.charges_remaining) || 0);
        const energyNow = Number(result.interactive_energy || 0);
        const tutorialMeta = result.tutorial || null;
        const tutorialCurrentTip = tutorialMeta && (tutorialMeta.current_tip || ((tutorialMeta.tips || [])[Math.min(result.interactive_round_index || 0, Math.max((tutorialMeta.tips || []).length - 1, 0))])) || null;
        const tutorialLegendMarkup = tutorialMeta && tutorialMeta.active
          ? tutorialActionLegendHtml(tutorialMeta, Number(result.interactive_round_index || 0), result)
          : '';
        const energyFill = `${Math.max(0, Math.min(100, (energyNow / 3) * 100))}%`;
        const cooldownFill = `${Math.max(0, Math.min(100, (activeAbilityCooldownNow / activeAbilityCooldownMax) * 100))}%`;
        const chargesFill = `${Math.max(0, Math.min(100, (activeAbilityChargesNow / activeAbilityChargesMax) * 100))}%`;
        const rewardSummary = result.reward_summary || (state.playerProfile && state.playerProfile.rewards) || null;
        const playerCosmetics = result.player_cosmetics || (rewardSummary && rewardSummary.equipped_cosmetics) || {};
        const opponentCosmetics = result.opponent_cosmetics || {};
        const battleArenaCosmetic = result.battle_arena_cosmetic && result.battle_arena_cosmetic.key
          ? result.battle_arena_cosmetic
          : ((playerCosmetics || {}).arena || null);
        const battleArenaCosmetics = {
          ...(playerCosmetics || {}),
          ...(battleArenaCosmetic ? {arena: battleArenaCosmetic} : {}),
        };
        const rewardGain = result.reward_gain || {};
        const rewardParts = [];
        if (Number(rewardGain.pack_shards || 0) > 0) rewardParts.push(`осколки +${Number(rewardGain.pack_shards || 0)}`);
        if (Number(rewardGain.rare_tokens || 0) > 0) rewardParts.push(`редкие +${Number(rewardGain.rare_tokens || 0)}`);
        if (Number(rewardGain.lucky_tokens || 0) > 0) rewardParts.push(`lucky +${Number(rewardGain.lucky_tokens || 0)}`);
        const rewardLine = resultKey === 'win' && rewardParts.length ? `<div class="battle-reward-line">Награда: <strong>${rewardParts.join(' • ')}</strong></div>` : '';
        const battleHeader = rewardSummary ? `
          <div class="showdown-header">
            <div class="tiny"><strong>Валюта</strong> • осколки ${Number(rewardSummary.pack_shards || 0)} • редкие ${Number(rewardSummary.rare_tokens || 0)} • lucky ${Number(rewardSummary.lucky_tokens || 0)}</div>
          </div>
        ` : '';
        const interactivePanel = result.interactive_session_id
          ? `
              <div class="arena-round-choice-strip">
                ${Array.from({ length: totalRounds }, (_, index) => {
                  const roundNumber = index + 1;
                  const isActive = result.interactive_live && roundNumber === activeRoundNumber;
                  const isResolved = !result.interactive_live || roundNumber < activeRoundNumber;
                  const roundResult = Array.isArray(result.rounds) ? result.rounds[index] : null;
                  const roundOutcomeClass = roundResult?.winner === 'player' ? 'win' : (roundResult?.winner === 'opponent' ? 'lose' : 'draw');
                  const roundOutcomeLabel = roundResult?.winner === 'player' ? 'WIN' : (roundResult?.winner === 'opponent' ? 'LOSE' : (roundResult ? 'DRAW' : 'Ждёт'));
                  const left = (arenaLanes[index] && arenaLanes[index].percent) || 50;
                  return `
                    <div class="arena-round-choice-slot ${isActive ? 'active' : ''} ${isResolved ? 'resolved' : ''}" style="left:${left}%;">
                      <div class="arena-round-marker"></div>
                      ${isActive ? '' : `<div class="arena-round-state ${isResolved ? roundOutcomeClass : ''}">${roundOutcomeLabel}</div>`}
                    </div>
                  `;
                }).join('')}
              </div>
            `
          : '';
        const interactiveDock = result.interactive_live
          ? `
              <div class="arena-battle-dock">
                <div class="interactive-battle-panel" id="interactive-battle-panel">
                  <div class="interactive-battle-head">
                    <div class="interactive-battle-title">Раунд ${activeRoundNumber}</div>
                    <div class="interactive-timer" id="interactive-timer">5 c</div>
                  </div>
                  ${tutorialMeta && tutorialCurrentTip ? `
                    <div class="tutorial-tip-badge">${tutorialCurrentTip.title || 'Подсказка'}</div>
                    <div class="user-item" style="margin-bottom:10px;">
                      <strong>${tutorialCurrentTip.title || 'Подсказка'}</strong>
                      <div class="tiny">${tutorialCurrentTip.body || ''}</div>
                    </div>
                  ` : ''}
                  <div class="interactive-battle-prompt" id="interactive-battle-status">${result.interactive_hint || 'Выбери действие'}</div>
                  ${tutorialLegendMarkup}
                  <div class="interactive-battle-actions" style="grid-template-columns: repeat(${Math.max(interactiveActionKeys.length, 1)}, minmax(0, 1fr));">
                    ${interactiveActionKeys.map((key) => {
                      const meta = actionRuleMeta(key);
                      return `<button type="button" class="interactive-action-btn ${key}" data-action-key="${key}" onclick="handleInteractiveBattleChoice('${key}', event)">${meta.ruLabel}</button>`;
                    }).join('')}
                  </div>
                  ${tutorialMeta && tutorialMeta.skip_allowed ? `<div class="actions" style="margin-top:10px;"><button class="secondary" id="skip-live-tutorial-btn">Пропустить туториал</button></div>` : ''}
                </div>
              </div>
            `
          : '';
        const playerActiveSlot = result.interactive_live
          ? Number((result.player_cards || [])[Math.min(result.interactive_round_index || 0, Math.max((result.player_cards || []).length - 1, 0))]?.slot || 0)
          : Number(result.player_featured_card?.slot || result.player_card?.slot || result.rounds?.[Math.max((result.rounds?.length || 1) - 1, 0)]?.player_card?.slot || 0);
        const opponentActiveSlot = result.interactive_live
          ? Number((result.opponent_cards || [])[Math.min(result.interactive_round_index || 0, Math.max((result.opponent_cards || []).length - 1, 0))]?.slot || 0)
          : Number(result.opponent_featured_card?.slot || result.opponent_card?.slot || result.rounds?.[Math.max((result.rounds?.length || 1) - 1, 0)]?.opponent_card?.slot || 0);
        const playerArenaDeck = arenaDeckMarkup(result.player_cards, result.player_card, 'player', playerActiveSlot, result.player_featured_card?.slot || result.selected_slot, playerCosmetics);
        const opponentArenaDeck = arenaDeckMarkup(result.opponent_cards, result.opponent_card, 'enemy', opponentActiveSlot, result.opponent_featured_card?.slot, opponentCosmetics);
        const resourceBarMarkup = result.interactive_session_id ? `
          <div class="arena-player-resource-bar">
            <div class="arena-resource-pill mana" style="--fill:${energyFill};">
              <div class="arena-resource-topline"><span>Мана</span><strong>${energyNow}/3</strong></div>
              <div class="arena-resource-barline"></div>
              <div class="arena-resource-caption">Доступно действий: ${interactiveActionKeys.length}</div>
            </div>
            <div class="arena-resource-pill cooldown" style="--fill:${cooldownFill};">
              <div class="arena-resource-topline"><span>КД</span><strong>${activeAbilityCooldownNow}</strong></div>
              <div class="arena-resource-barline"></div>
              <div class="arena-resource-caption">${activeAbilityCooldownNow > 0 ? `Осталось ходов: ${activeAbilityCooldownNow}` : 'Способность готова'}</div>
            </div>
            <div class="arena-resource-pill ability" style="--fill:${chargesFill};">
              <div class="arena-resource-topline"><span>Заряды</span><strong>${activeAbilityChargesNow}</strong></div>
              <div class="arena-resource-barline"></div>
              <div class="arena-resource-caption">${activeAbilityName}</div>
            </div>
          </div>
        ` : '';
        const arenaRoutes = `
          <div class="arena-route-overlay" aria-hidden="true">
            <svg viewBox="0 0 1000 440" preserveAspectRatio="none">
              ${arenaLanes.map((lane, index) => {
                const slot = index + 1;
                const isActive = slot === playerActiveSlot || slot === opponentActiveSlot;
                const laneClass = `arena-route-path ${slot % 2 === 0 ? 'alt' : ''} ${isActive ? 'active' : ''}`.trim();
                return `
                  <path class="${laneClass}" d="M ${lane.x} 0 L ${lane.x} 440" />
                `;
              }).join('')}
            </svg>
          </div>
        `;
        state.lastReplayMode = result.mode || (result.mode_title === 'Матч с ботом' ? 'bot' : (result.mode_title === 'Рейтинговый матч' ? 'ranked' : 'casual'));
        battleResult.classList.add('showdown-fullscreen');
        battleResult.classList.remove('result-win', 'result-lose', 'result-draw', 'battle-live');
        battleResult.classList.add(resultKey === 'win' ? 'result-win' : (resultKey === 'lose' ? 'result-lose' : 'result-draw'));
        document.body.classList.add('showdown-open');
        battleResult.scrollTop = 0;
        const immediateInteractiveOutcome = Boolean(result.interactive_session_id && !result.interactive_live);
        const hideLiveScoreCard = Boolean(result.interactive_live && (!Array.isArray(result.rounds) || !result.rounds.length));
        const outcomeClass = immediateInteractiveOutcome ? '' : 'delayed-outcome';
        battleResult.innerHTML = `
          ${battleHeader}
          <section class="showdown-main arena-board">
            <div class="arena-shell">
              <div class="arena-rail enemy">
                <div class="tiny"><strong>Колода соперника</strong> • ${opponentLabel}</div>
                <div class="arena-deck-grid">
                  ${opponentArenaDeck}
                </div>
              </div>
              <div class="arena-core" style="background:${battleArenaBackground(battleArenaCosmetics)}; ${battleArenaUiStyle(battleArenaCosmetics)};">
                ${arenaRoutes}
                <div class="arena-choice-hub">
                  <div class="prebattle-stage arena-choice-panel" id="prebattle-stage">
                    <div class="tiny" id="prebattle-ready-status">Колоды готовы. Нажми "Готов".</div>
                    ${tutorialMeta && tutorialMeta.active ? `
                      <div class="tutorial-prebattle-guide" style="margin-top:10px;">
                        <div class="tiny"><strong>Порядок колоды:</strong> снизу твои карты, сверху карты бота. Туториал ведёт по раундам слева направо.</div>
                        <div class="tiny"><strong>Тактическая карта:</strong> выбери слот и запомни его. В 3-м раунде подсказка поведёт именно к ней.</div>
                        <div class="tiny"><strong>Ресурсы:</strong> Блок стоит 1, Натиск 2, Способность 3 маны.</div>
                      </div>
                    ` : ''}
                    <div class="row" style="margin-top:10px;">
                      <select id="prebattle-tactical-slot">
                        ${(result.player_cards || []).map((card) => `
                          <option value="${card.slot}" ${Number((result.selected_slot || result.player_featured_card?.slot || 0)) === Number(card.slot) ? 'selected' : ''}>
                            Слот ${card.slot}: ${card.title} • ${card.skill_name || 'скилл'}
                          </option>
                        `).join('')}
                      </select>
                    </div>
                    <div class="row" style="margin-top:10px;">
                      <select id="prebattle-strategy">
                        ${['attack_boost', 'defense_boost', 'energy_boost', 'balanced'].map((key) => {
                          const meta = strategyMeta(key);
                          return `<option value="${key}" ${String(result.strategy_key || 'balanced') === key ? 'selected' : ''}>${meta.label}</option>`;
                        }).join('')}
                      </select>
                    </div>
                    <div class="tiny" id="prebattle-strategy-help" style="text-align:center;"><strong>${selectedStrategy.label}:</strong> ${selectedStrategy.description}</div>
                    <div class="tiny" id="prebattle-action-help">${result.player_featured_card ? skillCounterText(result.player_featured_card) : 'Тактическая карта сильнее всего влияет на раунд.'}</div>
                    <div class="showdown-entry-actions">
                      <button id="start-battle-btn">Готов</button>
                      <button class="secondary" onclick="openModes()">К режимам</button>
                    </div>
                  </div>
                  <div class="battle-stage" id="battle-stage">
                    ${interactivePanel}
                    ${interactiveDock}
                    <div class="arena-score-card ${outcomeClass} ${hideLiveScoreCard ? 'prestart-hidden' : ''}">
                      <div class="showdown-score">
                        <span class="count-up" data-count-to="${result.player_score}">0</span>
                        <span>:</span>
                        <span class="count-up" data-count-to="${result.opponent_score}">0</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="arena-rail player">
                <div class="tiny"><strong>Колода пользователя</strong> • ${result.player_domain}.ton</div>
                <div class="arena-deck-grid">
                  ${playerArenaDeck}
                </div>
                ${resourceBarMarkup}
              </div>
            </div>
          </section>
          <div class="result-actions delayed-outcome post-actions">
            ${ratingLine ? `<div class="tiny" style="width:100%; text-align:center;">${result.rating_before} → ${result.rating_after}</div>` : ''}
            ${rewardLine}
            ${result.tutorial && result.tutorial.completion_prompt ? `<div class="battle-reward-line">${result.tutorial.completion_prompt}</div>` : ''}
            <button class="secondary" onclick="viewBattleFlow()">Смотреть ход боя</button>
            ${result.opponent_wallet && result.opponent_wallet !== 'bot' ? '<button class="secondary" onclick="rematchLastOpponent()">Рематч</button>' : ''}
            ${result.mode === 'tutorial' && result.result === 'win' ? `<button onclick="launchRecommendedMode('casual')">В обычный бой</button><button class="secondary" onclick="launchRecommendedMode('ranked')">В рейтинг</button>` : ''}
            <button onclick="repeatLastMode()">Играть ещё раз</button>
            <button class="secondary" onclick="openModes()">К режимам</button>
          </div>
        `;

        let liveResult = result;
        const startBtn = battleResult.querySelector('#start-battle-btn');
        const prebattleReadyStatus = battleResult.querySelector('#prebattle-ready-status');
        const prebattleTacticalSlot = battleResult.querySelector('#prebattle-tactical-slot');
        const prebattleStrategy = battleResult.querySelector('#prebattle-strategy');
        const prebattleStrategyHelp = battleResult.querySelector('#prebattle-strategy-help');
        const prebattleActionHelp = battleResult.querySelector('#prebattle-action-help');
        const prebattleStage = battleResult.querySelector('#prebattle-stage');
        const showdownMain = battleResult.querySelector('.showdown-main');
        const interactiveBattlePanel = battleResult.querySelector('#interactive-battle-panel');
        const interactiveBattleStatus = battleResult.querySelector('#interactive-battle-status');
        const interactiveTimer = battleResult.querySelector('#interactive-timer');
        const skipLiveTutorialBtn = battleResult.querySelector('#skip-live-tutorial-btn');
        const wireInteractiveBattle = () => {
          const rows = Array.from(battleResult.querySelectorAll('.discipline-row'));
          rows.forEach((row) => row.classList.add('visible'));
          animateScoreCounters(battleResult);
          setScoreCountersInstant(battleResult);
          if (!liveResult.interactive_live || !interactiveBattlePanel) {
            if (!liveResult.interactive_live) {
              const showInteractiveOutcome = async () => {
                await playFinalClimax(resultKey, result.result_label);
                battleResult.querySelectorAll('.delayed-outcome').forEach((node) => node.classList.add('visible'));
                const actions = battleResult.querySelector('.result-actions');
                if (actions) {
                  actions.classList.add('visible');
                }
              };
              showInteractiveOutcome();
            }
            return;
          }
          state.interactiveActionInFlight = false;
          focusBattleChoiceMenu(interactiveBattlePanel);
          if (interactiveBattleStatus) {
            interactiveBattleStatus.textContent = 'Выбери действие';
          }
          startInteractiveChoiceTimer(interactiveTimer, () => handleInteractiveBattleChoice('guard', null, true), 850);
        };
        if (result.battle_session_id && prebattleStage) {
          prebattleStage.classList.add('accept-pop');
          setTimeout(() => prebattleStage.classList.remove('accept-pop'), 760);
          focusBattleSetupPanel(prebattleStage);
        } else if (result.battle_session_id && showdownMain) {
          showdownMain.classList.add('accept-pop');
          setTimeout(() => showdownMain.classList.remove('accept-pop'), 760);
        }
        if (prebattleTacticalSlot) {
          prebattleTacticalSlot.addEventListener('change', () => {
            const card = (liveResult.player_cards || []).find((item) => Number(item.slot) === Number(prebattleTacticalSlot.value));
            if (prebattleActionHelp && card) {
              prebattleActionHelp.textContent = `${skillCounterText(card)}`;
            }
          });
        }
        if (prebattleStrategy) {
          prebattleStrategy.addEventListener('change', () => {
            const meta = strategyMeta(prebattleStrategy.value);
            if (prebattleStrategyHelp) {
              prebattleStrategyHelp.innerHTML = `<strong>${meta.label}:</strong> ${meta.description}`;
            }
          });
        }
        if (startBtn) {
          startBtn.addEventListener('click', async () => {
            queueTmaModeSync();
            const launchBattle = () => {
              startBtn.disabled = true;
              startBtn.textContent = 'Бой идёт...';
              const prebattle = battleResult.querySelector('#prebattle-stage');
              const battleStage = battleResult.querySelector('#battle-stage');
              if (prebattle) {
                prebattle.classList.add('hidden');
              }
              if (battleStage) {
                battleStage.classList.add('visible');
              }
              if (liveResult.interactive_session_id) {
                focusBattleChoiceMenu(interactiveBattlePanel);
                wireInteractiveBattle();
                return;
              }
              const finalDelay = revealDisciplineRows(0, 1000);
              const showOutcome = async () => {
                await playFinalClimax(resultKey, result.result_label);
                battleResult.querySelectorAll('.delayed-outcome').forEach((node) => node.classList.add('visible'));
                animateScoreCounters(battleResult);
              };
              if (finalDelay > 0) {
                setTimeout(() => { showOutcome(); }, finalDelay);
              } else {
                showOutcome();
              }
            };

            if (!liveResult.requires_ready || !liveResult.battle_session_id || !liveResult.opponent_wallet || !state.wallet) {
              launchBattle();
              return;
            }

            startBtn.disabled = true;
            startBtn.textContent = 'Готов';
            if (prebattleReadyStatus) {
              prebattleReadyStatus.textContent = 'Ты готов. Ожидание соперника...';
            }

            const sessionId = liveResult.battle_session_id;
            const pollReadyStatus = async () => {
              try {
                const poll = await api(`/api/battle-ready/status?wallet=${encodeURIComponent(state.wallet)}&session_id=${encodeURIComponent(sessionId)}`);
                const st = poll.status || {};
                if (prebattleReadyStatus) {
                  prebattleReadyStatus.textContent = `Готовы: ${st.ready_count || 1}/2`;
                }
                if (st.started) {
                  if (st.payload) {
                    state.lastResult = st.payload;
                    renderBattleResult(st.payload);
                    const autoStartBtn = battleResult.querySelector('#start-battle-btn');
                    if (autoStartBtn) {
                      autoStartBtn.click();
                    }
                    return;
                  }
                  launchBattle();
                  return;
                }
                setTimeout(pollReadyStatus, 900);
	              } catch (error) {
	                if (prebattleReadyStatus) {
	                  prebattleReadyStatus.textContent = `Проблема связи: ${error.message}. Повторяем...`;
	                }
	                setTimeout(pollReadyStatus, 1200);
	              }
	            };

            api('/api/battle-ready', {
              method: 'POST',
              body: {
                wallet: state.wallet,
                session_id: sessionId,
                selected_slot: Number(prebattleTacticalSlot && prebattleTacticalSlot.value ? prebattleTacticalSlot.value : 0),
                strategy_key: prebattleStrategy && prebattleStrategy.value ? prebattleStrategy.value : (liveResult.strategy_key || 'balanced')
              }
            }).then((readyData) => {
              const st = readyData.status || {};
              if (prebattleReadyStatus) {
                prebattleReadyStatus.textContent = `Готовы: ${st.ready_count || 1}/2`;
              }
              if (st.started) {
                if (st.payload) {
                  state.lastResult = st.payload;
                  renderBattleResult(st.payload);
                  const autoStartBtn = battleResult.querySelector('#start-battle-btn');
                  if (autoStartBtn) {
                    autoStartBtn.click();
                  }
                  return;
                }
                launchBattle();
                return;
              }
              pollReadyStatus();
	            }).catch((error) => {
	              (async () => {
	                try {
	                  const poll = await api(`/api/battle-ready/status?wallet=${encodeURIComponent(state.wallet)}&session_id=${encodeURIComponent(sessionId)}`);
	                  const st = poll.status || {};
	                  if (prebattleReadyStatus) {
	                    prebattleReadyStatus.textContent = `Готовы: ${st.ready_count || 1}/2`;
	                  }
	                  if (st.ready_self || Number(st.ready_count || 0) > 0) {
	                    startBtn.disabled = true;
	                    startBtn.textContent = 'Готов';
	                    pollReadyStatus();
	                    return;
	                  }
	                } catch (_) {
	                }
	                startBtn.disabled = false;
	                startBtn.textContent = 'Готов';
	                if (prebattleReadyStatus) {
	                  prebattleReadyStatus.textContent = error.message;
	                }
	              })();
	            });
          });
        }
        if (skipLiveTutorialBtn) {
          bindFunctionalControl(skipLiveTutorialBtn, skipTutorialBattle);
        }
        if (result.autostart_battle && startBtn) {
          battleAutostartTimer = window.setTimeout(() => {
            battleAutostartTimer = null;
            if (document.body.contains(startBtn)) {
              startBtn.click();
            }
          }, 120);
        }
        if (result.tutorial && result.tutorial.active) {
          applyTutorialVisualFocus(result);
        }
      }
    }

    function animateScoreCounters(container) {
      const counters = container.querySelectorAll('.count-up');
      if (!counters.length) return;
      const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      counters.forEach((node) => {
        const target = Number(node.dataset.countTo || '0');
        if (!Number.isFinite(target)) {
          node.textContent = '0';
          return;
        }
        if (prefersReduced) {
          node.textContent = String(target);
          return;
        }
        const start = performance.now();
        const duration = 760;
        function step(now) {
          const progress = Math.min(1, (now - start) / duration);
          const eased = 1 - Math.pow(1 - progress, 3);
          node.textContent = String(Math.round(target * eased));
          if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      });
    }

    function setScoreCountersInstant(container) {
      const counters = container.querySelectorAll('.count-up');
      if (!counters.length) return;
      counters.forEach((node) => {
        const target = Number(node.dataset.countTo || '0');
        node.textContent = Number.isFinite(target) ? String(target) : '0';
      });
    }

    function focusBattleChoiceMenu(panel) {
      if (!panel) return;
      requestAnimationFrame(() => {
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
      });
      panel.classList.remove('menu-live');
      void panel.offsetWidth;
      panel.classList.add('menu-live');
      const buttons = Array.from(panel.querySelectorAll('.interactive-action-btn'));
      buttons.forEach((button, index) => {
        button.classList.remove('choice-ready', 'choice-picked');
      });
    }

    function focusBattleSetupPanel(panel) {
      if (!panel) return;
      requestAnimationFrame(() => {
        panel.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
      });
    }

    async function openModes() {
      await prepareFunctionalInteraction();
      clearInteractiveChoiceTimer();
      clearFinalClimax();
      document.body.classList.remove('showdown-open');
      battleResult.className = 'result-box';
      battleResult.style.display = 'none';
      inviteResult.style.display = 'none';
      switchView('modes');
      resetModeChoice('');
    }

    async function viewBattleFlow() {
      await prepareFunctionalInteraction();
      clearFinalClimax();
      if (!state.lastResult) return;
      battleResult.className = 'result-box';
      battleResult.style.display = 'none';
      document.body.classList.remove('showdown-open');
      renderBattleFlowView(state.lastResult);
      switchView('battleflow');
      softCameraFocus(battleFlowView, 'start');
    }

    async function repeatLastMode() {
      await prepareFunctionalInteraction();
      const now = Date.now();
      if (state.lastReplayTapAt && now - state.lastReplayTapAt < 1200) return;
      if (state.battleLaunchInFlight) return;
      state.lastReplayTapAt = now;
      setBattleLaunchInFlight(true);
      resetBattleStage();
      if (state.lastReplayMode === 'bot') {
        setTimeout(() => playBotMatch(true), 40);
        return;
      }
      if (state.lastReplayMode === 'ranked' || state.lastReplayMode === 'casual') {
        setTimeout(() => startMatchmaking(state.lastReplayMode, true), 40);
        return;
      }
      setBattleLaunchInFlight(false);
      switchView('modes');
    }

    async function rematchLastOpponent() {
      await prepareFunctionalInteraction();
      const result = state.lastResult || {};
      const reference = result.opponent_domain ? `${result.opponent_domain}.ton` : result.opponent_wallet;
      if (!reference) return;
      document.getElementById('opponent-wallet').value = reference;
      switchView('modes');
      await playMatch('duel');
    }

    async function launchRecommendedMode(mode) {
      await prepareFunctionalInteraction();
      switchView('modes');
      if (mode === 'ranked' || mode === 'casual') {
        await startMatchmaking(mode);
      }
    }

    function rebindDomain() {
      state.selectedDomain = null;
      state.cards = [];
      state.canRestorePreviousDeck = false;
      state.pendingPackSource = null;
      state.pendingPackPaymentId = null;
      state.packOpening = false;
      state.selectedBattleSlot = null;
      state.lastResult = null;
      packCards.innerHTML = '';
      packScoreLabel.textContent = 'Вклад карт: -';
      packShowcase.classList.remove('opened');
      foilPack.classList.remove('opening');
      packNote.textContent = 'НАЖМИ, ЧТОБЫ ОТКРЫТЬ';
      battleResult.style.display = 'none';
      battleResult.className = 'result-box';
      document.body.classList.remove('showdown-open');
      inviteResult.style.display = 'none';
      renderDomains(state.domains);
      renderProfile();
      renderDeck(null);
      refreshOneCardSelector();
      updateButtons();
      mountWalletIntoProfile();
      switchView('profile');
      setStatus(walletStatus, 'Выбери домен заново и открой новую колоду.', 'warning');
      setStatus(document.getElementById('pack-status'), 'Привязка домена сброшена. Можно выбрать другой домен.', 'warning');
      renderDisciplineBuild({pool: 0, points: {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0}});
    }

    function renderRoom(room) {
      if (!teamPanel || !refreshRoomBtn || !startRoomBtn) return;
      const view = document.getElementById('team-room-view');
      if (!view) return;
      state.room = room;
      state.roomId = room.id;
      const roomCodeInput = document.getElementById('room-code-input');
      if (roomCodeInput) {
        roomCodeInput.value = room.id;
      }
      refreshRoomBtn.disabled = false;
      startRoomBtn.disabled = !(room.is_owner && room.players.length >= 2 && room.status === 'waiting');
      view.innerHTML = `
        <div class="team-card">
          <div class="team-line"><strong>Комната ${room.id}</strong><span>${room.players.length}/${room.max_players}</span></div>
          <div class="tiny">Статус: ${room.status === 'waiting' ? 'ожидание игроков' : 'завершена'}</div>
          ${room.players.map((player) => `
            <div class="team-line">
              <span>${player.username} • ${player.domain}.ton ${player.wallet === room.owner_wallet ? '(создатель)' : ''}</span>
              <strong>${shortAddress(player.wallet)}</strong>
            </div>
          `).join('')}
        </div>
      `;
    }

    async function loadLeaderboard() {
      const data = await api('/api/leaderboard');
      renderLeaderBoard(data.players);
    }

    async function loadActiveUsers() {
      const data = await api('/api/active-users');
      renderActiveUsers(data.players);
    }

    async function loadProfile() {
      if (!state.wallet) {
        state.playerProfile = null;
        state.socialData = null;
        state.guildData = null;
        state.tutorialData = null;
        renderProfile();
        renderIdentityPanel();
        renderSocialPanel();
        renderGuildPanel();
        renderTutorialPanel();
        renderOwnedDecks([], null);
        return;
      }
      const profile = await api(`/api/player/${encodeURIComponent(state.wallet)}`);
      state.playerProfile = profile.player;
      if (!state.selectedDomain && state.playerProfile && state.playerProfile.current_domain) {
        state.selectedDomain = state.playerProfile.current_domain;
      }
      renderProfile();
      await Promise.all([loadSocialData(), loadGuildData(), loadTutorialData()]);
    }

    async function loadTutorialData() {
      if (!state.wallet) {
        state.tutorialData = null;
        renderTutorialPanel();
        return;
      }
      const data = await api(`/api/tutorial/${encodeURIComponent(state.wallet)}`);
      state.tutorialData = data.tutorial || null;
      renderTutorialPanel();
    }

    async function loadSocialData() {
      if (!state.wallet) {
        state.socialData = null;
        renderIdentityPanel();
        renderSocialPanel();
        return;
      }
      const data = await api(`/api/social/${encodeURIComponent(state.wallet)}`);
      state.socialData = data.social || null;
      state.friends = (state.socialData && state.socialData.friends) || [];
      renderIdentityPanel();
      renderSocialPanel();
    }

    async function loadGuildData(query = '') {
      if (!state.wallet) {
        state.guildData = null;
        renderGuildPanel();
        return;
      }
      const suffix = query ? `?q=${encodeURIComponent(query)}` : '';
      const data = await api(`/api/guilds/overview/${encodeURIComponent(state.wallet)}${suffix}`);
      state.guildData = data.guilds || null;
      renderGuildPanel();
    }

    async function saveProfileIdentity() {
      if (!state.wallet) return;
      const profile = (state.socialData && state.socialData.profile) || {};
      const nickname = document.getElementById('profile-nickname-input')?.value ?? (profile.nickname || '');
      const bio = document.getElementById('profile-bio-input')?.value ?? (profile.bio || '');
      const profileTitle = document.getElementById('profile-title-input')?.value ?? (profile.profile_title || '');
      const profileBannerKey = document.getElementById('profile-banner-select')?.value ?? (profile.profile_banner_key || '');
      const data = await api('/api/profile', {
        method: 'POST',
        body: {
          wallet: state.wallet,
          nickname,
          bio,
          profile_title: profileTitle,
          profile_banner_key: profileBannerKey,
          language: 'ru'
        }
      });
      state.playerProfile = data.player;
      state.socialData = data.social || state.socialData;
      renderProfile();
      renderIdentityPanel();
      renderSocialPanel();
      renderGuildPanel();
    }

    async function sendLobbyMessage() {
      if (!state.wallet) return;
      const input = document.getElementById('lobby-message-input');
      if (!input || !input.value.trim()) return;
      const data = await api('/api/lobby-chat', {
        method: 'POST',
        body: { wallet: state.wallet, message: input.value }
      });
      input.value = '';
      if (state.socialData) {
        state.socialData.lobby_messages = data.messages || [];
      }
      renderSocialPanel();
    }

    async function submitUserReport(reference, scope) {
      if (!state.wallet || !reference) return;
      await api('/api/report', {
        method: 'POST',
        body: {
          wallet: state.wallet,
          reference,
          scope: scope || 'general',
          reason: `Жалоба из ${scope || 'general'}`
        }
      });
      setStatus(walletStatus, 'Жалоба отправлена. Спасибо.', 'success');
    }

    async function handleSocialAction(action, dataset) {
      if (!state.wallet) return;
      if (action === 'request-friend') {
        const data = await api('/api/friends/request', {
          method: 'POST',
          body: { wallet: state.wallet, reference: dataset.reference }
        });
        state.socialData = data.social || state.socialData;
        renderIdentityPanel();
        renderSocialPanel();
        return;
      }
      if (action === 'accept-friend' || action === 'decline-friend') {
        const data = await api('/api/friends/respond', {
          method: 'POST',
          body: { wallet: state.wallet, request_id: dataset.requestId, action: action === 'accept-friend' ? 'accept' : 'decline' }
        });
        state.socialData = data.social || state.socialData;
        renderIdentityPanel();
        renderSocialPanel();
        return;
      }
      if (action === 'remove-friend') {
        const data = await api('/api/friends/remove', {
          method: 'POST',
          body: { wallet: state.wallet, reference: dataset.reference }
        });
        state.socialData = data.social || state.socialData;
        renderSocialPanel();
        return;
      }
      if (action === 'block') {
        const data = await api('/api/blocks', {
          method: 'POST',
          body: { wallet: state.wallet, reference: dataset.reference }
        });
        state.socialData = data.social || state.socialData;
        renderSocialPanel();
        return;
      }
      if (action === 'report') {
        await submitUserReport(dataset.reference, dataset.scope || 'general');
        return;
      }
      if (action === 'accept-duel' || action === 'decline-duel') {
        const data = await api('/api/match-invite/respond', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            invite_id: dataset.inviteId,
            action: action === 'accept-duel' ? 'accept' : 'decline'
          }
        });
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
        }
        state.socialData = data.social || state.socialData;
        renderSocialPanel();
        if (data.result) {
          state.lastResult = data.result;
          renderBattleResult(data.result);
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = '<strong>Дуэль принята.</strong><p class="muted">Нажми «Готов», чтобы стартовать после 2/2.</p>';
        } else if (action === 'decline-duel') {
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = '<strong>Приглашение отклонено.</strong>';
        }
        return;
      }
      if (action === 'open-duel') {
        const data = await api(`/api/match-invite/${encodeURIComponent(dataset.inviteId)}?wallet=${encodeURIComponent(state.wallet)}`);
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
        }
        if (data.result) {
          state.lastResult = data.result;
          renderBattleResult(data.result);
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = data.result.requires_ready
            ? `<strong>Приглашение ${dataset.inviteId} принято.</strong><p class="muted">Ожидание готовности 2/2.</p>`
            : `<strong>Приглашение ${dataset.inviteId} завершено.</strong>`;
        } else {
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = `<strong>Статус приглашения ${dataset.inviteId}: ${escapeHtml((data.invite && data.invite.status) || 'pending')}</strong>`;
        }
        return;
      }
      if (action === 'duel') {
        await fillOpponent(dataset.reference);
      }
    }

    async function createGuildFromUI() {
      if (!state.wallet) return;
      const name = document.getElementById('guild-name-input')?.value || '';
      const language = document.getElementById('guild-language-input')?.value || 'ru';
      const description = document.getElementById('guild-description-input')?.value || '';
      const data = await api('/api/guilds/create', {
        method: 'POST',
        body: { wallet: state.wallet, name, language, description, is_public: true }
      });
      state.guildData = data.guilds || state.guildData;
      state.playerProfile = data.player || state.playerProfile;
      renderProfile();
      renderGuildPanel();
    }

    async function sendGuildChatMessage() {
      if (!state.wallet || !state.guildData || !state.guildData.current_guild) return;
      const input = document.getElementById('guild-chat-input');
      if (!input || !input.value.trim()) return;
      const data = await api('/api/guilds/chat', {
        method: 'POST',
        body: { wallet: state.wallet, guild_id: state.guildData.current_guild.id, message: input.value }
      });
      state.guildData = data.guilds || state.guildData;
      input.value = '';
      renderGuildPanel();
    }

    async function sendGuildAnnouncement() {
      if (!state.wallet || !state.guildData || !state.guildData.current_guild) return;
      const input = document.getElementById('guild-announcement-input');
      if (!input || !input.value.trim()) return;
      const data = await api('/api/guilds/announcement', {
        method: 'POST',
        body: { wallet: state.wallet, guild_id: state.guildData.current_guild.id, message: input.value }
      });
      state.guildData = data.guilds || state.guildData;
      input.value = '';
      renderGuildPanel();
    }

    async function sendGuildInvite() {
      if (!state.wallet || !state.guildData || !state.guildData.current_guild) return;
      const input = document.getElementById('guild-invite-reference-input');
      if (!input || !input.value.trim()) return;
      const data = await api('/api/guilds/invite', {
        method: 'POST',
        body: { wallet: state.wallet, guild_id: state.guildData.current_guild.id, reference: input.value }
      });
      state.guildData = data.guilds || state.guildData;
      input.value = '';
      renderGuildPanel();
    }

    async function handleGuildAction(action, dataset) {
      if (!state.wallet) return;
      if (action === 'apply') {
        const data = await api('/api/guilds/apply', {
          method: 'POST',
          body: { wallet: state.wallet, guild_id: dataset.guildId, message: '' }
        });
        state.guildData = data.guilds || state.guildData;
        renderGuildPanel();
        return;
      }
      if (action === 'accept-request' || action === 'decline-request') {
        const data = await api('/api/guilds/request/respond', {
          method: 'POST',
          body: { wallet: state.wallet, request_id: dataset.requestId, action: action === 'accept-request' ? 'accept' : 'decline' }
        });
        state.guildData = data.guilds || state.guildData;
        renderGuildPanel();
        return;
      }
      if (action === 'accept-invite' || action === 'decline-invite') {
        const data = await api('/api/guilds/invite/respond', {
          method: 'POST',
          body: { wallet: state.wallet, invite_id: dataset.inviteId, action: action === 'accept-invite' ? 'accept' : 'decline' }
        });
        state.guildData = data.guilds || state.guildData;
        state.playerProfile = data.player || state.playerProfile;
        renderProfile();
        renderGuildPanel();
        return;
      }
      if (action === 'toggle-role') {
        const data = await api('/api/guilds/member/role', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            guild_id: dataset.guildId,
            target_wallet: dataset.targetWallet,
            role: dataset.nextRole
          }
        });
        state.guildData = data.guilds || state.guildData;
        renderGuildPanel();
      }
    }

    async function shareLastResultToTelegram() {
      if (!state.lastResult) return;
      const result = state.lastResult;
      const label = result.result_label || 'Матч завершён';
      const domain = result.player_domain ? `${result.player_domain}.ton` : 'мой домен';
      const opp = result.opponent_domain ? `${result.opponent_domain}.ton` : 'соперник';
      const text = encodeURIComponent(`Ton Domain Game\n${domain} vs ${opp}\nИтог: ${label}\nСчёт: ${result.player_score}:${result.opponent_score}`);
      const url = `https://t.me/share/url?url=${encodeURIComponent(window.location.origin)}&text=${text}`;
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      if (tg && typeof tg.openTelegramLink === 'function') {
        tg.openTelegramLink(url);
        return;
      }
      window.open(url, '_blank', 'noopener');
    }

    async function checkDomains() {
      setStatus(walletStatus, 'Запускаем проверку доменов...', 'warning');
      if (!state.wallet) {
        await openWalletConnect();
        return;
      }
      setStatus(walletStatus, 'Проверяем NFT и 10K домены в кошельке...', 'warning');
      try {
        const data = await api('/api/wallet/domains', {
          method: 'POST',
          body: {wallet: state.wallet}
        });
        state.domainsChecked = true;
        state.domains = data.domains;
        if (!state.domains.some((item) => item.domain === state.selectedDomain)) {
          state.selectedDomain = null;
          state.cards = [];
          state.canRestorePreviousDeck = false;
          state.selectedBattleSlot = null;
          packCards.innerHTML = '';
          packScoreLabel.textContent = 'Вклад карт: -';
          refreshOneCardSelector();
        }
        const guestOnly = data.domains.length === 1 && data.domains[0].is_guest;
        if (guestOnly) {
          setStatus(walletStatus, `Реальные домены не найдены. Доступен гостевой домен ${data.domains[0].domain}.ton.`, 'warning');
        } else if (data.domains.length) {
          setStatus(walletStatus, `Найдено доменов: ${data.domains.length}. Выбери тот, который хочешь использовать для колоды.`, 'success');
        } else {
          setStatus(walletStatus, 'Подключение прошло успешно, но 10K Club доменов в кошельке не найдено.', 'warning');
        }
        renderDomains(data.domains);
        renderProfile();
        updateButtons();
        const decksData = await loadOwnedDecks();
        const preferredDomain = preferredDeckDomain((decksData && decksData.decks) || [], state.playerProfile && state.playerProfile.current_domain);
        if (!state.selectedDomain && preferredDomain) {
          await selectDeckDomain(preferredDomain, {silent: true, switchToPack: false, skipSync: true});
          setStatus(walletStatus, `Найдена готовая колода ${preferredDomain}.ton. Она выбрана автоматически.`, 'success');
        } else {
          loadDisciplineBuild();
        }
      } catch (error) {
        setStatus(walletStatus, error.message, 'error');
      }
    }

    async function openWalletConnect() {
      setStatus(walletStatus, 'Открываем TonConnect...', 'warning');
      if (!tonConnectUI) {
        await initTonConnect();
      }
      if (!tonConnectUI) {
        setStatus(walletStatus, 'TonConnect не инициализирован. Обнови страницу и попробуй снова.', 'error');
        return;
      }
      if (tonConnectUI.account && tonConnectUI.account.address) {
        setStatus(walletStatus, `Кошелёк уже подключен: ${tonConnectUI.account.address}`, 'success');
        return;
      }
      try {
        const nativeTrigger = document.querySelector('#ton-connect button, #ton-connect [role="button"]');
        if (nativeTrigger && typeof nativeTrigger.click === 'function') {
          nativeTrigger.click();
        } else if (typeof tonConnectUI.connectWallet === 'function') {
          await tonConnectUI.connectWallet();
        } else if (typeof tonConnectUI.openModal === 'function') {
          await tonConnectUI.openModal();
        } else {
          throw new Error('TonConnect modal недоступен');
        }
        setStatus(walletStatus, 'Открой кошелёк и подтверди подключение.', 'warning');
      } catch (error) {
        setStatus(walletStatus, 'Не удалось открыть TonConnect. Обнови страницу и попробуй снова.', 'error');
      }
      const tonConnectRoot = document.getElementById('ton-connect');
      if (tonConnectRoot) {
        tonConnectRoot.scrollIntoView({behavior: 'smooth', block: 'center'});
      }
    }

    async function onTelegramSiteAuth(user) {
      if (!state.wallet) {
        setStatus(telegramLinkStatus, 'Сначала подключи TON-кошелёк, потом привязывай Telegram.', 'warning');
        return;
      }
      setStatus(telegramLinkStatus, 'Привязываем Telegram к текущему кошельку...', 'warning');
      try {
        const data = await api('/api/telegram/site-link', {
          method: 'POST',
          body: { wallet: state.wallet, telegram: user || {} }
        });
        state.playerProfile = data.player || state.playerProfile;
        renderProfile();
        setStatus(
          telegramLinkStatus,
          `Telegram привязан: ${data.telegram && data.telegram.username ? `@${data.telegram.username}` : (data.telegram && data.telegram.first_name) || 'аккаунт подключён'}.`,
          'success'
        );
      } catch (error) {
        setStatus(telegramLinkStatus, error.message, 'error');
      }
    }

    async function requestTelegramWriteAccess() {
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      if (!tg || typeof tg.requestWriteAccess !== 'function') {
        return false;
      }
      return await new Promise((resolve) => {
        try {
          tg.requestWriteAccess((allowed) => resolve(Boolean(allowed)));
        } catch (_) {
          resolve(false);
        }
      });
    }

    async function linkTelegramFromMiniApp(options = {}) {
      const {requestWrite = false, silent = false} = options;
      if (!state.wallet || state.telegramMiniLinkInFlight) {
        return false;
      }
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      if (!tg || !tg.initData) {
        if (!silent) {
          setStatus(telegramLinkStatus, 'Это действие доступно только внутри Telegram mini app.', 'error');
        }
        return false;
      }
      state.telegramMiniLinkInFlight = true;
      if (!silent) {
        setStatus(telegramLinkStatus, 'Привязываем Telegram через mini app...', 'warning');
      }
      try {
        if (requestWrite) {
          const writeAllowed = await requestTelegramWriteAccess();
          if (!writeAllowed) {
            throw new Error('Telegram не дал разрешение на отправку сообщений.');
          }
        }
        const data = await api('/api/telegram/link', {
          method: 'POST',
          body: { wallet: state.wallet, init_data: tg.initData }
        });
        state.playerProfile = data.player || state.playerProfile;
        renderProfile();
        if (!silent) {
          const linked = data.telegram || {};
          setStatus(
            telegramLinkStatus,
            `Telegram привязан в mini app: ${linked.username ? `@${linked.username}` : linked.first_name || 'аккаунт подключён'}.`,
            'success'
          );
        }
        return true;
      } catch (error) {
        if (!silent) {
          setStatus(telegramLinkStatus, error.message, 'error');
        }
        return false;
      } finally {
        state.telegramMiniLinkInFlight = false;
      }
    }
    window.openWalletConnect = openWalletConnect;
    window.checkDomains = checkDomains;
    window.onTelegramSiteAuth = onTelegramSiteAuth;
    window.linkTelegramFromMiniApp = linkTelegramFromMiniApp;

    async function playCosmeticRouletteReveal(cosmeticReward) {
      await resumeRouletteAudioContext();
      const rewards = (state.playerProfile && state.playerProfile.rewards) || {};
      const catalog = Array.isArray(rewards.cosmetic_catalog) ? rewards.cosmetic_catalog.slice() : [];
      const fallback = {
        key: cosmeticReward && cosmeticReward.key ? cosmeticReward.key : 'cosmetic_reward',
        name: cosmeticReward && cosmeticReward.name ? cosmeticReward.name : 'Косметический предмет',
        type: cosmeticReward && cosmeticReward.type ? cosmeticReward.type : 'cosmetic',
        emoji: cosmeticReward && cosmeticReward.emoji ? cosmeticReward.emoji : '',
        rarity_key: cosmeticReward && cosmeticReward.rarity_key ? cosmeticReward.rarity_key : 'basic',
      };
      if (!catalog.find((item) => item.key === fallback.key)) {
        catalog.push(fallback);
      }
      const stripSize = 42;
      const winnerIndex = 32;
      const stripItems = [];
      for (let i = 0; i < stripSize; i += 1) {
        if (i === winnerIndex) {
          stripItems.push(fallback);
        } else {
          stripItems.push(drawRouletteCosmetic(catalog));
        }
      }
      const cardsMarkup = stripItems.map((item, idx) => {
        const rarityKey = cosmeticRarityKey(item);
        return `
          <article class="cosmetic-roulette-card ${rarityKey}" data-roulette-index="${idx}">
            <div class="icon">${escapeHtml(cosmeticTypeIcon(item))}</div>
            <div class="name">${escapeHtml(item.name || 'Косметика')}</div>
            <div class="rarity">${escapeHtml(cosmeticRarityLabel(item))}</div>
            <div class="beam"></div>
          </article>
        `;
      }).join('');
      packCards.classList.remove('reveal', 'pack-emerge', 'sequence-prep');
      packCards.innerHTML = `
        <div class="cosmetic-roulette">
          <div class="cosmetic-roulette-marker">▼</div>
          <div class="cosmetic-roulette-marker-bottom">▼</div>
          <div class="cosmetic-roulette-window">
            <div class="cosmetic-roulette-track" id="cosmetic-roulette-track">
              ${cardsMarkup}
            </div>
          </div>
        </div>
      `;
      const rouletteWindow = packCards.querySelector('.cosmetic-roulette-window');
      const rouletteTrack = packCards.querySelector('#cosmetic-roulette-track');
      const firstCard = packCards.querySelector('.cosmetic-roulette-card');
      if (!rouletteWindow || !rouletteTrack || !firstCard) {
        return;
      }
      const cardRect = firstCard.getBoundingClientRect();
      const styles = window.getComputedStyle(rouletteTrack);
      const gap = Number.parseFloat(styles.columnGap || styles.gap || '10') || 10;
      const cardStep = Math.max(1, cardRect.width + gap);
      const centerOffset = rouletteWindow.clientWidth / 2 - cardRect.width / 2;
      const target = Math.max(0, winnerIndex * cardStep - centerOffset);
      const fastTarget = Math.max(0, target - cardStep * 4);
      const tickPromise = runRouletteTickSequence(target, cardStep).catch(() => {});
      rouletteTrack.style.transform = 'translateX(0px)';
      rouletteTrack.style.transition = 'none';
      rouletteTrack.classList.add('spinning');
      await sleep(40);
      rouletteTrack.style.transition = 'transform 2200ms cubic-bezier(.18,.88,.24,1)';
      rouletteTrack.style.transform = `translateX(-${fastTarget.toFixed(2)}px)`;
      await sleep(2240);
      rouletteTrack.style.transition = 'transform 2050ms cubic-bezier(.06,.96,.12,1)';
      rouletteTrack.style.transform = `translateX(-${target.toFixed(2)}px)`;
      await sleep(2090);
      rouletteTrack.style.transition = 'transform 210ms ease-out';
      rouletteTrack.style.transform = `translateX(-${(target - 6).toFixed(2)}px)`;
      await sleep(220);
      rouletteTrack.style.transition = 'transform 170ms ease-in';
      rouletteTrack.style.transform = `translateX(-${target.toFixed(2)}px)`;
      await sleep(180);
      rouletteTrack.classList.remove('spinning');
      await tickPromise;
      playRouletteDropSound();
      const finalCard = packCards.querySelector(`.cosmetic-roulette-card[data-roulette-index="${winnerIndex}"]`);
      if (finalCard) {
        finalCard.style.boxShadow = '0 0 0 1px rgba(255, 211, 110, 0.58), 0 0 24px rgba(255, 211, 110, 0.34)';
      }
      await sleep(260);
      packCards.innerHTML = `
        <article class="game-card ${cosmeticRarityKey(fallback)}">
          <div class="tiny">Cosmetic • ${escapeHtml(cosmeticRarityLabel(fallback))}</div>
          <h3>${escapeHtml(fallback.name || 'Косметический предмет')}</h3>
          <p>${escapeHtml(cosmeticTypeLabelRu(fallback.type || 'cosmetic'))}</p>
          <div class="team-line"><span>Источник</span><strong>Косметический пак</strong></div>
          <p>Предмет добавлен в коллекцию и доступен во вкладке «Профиль».</p>
        </article>
      `;
      packCards.classList.add('reveal');
    }

    async function openPack(source = 'daily', paymentId = null, packType = null) {
      await prepareFunctionalInteraction();
      if (state.packOpening) return;
      const resolvedPackType = packType || (source === 'paid' ? 'lucky' : 'common');
      const hadPreviousDeck = Array.isArray(state.cards) && state.cards.length === 5;
      const isCosmeticPack = resolvedPackType === 'cosmetic';
      state.pendingRewardPackType = null;
      state.packOpening = true;
      setStatus(document.getElementById('pack-status'), `Распаковываем ${packTypeMeta(resolvedPackType)?.label || resolvedPackType}...`, 'warning');
      foilPack.classList.remove('opening');
      foilPack.classList.remove('vanishing');
      packShowcase.classList.remove('opened');
      packShowcase.classList.add('cinematic');
      requestAnimationFrame(() => foilPack.classList.add('opening'));
      packNote.textContent = 'Открываем...';
      try {
        const data = await api('/api/pack', {
          method: 'POST',
          body: {wallet: state.wallet, domain: state.selectedDomain, source, payment_id: paymentId, pack_type: resolvedPackType}
        });
        if (!isCosmeticPack) {
          state.cards = data.cards;
        }
        state.canRestorePreviousDeck = hadPreviousDeck;
        state.pendingPackSource = null;
        state.pendingPackPaymentId = null;
        if (state.playerProfile && data.rewards) {
          state.playerProfile.rewards = data.rewards;
        }
        await sleep(1300);
        packShowcase.classList.add('opened');
        packNote.textContent = 'Карты уже летят';
        if (isCosmeticPack) {
          const cosmetic = data.cosmetic_reward || {};
          await playCosmeticRouletteReveal(cosmetic);
          packScoreLabel.textContent = `Открыт предмет: ${cosmetic.name || '-'}`;
        } else {
          await renderPack(data.cards, data.total_score);
        }
        packShowcase.classList.remove('cinematic');
        setStatus(
          document.getElementById('pack-status'),
          isCosmeticPack
            ? `Открыт ${data.cosmetic_reward && data.cosmetic_reward.name ? data.cosmetic_reward.name : 'косметический предмет'}.`
            : `Колода готова. ${packTypeMeta(resolvedPackType)?.label || resolvedPackType} дал вклад ${data.total_score}.`,
          'success'
        );
        updateButtons();
        if (!isCosmeticPack) {
          showDeck();
          await loadDisciplineBuild();
        }
        loadOwnedDecks();
        loadActiveUsers();
        loadGlobalPlayers();
        loadAchievements();
        loadProfile();
      } catch (error) {
        foilPack.classList.remove('opening');
        foilPack.classList.remove('vanishing');
        packShowcase.classList.remove('cinematic');
        packNote.textContent = 'НАЖМИ, ЧТОБЫ ОТКРЫТЬ';
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      } finally {
        state.packOpening = false;
      }
    }

    async function restorePreviousDeck() {
      await prepareFunctionalInteraction();
      if (!state.wallet || !state.selectedDomain) return;
      restorePreviousDeckBtn.disabled = true;
      setStatus(document.getElementById('pack-status'), 'Возвращаем предыдущую колоду...', 'warning');
      try {
        const data = await api('/api/deck/restore-previous', {
          method: 'POST',
          body: {wallet: state.wallet, domain: state.selectedDomain}
        });
        state.cards = data.cards || [];
        state.canRestorePreviousDeck = false;
        await renderPack(state.cards, data.total_score || 0, false);
        packScoreLabel.textContent = `Вклад карт: ${data.total_score || 0}`;
        refreshOneCardSelector();
        updateButtons();
        await loadDisciplineBuild();
        loadOwnedDecks();
        setStatus(document.getElementById('pack-status'), 'Предыдущая колода восстановлена и снова активна.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      } finally {
        updatePreviousDeckRestoreButton();
      }
    }

    async function openRewardPack(packType) {
      if (!state.wallet || !state.selectedDomain) return;
      if (String(packType || '').toLowerCase() === 'cosmetic') {
        state.pendingRewardPackType = 'cosmetic';
        packNote.textContent = 'Нажми на пак, чтобы открыть косметический';
        packShowcase.classList.remove('opened');
        foilPack.classList.remove('opening');
        foilPack.classList.remove('vanishing');
        setStatus(document.getElementById('pack-status'), 'Косметический пак готов к открытию. Нажми на пак.', 'warning');
        return;
      }
      state.pendingRewardPackType = null;
      await openPack('reward', null, packType);
    }

    async function claimDailyReward() {
      if (!state.wallet) return;
      try {
        const data = await api('/api/rewards/daily', {
          method: 'POST',
          body: {wallet: state.wallet}
        });
        if (state.playerProfile) {
          state.playerProfile.rewards = data.rewards;
        }
        renderProfile();
        setStatus(document.getElementById('pack-status'), 'Daily reward получен.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function claimQuestReward() {
      if (!state.wallet) return;
      try {
        const data = await api('/api/rewards/quest', {
          method: 'POST',
          body: {wallet: state.wallet}
        });
        if (state.playerProfile) {
          state.playerProfile.rewards = data.rewards;
        }
        renderProfile();
        setStatus(document.getElementById('pack-status'), 'Quest reward получен.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function claimGuildWeeklyReward() {
      if (!state.wallet || !state.guildData || !state.guildData.current_guild) return;
      try {
        const data = await api('/api/guilds/reward/claim', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            guild_id: state.guildData.current_guild.id
          }
        });
        state.guildData = data.guilds || state.guildData;
        if (state.playerProfile) {
          state.playerProfile.rewards = data.rewards;
        }
        renderProfile();
        setStatus(document.getElementById('pack-status'), 'Недельная награда клана получена.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function buySeasonPassWithTon() {
      await prepareFunctionalInteraction();
      if (!state.wallet) return;
      if (!tonConnectUI) {
        setStatus(document.getElementById('pack-status'), 'TonConnect не инициализирован.', 'error');
        return;
      }
      try {
        setStatus(document.getElementById('pack-status'), 'Создаём TON-платёж для премиум-пропуска...', 'warning');
        const intent = await api('/api/pass/payment-intent', {
          method: 'POST',
          body: { wallet: state.wallet }
        });
        const tx = await tonConnectUI.sendTransaction({
          validUntil: intent.valid_until,
          messages: [
            {
              address: intent.receiver_wallet,
              amount: String(intent.amount_nano)
            }
          ]
        });
        const confirmed = await api('/api/pass/payment-confirm', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            payment_id: intent.payment_id,
            tx_hash: tx && tx.boc ? tx.boc.slice(0, 120) : ''
          }
        });
        if (state.playerProfile) {
          state.playerProfile.rewards = confirmed.rewards;
        }
        renderProfile();
        updateButtons();
        setStatus(document.getElementById('pack-status'), 'Премиум-пропуск активирован. Карты за донат больше не продаются: только косметика и ускорение прогресса.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function loadCardCatalog() {
      try {
        const data = await api('/api/cards/catalog');
        state.packTypes = data.pack_types || [];
        if (!(state.packTypes || []).some((item) => item.key === state.selectedPackType)) {
          state.selectedPackType = 'common';
        }
        state.packPityThreshold = Number(data.pity_threshold || 20);
        renderCardCatalog(data.cards || [], data.skills || []);
        renderPackEconomy();
        renderPackTypePicker();
      } catch (error) {
        cardCatalogList.innerHTML = `<div class="user-item error">${error.message}</div>`;
      }
    }

    async function pollInvite(inviteId) {
      const startedAt = Date.now();
      const maxPollMs = 1000 * 60 * 15;
      const loop = async () => {
        let data = null;
        try {
          data = await api(`/api/match-invite/${inviteId}?wallet=${encodeURIComponent(state.wallet)}`);
        } catch (error) {
          const elapsed = Date.now() - startedAt;
          if (elapsed < maxPollMs) {
            inviteResult.style.display = 'block';
            inviteResult.classList.add('duel-anim');
            inviteResult.innerHTML = `<strong>Проблема связи при проверке дуэли.</strong><p class="muted">Повторяем автоматически: ${escapeHtml(error.message || 'network error')}</p>`;
            setTimeout(loop, 3200);
            return;
          }
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = `<strong class="error">Ошибка дуэли: ${escapeHtml(error.message || 'Request failed')}</strong>`;
          return;
        }
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
          loadLeaderboard();
          loadActiveUsers();
        }
        if (data.result) {
          state.lastResult = data.result;
          renderBattleResult(data.result);
          await loadSocialData();
          loadAchievements();
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = data.result.requires_ready
            ? `<strong>Приглашение ${inviteId} принято.</strong><p class="muted">Матч готовится в live-режиме. Нажмите «Готов» и дождитесь 2/2.</p>`
            : `<strong>Приглашение ${inviteId} завершено.</strong>`;
          return;
        }
        if (['declined', 'expired', 'completed'].includes(data.invite.status)) {
          await loadSocialData();
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = `<strong>Статус приглашения ${inviteId}: ${data.invite.status}</strong>`;
          return;
        }
        if (data.invite.status === 'accepted') {
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = `<strong>Приглашение ${inviteId} принято.</strong><p class="muted">Подготавливаем бой...</p>`;
        }
        if (Date.now() - startedAt < maxPollMs) {
          setTimeout(loop, 4000);
        }
      };
      loop();
    }

    function stopMatchmakingUI(message = '') {
      state.matchmakingPolling = false;
      state.matchmakingMode = null;
      state.matchmakingErrorStreak = 0;
      if (matchmakingPollTimer) {
        window.clearTimeout(matchmakingPollTimer);
        matchmakingPollTimer = null;
      }
      resetModeChoice(message);
      if (message) {
        matchmakingStatus.textContent = message;
      }
      updateButtons();
    }

    async function pollMatchmaking(mode) {
      if (!state.matchmakingPolling || state.matchmakingMode !== mode) return;
      try {
        const data = await api(`/api/matchmaking/${mode}/status?wallet=${encodeURIComponent(state.wallet)}`);
        if (!state.matchmakingPolling || state.matchmakingMode !== mode) return;
        state.matchmakingErrorStreak = 0;
        if (data.status === 'searching') {
          const waited = Number(data.waited_seconds || 0);
          if (data.cooldown_seconds) {
            matchmakingStatus.textContent = `Повтор с тем же соперником через ${data.cooldown_seconds} сек. Идёт поиск (${waited} сек)...`;
          } else {
            matchmakingStatus.textContent = `Идёт поиск соперника (${waited} сек)...`;
          }
          matchmakingPollTimer = window.setTimeout(() => pollMatchmaking(mode), 2500);
          return;
        }
        if (data.status === 'matched' && data.result) {
          stopMatchmakingUI('Соперник найден. Матч запущен.');
          state.lastResult = data.result;
          renderBattleResult(data.result);
          if (data.player) {
            state.playerProfile = data.player;
            renderProfile();
          }
          await loadAchievements();
          await loadLeaderboard();
          await loadActiveUsers();
          return;
        }
        if (data.status === 'cancelled' || data.status === 'expired' || data.status === 'completed' || data.status === 'idle') {
          stopMatchmakingUI('Поиск остановлен.');
          return;
        }
        matchmakingPollTimer = window.setTimeout(() => pollMatchmaking(mode), 2500);
      } catch (error) {
        if (!state.matchmakingPolling || state.matchmakingMode !== mode) return;
        state.matchmakingErrorStreak = Number(state.matchmakingErrorStreak || 0) + 1;
        if (state.matchmakingErrorStreak >= 20) {
          stopMatchmakingUI(`Поиск остановлен: ${error.message}`);
          return;
        }
        const retryMs = Math.min(6500, 1800 + state.matchmakingErrorStreak * 350);
        matchmakingStatus.textContent = `Проблема связи (${state.matchmakingErrorStreak}). Повторяем через ${Math.round(retryMs / 1000)} сек...`;
        matchmakingPollTimer = window.setTimeout(() => pollMatchmaking(mode), retryMs);
      }
    }

    async function startMatchmaking(mode, forceLaunch = false) {
      await prepareFunctionalInteraction();
      if (state.battleLaunchInFlight && !forceLaunch) return;
      setBattleLaunchInFlight(true);
      bumpUsage(`mode:${mode}`);
      animateModeChoice(mode);
      state.matchmakingMode = mode;
      state.matchmakingPolling = true;
      state.matchmakingErrorStreak = 0;
      matchmakingStatus.textContent = 'Запускаем поиск соперника...';
      updateButtons();
      try {
        const data = await api(`/api/matchmaking/${mode}/search`, {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain
          }
        });
        if (data.status === 'matched' && data.result) {
          stopMatchmakingUI('Соперник найден. Матч запущен.');
          state.lastResult = data.result;
          renderBattleResult(data.result);
          if (data.player) {
            state.playerProfile = data.player;
            renderProfile();
          }
          await loadAchievements();
          await loadLeaderboard();
          await loadActiveUsers();
          return;
        }
        setBattleLaunchInFlight(false);
        matchmakingStatus.textContent = data.cooldown_seconds
          ? `Повтор с тем же соперником через ${data.cooldown_seconds} сек. Идёт поиск...`
          : 'Идёт поиск соперника...';
        matchmakingPollTimer = window.setTimeout(() => pollMatchmaking(mode), 2200);
      } catch (error) {
        setBattleLaunchInFlight(false);
        stopMatchmakingUI(error.message);
      }
    }

    async function cancelMatchmaking() {
      await prepareFunctionalInteraction();
      if (!state.matchmakingMode) return;
      const mode = state.matchmakingMode;
      try {
        await api(`/api/matchmaking/${mode}/cancel`, {
          method: 'POST',
          body: { wallet: state.wallet }
        });
      } catch (_) {
      }
      stopMatchmakingUI('Поиск отменён.');
    }

    async function playMatch(mode, options = {}) {
      await prepareFunctionalInteraction();
      bumpUsage(`mode:${mode}`);
      const opponentWallet = document.getElementById('opponent-wallet').value.trim();
      const timeoutSeconds = Number(options.timeoutSeconds || 30);
      const delivery = (options.delivery || 'telegram').trim();
      animateModeChoice(mode);
      try {
        const data = await api(`/api/match/${mode}`, {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            opponent_wallet: opponentWallet,
            timeout_seconds: timeoutSeconds,
            delivery,
            selected_slot: Number(battleCardSlot.value || state.selectedBattleSlot || 0)
          }
        });

        if (data.result) {
          state.lastResult = data.result;
          renderBattleResult(data.result);
          if (data.player) {
            state.playerProfile = data.player;
            renderProfile();
          }
          await loadAchievements();
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = '<strong>Матч запущен прямо на сайте.</strong>';
          return;
        }

        inviteResult.style.display = 'block';
        inviteResult.classList.add('duel-anim');
        inviteResult.innerHTML = `
          <strong>Приглашение ${data.invite.id} отправлено.</strong>
          <p class="muted">Сопернику отправлено приглашение в Telegram. Время на ответ: ${data.invite.timeout_seconds} сек.</p>
        `;
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
        }
        loadActiveUsers();
        pollInvite(data.invite.id);
      } catch (error) {
        inviteResult.style.display = 'block';
        inviteResult.classList.add('duel-anim');
        inviteResult.innerHTML = `<strong class="error">${error.message}</strong>`;
      }
    }

    async function playTelegramDuel() {
      await playMatch('duel', {timeoutSeconds: 30, delivery: 'telegram'});
    }

    async function playBotMatch(forceLaunch = false) {
      await prepareFunctionalInteraction();
      if (state.battleLaunchInFlight && !forceLaunch) return;
      setBattleLaunchInFlight(true);
      bumpUsage('mode:bot');
      animateModeChoice('bot');
      showMatchIntro('Запуск матча с ботом');
      try {
        const data = await api('/api/match/bot', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            selected_slot: Number(battleCardSlot.value || state.selectedBattleSlot || 0)
          }
        });
        state.lastResult = data.result;
        renderBattleResult(data.result);
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
        }
        await loadAchievements();
      } catch (error) {
        setBattleLaunchInFlight(false);
        battleResult.className = 'result-box duel-anim';
        battleResult.style.display = 'block';
        document.body.classList.remove('showdown-open');
        battleResult.innerHTML = `<strong class="error">${error.message}</strong>`;
      }
    }

    async function startTutorialBattle() {
      await prepareFunctionalInteraction();
      if (!state.wallet || !state.selectedDomain) return;
      showMatchIntro('Запуск боевого туториала');
      try {
        const data = await api('/api/tutorial/start', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            selected_slot: Number(battleCardSlot.value || state.selectedBattleSlot || 0)
          }
        });
        state.lastResult = data.result;
        state.playerProfile = data.player || state.playerProfile;
        state.tutorialData = data.tutorial || state.tutorialData;
        renderProfile();
        renderBattleResult(data.result);
      } catch (error) {
        setBattleLaunchInFlight(false);
        battleResult.className = 'result-box duel-anim';
        battleResult.style.display = 'block';
        document.body.classList.remove('showdown-open');
        battleResult.innerHTML = `<strong class="error">${error.message}</strong>`;
      }
    }

    async function skipTutorialBattle() {
      await prepareFunctionalInteraction();
      if (!state.wallet) return;
      try {
        const data = await api('/api/tutorial/skip', {
          method: 'POST',
          body: { wallet: state.wallet }
        });
        state.tutorialData = data.tutorial || state.tutorialData;
        state.playerProfile = data.player || state.playerProfile;
        renderProfile();
      } catch (error) {
        setStatus(walletStatus, error.message, 'error');
      }
    }

    async function createRoom() {
      await prepareFunctionalInteraction();
      if (!teamPanel) return;
      const teamUsername = document.getElementById('team-username');
      const teamRoomSize = document.getElementById('team-room-size');
      const teamStatus = document.getElementById('team-status');
      if (!teamUsername || !teamRoomSize || !teamStatus) return;
      bumpUsage('mode:team');
      const username = teamUsername.value.trim() || shortAddress(state.wallet);
      try {
        const data = await api('/api/team-room/create', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            username,
            max_players: Number(teamRoomSize.value)
          }
        });
        setStatus(teamStatus, `Комната ${data.room.id} создана. Приглашай игроков по коду.`, 'success');
        renderRoom(data.room);
      } catch (error) {
        setStatus(teamStatus, error.message, 'error');
      }
    }

    async function joinRoom() {
      await prepareFunctionalInteraction();
      if (!teamPanel) return;
      const teamUsername = document.getElementById('team-username');
      const roomCodeInput = document.getElementById('room-code-input');
      const teamStatus = document.getElementById('team-status');
      if (!teamUsername || !roomCodeInput || !teamStatus) return;
      bumpUsage('mode:team');
      const username = teamUsername.value.trim() || shortAddress(state.wallet);
      const roomId = roomCodeInput.value.trim().toUpperCase();
      try {
        const data = await api('/api/team-room/join', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            username,
            room_id: roomId
          }
        });
        setStatus(teamStatus, `Ты вошёл в комнату ${roomId}.`, 'success');
        renderRoom(data.room);
      } catch (error) {
        setStatus(teamStatus, error.message, 'error');
      }
    }

    async function refreshRoom() {
      await prepareFunctionalInteraction();
      if (!teamPanel) return;
      const teamStatus = document.getElementById('team-status');
      if (!state.roomId) return;
      try {
        const data = await api(`/api/team-room/${state.roomId}?wallet=${encodeURIComponent(state.wallet)}`);
        renderRoom(data.room);
      } catch (error) {
        if (teamStatus) {
          setStatus(teamStatus, error.message, 'error');
        }
      }
    }

    async function startRoom() {
      await prepareFunctionalInteraction();
      if (!teamPanel) return;
      const teamStatus = document.getElementById('team-status');
      if (!state.roomId) return;
      bumpUsage('mode:team');
      try {
        const data = await api('/api/team-room/start', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            room_id: state.roomId
          }
        });
        renderRoom(data.room);
        state.lastResult = data.result;
        renderBattleResult(data.result);
        if (teamStatus) {
          setStatus(teamStatus, 'Командный матч завершён.', 'success');
        }
      } catch (error) {
        if (teamStatus) {
          setStatus(teamStatus, error.message, 'error');
        }
      }
    }

    async function showDeck() {
      await prepareFunctionalInteraction();
      if (!state.wallet) return;
      try {
        const deck = await api(`/api/deck/${encodeURIComponent(state.wallet)}`);
        renderDeck(deck);
        await loadDisciplineBuild();
      } catch (error) {
        deckView.innerHTML = `<div class="user-item error">${error.message}</div>`;
      }
    }

    async function loadOwnedDecks() {
      if (!state.wallet) {
        renderOwnedDecks([], null);
        return null;
      }
      try {
        const data = await api(`/api/decks/${encodeURIComponent(state.wallet)}`);
        renderOwnedDecks(data.decks || [], data.current_domain);
        return data;
      } catch (error) {
        ownedDecksList.innerHTML = `<div class="user-item error">${error.message}</div>`;
        walletOwnedDecksList.innerHTML = `<div class="user-item error">${error.message}</div>`;
        return null;
      }
    }

    async function selectDeckDomain(domain, options = {}) {
      const {silent = false, switchToPack = true, skipSync = false} = options;
      if (!state.wallet) return;
      if (!skipSync) {
        await prepareFunctionalInteraction();
      }
      try {
        const data = await api('/api/deck/select', {
          method: 'POST',
          body: { wallet: state.wallet, domain }
        });
        state.selectedDomain = data.domain;
        state.playerProfile = data.player;
        state.cards = data.deck.cards || [];
        state.canRestorePreviousDeck = false;
        state.pendingPackSource = null;
        state.pendingPackPaymentId = null;
        state.packOpening = false;
        packShowcase.classList.remove('opened');
        foilPack.classList.remove('opening');
        packNote.textContent = 'НАЖМИ, ЧТОБЫ ОТКРЫТЬ';
        renderProfile();
        renderDomains(state.domains);
        renderDeck({ wallet: state.wallet, domain: data.domain, deck: data.deck });
        await renderPack(state.cards, data.deck.total_score || 0, false);
        refreshOneCardSelector();
        updateButtons();
        await loadOwnedDecks();
        if (switchToPack) {
          switchView('pack');
        }
        if (!silent) {
          setStatus(document.getElementById('pack-status'), `Активная колода переключена на ${data.domain}.ton.`, 'success');
        }
        await loadDisciplineBuild();
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function loadGlobalPlayers() {
      try {
        const data = await api('/api/players/global');
        renderGlobalPlayers(data.players || []);
      } catch (error) {
        globalPlayersList.innerHTML = `<div class="user-item error">${error.message}</div>`;
      }
    }

    async function loadAchievements() {
      renderClanSeasonHub();
    }

    async function registerPlayer() {
      if (!state.wallet) return;
      try {
        await api('/api/player/register', {
          method: 'POST',
          body: { wallet: state.wallet }
        });
      } catch (_) {
      }
    }

    async function playOneCardMatch() {
      if (!oneCardSlot) {
        setStatus(matchmakingStatus, 'Режим одной карты скрыт из интерфейса.', 'warning');
        return;
      }
      const slot = Number(oneCardSlot.value || 0);
      if (!slot) {
        setStatus(document.getElementById('pack-status'), 'Для режима одной карты выбери карту из колоды.', 'warning');
        return;
      }
      bumpUsage('mode:onecard');
      animateModeChoice('onecard');
      showMatchIntro('Запуск дуэли одной картой');
      try {
        const data = await api('/api/match/one-card', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            card_slot: slot
          }
        });
        state.lastResult = data.result;
        renderBattleResult(data.result);
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
        }
        await loadAchievements();
      } catch (error) {
        battleResult.className = 'result-box duel-anim';
        battleResult.style.display = 'block';
        document.body.classList.remove('showdown-open');
        battleResult.innerHTML = `<strong class="error">${error.message}</strong>`;
      }
    }

    function toggleDeck() {
      const isHidden = deckView.style.display === 'none';
      deckView.style.display = isHidden ? 'grid' : 'none';
      toggleDeckBtn.textContent = isHidden ? 'Скрыть' : 'Открыть';
    }

    async function initTonConnect() {
      const tonConnectReady = await ensureTonConnectUiScript();
      if (!tonConnectReady || !window.TON_CONNECT_UI || !window.TON_CONNECT_UI.TonConnectUI) {
        setStatus(walletStatus, 'TonConnect UI не загрузился. Обнови страницу или отключи блокировщики скриптов/VPN для этого сайта.', 'error');
        const tonConnectRoot = document.getElementById('ton-connect');
        if (tonConnectRoot) {
          tonConnectRoot.innerHTML = '<div class="tiny" style="color: var(--danger);">TonConnect не загрузился</div>';
        }
        return;
      }
      tonConnectUI = new TON_CONNECT_UI.TonConnectUI({
        manifestUrl: `${window.location.origin}/tonconnect-manifest.json`,
        buttonRootId: 'ton-connect'
      });

      tonConnectUI.uiOptions = {
        language: 'ru',
        uiPreferences: { theme: TON_CONNECT_UI.THEME.DARK }
      };

      let previousWallet = null;
      const applyConnection = async () => {
        const account = tonConnectUI.account;
        state.wallet = account && account.address ? account.address : null;
        if (state.wallet !== previousWallet) {
          stopMatchmakingUI('');
          state.domainsChecked = false;
          state.domains = [];
          state.selectedDomain = null;
          state.cards = [];
          state.pendingPackSource = null;
          state.pendingPackPaymentId = null;
          state.pendingRewardPackType = null;
          state.packOpening = false;
          state.selectedBattleSlot = null;
          packCards.innerHTML = '';
          packScoreLabel.textContent = 'Вклад карт: -';
          packShowcase.classList.remove('opened');
          foilPack.classList.remove('opening');
          packNote.textContent = 'НАЖМИ, ЧТОБЫ ОТКРЫТЬ';
          renderDomains([]);
          renderDisciplineBuild({pool: 0, points: {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0}});
        }
        previousWallet = state.wallet;
        updateButtons();
        if (state.wallet) {
          await registerPlayer();
          setStatus(walletStatus, `Кошелёк подключен: ${state.wallet}`, 'success');
          await loadOwnedDecks();
          await loadGlobalPlayers();
          await loadProfile();
          if (isTelegramMiniApp() && state.playerProfile && !state.playerProfile.telegram_linked) {
            await linkTelegramFromMiniApp({silent: true});
          }
          await loadAchievements();
          await loadDisciplineBuild();
        } else {
          stopMatchmakingUI('');
          state.domainsChecked = false;
          state.domains = [];
          state.selectedDomain = null;
          state.cards = [];
          state.canRestorePreviousDeck = false;
          state.pendingPackSource = null;
          state.pendingPackPaymentId = null;
          state.pendingRewardPackType = null;
          state.packOpening = false;
          state.selectedBattleSlot = null;
          renderDomains([]);
          renderProfile();
          renderDeck(null);
          renderOwnedDecks([], null);
          renderClanSeasonHub();
          renderDisciplineBuild({pool: 0, points: {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0}});
          setStatus(walletStatus, 'Подключи кошелёк через TonConnect.', 'warning');
        }
      };

      tonConnectUI.onStatusChange(async () => {
        await applyConnection();
      });

      await applyConnection();
    }

    bindFunctionalControl(document.getElementById('connect-wallet-btn'), openWalletConnect, 'click', {skipPrepare: true});
    bindFunctionalControl(document.getElementById('check-domains-btn'), checkDomains, 'click', {skipPrepare: true});
    if (startupGuideCloseBtn) {
      bindFunctionalControl(startupGuideCloseBtn, () => closeStartupGuide(true), 'click', {skipPrepare: true});
    }
    if (startupGuideSkipBtn) {
      bindFunctionalControl(startupGuideSkipBtn, () => closeStartupGuide(true), 'click', {skipPrepare: true});
    }
    if (startupGuideNextBtn) {
      bindFunctionalControl(startupGuideNextBtn, nextStartupGuideStep, 'click', {skipPrepare: true});
    }
    if (startupGuidePrevBtn) {
      bindFunctionalControl(startupGuidePrevBtn, prevStartupGuideStep, 'click', {skipPrepare: true});
    }
    if (telegramMiniappLinkBtn) {
      bindFunctionalControl(telegramMiniappLinkBtn, () => linkTelegramFromMiniApp({requestWrite: true}), 'click', {skipPrepare: true});
    }
    bindFunctionalControl(walletOpenPackBtn, () => switchView('pack'));
    bindFunctionalControl(document.getElementById('back-to-wallet-btn'), () => switchView('profile'));
    bindFunctionalControl(document.getElementById('rebind-domain-btn'), rebindDomain);
    bindFunctionalControl(document.getElementById('shuffle-deck-btn'), shuffleDeck);
    bindFunctionalControl(document.getElementById('open-pack-btn'), () => openPack('daily'));
    bindFunctionalControl(buyPackBtn, buySeasonPassWithTon);
    bindFunctionalControl(claimDailyRewardBtn, claimDailyReward);
    bindFunctionalControl(claimQuestRewardBtn, claimQuestReward);
    if (restorePreviousDeckBtn) {
      bindFunctionalControl(restorePreviousDeckBtn, restorePreviousDeck);
    }
    document.querySelectorAll('.reward-pack-btn').forEach((button) => {
      bindFunctionalControl(button, () => openRewardPack(button.dataset.rewardPack));
    });
    bindFunctionalControl(foilPack, () => {
      if (state.packOpening) {
        return;
      }
      if (state.pendingRewardPackType) {
        const rewardType = state.pendingRewardPackType;
        state.pendingRewardPackType = null;
        openPack('reward', null, rewardType);
        return;
      }
      if (!document.getElementById('open-pack-btn').disabled) {
        openPack('daily', null, 'common');
      }
    });
    bindFunctionalControl(document.getElementById('continue-to-modes-btn'), () => switchView('modes'));
    bindFunctionalControl(document.getElementById('play-ranked-btn'), () => startMatchmaking('ranked'));
    bindFunctionalControl(document.getElementById('play-casual-btn'), () => startMatchmaking('casual'));
    bindFunctionalControl(cancelMatchmakingBtn, cancelMatchmaking);
    bindFunctionalControl(saveBuildBtn, saveDisciplineBuild);
    bindFunctionalControl(document.getElementById('play-bot-btn'), playBotMatch);
    const playDuelBtn = document.getElementById('play-duel-btn');
    const opponentWalletInput = document.getElementById('opponent-wallet');
    if (playDuelBtn) {
      bindFunctionalControl(playDuelBtn, playTelegramDuel);
    }
    if (opponentWalletInput) {
      opponentWalletInput.addEventListener('input', updateButtons);
      opponentWalletInput.addEventListener('change', updateButtons);
    }
    if (playOnecardBtn) {
      bindFunctionalControl(playOnecardBtn, playOneCardMatch);
    }
    if (oneCardSlot) {
      oneCardSlot.addEventListener('change', updateButtons);
    }
    battleCardSlot.addEventListener('change', () => {
      state.selectedBattleSlot = Number(battleCardSlot.value || 0) || null;
      updateButtons();
    });
    bindFunctionalControl(refreshAchievementsBtn, loadAchievements);
    if (showTeamBtn) {
      bindFunctionalControl(showTeamBtn, () => {
        bumpUsage('mode:team');
        animateModeChoice('team');
        if (teamPanel) {
          teamPanel.style.display = 'block';
        }
        const teamStatus = document.getElementById('team-status');
        if (teamStatus) {
          setStatus(teamStatus, 'Создай командную комнату или войди по коду.', 'warning');
        }
      });
    }
    if (createRoomBtn) {
      bindFunctionalControl(createRoomBtn, createRoom);
    }
    if (joinRoomBtn) {
      bindFunctionalControl(joinRoomBtn, joinRoom);
    }
    if (refreshRoomBtn) {
      bindFunctionalControl(refreshRoomBtn, refreshRoom);
    }
    if (startRoomBtn) {
      bindFunctionalControl(startRoomBtn, startRoom);
    }
    bindFunctionalControl(showDeckBtn, showDeck);
    bindFunctionalControl(toggleDeckBtn, toggleDeck);
    bindFunctionalControl(document.getElementById('mobile-show-deck-btn'), showDeck);
    bindFunctionalControl(document.getElementById('nav-pack'), () => switchView('pack'));
    bindFunctionalControl(document.getElementById('nav-modes'), () => switchView('modes'));
    bindFunctionalControl(topNavPack, () => switchView('pack'));
    bindFunctionalControl(topNavModes, () => switchView('modes'));
    bindFunctionalControl(document.getElementById('nav-profile'), () => {
      switchView('profile');
    });
    bindFunctionalControl(topNavProfile, () => {
      switchView('profile');
    });
    bindFunctionalControl(document.getElementById('nav-guilds'), () => switchView('guilds'));
    bindFunctionalControl(document.getElementById('nav-achievements'), () => switchView('achievements'));
    bindFunctionalControl(topNavGuilds, () => switchView('guilds'));
    bindFunctionalControl(topNavAchievements, () => switchView('achievements'));
    if (mascotFab) {
      bindFunctionalControl(mascotFab, () => {
        if (mascotPopoverCopy) mascotPopoverCopy.textContent = mascotHintText();
        setMascotOpen(!(mascotWidget && mascotWidget.classList.contains('open')));
      });
    }
    if (mascotOpenProfileBtn) {
      bindFunctionalControl(mascotOpenProfileBtn, () => {
        setMascotOpen(false);
        switchView('profile');
      });
    }
    if (mascotOpenPackBtn) {
      bindFunctionalControl(mascotOpenPackBtn, () => {
        setMascotOpen(false);
        switchView('pack');
      });
    }
    if (mascotOpenBattleBtn) {
      bindFunctionalControl(mascotOpenBattleBtn, () => {
        setMascotOpen(false);
        switchView('modes');
      });
    }
    if (mascotOpenGuideBtn) {
      bindFunctionalControl(mascotOpenGuideBtn, () => {
        setMascotOpen(false);
        try {
          window.localStorage.removeItem(startupGuideStorageKey);
        } catch (_) {
        }
        showStartupGuideIfNeeded();
      });
    }
    [buildAttack, buildDefense, buildLuck, buildSpeed, buildMagic].forEach((node) => {
      node.addEventListener('input', () => {
        const pool = Number((state.disciplineBuild && state.disciplineBuild.pool) || 0);
        const points = collectBuildPoints();
        const spent = points.attack + points.defense + points.luck + points.speed + points.magic;
        buildStatus.textContent = `Пул: ${pool} • Потрачено: ${spent} • Остаток: ${Math.max(0, pool - spent)}`;
      });
    });

    window.fillOpponent = fillOpponent;
    window.repeatLastMode = repeatLastMode;
    window.rematchLastOpponent = rematchLastOpponent;
    window.launchRecommendedMode = launchRecommendedMode;
    window.openModes = openModes;
    window.viewBattleFlow = viewBattleFlow;
    window.selectDeckDomain = selectDeckDomain;
    window.handleInteractiveBattleChoice = handleInteractiveBattleChoice;

    syncTmaMode();
    syncTmaViewport();
    resetHorizontalViewportDrift();
    const tgWebApp = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (tgWebApp && typeof tgWebApp.onEvent === 'function') {
      tgWebApp.onEvent('viewportChanged', queueTmaModeSync);
      tgWebApp.onEvent('themeChanged', queueTmaModeSync);
    }
    document.addEventListener('click', (event) => {
      interceptDeckDomainAction(event).catch(() => {});
    }, true);
    document.addEventListener('click', (event) => {
      interceptInteractiveBattleAction(event).catch(() => {});
    }, true);
    document.addEventListener('click', (event) => {
      interceptSocialAction(event).catch(() => {});
    }, true);
    document.addEventListener('click', (event) => {
      interceptGuildAction(event).catch(() => {});
    }, true);
    document.addEventListener('click', (event) => {
      interceptPublicProfileAction(event).catch(() => {});
    }, true);
    if (publicProfileBackdrop) {
      publicProfileBackdrop.addEventListener('click', (event) => {
        if (event.target === publicProfileBackdrop) {
          closePublicProfile();
        }
      });
    }
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && state.publicProfile) {
        closePublicProfile();
      }
    });
    ['pointerdown', 'touchstart', 'click', 'change', 'focusin'].forEach((eventName) => {
      document.addEventListener(eventName, syncTmaModeForFunctionalAction, true);
    });
    document.addEventListener('submit', queueTmaModeSync, true);
    window.addEventListener('pageshow', queueTmaModeSync);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        queueTmaModeSync();
      }
    });
    window.addEventListener('orientationchange', queueTmaModeSync);
    window.addEventListener('resize', queueTmaModeSync);
    initTonConnect().catch((error) => {
      setStatus(walletStatus, `Ошибка TonConnect: ${error.message}`, 'error');
    });
    loadLeaderboard();
    loadActiveUsers();
    loadGlobalPlayers();
    loadAchievements();
    loadCardCatalog();
    mountWalletIntoProfile();
    renderProfile();
    renderDisciplineBuild({pool: 0, points: {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0}});
    renderDeck(null);
    renderOwnedDecks([], null);
    renderClanSeasonHub();
    refreshOneCardSelector();
    switchView('profile');
    updateButtons();
    window.setTimeout(showStartupGuideIfNeeded, 160);
    document.addEventListener('click', (event) => {
      if (!mascotWidget || !mascotWidget.classList.contains('open')) return;
      if (event.target.closest('#mascot-widget')) return;
      setMascotOpen(false);
    });
  </script>
</body>
</html>
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def now_utc():
    return datetime.now(timezone.utc)


def parse_iso(value):
    return datetime.fromisoformat(value)


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA busy_timeout = 15000')
    conn.execute('PRAGMA synchronous = NORMAL')
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def is_retryable_sqlite_error(exc):
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    message = str(exc).lower()
    return 'locked' in message or 'busy' in message


def run_with_sqlite_retry(handler, attempts=5, base_delay=0.05):
    attempts = max(1, int(attempts or 1))
    for attempt in range(attempts):
        try:
            return handler()
        except sqlite3.OperationalError as exc:
            if not is_retryable_sqlite_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(base_delay * (attempt + 1))
    return handler()


def init_db():
    with closing(get_db()) as conn:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS players (
                wallet TEXT PRIMARY KEY,
                rating INTEGER NOT NULL DEFAULT 1000,
                games_played INTEGER NOT NULL DEFAULT 0,
                ranked_wins INTEGER NOT NULL DEFAULT 0,
                ranked_losses INTEGER NOT NULL DEFAULT 0,
                best_domain TEXT,
                current_domain TEXT,
                first_seen TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ranked_matches (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                opponent_domain TEXT NOT NULL,
                result TEXT NOT NULL,
                rating_before INTEGER NOT NULL,
                rating_after INTEGER NOT NULL,
                player_score INTEGER NOT NULL,
                opponent_score INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS team_rooms (
                id TEXT PRIMARY KEY,
                owner_wallet TEXT NOT NULL,
                max_players INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS team_room_players (
                room_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                username TEXT NOT NULL,
                domain TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (room_id, wallet)
            );

            CREATE TABLE IF NOT EXISTS telegram_users (
                telegram_user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                wallet TEXT,
                linked_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS telegram_notification_prefs (
                wallet TEXT PRIMARY KEY,
                notify_duel_invites INTEGER NOT NULL DEFAULT 1,
                notify_daily_reward INTEGER NOT NULL DEFAULT 1,
                notify_win_quest INTEGER NOT NULL DEFAULT 1,
                notify_guild_invites INTEGER NOT NULL DEFAULT 1,
                notify_guild_reward INTEGER NOT NULL DEFAULT 1,
                notify_season_pass INTEGER NOT NULL DEFAULT 1,
                last_daily_notified_on TEXT,
                last_quest_notified_target INTEGER NOT NULL DEFAULT 0,
                last_guild_reward_week TEXT,
                last_season_notified_level INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS duel_invites (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                inviter_wallet TEXT NOT NULL,
                inviter_domain TEXT NOT NULL,
                invitee_wallet TEXT NOT NULL,
                invitee_domain TEXT NOT NULL,
                status TEXT NOT NULL,
                timeout_seconds INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                responded_at TEXT,
                telegram_message_id INTEGER,
                result_json TEXT
            );

            CREATE TABLE IF NOT EXISTS matchmaking_queue (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                selected_slot INTEGER,
                status TEXT NOT NULL,
                opponent_wallet TEXT,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                consumed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS matchmaking_cooldowns (
                wallet_a TEXT NOT NULL,
                wallet_b TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (wallet_a, wallet_b)
            );

            CREATE TABLE IF NOT EXISTS battle_sessions (
                id TEXT PRIMARY KEY,
                wallet_a TEXT NOT NULL,
                wallet_b TEXT NOT NULL,
                payload_a_json TEXT NOT NULL,
                payload_b_json TEXT NOT NULL,
                ready_a INTEGER NOT NULL DEFAULT 0,
                ready_b INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS solo_battles (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                mode TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deck_builds (
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                attack INTEGER NOT NULL,
                defense INTEGER NOT NULL,
                luck INTEGER NOT NULL,
                speed INTEGER NOT NULL,
                magic INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wallet, domain)
            );

            CREATE TABLE IF NOT EXISTS friends (
                owner_wallet TEXT NOT NULL,
                friend_wallet TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_wallet, friend_wallet)
            );

            CREATE TABLE IF NOT EXISTS player_profiles (
                wallet TEXT PRIMARY KEY,
                nickname TEXT,
                avatar TEXT,
                bio TEXT,
                language TEXT,
                visibility TEXT NOT NULL DEFAULT 'public',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS friend_requests (
                id TEXT PRIMARY KEY,
                sender_wallet TEXT NOT NULL,
                receiver_wallet TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                responded_at TEXT
            );

            CREATE TABLE IF NOT EXISTS blocks (
                owner_wallet TEXT NOT NULL,
                blocked_wallet TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_wallet, blocked_wallet)
            );

            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                reporter_wallet TEXT NOT NULL,
                target_wallet TEXT NOT NULL,
                scope TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guilds (
                id TEXT PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                owner_wallet TEXT NOT NULL,
                domain_identity TEXT,
                description TEXT,
                language TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS telegram_notification_prefs (
                wallet TEXT PRIMARY KEY,
                notify_duel_invites INTEGER NOT NULL DEFAULT 1,
                notify_daily_reward INTEGER NOT NULL DEFAULT 1,
                notify_win_quest INTEGER NOT NULL DEFAULT 1,
                notify_guild_invites INTEGER NOT NULL DEFAULT 1,
                notify_guild_reward INTEGER NOT NULL DEFAULT 1,
                notify_season_pass INTEGER NOT NULL DEFAULT 1,
                last_daily_notified_on TEXT,
                last_quest_notified_target INTEGER NOT NULL DEFAULT 0,
                last_guild_reward_week TEXT,
                last_season_notified_level INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guild_members (
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                role TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, wallet)
            );

            CREATE TABLE IF NOT EXISTS guild_join_requests (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                message TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                responded_at TEXT
            );

            CREATE TABLE IF NOT EXISTS guild_invites (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                inviter_wallet TEXT NOT NULL,
                invitee_wallet TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                responded_at TEXT
            );

            CREATE TABLE IF NOT EXISTS guild_messages (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guild_announcements (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lobby_messages (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pack_opens (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                source TEXT NOT NULL,
                opened_on TEXT NOT NULL,
                payment_id TEXT,
                cards_json TEXT NOT NULL,
                total_score INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pack_payments (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                amount_nano INTEGER NOT NULL,
                memo TEXT NOT NULL,
                status TEXT NOT NULL,
                tx_hash TEXT,
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS domain_progress (
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                experience INTEGER NOT NULL DEFAULT 0,
                total_matches INTEGER NOT NULL DEFAULT 0,
                total_wins INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wallet, domain)
            );

            CREATE TABLE IF NOT EXISTS domain_telemetry (
                id TEXT PRIMARY KEY,
                wallet TEXT,
                domain TEXT,
                rarity_label TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pack_pity (
                wallet TEXT NOT NULL,
                pack_type TEXT NOT NULL,
                opens_without_legendary INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wallet, pack_type)
            );

            CREATE TABLE IF NOT EXISTS player_rewards (
                wallet TEXT PRIMARY KEY,
                pack_shards INTEGER NOT NULL DEFAULT 0,
                rare_tokens INTEGER NOT NULL DEFAULT 0,
                lucky_tokens INTEGER NOT NULL DEFAULT 0,
                cosmetic_packs INTEGER NOT NULL DEFAULT 0,
                season_points INTEGER NOT NULL DEFAULT 0,
                season_level INTEGER NOT NULL DEFAULT 1,
                premium_pass INTEGER NOT NULL DEFAULT 0,
                wins_for_quest INTEGER NOT NULL DEFAULT 0,
                wins_claimed INTEGER NOT NULL DEFAULT 0,
                daily_claimed_on TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_reward_claims (
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                week_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, wallet, week_key)
            );
            CREATE TABLE IF NOT EXISTS player_cosmetics (
                wallet TEXT NOT NULL,
                cosmetic_key TEXT NOT NULL,
                cosmetic_type TEXT,
                serial_number INTEGER,
                source TEXT NOT NULL,
                equipped INTEGER NOT NULL DEFAULT 0,
                unlocked_at TEXT NOT NULL,
                PRIMARY KEY (wallet, cosmetic_key)
            );
            CREATE TABLE IF NOT EXISTS season_pass_payments (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                amount_nano INTEGER NOT NULL,
                memo TEXT NOT NULL,
                status TEXT NOT NULL,
                tx_hash TEXT,
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS season_pass_claims (
                wallet TEXT NOT NULL,
                reward_tier TEXT NOT NULL,
                level INTEGER NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (wallet, reward_tier, level)
            );
            CREATE TABLE IF NOT EXISTS season_task_claims (
                wallet TEXT NOT NULL,
                task_key TEXT NOT NULL,
                task_day TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (wallet, task_key, task_day)
            );
            CREATE TABLE IF NOT EXISTS tutorial_progress (
                wallet TEXT PRIMARY KEY,
                started_at TEXT,
                completed_at TEXT,
                skipped_at TEXT,
                rewarded_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS player_profiles (
                wallet TEXT PRIMARY KEY,
                nickname TEXT,
                avatar TEXT,
                bio TEXT,
                language TEXT,
                visibility TEXT NOT NULL DEFAULT 'public',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS player_behavior_stats (
                wallet TEXT PRIMARY KEY,
                stats_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS friend_requests (
                id TEXT PRIMARY KEY,
                sender_wallet TEXT NOT NULL,
                receiver_wallet TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                responded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS blocks (
                owner_wallet TEXT NOT NULL,
                blocked_wallet TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_wallet, blocked_wallet)
            );
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                reporter_wallet TEXT NOT NULL,
                target_wallet TEXT NOT NULL,
                scope TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guilds (
                id TEXT PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                owner_wallet TEXT NOT NULL,
                domain_identity TEXT,
                description TEXT,
                language TEXT,
                is_public INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_members (
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                role TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, wallet)
            );
            CREATE TABLE IF NOT EXISTS guild_join_requests (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                message TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                responded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS guild_invites (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                inviter_wallet TEXT NOT NULL,
                invitee_wallet TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                responded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS guild_messages (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_announcements (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lobby_messages (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            '''
        )
        columns = {row['name'] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
        if 'current_domain' not in columns:
            conn.execute('ALTER TABLE players ADD COLUMN current_domain TEXT')
        if 'first_seen' not in columns:
            conn.execute('ALTER TABLE players ADD COLUMN first_seen TEXT')
            conn.execute('UPDATE players SET first_seen = COALESCE(first_seen, updated_at)')
        matchmaking_columns = {row['name'] for row in conn.execute("PRAGMA table_info(matchmaking_queue)").fetchall()}
        if 'selected_slot' not in matchmaking_columns:
            conn.execute('ALTER TABLE matchmaking_queue ADD COLUMN selected_slot INTEGER')
        reward_columns = {row['name'] for row in conn.execute("PRAGMA table_info(player_rewards)").fetchall()}
        if 'premium_pass' not in reward_columns:
            conn.execute('ALTER TABLE player_rewards ADD COLUMN premium_pass INTEGER NOT NULL DEFAULT 0')
        if 'cosmetic_packs' not in reward_columns:
            conn.execute('ALTER TABLE player_rewards ADD COLUMN cosmetic_packs INTEGER NOT NULL DEFAULT 0')
        conn.commit()


def ensure_runtime_tables():
    with closing(get_db()) as conn:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS matchmaking_queue (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                selected_slot INTEGER,
                status TEXT NOT NULL,
                opponent_wallet TEXT,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                consumed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS matchmaking_cooldowns (
                wallet_a TEXT NOT NULL,
                wallet_b TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (wallet_a, wallet_b)
            );
            CREATE TABLE IF NOT EXISTS battle_sessions (
                id TEXT PRIMARY KEY,
                wallet_a TEXT NOT NULL,
                wallet_b TEXT NOT NULL,
                payload_a_json TEXT NOT NULL,
                payload_b_json TEXT NOT NULL,
                ready_a INTEGER NOT NULL DEFAULT 0,
                ready_b INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS solo_battles (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                mode TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deck_builds (
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                attack INTEGER NOT NULL,
                defense INTEGER NOT NULL,
                luck INTEGER NOT NULL,
                speed INTEGER NOT NULL,
                magic INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wallet, domain)
            );
            CREATE TABLE IF NOT EXISTS domain_progress (
                wallet TEXT NOT NULL,
                domain TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                experience INTEGER NOT NULL DEFAULT 0,
                total_matches INTEGER NOT NULL DEFAULT 0,
                total_wins INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wallet, domain)
            );
            CREATE TABLE IF NOT EXISTS domain_telemetry (
                id TEXT PRIMARY KEY,
                wallet TEXT,
                domain TEXT,
                rarity_label TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pack_pity (
                wallet TEXT NOT NULL,
                pack_type TEXT NOT NULL,
                opens_without_legendary INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wallet, pack_type)
            );
            CREATE TABLE IF NOT EXISTS player_rewards (
                wallet TEXT PRIMARY KEY,
                pack_shards INTEGER NOT NULL DEFAULT 0,
                rare_tokens INTEGER NOT NULL DEFAULT 0,
                lucky_tokens INTEGER NOT NULL DEFAULT 0,
                cosmetic_packs INTEGER NOT NULL DEFAULT 0,
                season_points INTEGER NOT NULL DEFAULT 0,
                season_level INTEGER NOT NULL DEFAULT 1,
                premium_pass INTEGER NOT NULL DEFAULT 0,
                wins_for_quest INTEGER NOT NULL DEFAULT 0,
                wins_claimed INTEGER NOT NULL DEFAULT 0,
                daily_claimed_on TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_reward_claims (
                guild_id TEXT NOT NULL,
                wallet TEXT NOT NULL,
                week_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, wallet, week_key)
            );
            CREATE TABLE IF NOT EXISTS player_cosmetics (
                wallet TEXT NOT NULL,
                cosmetic_key TEXT NOT NULL,
                cosmetic_type TEXT,
                serial_number INTEGER,
                source TEXT NOT NULL,
                equipped INTEGER NOT NULL DEFAULT 0,
                unlocked_at TEXT NOT NULL,
                PRIMARY KEY (wallet, cosmetic_key)
            );
            CREATE TABLE IF NOT EXISTS season_pass_payments (
                id TEXT PRIMARY KEY,
                wallet TEXT NOT NULL,
                amount_nano INTEGER NOT NULL,
                memo TEXT NOT NULL,
                status TEXT NOT NULL,
                tx_hash TEXT,
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS season_pass_claims (
                wallet TEXT NOT NULL,
                reward_tier TEXT NOT NULL,
                level INTEGER NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (wallet, reward_tier, level)
            );
            CREATE TABLE IF NOT EXISTS season_task_claims (
                wallet TEXT NOT NULL,
                task_key TEXT NOT NULL,
                task_day TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (wallet, task_key, task_day)
            );
            CREATE TABLE IF NOT EXISTS tutorial_progress (
                wallet TEXT PRIMARY KEY,
                started_at TEXT,
                completed_at TEXT,
                skipped_at TEXT,
                rewarded_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                reporter_wallet TEXT NOT NULL,
                target_wallet TEXT NOT NULL,
                scope TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS player_behavior_stats (
                wallet TEXT PRIMARY KEY,
                stats_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            '''
        )
        matchmaking_columns = {row['name'] for row in conn.execute("PRAGMA table_info(matchmaking_queue)").fetchall()}
        if 'selected_slot' not in matchmaking_columns:
            conn.execute('ALTER TABLE matchmaking_queue ADD COLUMN selected_slot INTEGER')
        reward_columns = {row['name'] for row in conn.execute("PRAGMA table_info(player_rewards)").fetchall()}
        if 'premium_pass' not in reward_columns:
            conn.execute('ALTER TABLE player_rewards ADD COLUMN premium_pass INTEGER NOT NULL DEFAULT 0')
        if 'cosmetic_packs' not in reward_columns:
            conn.execute('ALTER TABLE player_rewards ADD COLUMN cosmetic_packs INTEGER NOT NULL DEFAULT 0')
        cosmetic_columns = {row['name'] for row in conn.execute("PRAGMA table_info(player_cosmetics)").fetchall()}
        if 'cosmetic_type' not in cosmetic_columns:
            conn.execute('ALTER TABLE player_cosmetics ADD COLUMN cosmetic_type TEXT')
        if 'serial_number' not in cosmetic_columns:
            conn.execute('ALTER TABLE player_cosmetics ADD COLUMN serial_number INTEGER')
        conn.commit()
        reset_legacy_cosmetic_serials(conn)
        ensure_cosmetic_serials(conn)
        conn.commit()


def json_error(message, status=400):
    return jsonify({'error': message}), status


MANAGED_ENV_KEYS = {
    'HOST': {'type': 'str', 'description': 'Хост для Flask/Gunicorn'},
    'PORT': {'type': 'int', 'description': 'Порт приложения'},
    'DEBUG': {'type': 'bool', 'description': 'Режим отладки'},
    'APP_DB_PATH': {'type': 'str', 'description': 'Путь к SQLite базе'},
    'TONAPI_KEY': {'type': 'str', 'description': 'API ключ TonAPI'},
    'TG_WEBAPP_URL': {'type': 'str', 'description': 'URL Telegram mini app'},
    'TG_BOT_TOKEN': {'type': 'str', 'description': 'Telegram bot token'},
    'TG_BOT_USERNAME': {'type': 'str', 'description': 'Username Telegram-бота'},
    'PACK_RECEIVER_WALLET': {'type': 'str', 'description': 'Кошелек получателя оплаты пака'},
    'PACK_PRICE_NANO': {'type': 'int', 'description': 'Цена пака в nanoTON'},
    'DAILY_FREE_PACKS': {'type': 'int', 'description': 'Лимит бесплатных паков в сутки'},
    'ALLOW_GUEST_WITHOUT_DOMAIN': {'type': 'bool', 'description': 'Разрешить игру без домена'},
    'MATCHMAKING_SEARCH_TTL_SECONDS': {'type': 'int', 'description': 'TTL поиска матчмейкинга'},
    'MATCHMAKING_REMATCH_COOLDOWN_SECONDS': {'type': 'int', 'description': 'Кулдаун повторного матча пары'},
}

ENV_DEFAULT_VALUES = {
    'HOST': str(HOST),
    'PORT': str(PORT),
    'DEBUG': '1' if DEBUG else '0',
    'APP_DB_PATH': str(DB_PATH),
    'TONAPI_KEY': str(TONAPI_KEY or ''),
    'TG_WEBAPP_URL': str(TG_WEBAPP_URL),
    'TG_BOT_TOKEN': str(TG_BOT_TOKEN or ''),
    'TG_BOT_USERNAME': str(TG_BOT_USERNAME or ''),
    'PACK_RECEIVER_WALLET': str(PACK_RECEIVER_WALLET or ''),
    'PACK_PRICE_NANO': str(PACK_PRICE_NANO),
    'DAILY_FREE_PACKS': str(DAILY_FREE_PACKS),
    'ALLOW_GUEST_WITHOUT_DOMAIN': '1' if ALLOW_GUEST_WITHOUT_DOMAIN else '0',
    'MATCHMAKING_SEARCH_TTL_SECONDS': str(MATCHMAKING_SEARCH_TTL_SECONDS),
    'MATCHMAKING_REMATCH_COOLDOWN_SECONDS': str(MATCHMAKING_REMATCH_COOLDOWN_SECONDS),
}


def parse_bool_text(value):
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def cast_env_value(key, value):
    meta = MANAGED_ENV_KEYS.get(key, {'type': 'str'})
    value_type = meta.get('type', 'str')
    if value_type == 'bool':
        return '1' if parse_bool_text(value) else '0'
    if value_type == 'int':
        return str(int(value))
    return str(value)


def read_env_lines():
    if not ENV_FILE_PATH.exists():
        return []
    return ENV_FILE_PATH.read_text(encoding='utf-8').splitlines()


def set_env_key(key, value):
    lines = read_env_lines()
    rendered = f'{key}={value}'
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*=')
    replaced = False
    updated = []
    for line in lines:
        if pattern.match(line):
            updated.append(rendered)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(rendered)
    ENV_FILE_PATH.write_text('\n'.join(updated).strip() + '\n', encoding='utf-8')


def unset_env_key(key):
    lines = read_env_lines()
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*=')
    updated = [line for line in lines if not pattern.match(line)]
    ENV_FILE_PATH.write_text(('\n'.join(updated).strip() + '\n') if updated else '', encoding='utf-8')


def get_env_value(key):
    lines = read_env_lines()
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*=\s*(.*)\s*$')
    for line in reversed(lines):
        match = pattern.match(line)
        if match:
            return match.group(1)
    return os.getenv(key, ENV_DEFAULT_VALUES.get(key))


def settings_snapshot():
    data = {}
    for key in MANAGED_ENV_KEYS:
        data[key] = get_env_value(key)
    return data


def handle_settings_cli(args):
    if not args or args[0] in {'help', '--help', '-h'}:
        print('Usage:')
        print('  python3 app.py settings list')
        print('  python3 app.py settings get <KEY>')
        print('  python3 app.py settings set <KEY> <VALUE>')
        print('  python3 app.py settings unset <KEY>')
        print('\nManaged keys:')
        for key, meta in MANAGED_ENV_KEYS.items():
            print(f'  {key:<34} ({meta["type"]}) - {meta["description"]}')
        return 0

    command = args[0]
    if command == 'list':
        for key, value in settings_snapshot().items():
            print(f'{key}={value if value is not None else ""}')
        return 0

    if command == 'get':
        if len(args) < 2:
            print('Missing KEY for settings get')
            return 1
        key = args[1]
        value = get_env_value(key)
        print(value if value is not None else '')
        return 0

    if command == 'set':
        if len(args) < 3:
            print('Missing KEY/VALUE for settings set')
            return 1
        key = args[1]
        value = ' '.join(args[2:])
        normalized = cast_env_value(key, value)
        set_env_key(key, normalized)
        print(f'Set {key}={normalized} in {ENV_FILE_PATH}')
        return 0

    if command == 'unset':
        if len(args) < 2:
            print('Missing KEY for settings unset')
            return 1
        key = args[1]
        unset_env_key(key)
        print(f'Removed {key} from {ENV_FILE_PATH}')
        return 0

    print(f'Unknown settings command: {command}')
    return 1


def valid_wallet_address(wallet):
    return bool(wallet) and len(wallet) >= 20 and wallet[0] in {'E', 'U', 'k', '0'}


def normalize_domain(value):
    if not value:
        return None
    text = str(value).strip().lower()
    if text.endswith('.ton'):
        text = text[:-4]
    if re.fullmatch(r'\d{4}', text):
        return text
    return None


def normalize_strict_ton_domain(value):
    text = str(value or '').strip().lower()
    match = re.fullmatch(r'(\d{4})\.ton', text)
    if not match:
        return None
    return match.group(1)


ROOT_TON_DOMAIN_PATTERN = re.compile(r'(?<![a-z0-9.-])(\d{4})\.ton(?![a-z0-9-])')


def extract_root_ton_domains_from_text(value):
    if value is None:
        return []
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return sorted(set(ROOT_TON_DOMAIN_PATTERN.findall(text.lower())))


def guest_access_enabled():
    return ALLOW_GUEST_WITHOUT_DOMAIN


def guest_domain_for_wallet(wallet):
    digest = hashlib.sha256(str(wallet).encode()).hexdigest()
    return f'{int(digest[:8], 16) % 10000:04d}'


def load_domain_progress(wallet, domain):
    normalized = normalize_domain(domain)
    if not wallet or not normalized:
        return {'level': 1, 'experience': 0, 'total_matches': 0, 'total_wins': 0}
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT level, experience, total_matches, total_wins
            FROM domain_progress
            WHERE wallet = ? AND domain = ?
            ''',
            (wallet, normalized),
        ).fetchone()
    if row is None:
        return {'level': 1, 'experience': 0, 'total_matches': 0, 'total_wins': 0}
    return dict(row)


def grant_domain_experience(wallet, domain, amount, won=False):
    normalized = normalize_domain(domain)
    if not wallet or not normalized:
        return {'level': 1, 'experience': 0, 'total_matches': 0, 'total_wins': 0}
    ensure_runtime_tables()
    current = load_domain_progress(wallet, normalized)
    experience = int(current.get('experience', 0)) + max(0, int(amount or 0))
    level = max(1, int(current.get('level', 1)))
    while experience >= level * 100:
        experience -= level * 100
        level += 1
    total_matches = int(current.get('total_matches', 0)) + 1
    total_wins = int(current.get('total_wins', 0)) + (1 if won else 0)
    updated = {
        'level': level,
        'experience': experience,
        'total_matches': total_matches,
        'total_wins': total_wins,
    }
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO domain_progress (wallet, domain, level, experience, total_matches, total_wins, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet, domain) DO UPDATE SET
                level = excluded.level,
                experience = excluded.experience,
                total_matches = excluded.total_matches,
                total_wins = excluded.total_wins,
                updated_at = excluded.updated_at
            ''',
            (wallet, normalized, level, experience, total_matches, total_wins, now_iso()),
        )
        conn.commit()
    return updated


def log_domain_telemetry(event_type, *, wallet=None, domain=None, rarity_label=None, payload=None):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO domain_telemetry (id, wallet, domain, rarity_label, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                uuid.uuid4().hex,
                wallet,
                normalize_domain(domain) if domain else None,
                rarity_label,
                str(event_type or 'unknown'),
                json.dumps(payload or {}, ensure_ascii=False),
                now_iso(),
            ),
        )
        conn.commit()


def ensure_player_rewards(wallet):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM player_rewards WHERE wallet = ?', (wallet,)).fetchone()
        if row is None:
            conn.execute(
                '''
                INSERT INTO player_rewards (
                    wallet, pack_shards, rare_tokens, lucky_tokens, cosmetic_packs, season_points,
                    season_level, premium_pass, wins_for_quest, wins_claimed, daily_claimed_on, updated_at
                ) VALUES (?, 0, 0, 0, 0, 0, 1, 0, 0, 0, NULL, ?)
                ''',
                (wallet, now_iso()),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM player_rewards WHERE wallet = ?', (wallet,)).fetchone()
    ensure_default_cosmetics(wallet)
    return dict(row)


def app_setting_value(conn, key, default=None):
    row = conn.execute('SELECT value FROM app_settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def set_app_setting(conn, key, value):
    conn.execute(
        '''
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        ''',
        (key, str(value), now_iso()),
    )


def week_utc_key():
    now_dt = now_utc()
    return f'{now_dt.isocalendar().year}-W{now_dt.isocalendar().week:02d}'


def cosmetic_serial_prefix(cosmetic_type):
    return {
        'frame': 'FRM',
        'cardback': 'CBK',
        'arena': 'ARN',
        'guild': 'GBN',
    }.get(str(cosmetic_type or ''), 'CSM')


def ensure_cosmetic_serials(conn):
    meta_by_key = {item['key']: item for item in COSMETIC_CATALOG}
    rows = conn.execute(
        '''
        SELECT wallet, cosmetic_key, cosmetic_type, serial_number, unlocked_at
        FROM player_cosmetics
        ORDER BY unlocked_at ASC, wallet ASC, cosmetic_key ASC
        '''
    ).fetchall()
    counters = {}
    for row in rows:
        meta = meta_by_key.get(row['cosmetic_key']) or {}
        cosmetic_type = row['cosmetic_type'] or meta.get('type') or 'cosmetic'
        current_max = counters.get(cosmetic_type, 0)
        serial_number = row['serial_number']
        conn.execute(
            'UPDATE player_cosmetics SET cosmetic_type = ? WHERE wallet = ? AND cosmetic_key = ?',
            (cosmetic_type, row['wallet'], row['cosmetic_key']),
        )
        counters[cosmetic_type] = max(current_max, int(serial_number or 0))


def reset_legacy_cosmetic_serials(conn):
    if app_setting_value(conn, 'cosmetic_serials_reset_v1', '0') == '1':
        return
    conn.execute('UPDATE player_cosmetics SET serial_number = NULL')
    set_app_setting(conn, 'cosmetic_serials_reset_v1', '1')


def cosmetic_serial_label(cosmetic_type, serial_number):
    if serial_number is None:
        return None
    return f"{cosmetic_serial_prefix(cosmetic_type)}-{int(serial_number):03d}"


def ensure_default_cosmetics(wallet):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        existing = {
            row['cosmetic_key']
            for row in conn.execute('SELECT cosmetic_key FROM player_cosmetics WHERE wallet = ?', (wallet,)).fetchall()
        }
    for key in DEFAULT_STOCK_COSMETICS:
        if key not in existing:
            grant_cosmetic(wallet, key, 'stock')


def grant_cosmetic(wallet, cosmetic_key, source):
    ensure_runtime_tables()
    meta = next((item for item in COSMETIC_CATALOG if item['key'] == cosmetic_key), None)
    with closing(get_db()) as conn:
        if meta:
            serial_row = conn.execute(
                'SELECT COALESCE(MAX(serial_number), 0) AS max_serial FROM player_cosmetics WHERE cosmetic_type = ?',
                (meta['type'],),
            ).fetchone()
            next_serial = int((serial_row['max_serial'] if serial_row else 0) or 0) + 1
        else:
            next_serial = None
        conn.execute(
            '''
            INSERT OR IGNORE INTO player_cosmetics (wallet, cosmetic_key, cosmetic_type, serial_number, source, equipped, unlocked_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            ''',
            (wallet, cosmetic_key, (meta or {}).get('type'), next_serial, source, now_iso()),
        )
        if meta:
            same_type = conn.execute(
                '''
                SELECT pc.equipped, pc.cosmetic_key
                FROM player_cosmetics pc
                WHERE pc.wallet = ?
                ''',
                (wallet,),
            ).fetchall()
            type_keys = {item['key'] for item in COSMETIC_CATALOG if item['type'] == meta['type']}
            if not any(row['equipped'] and row['cosmetic_key'] in type_keys for row in same_type):
                conn.execute(
                    'UPDATE player_cosmetics SET equipped = 1 WHERE wallet = ? AND cosmetic_key = ?',
                    (wallet, cosmetic_key),
                )
        conn.commit()


def equipped_cosmetics(wallet):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT cosmetic_key, serial_number, cosmetic_type FROM player_cosmetics WHERE wallet = ? AND equipped = 1 ORDER BY unlocked_at DESC',
            (wallet,),
        ).fetchall()
    meta_by_key = {item['key']: item for item in COSMETIC_CATALOG}
    equipped = {}
    for row in rows:
        meta = meta_by_key.get(row['cosmetic_key'])
        if not meta:
            continue
        equipped.setdefault(meta['type'], {
            'key': meta['key'],
            'name': meta['name'],
            'type': meta['type'],
            'emoji': meta.get('emoji'),
            'rarity_key': cosmetic_item_rarity(meta),
            'serial_number': row['serial_number'],
            'serial': cosmetic_serial_label(row['cosmetic_type'] or meta['type'], row['serial_number']),
        })
    return equipped


def equip_cosmetic(wallet, cosmetic_key):
    ensure_runtime_tables()
    meta = next((item for item in COSMETIC_CATALOG if item['key'] == cosmetic_key), None)
    if not meta:
        raise ValueError('Косметический предмет не найден.')
    with closing(get_db()) as conn:
        row = conn.execute(
            'SELECT cosmetic_key FROM player_cosmetics WHERE wallet = ? AND cosmetic_key = ?',
            (wallet, cosmetic_key),
        ).fetchone()
        if row is None:
            raise ValueError('Этот предмет ещё не открыт.')
        type_keys = [item['key'] for item in COSMETIC_CATALOG if item['type'] == meta['type']]
        conn.executemany(
            'UPDATE player_cosmetics SET equipped = 0 WHERE wallet = ? AND cosmetic_key = ?',
            [(wallet, key) for key in type_keys],
        )
        conn.execute(
            'UPDATE player_cosmetics SET equipped = 1 WHERE wallet = ? AND cosmetic_key = ?',
            (wallet, cosmetic_key),
        )
        conn.commit()
    return cosmetic_inventory(wallet), equipped_cosmetics(wallet)


def cosmetic_inventory(wallet):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT cosmetic_key, cosmetic_type, serial_number, source, equipped, unlocked_at FROM player_cosmetics WHERE wallet = ? ORDER BY unlocked_at DESC',
            (wallet,),
        ).fetchall()
    meta_by_key = {item['key']: item for item in COSMETIC_CATALOG}
    return [
        {
            'key': row['cosmetic_key'],
            'name': meta_by_key.get(row['cosmetic_key'], {}).get('name', row['cosmetic_key']),
            'type': meta_by_key.get(row['cosmetic_key'], {}).get('type', 'cosmetic'),
            'emoji': meta_by_key.get(row['cosmetic_key'], {}).get('emoji'),
            'rarity_key': cosmetic_item_rarity(meta_by_key.get(row['cosmetic_key'], {})),
            'serial_number': row['serial_number'],
            'serial': cosmetic_serial_label(row['cosmetic_type'] or meta_by_key.get(row['cosmetic_key'], {}).get('type', 'cosmetic'), row['serial_number']),
            'nft_family': meta_by_key.get(row['cosmetic_key'], {}).get('nft_family'),
            'source': row['source'],
            'equipped': bool(row['equipped']),
            'unlocked_at': row['unlocked_at'],
        }
        for row in rows
    ]


def season_pass_cosmetic_pool(cosmetic_type):
    return [item for item in COSMETIC_CATALOG if item['type'] == cosmetic_type]


def season_pass_random_cosmetic(wallet, level, cosmetic_type):
    pool = season_pass_cosmetic_pool(cosmetic_type)
    if not pool:
        return None
    seed = f'{wallet}:{int(level)}:{cosmetic_type}:season-pass-v2'
    digest = hashlib.sha256(seed.encode('utf-8')).hexdigest()
    index = int(digest[:8], 16) % len(pool)
    return pool[index]


def season_pass_random_cosmetic_pack_item(wallet, level):
    pool = list(COSMETIC_CATALOG)
    if not pool:
        return None
    seed = f'{wallet}:{int(level)}:cosmetic-pack:season-pass-v3'
    digest = hashlib.sha256(seed.encode('utf-8')).hexdigest()
    index = int(digest[:8], 16) % len(pool)
    return pool[index]


def cosmetic_item_rarity(item):
    key = str((item or {}).get('rarity_key') or 'basic').strip().lower()
    if key not in COSMETIC_PACK_RARITY_WEIGHTS:
        return 'basic'
    return key


def draw_cosmetic_pack_item(seed_text):
    pool = list(COSMETIC_CATALOG)
    if not pool:
        return None
    rng = random.Random(hashlib.sha256(str(seed_text).encode('utf-8')).hexdigest())
    by_rarity = {}
    for item in pool:
        rarity = cosmetic_item_rarity(item)
        by_rarity.setdefault(rarity, []).append(item)
    rarities = [key for key in COSMETIC_PACK_RARITY_WEIGHTS.keys() if by_rarity.get(key)]
    if not rarities:
        return pool[rng.randint(0, len(pool) - 1)]
    rarity_weights = [COSMETIC_PACK_RARITY_WEIGHTS.get(key, 0) for key in rarities]
    chosen_rarity = rng.choices(rarities, weights=rarity_weights, k=1)[0]
    candidates = by_rarity.get(chosen_rarity) or pool
    candidate_weights = [max(0.01, float((item or {}).get('drop_weight', 1.0))) for item in candidates]
    return rng.choices(candidates, weights=candidate_weights, k=1)[0]


def season_pass_claimed_levels(wallet):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT reward_tier, level FROM season_pass_claims WHERE wallet = ?',
            (wallet,),
        ).fetchall()
    claimed = {'free': set(), 'premium': set()}
    for row in rows:
        tier = str(row['reward_tier'] or '').strip().lower()
        if tier in claimed:
            claimed[tier].add(int(row['level'] or 0))
    return claimed


def season_pass_reward_descriptor(wallet, level, reward_tier):
    item = next((entry for entry in SEASON_PASS_TRACK if int(entry['level']) == int(level)), None)
    if not item:
        raise ValueError('Уровень пропуска не найден.')
    tier = str(reward_tier or '').strip().lower()
    if tier not in {'free', 'premium'}:
        raise ValueError('Неизвестный тип награды пропуска.')
    reward = dict(item.get(f'{tier}_reward') or {})
    if not reward:
        return {'level': int(level), 'tier': tier, 'reward': None, 'label': 'Нет награды'}
    if reward.get('kind') == 'cosmetic_pack':
        return {
            'level': int(level),
            'tier': tier,
            'reward': reward,
            'label': 'Косметический пак',
            'reward_meta': None,
        }
    return {
        'level': int(level),
        'tier': tier,
        'reward': reward,
        'label': reward.get('label') or 'Награда',
        'reward_meta': None,
    }


def claim_season_pass_reward(wallet, level, reward_tier):
    rewards = ensure_player_rewards(wallet)
    descriptor = season_pass_reward_descriptor(wallet, level, reward_tier)
    reward = descriptor.get('reward')
    if not reward:
        raise ValueError('На этом уровне нет награды.')
    tier = descriptor['tier']
    level = int(descriptor['level'])
    season_level = int(rewards.get('season_level', 1) or 1)
    if season_level < level:
        raise ValueError('Этот уровень пропуска ещё не открыт.')
    if tier == 'premium' and not bool(int(rewards.get('premium_pass', 0) or 0)):
        raise ValueError('Премиум-пропуск не активирован.')
    claimed = season_pass_claimed_levels(wallet)
    if level in claimed[tier]:
        raise ValueError('Награда этого уровня уже собрана.')
    with closing(get_db()) as conn:
        if reward.get('kind') == 'cosmetic_pack':
            current = ensure_player_rewards(wallet)
            cosmetic_packs = int(current.get('cosmetic_packs', 0) or 0) + 1
            conn.execute(
                '''
                UPDATE player_rewards
                SET cosmetic_packs = ?, updated_at = ?
                WHERE wallet = ?
                ''',
                (cosmetic_packs, now_iso(), wallet),
            )
        elif reward.get('kind') == 'currency':
            current = ensure_player_rewards(wallet)
            pack_shards = int(current.get('pack_shards', 0) or 0) + int(reward.get('pack_shards', 0) or 0)
            rare_tokens = int(current.get('rare_tokens', 0) or 0) + int(reward.get('rare_tokens', 0) or 0)
            lucky_tokens = int(current.get('lucky_tokens', 0) or 0) + int(reward.get('lucky_tokens', 0) or 0)
            conn.execute(
                '''
                UPDATE player_rewards
                SET pack_shards = ?, rare_tokens = ?, lucky_tokens = ?, updated_at = ?
                WHERE wallet = ?
                ''',
                (pack_shards, rare_tokens, lucky_tokens, now_iso(), wallet),
            )
        conn.execute(
            '''
            INSERT INTO season_pass_claims (wallet, reward_tier, level, claimed_at)
            VALUES (?, ?, ?, ?)
            ''',
            (wallet, tier, level, now_iso()),
        )
        conn.commit()
    return reward_summary(wallet)


def season_pass_track_payload(wallet=None, rewards=None):
    rewards = rewards or ({'season_level': 1, 'premium_pass': 0} if wallet is None else ensure_player_rewards(wallet))
    season_level = int(rewards.get('season_level', 1) or 1)
    premium_active = bool(rewards.get('premium_pass', 0))
    claimed = season_pass_claimed_levels(wallet) if wallet else {'free': set(), 'premium': set()}
    payload = []
    for item in SEASON_PASS_TRACK:
        premium_descriptor = season_pass_reward_descriptor(wallet, item['level'], 'premium') if wallet else {
            'label': (dict(item.get('premium_reward') or {}).get('label') if dict(item.get('premium_reward') or {}).get('kind') == 'currency' else 'Косметический пак')
            if item.get('premium_reward') else None,
            'reward': dict(item.get('premium_reward') or {}),
        }
        free_descriptor = season_pass_reward_descriptor(wallet, item['level'], 'free') if wallet else {
            'label': (
                dict(item.get('free_reward') or {}).get('label')
                if dict(item.get('free_reward') or {}).get('kind') == 'currency'
                else ('Косметический пак' if item.get('free_reward') else None)
            ),
            'reward': dict(item.get('free_reward') or {}),
        }
        premium_claimed = int(item['level']) in claimed['premium']
        free_claimed = int(item['level']) in claimed['free']
        payload.append(
            {
                **item,
                'premium': premium_descriptor.get('label'),
                'premium_key': (premium_descriptor.get('reward_meta') or {}).get('key') if premium_descriptor else None,
                'free': free_descriptor.get('label'),
                'free_ready': season_level >= int(item['level']),
                'premium_ready': premium_active and season_level >= int(item['level']),
                'free_claimed': free_claimed,
                'premium_claimed': premium_claimed,
                'free_claimable': bool(free_descriptor.get('reward')) and season_level >= int(item['level']) and not free_claimed,
                'premium_claimable': bool(premium_descriptor.get('reward')) and premium_active and season_level >= int(item['level']) and not premium_claimed,
            }
        )
    return payload


SEASON_PASS_LEVEL_POINTS = 16
SEASON_PASS_TUTORIAL_POINTS = 3
SEASON_PASS_DAILY_POINTS = 1
SEASON_PASS_GUILD_CLAIM_POINTS = 3
SEASON_PASS_TASKS = [
    {'key': 'daily_play_6', 'label': 'Сыграть 6 матчей', 'target': 6, 'reward_points': 10},
    {'key': 'daily_win_4', 'label': 'Выиграть 4 матча', 'target': 4, 'reward_points': 14},
    {'key': 'daily_open_3_packs', 'label': 'Открыть 3 пака', 'target': 3, 'reward_points': 12},
]


def normalize_reward_progress_fields(*, pack_shards, rare_tokens, lucky_tokens, season_points, season_level, wins_for_quest, wins_claimed, cosmetic_packs=None):
    season_level = max(1, int(season_level or 1))
    season_points = max(0, int(season_points or 0))
    lucky_tokens = max(0, int(lucky_tokens or 0))
    while season_points >= season_level * SEASON_PASS_LEVEL_POINTS:
        season_points -= season_level * SEASON_PASS_LEVEL_POINTS
        season_level += 1
        lucky_tokens += 1
    return {
        'pack_shards': max(0, int(pack_shards or 0)),
        'rare_tokens': max(0, int(rare_tokens or 0)),
        'lucky_tokens': lucky_tokens,
        'cosmetic_packs': max(0, int(cosmetic_packs or 0)),
        'season_points': season_points,
        'season_level': season_level,
        'wins_for_quest': max(0, int(wins_for_quest or 0)),
        'wins_claimed': max(0, int(wins_claimed or 0)),
    }


def season_task_claimed_keys(wallet, task_day=None):
    day_key = task_day or today_utc_str()
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT task_key FROM season_task_claims WHERE wallet = ? AND task_day = ?',
            (wallet, day_key),
        ).fetchall()
    return {row['task_key'] for row in rows}


def season_task_progress(wallet):
    ensure_runtime_tables()
    day_key = today_utc_str()
    with closing(get_db()) as conn:
        telemetry_rows = conn.execute(
            '''
            SELECT event_type, payload_json
            FROM domain_telemetry
            WHERE wallet = ? AND created_at LIKE ?
            ''',
            (wallet, f'{day_key}%'),
        ).fetchall()
        pack_row = conn.execute(
            'SELECT COUNT(*) AS value FROM pack_opens WHERE wallet = ? AND opened_on = ?',
            (wallet, day_key),
        ).fetchone()
    matches_today = 0
    wins_today = 0
    for row in telemetry_rows:
        event_type = str(row['event_type'] or '')
        if not event_type.endswith('_battle_complete'):
            continue
        matches_today += 1
        try:
            payload = json.loads(row['payload_json'] or '{}')
        except json.JSONDecodeError:
            payload = {}
        if str(payload.get('result') or '').lower() == 'win':
            wins_today += 1
    packs_today = int((pack_row['value'] if pack_row else 0) or 0)
    claimed_keys = season_task_claimed_keys(wallet, task_day=day_key)
    metrics = {
        'daily_play_6': matches_today,
        'daily_win_4': wins_today,
        'daily_open_3_packs': packs_today,
    }
    tasks = []
    for item in SEASON_PASS_TASKS:
        progress = int(metrics.get(item['key'], 0) or 0)
        target = int(item['target'])
        claimed = item['key'] in claimed_keys
        tasks.append(
            {
                **item,
                'progress': min(progress, target),
                'claimed': claimed,
                'claimable': (progress >= target) and not claimed,
                'day_key': day_key,
            }
        )
    return tasks


def reward_summary(wallet):
    rewards = ensure_player_rewards(wallet)
    rewards['daily_available'] = rewards.get('daily_claimed_on') != today_utc_str()
    rewards['quest_ready'] = int(rewards.get('wins_for_quest', 0)) - int(rewards.get('wins_claimed', 0)) >= 3
    rewards['next_quest_target'] = int(rewards.get('wins_claimed', 0)) + 3
    rewards['season_target'] = max(SEASON_PASS_LEVEL_POINTS, int(rewards.get('season_level', 1)) * SEASON_PASS_LEVEL_POINTS)
    rewards['season_progress'] = round(int(rewards.get('season_points', 0)) / max(1, rewards['season_target']), 3)
    rewards['premium_pass'] = int(rewards.get('premium_pass', 0) or 0)
    rewards['premium_pass_active'] = bool(rewards['premium_pass'])
    rewards['season_pass_track'] = season_pass_track_payload(wallet=wallet, rewards=rewards)
    rewards['season_tasks'] = season_task_progress(wallet)
    rewards['season_tasks_claimable'] = sum(1 for item in rewards['season_tasks'] if item.get('claimable'))
    rewards['cosmetics'] = cosmetic_inventory(wallet)
    rewards['cosmetic_catalog'] = COSMETIC_CATALOG
    rewards['equipped_cosmetics'] = equipped_cosmetics(wallet)
    return rewards


def ensure_tutorial_progress(wallet):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM tutorial_progress WHERE wallet = ?', (wallet,)).fetchone()
        if row is None:
            conn.execute(
                '''
                INSERT INTO tutorial_progress (wallet, started_at, completed_at, skipped_at, rewarded_at, attempts, wins, updated_at)
                VALUES (?, NULL, NULL, NULL, NULL, 0, 0, ?)
                ''',
                (wallet, now_iso()),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM tutorial_progress WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row)


def tutorial_summary(wallet):
    progress = ensure_tutorial_progress(wallet)
    completed = bool(progress.get('completed_at'))
    skipped = bool(progress.get('skipped_at')) and not completed
    return {
        'started': bool(progress.get('started_at')),
        'completed': completed,
        'skipped': skipped,
        'rewarded': bool(progress.get('rewarded_at')),
        'attempts': int(progress.get('attempts', 0) or 0),
        'wins': int(progress.get('wins', 0) or 0),
        'available': not completed,
        'cta': 'Пройти боевой туториал' if not completed else 'Туториал завершён',
    }


def update_tutorial_progress(wallet, **fields):
    ensure_tutorial_progress(wallet)
    updates = []
    params = []
    for key, value in fields.items():
        updates.append(f'{key} = ?')
        params.append(value)
    updates.append('updated_at = ?')
    params.append(now_iso())
    params.append(wallet)
    with closing(get_db()) as conn:
        conn.execute(f'UPDATE tutorial_progress SET {", ".join(updates)} WHERE wallet = ?', params)
        conn.commit()
    return tutorial_summary(wallet)


def mark_tutorial_started(wallet):
    progress = ensure_tutorial_progress(wallet)
    return update_tutorial_progress(
        wallet,
        started_at=progress.get('started_at') or now_iso(),
        attempts=int(progress.get('attempts', 0) or 0) + 1,
    )


def mark_tutorial_skipped(wallet):
    summary = update_tutorial_progress(wallet, skipped_at=now_iso())
    log_domain_telemetry('tutorial_skipped', wallet=wallet, payload={'attempts': summary['attempts']})
    return summary


def grant_tutorial_reward(wallet):
    progress = ensure_tutorial_progress(wallet)
    if progress.get('rewarded_at'):
        return reward_summary(wallet), {'pack_shards': 0, 'rare_tokens': 0, 'lucky_tokens': 0, 'season_points': 0}
    rewards = ensure_player_rewards(wallet)
    normalized = normalize_reward_progress_fields(
        pack_shards=int(rewards.get('pack_shards', 0)) + 5,
        rare_tokens=int(rewards.get('rare_tokens', 0)) + 1,
        lucky_tokens=int(rewards.get('lucky_tokens', 0)),
        season_points=int(rewards.get('season_points', 0)) + SEASON_PASS_TUTORIAL_POINTS,
        season_level=rewards.get('season_level', 1),
        wins_for_quest=rewards.get('wins_for_quest', 0),
        wins_claimed=rewards.get('wins_claimed', 0),
    )
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE player_rewards
            SET pack_shards = ?, rare_tokens = ?, lucky_tokens = ?, season_points = ?, season_level = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                normalized['pack_shards'],
                normalized['rare_tokens'],
                normalized['lucky_tokens'],
                normalized['season_points'],
                normalized['season_level'],
                now_iso(),
                wallet,
            ),
        )
        conn.commit()
    update_tutorial_progress(wallet, rewarded_at=now_iso())
    return reward_summary(wallet), {'pack_shards': 5, 'rare_tokens': 1, 'lucky_tokens': 0, 'season_points': SEASON_PASS_TUTORIAL_POINTS}


def grant_match_rewards(wallet, *, won=False, ranked=False):
    rewards = ensure_player_rewards(wallet)
    premium_bonus = 1 if int(rewards.get('premium_pass', 0) or 0) else 0
    pack_shards = int(rewards.get('pack_shards', 0)) + (2 if won else 1) + premium_bonus
    rare_tokens = int(rewards.get('rare_tokens', 0))
    lucky_tokens = int(rewards.get('lucky_tokens', 0))
    season_points = int(rewards.get('season_points', 0)) + (3 if ranked else 2) + (2 if won else 0) + premium_bonus
    wins_for_quest = int(rewards.get('wins_for_quest', 0)) + (1 if won else 0)
    wins_claimed = int(rewards.get('wins_claimed', 0))
    normalized = normalize_reward_progress_fields(
        pack_shards=pack_shards,
        rare_tokens=rare_tokens,
        lucky_tokens=lucky_tokens,
        season_points=season_points,
        season_level=rewards.get('season_level', 1),
        wins_for_quest=wins_for_quest,
        wins_claimed=wins_claimed,
    )
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE player_rewards
            SET pack_shards = ?, rare_tokens = ?, lucky_tokens = ?, season_points = ?,
                season_level = ?, wins_for_quest = ?, wins_claimed = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                normalized['pack_shards'],
                normalized['rare_tokens'],
                normalized['lucky_tokens'],
                normalized['season_points'],
                normalized['season_level'],
                normalized['wins_for_quest'],
                normalized['wins_claimed'],
                now_iso(),
                wallet,
            ),
        )
        conn.commit()
    return reward_summary(wallet)


def claim_daily_reward(wallet):
    rewards = ensure_player_rewards(wallet)
    if rewards.get('daily_claimed_on') == today_utc_str():
        raise ValueError('Ежедневная награда уже получена.')
    normalized = normalize_reward_progress_fields(
        pack_shards=int(rewards.get('pack_shards', 0)) + 3,
        rare_tokens=rewards.get('rare_tokens', 0),
        lucky_tokens=rewards.get('lucky_tokens', 0),
        season_points=int(rewards.get('season_points', 0)) + SEASON_PASS_DAILY_POINTS,
        season_level=rewards.get('season_level', 1),
        wins_for_quest=rewards.get('wins_for_quest', 0),
        wins_claimed=rewards.get('wins_claimed', 0),
    )
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE player_rewards
            SET pack_shards = ?, lucky_tokens = ?, season_points = ?, season_level = ?, daily_claimed_on = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                normalized['pack_shards'],
                normalized['lucky_tokens'],
                normalized['season_points'],
                normalized['season_level'],
                today_utc_str(),
                now_iso(),
                wallet,
            ),
        )
        conn.commit()
    return reward_summary(wallet)


def claim_win_quest_reward(wallet):
    rewards = ensure_player_rewards(wallet)
    available = int(rewards.get('wins_for_quest', 0)) - int(rewards.get('wins_claimed', 0))
    if available < 3:
        raise ValueError('Квест на победы ещё не готов.')
    rare_tokens = int(rewards.get('rare_tokens', 0)) + 1
    wins_claimed = int(rewards.get('wins_claimed', 0)) + 3
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE player_rewards
            SET rare_tokens = ?, wins_claimed = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (rare_tokens, wins_claimed, now_iso(), wallet),
        )
        conn.commit()
    return reward_summary(wallet)


def claim_season_task_reward(wallet, task_key):
    rewards = ensure_player_rewards(wallet)
    tasks = {item['key']: item for item in season_task_progress(wallet)}
    task = tasks.get(str(task_key or '').strip())
    if not task:
        raise ValueError('Такое задание пропуска не найдено.')
    if task.get('claimed'):
        raise ValueError('Награда за это задание уже забрана.')
    if not task.get('claimable'):
        raise ValueError('Задание пропуска ещё не выполнено.')
    normalized = normalize_reward_progress_fields(
        pack_shards=int(rewards.get('pack_shards', 0)),
        rare_tokens=int(rewards.get('rare_tokens', 0)),
        lucky_tokens=int(rewards.get('lucky_tokens', 0)),
        cosmetic_packs=int(rewards.get('cosmetic_packs', 0)),
        season_points=int(rewards.get('season_points', 0)) + int(task.get('reward_points', 0) or 0),
        season_level=rewards.get('season_level', 1),
        wins_for_quest=rewards.get('wins_for_quest', 0),
        wins_claimed=rewards.get('wins_claimed', 0),
    )
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO season_task_claims (wallet, task_key, task_day, claimed_at)
            VALUES (?, ?, ?, ?)
            ''',
            (wallet, task['key'], task['day_key'], now_iso()),
        )
        conn.execute(
            '''
            UPDATE player_rewards
            SET pack_shards = ?, rare_tokens = ?, lucky_tokens = ?, cosmetic_packs = ?, season_points = ?, season_level = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                normalized['pack_shards'],
                normalized['rare_tokens'],
                normalized['lucky_tokens'],
                normalized['cosmetic_packs'],
                normalized['season_points'],
                normalized['season_level'],
                now_iso(),
                wallet,
            ),
        )
        conn.commit()
    return reward_summary(wallet)


def pack_costs(pack_type):
    return dict(pack_config(pack_type).get('costs') or {})


def can_afford_pack_type(wallet, pack_type):
    rewards = ensure_player_rewards(wallet)
    costs = pack_costs(pack_type)
    missing = {
        key: max(0, int(value or 0) - int(rewards.get(key, 0) or 0))
        for key, value in costs.items()
        if int(rewards.get(key, 0) or 0) < int(value or 0)
    }
    return {'ok': not missing, 'costs': costs, 'missing': missing, 'rewards': rewards}


def spend_pack_currency(wallet, pack_type):
    affordability = can_afford_pack_type(wallet, pack_type)
    if not affordability['ok']:
        details = ', '.join(f'{key}:{value}' for key, value in affordability['missing'].items())
        raise ValueError(f'Недостаточно валюты для {pack_config(pack_type)["label"]}: {details}')
    rewards = affordability['rewards']
    costs = affordability['costs']
    normalized = normalize_reward_progress_fields(
        pack_shards=int(rewards.get('pack_shards', 0)) - int(costs.get('pack_shards', 0)),
        rare_tokens=int(rewards.get('rare_tokens', 0)) - int(costs.get('rare_tokens', 0)),
        lucky_tokens=int(rewards.get('lucky_tokens', 0)) - int(costs.get('lucky_tokens', 0)),
        cosmetic_packs=int(rewards.get('cosmetic_packs', 0)) - int(costs.get('cosmetic_packs', 0)),
        season_points=rewards.get('season_points', 0),
        season_level=rewards.get('season_level', 1),
        wins_for_quest=rewards.get('wins_for_quest', 0),
        wins_claimed=rewards.get('wins_claimed', 0),
    )
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE player_rewards
            SET pack_shards = ?, rare_tokens = ?, lucky_tokens = ?, cosmetic_packs = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                normalized['pack_shards'],
                normalized['rare_tokens'],
                normalized['lucky_tokens'],
                normalized['cosmetic_packs'],
                now_iso(),
                wallet,
            ),
        )
        conn.commit()
    return reward_summary(wallet)


def extract_trait_flags(meta):
    return set(meta.get('traitFlags') or [])


def compute_domain_synergies(wallet, domains=None):
    if not wallet:
        return {'attack': 0, 'defense': 0, 'luck': 0, 'energy': 0, 'labels': []}
    if domains is None:
        try:
            domains = wallet_domains_for_game(wallet, allow_fallback=True)
        except Exception:
            domains = []
    metas = []
    for item in domains or []:
        domain = item.get('domain') if isinstance(item, dict) else normalize_domain(item)
        if not domain:
            continue
        metas.append(get_domain_metadata_payload(domain, wallet=wallet))
    flags = [extract_trait_flags(meta or {}) for meta in metas]
    labels = []
    attack = defense = luck = energy = 0
    pairish = sum(1 for item in flags if {'low-entropy', 'palindrome'} & item or 'double-pair' in item)
    has_eight = sum(1 for item in flags if 'has-eight' in item)
    mirrorish = sum(1 for item in flags if 'palindrome' in item)
    zeroish = sum(1 for item in flags if 'has-zero' in item)
    if pairish >= 2:
        defense += 1
        labels.append('2 домена с повтором: +1 к защите')
    if has_eight >= 3:
        luck += 1
        labels.append('3 домена с 8: +1 к удаче')
    if mirrorish >= 2:
        energy += 1
        labels.append('2 зеркальных домена: +1 к энергии')
    if zeroish >= 2:
        attack += 1
        labels.append('2 домена с 0: +1 к атаке')
    return {'attack': attack, 'defense': defense, 'luck': luck, 'energy': energy, 'labels': labels}


def telemetry_summary(wallet=None):
    ensure_runtime_tables()
    params = []
    where = ''
    if wallet:
        where = 'WHERE wallet = ?'
        params.append(wallet)
    with closing(get_db()) as conn:
        rows = conn.execute(
            f'''
            SELECT wallet, domain, rarity_label, event_type, payload_json, created_at
            FROM domain_telemetry
            {where}
            ORDER BY created_at DESC
            ''',
            tuple(params),
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        try:
            item['payload'] = json.loads(item.pop('payload_json') or '{}')
        except json.JSONDecodeError:
            item['payload'] = {}
        events.append(item)

    battle_events = [item for item in events if item['event_type'].endswith('_battle_complete')]
    pack_events = [item for item in events if item['event_type'] == 'pack_open']
    rarity_stats = {}
    domain_stats = {}
    ability_usage = 0
    damage_distribution = []
    match_durations = []
    for item in battle_events:
        payload = item.get('payload') or {}
        rarity_key = item.get('rarity_label') or 'Unknown'
        rarity_stats.setdefault(rarity_key, {'matches': 0, 'wins': 0})
        rarity_stats[rarity_key]['matches'] += 1
        if payload.get('result') == 'win':
            rarity_stats[rarity_key]['wins'] += 1
        domain_key = item.get('domain') or 'unknown'
        domain_stats.setdefault(domain_key, {'matches': 0, 'wins': 0})
        domain_stats[domain_key]['matches'] += 1
        if payload.get('result') == 'win':
            domain_stats[domain_key]['wins'] += 1
        if payload.get('ability_used'):
            ability_usage += 1
        if payload.get('match_duration_rounds') is not None:
            match_durations.append(int(payload.get('match_duration_rounds') or 0))
        if payload.get('own_score') is not None and payload.get('opp_score') is not None:
            damage_distribution.append({'own_score': payload.get('own_score'), 'opp_score': payload.get('opp_score')})

    for bucket in list(rarity_stats.values()) + list(domain_stats.values()):
        matches = max(1, int(bucket.get('matches', 0)))
        bucket['win_rate'] = round(bucket.get('wins', 0) / matches, 3)

    return {
        'events_total': len(events),
        'battle_events_total': len(battle_events),
        'pack_events_total': len(pack_events),
        'rarity_win_rates': rarity_stats,
        'domain_win_rates': domain_stats,
        'ability_usage_rate': round(ability_usage / max(1, len(battle_events)), 3),
        'match_duration_avg': round(sum(match_durations) / max(1, len(match_durations)), 2) if match_durations else 0,
        'damage_distribution': damage_distribution[-25:],
        'recent_events': events[:25],
    }


def get_domain_metadata_payload(domain, wallet=None):
    normalized = normalize_domain(domain)
    if not normalized:
        return None
    progress = load_domain_progress(wallet, normalized) if wallet else {'level': 1, 'experience': 0}
    metadata = getDomainMetadata(normalized, progress=progress)
    metadata['winRate'] = (
        round(progress.get('total_wins', 0) / progress.get('total_matches', 1), 3)
        if progress.get('total_matches', 0)
        else 0
    )
    metadata['totalMatches'] = int(progress.get('total_matches', 0))
    metadata['totalWins'] = int(progress.get('total_wins', 0))
    return metadata


def guest_domain_payload(wallet):
    domain = guest_domain_for_wallet(wallet)
    base = score_from_domain(domain, wallet=wallet)
    return {
        'domain': domain,
        'domain_exists': True,
        'source_label': 'Гостевой профиль (игра без домена)',
        'patterns': base['patterns'],
        'tier': base['tier'],
        'special_collections': base.get('special_collections', []),
        'luck': base.get('luck', 0),
        'score': base['score'],
        'rarity': base.get('rarity'),
        'metadata': base.get('metadata'),
        'is_guest': True,
    }


def wallet_domains_for_game(wallet, force_refresh=False, allow_fallback=False):
    try:
        domains = fetch_wallet_domains(wallet, force_refresh=force_refresh)
    except (RuntimeError, ValueError):
        if not (allow_fallback and guest_access_enabled()):
            raise
        domains = []
    if not domains and guest_access_enabled():
        return [guest_domain_payload(wallet)]
    return domains


def today_utc_str():
    return now_utc().date().isoformat()


def weekly_notification_key():
    return week_utc_key()


def maybe_send_daily_reward_notification(wallet, rewards=None):
    if not TG_BOT_TOKEN:
        return None
    prefs = ensure_telegram_notification_prefs(wallet)
    if not int(prefs.get('notify_daily_reward', 1) or 0):
        return None
    rewards = rewards or reward_summary(wallet)
    today_key = today_utc_str()
    if not rewards.get('daily_available'):
        return False
    with closing(get_db()) as conn:
        cursor = conn.execute(
            '''
            UPDATE telegram_notification_prefs
            SET last_daily_notified_on = ?, updated_at = ?
            WHERE wallet = ?
              AND notify_daily_reward = 1
              AND (last_daily_notified_on IS NULL OR last_daily_notified_on != ?)
            ''',
            (today_key, now_iso(), wallet, today_key),
        )
        conn.commit()
        should_send = cursor.rowcount > 0
    if not should_send:
        return None
    return 'Ежедневная награда обновилась. Зайди в профиль и забери её.'


def maybe_send_win_quest_notification(wallet, rewards=None):
    if not TG_BOT_TOKEN:
        return None
    prefs = ensure_telegram_notification_prefs(wallet)
    if not int(prefs.get('notify_win_quest', 1) or 0):
        return None
    rewards = rewards or reward_summary(wallet)
    if not rewards.get('quest_ready'):
        return None
    target = int(rewards.get('next_quest_target', 0) or 0)
    if target <= 0:
        return False
    with closing(get_db()) as conn:
        cursor = conn.execute(
            '''
            UPDATE telegram_notification_prefs
            SET last_quest_notified_target = ?, updated_at = ?
            WHERE wallet = ?
              AND notify_win_quest = 1
              AND COALESCE(last_quest_notified_target, 0) < ?
            ''',
            (target, now_iso(), wallet, target),
        )
        conn.commit()
        should_send = cursor.rowcount > 0
    if not should_send:
        return None
    return 'Готова награда за квест на победы. В профиле доступен сбор.'


def maybe_send_season_pass_notification(wallet, rewards=None):
    if not TG_BOT_TOKEN:
        return None
    prefs = ensure_telegram_notification_prefs(wallet)
    if not int(prefs.get('notify_season_pass', 1) or 0):
        return None
    rewards = rewards or reward_summary(wallet)
    track = rewards.get('season_pass_track') or []
    claimable_levels = [
        int(item.get('level') or 0)
        for item in track
        if item.get('premium_claimable') or item.get('free_claimable')
    ]
    if not claimable_levels:
        return None
    top_level = max(claimable_levels)
    with closing(get_db()) as conn:
        cursor = conn.execute(
            '''
            UPDATE telegram_notification_prefs
            SET last_season_notified_level = ?, updated_at = ?
            WHERE wallet = ?
              AND notify_season_pass = 1
              AND COALESCE(last_season_notified_level, 0) < ?
            ''',
            (top_level, now_iso(), wallet, top_level),
        )
        conn.commit()
        should_send = cursor.rowcount > 0
    if not should_send:
        return None
    return f'В сезонном пропуске доступна награда. Текущий уровень: {top_level}.'


def maybe_send_guild_reward_notification(wallet):
    if not TG_BOT_TOKEN:
        return None
    prefs = ensure_telegram_notification_prefs(wallet)
    if not int(prefs.get('notify_guild_reward', 1) or 0):
        return None
    membership = current_guild_membership(wallet)
    if not membership:
        return None
    goals = guild_goal_summary(membership['guild_id'])
    week_key = weekly_notification_key()
    if not goals.get('weekly_reward_ready'):
        return False
    with closing(get_db()) as conn:
        cursor = conn.execute(
            '''
            UPDATE telegram_notification_prefs
            SET last_guild_reward_week = ?, updated_at = ?
            WHERE wallet = ?
              AND notify_guild_reward = 1
              AND (last_guild_reward_week IS NULL OR last_guild_reward_week != ?)
            ''',
            (week_key, now_iso(), wallet, week_key),
        )
        conn.commit()
        should_send = cursor.rowcount > 0
    if not should_send:
        return None
    return f'Готова недельная награда клана «{membership["name"]}».'


def dispatch_wallet_telegram_notifications(wallet):
    if not TG_BOT_TOKEN or not telegram_wallet_link(wallet):
        return []
    rewards = reward_summary(wallet)
    sent = []
    messages = []
    daily = maybe_send_daily_reward_notification(wallet, rewards=rewards)
    if daily:
        sent.append('daily_reward')
        messages.append(f'• {daily}')
    quest = maybe_send_win_quest_notification(wallet, rewards=rewards)
    if quest:
        sent.append('win_quest')
        messages.append(f'• {quest}')
    season = maybe_send_season_pass_notification(wallet, rewards=rewards)
    if season:
        sent.append('season_pass')
        messages.append(f'• {season}')
    guild = maybe_send_guild_reward_notification(wallet)
    if guild:
        sent.append('guild_reward')
        messages.append(f'• {guild}')
    if messages:
        telegram_notify_wallet(
            wallet,
            'Новые события в tondomaingame:\n' + '\n'.join(messages) + '\n\nОткрой игру, чтобы забрать награды и проверить прогресс.',
        )
    return sent


def telegram_notification_scan_once():
    for wallet in telegram_notification_wallets():
        try:
            dispatch_wallet_telegram_notifications(wallet)
        except Exception:
            continue


def telegram_notification_loop():
    while True:
        try:
            telegram_notification_scan_once()
        except Exception:
            pass
        time.sleep(max(30, TELEGRAM_NOTIFY_SCAN_INTERVAL_SECONDS))


def ensure_telegram_notification_worker():
    global TELEGRAM_NOTIFY_THREAD
    if not TG_BOT_TOKEN:
        return
    with TELEGRAM_NOTIFY_THREAD_LOCK:
        if TELEGRAM_NOTIFY_THREAD and TELEGRAM_NOTIFY_THREAD.is_alive():
            return
        TELEGRAM_NOTIFY_THREAD = threading.Thread(
            target=telegram_notification_loop,
            name='telegram-notify-loop',
            daemon=True,
        )
        TELEGRAM_NOTIFY_THREAD.start()


def can_open_daily_pack(wallet, domain):
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT COUNT(*) AS cnt
            FROM pack_opens
            WHERE wallet = ? AND domain = ? AND opened_on = ? AND source = 'daily'
            ''',
            (wallet, domain, today_utc_str()),
        ).fetchone()
    return (row['cnt'] if row else 0) < DAILY_FREE_PACKS


def store_pack_open(wallet, domain, source, cards, total_score, payment_id=None):
    pack_id = uuid.uuid4().hex
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO pack_opens (id, wallet, domain, source, opened_on, payment_id, cards_json, total_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                pack_id,
                wallet,
                domain,
                source,
                today_utc_str(),
                payment_id,
                json.dumps(cards, ensure_ascii=False),
                total_score,
                now_iso(),
            ),
        )
        conn.commit()
    return pack_id


def reseat_cards(cards):
    reseated = []
    for idx, card in enumerate(cards or [], start=1):
        normalized = normalize_card_profile(card)
        normalized['slot'] = idx
        reseated.append(normalized)
    return reseated


def shuffle_deck_cards(cards, seed_value):
    rng = random.Random(hashlib.sha256(str(seed_value).encode()).hexdigest())
    shuffled = [normalize_card_profile(card) for card in (cards or [])]
    rng.shuffle(shuffled)
    return reseat_cards(shuffled)


def ensure_battle_ready_cards(cards, domain, seed_value=None):
    normalized_domain = normalize_domain(domain)
    prepared = [normalize_card_profile(card) for card in (cards or [])][:CARD_POOL_SIZE]
    if normalized_domain and len(prepared) < CARD_POOL_SIZE:
        filler_seed = seed_value or f'battle-ready:{normalized_domain}:{len(prepared)}'
        rng = random.Random(hashlib.sha256(str(filler_seed).encode()).hexdigest())
        base = score_from_domain(normalized_domain)
        weights = rarity_weights_for_domain(base)
        taken_slots = {int(card.get('slot') or 0) for card in prepared}
        for slot_value in range(1, CARD_POOL_SIZE + 1):
            if len(prepared) >= CARD_POOL_SIZE:
                break
            if slot_value in taken_slots:
                continue
            rarity = weighted_choice(weights, rng)
            template = rng.choice(CARD_CATALOG_BY_RARITY[rarity])
            filler = materialize_card(template, normalized_domain, slot_value)
            filler['patterns'] = base.get('patterns', [])
            filler['domain_metadata'] = base.get('metadata')
            prepared.append(normalize_card_profile(filler))
            taken_slots.add(slot_value)
    return reseat_cards(prepared[:CARD_POOL_SIZE])


def create_pack_payment(wallet, domain):
    payment_id = uuid.uuid4().hex
    memo = f'PACK:{payment_id}:{wallet[:8]}'
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO pack_payments (id, wallet, domain, amount_nano, memo, status, tx_hash, created_at, confirmed_at)
            VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?, NULL)
            ''',
            (payment_id, wallet, domain, PACK_PRICE_NANO, memo, now_iso()),
        )
        conn.commit()
    return payment_id, memo


def confirm_pack_payment(payment_id, wallet, tx_hash=None):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM pack_payments WHERE id = ?', (payment_id,)).fetchone()
        if row is None:
            raise ValueError('Платёж не найден.')
        if row['wallet'] != wallet:
            raise ValueError('Платёж принадлежит другому кошельку.')
        if row['status'] == 'confirmed':
            return dict(row)
        conn.execute(
            'UPDATE pack_payments SET status = ?, tx_hash = ?, confirmed_at = ? WHERE id = ?',
            ('confirmed', tx_hash, now_iso(), payment_id),
        )
        conn.commit()
        updated = conn.execute('SELECT * FROM pack_payments WHERE id = ?', (payment_id,)).fetchone()
    return dict(updated)


def create_season_pass_payment(wallet):
    payment_id = uuid.uuid4().hex
    memo = f'PASS:{payment_id}:{wallet[:8]}'
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO season_pass_payments (id, wallet, amount_nano, memo, status, tx_hash, created_at, confirmed_at)
            VALUES (?, ?, ?, ?, 'pending', NULL, ?, NULL)
            ''',
            (payment_id, wallet, SEASON_PASS_PRICE_NANO, memo, now_iso()),
        )
        conn.commit()
    return payment_id, memo


def confirm_season_pass_payment(payment_id, wallet, tx_hash=None):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM season_pass_payments WHERE id = ?', (payment_id,)).fetchone()
        if row is None:
            raise ValueError('Платёж пропуска не найден.')
        if row['wallet'] != wallet:
            raise ValueError('Платёж принадлежит другому кошельку.')
        if row['status'] != 'confirmed':
            conn.execute(
                'UPDATE season_pass_payments SET status = ?, tx_hash = ?, confirmed_at = ? WHERE id = ?',
                ('confirmed', tx_hash, now_iso(), payment_id),
            )
            conn.execute(
                'UPDATE player_rewards SET premium_pass = 1, updated_at = ? WHERE wallet = ?',
                (now_iso(), wallet),
            )
            conn.commit()
        updated = conn.execute('SELECT * FROM season_pass_payments WHERE id = ?', (payment_id,)).fetchone()
    return dict(updated), reward_summary(wallet)


def claim_guild_weekly_reward(wallet, guild_id):
    membership = current_guild_membership(wallet)
    if membership is None or membership['guild_id'] != guild_id:
        raise ValueError('Ты не состоишь в этом клане.')
    goals = guild_goal_summary(guild_id)
    if not goals.get('weekly_reward_ready'):
        raise ValueError('Клан ещё не выполнил недельную цель.')
    claim_key = week_utc_key()
    with closing(get_db()) as conn:
        existing = conn.execute(
            'SELECT 1 FROM guild_reward_claims WHERE guild_id = ? AND wallet = ? AND week_key = ? LIMIT 1',
            (guild_id, wallet, claim_key),
        ).fetchone()
        if existing is not None:
            raise ValueError('Недельная награда клана уже забрана.')
    rewards = ensure_player_rewards(wallet)
    normalized = normalize_reward_progress_fields(
        pack_shards=int(rewards.get('pack_shards', 0)) + 5,
        rare_tokens=int(rewards.get('rare_tokens', 0)) + 1,
        lucky_tokens=int(rewards.get('lucky_tokens', 0)) + (1 if goals.get('war_score', 0) >= goals.get('war_target', 999999) else 0),
        season_points=int(rewards.get('season_points', 0)) + SEASON_PASS_GUILD_CLAIM_POINTS,
        season_level=int(rewards.get('season_level', 1) or 1),
        wins_for_quest=int(rewards.get('wins_for_quest', 0) or 0),
        wins_claimed=int(rewards.get('wins_claimed', 0) or 0),
    )
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE player_rewards
            SET pack_shards = ?, rare_tokens = ?, lucky_tokens = ?, season_points = ?, season_level = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                normalized['pack_shards'],
                normalized['rare_tokens'],
                normalized['lucky_tokens'],
                normalized['season_points'],
                normalized['season_level'],
                now_iso(),
                wallet,
            ),
        )
        conn.execute(
            'INSERT INTO guild_reward_claims (guild_id, wallet, week_key, created_at) VALUES (?, ?, ?, ?)',
            (guild_id, wallet, claim_key, now_iso()),
        )
        conn.commit()
    if goals.get('war_score', 0) >= goals.get('war_target', 999999):
        grant_cosmetic(wallet, 'guild_banner_fire_engine', 'guild_reward')
    return reward_summary(wallet)


def fetch_10k_config(force_refresh=False):
    now_ts = datetime.now().timestamp()
    if (
        TEN_K_CONFIG_CACHE['config'] is not None
        and not force_refresh
        and TEN_K_CONFIG_CACHE['expires_at'] > now_ts
    ):
        return TEN_K_CONFIG_CACHE['config']

    response = HTTP.get(TEN_K_CONFIG_URL, timeout=15)
    response.raise_for_status()
    payload = response.json()
    config = payload.get('config') or {}
    if not isinstance(config, dict):
        raise RuntimeError('Некорректный ответ 10kclub config.')
    TEN_K_CONFIG_CACHE['config'] = config
    TEN_K_CONFIG_CACHE['expires_at'] = now_ts + TEN_K_CONFIG_TTL
    return config


def _match_mask(mask, domain):
    if len(mask) != len(domain):
        return False, {}
    bindings = {}
    for digit, token in zip(domain, mask):
        if token.isdigit():
            if digit != token:
                return False, {}
            continue
        bound = bindings.get(token)
        if bound is None:
            bindings[token] = digit
        elif bound != digit:
            return False, {}
    if len(set(bindings.values())) != len(bindings):
        return False, {}
    return True, bindings


def _calendar_date_match(domain, formats):
    value = domain.zfill(4)
    for fmt in formats:
        if fmt == 'MMDD':
            month = int(value[:2])
            day = int(value[2:])
        elif fmt == 'DDMM':
            day = int(value[:2])
            month = int(value[2:])
        else:
            continue
        if month < 1 or month > 12:
            continue
        days_in_month = calendar.monthrange(2024, month)[1]
        if 1 <= day <= days_in_month:
            return True
    return False


def _eval_rule_condition(condition, domain, matched_patterns=None, matched_groups=None):
    matched_patterns = matched_patterns or set()
    matched_groups = matched_groups or set()
    ctype = (condition or {}).get('type')
    if not ctype:
        return False

    if ctype == 'mask':
        ok, bindings = _match_mask((condition.get('mask') or '').strip(), domain)
        if not ok:
            return False
        for item in condition.get('constraints') or []:
            if item.get('operator') != 'adjacent':
                continue
            left = bindings.get(item.get('left'))
            right = bindings.get(item.get('right'))
            if left is None or right is None:
                return False
            if abs(int(left) - int(right)) != 1:
                return False
        return True

    if ctype == 'numeric-range':
        number = int(domain)
        min_value = int(condition.get('min', 0))
        max_value = int(condition.get('max', 9999))
        return min_value <= number <= max_value

    if ctype == 'arithmetic-sequence':
        steps = condition.get('steps') or []
        if not steps:
            return False
        digits = [int(ch) for ch in domain]
        diffs = [digits[idx + 1] - digits[idx] for idx in range(len(digits) - 1)]
        return any(all(diff == int(step) for diff in diffs) for step in steps)

    if ctype == 'calendar-date':
        return _calendar_date_match(domain, condition.get('formats') or ['MMDD', 'DDMM'])

    if ctype == 'palindrome':
        return domain == domain[::-1]

    if ctype == 'all-of':
        return all(
            _eval_rule_condition(sub, domain, matched_patterns, matched_groups)
            for sub in (condition.get('conditions') or [])
        )

    if ctype == 'any-of':
        return any(
            _eval_rule_condition(sub, domain, matched_patterns, matched_groups)
            for sub in (condition.get('conditions') or [])
        )

    if ctype == 'pattern-ref':
        refs = condition.get('anyOf') or []
        return any(ref in matched_patterns for ref in refs)

    if ctype == 'group-ref':
        required = condition.get('requiredGroups') or []
        min_matched = int(condition.get('minMatchedPatterns', 0))
        return all(group_id in matched_groups for group_id in required) and len(matched_patterns) >= min_matched

    return False


def classify_domain_with_10k_config(domain):
    config = fetch_10k_config()
    pattern_list = config.get('patterns') or []
    pattern_rules = sorted(config.get('patternRules') or [], key=lambda item: int(item.get('priority', 0)))
    group_list = config.get('groups') or []
    group_rules = sorted(config.get('groupRules') or [], key=lambda item: int(item.get('priority', 0)))

    patterns_by_id = {item.get('id'): item for item in pattern_list if item.get('id')}
    groups_by_id = {item.get('id'): item for item in group_list if item.get('id')}
    matched_pattern_ids = set()

    for rule in pattern_rules:
        if _eval_rule_condition(rule.get('condition') or {}, domain, matched_pattern_ids, set()):
            pattern_id = rule.get('patternId')
            if pattern_id:
                matched_pattern_ids.add(pattern_id)

    matched_group_ids = set()
    for rule in group_rules:
        if _eval_rule_condition(rule.get('condition') or {}, domain, matched_pattern_ids, matched_group_ids):
            group_id = rule.get('groupId')
            if group_id:
                matched_group_ids.add(group_id)

    if not any(group_id in matched_group_ids for group_id in ('tier0', 'tier1', 'tier2')):
        matched_group_ids.add('regular')
    if any(group_id.startswith('g-') for group_id in matched_group_ids):
        matched_group_ids.add('special')

    tier_group_id = 'regular'
    for candidate in ('tier0', 'tier1', 'tier2', 'regular'):
        if candidate in matched_group_ids:
            tier_group_id = candidate
            break
    tier_group = groups_by_id.get(tier_group_id) or {}

    base_score_values = []
    bonus_score_values = []
    for group_id in matched_group_ids:
        group = groups_by_id.get(group_id) or {}
        score_mode = group.get('scoreMode')
        score_value = int(group.get('scoreValue') or 0)
        if score_mode == 'base':
            base_score_values.append(score_value)
        elif score_mode == 'bonus':
            bonus_score_values.append(score_value)

    base_score = max(base_score_values) if base_score_values else 2500
    bonus_score = sum(bonus_score_values)
    tier_name = tier_group.get('label') or tier_group_id
    special_collections = [
        (groups_by_id[group_id].get('label') or group_id)
        for group_id in sorted(matched_group_ids)
        if group_id.startswith('g-') and group_id in groups_by_id
    ]
    pattern_labels = [
        (patterns_by_id[pattern_id].get('label') or pattern_id)
        for pattern_id in sorted(matched_pattern_ids)
        if pattern_id in patterns_by_id
    ]

    return {
        'patterns': pattern_labels,
        'pattern_ids': sorted(matched_pattern_ids),
        'tier': tier_name,
        'tier_id': tier_group_id,
        'base_score': base_score,
        'bonus_score': bonus_score,
        'special_collections': special_collections,
        'groups': sorted(matched_group_ids),
    }


def detect_10k_patterns(domain):
    digits = [int(char) for char in domain]
    patterns = []
    if domain == domain[::-1]:
        patterns.append('mirror')
    if len(set(domain)) == 1:
        patterns.append('all_same')
    if digits[0] < digits[1] < digits[2] < digits[3]:
        patterns.append('stairs_up')
    if digits[0] > digits[1] > digits[2] > digits[3]:
        patterns.append('stairs_down')
    if digits[0] == digits[1] and digits[2] == digits[3] and digits[0] != digits[2]:
        patterns.append('double_repeat')
    if digits[0] == digits[3] and digits[1] == digits[2] and digits[0] != digits[1]:
        patterns.append('ambigram')
    if int(domain) < 100:
        patterns.append('first_100')
    if domain.startswith('0') and domain.endswith('0'):
        patterns.append('zero_frames')
    return patterns


def score_from_domain(domain, wallet=None):
    metadata = get_domain_metadata_payload(domain, wallet=wallet)
    if metadata is None:
        return {
            'domain': normalize_domain(domain),
            'attack': ATTACK_BASE,
            'defense': DEFENSE_BASE,
            'luck': 0,
            'patterns': [],
            'tier': 'Regular',
            'tier_id': 'regular',
            'rarity': 'Common',
            'special_collections': [],
            'bonus_score': 0,
            'pool_base': 2500,
            'pool_total': 2500,
            'score': 2500,
            'metadata': None,
        }

    score = int(metadata.get('score') or 2500)
    level = max(1, int(metadata.get('level') or 1))
    rarity = metadata.get('rarityLabel') or 'Common'
    bonus_score = int(metadata.get('bonusScore') or 0)
    base_score = int(metadata.get('baseScore') or 2500)
    tier_bonus = {
        'regular': 0,
        'tier2': 3,
        'tier1': 6,
        'tier0': 9,
    }.get(str(metadata.get('tierId') or 'regular').lower(), 0)
    rarity_bonus = {
        'Common': 0,
        'Uncommon': 1,
        'Rare': 2,
        'Epic': 3,
        'Legendary': 4,
    }.get(rarity, 0)
    bounded_domain_edge = min(8, max(0, round((score - 2500) / 12000)))
    attack = ATTACK_BASE + rarity_bonus + tier_bonus + min(4, level - 1)
    defense = DEFENSE_BASE + max(0, rarity_bonus - 1) + tier_bonus + min(4, level - 1)
    luck = min(6, len(metadata.get('specialCollections') or []) + (1 if '8' in str(metadata.get('normalizedNumber') or '') else 0))

    return {
        'domain': metadata['domain'].replace('.ton', ''),
        'attack': attack,
        'defense': defense,
        'luck': luck,
        'patterns': list(metadata.get('atomicPatterns') or []),
        'tier': metadata.get('tierLabel') or 'Regular',
        'tier_id': metadata.get('tierId') or 'regular',
        'rarity': rarity,
        'special_collections': list(metadata.get('specialCollections') or []),
        'bonus_score': bonus_score,
        'pool_base': base_score,
        'pool_total': score,
        'score': score,
        'metadata': metadata,
    }


def card_rarity(score):
    if score >= 95:
        return 'Legendary'
    if score >= 75:
        return 'Epic'
    if score >= 55:
        return 'Rare'
    return 'Core'


RARITY_ORDER = ('basic', 'rare', 'epic', 'mythic', 'legendary')
RARITY_LABELS = {
    'basic': 'Basic',
    'rare': 'Rare',
    'epic': 'Epic',
    'mythic': 'Mythic',
    'legendary': 'Legendary',
}
CARD_POOL_SIZE = 5
DISCIPLINE_KEYS = ('attack', 'defense', 'luck', 'speed', 'magic')
CARD_SKILLS = [
    {'key': 'underdog', 'name': 'Андердог', 'description': 'Если ты отстаешь, карта резко добирает силу.'},
    {'key': 'tempo', 'name': 'Темп', 'description': 'После проигранного раунда усиливает следующий ход.'},
    {'key': 'mirror', 'name': 'Зеркало', 'description': 'Лучше работает против более прокачанного соперника.'},
    {'key': 'attack_burst', 'name': 'Пролом', 'description': 'Сильно давит в атаке и магии.'},
    {'key': 'defense_lock', 'name': 'Замок', 'description': 'Особенно хороша в защите и скорости.'},
    {'key': 'wildcard', 'name': 'Джокер', 'description': 'Может резко перевернуть удачу и магию.'},
    {'key': 'anchor', 'name': 'Якорь', 'description': 'Стабилизирует раунд и лучше держит тяжёлые размены.'},
    {'key': 'overclock', 'name': 'Оверклок', 'description': 'Разгоняется к концу боя и любит высокий темп.'},
    {'key': 'oracle', 'name': 'Оракул', 'description': 'Лучше читает рискованные раунды и редкие контры.'},
    {'key': 'reactor', 'name': 'Реактор', 'description': 'Накапливает давление, если карта и так сильная.'},
]
ACTION_RULES = {
    'burst': {
        'label': 'Burst',
        'ru_label': 'Натиск',
        'beats': 'guard',
        'cost': 2,
        'color': 'rgba(255, 122, 134, 0.9)',
        'description': 'Давит напрямую. Слабее против блока.',
    },
    'guard': {
        'label': 'Guard',
        'ru_label': 'Блок',
        'beats': 'burst',
        'cost': 1,
        'color': 'rgba(83, 246, 184, 0.9)',
        'description': 'Сдерживает натиск.',
    },
    'ability': {
        'label': 'Ability',
        'ru_label': 'Способность',
        'beats': None,
        'cost': 3,
        'color': 'rgba(69, 215, 255, 0.9)',
        'description': 'Активная способность домена. Сильна в нужный тайминг.',
    },
}
STRATEGY_PRESETS = {
    'attack_boost': {
        'label': 'Атакующий буст',
        'description': 'Больше давления в атакующих раундах. Сильнее, если сам навязываешь темп.',
        'plan': ['burst', 'burst', 'guard', 'burst', 'burst'],
    },
    'defense_boost': {
        'label': 'Защитный буст',
        'description': 'Надежнее держит контр-ходы и затяжной бой. Сильнее против прямого давления.',
        'plan': ['guard', 'guard', 'burst', 'guard', 'guard'],
    },
    'energy_boost': {
        'label': 'Энергобуст',
        'description': 'Лучше раскрывает способности домена и тайминг ходов. Сильнее в середине и конце матча.',
        'plan': ['guard', 'ability', 'burst', 'ability', 'burst'],
    },
    'aggressive': {
        'label': 'Агрессия',
        'description': 'Сразу давит, лучше на добивании и против пассивной игры.',
        'plan': ['burst', 'burst', 'burst', 'burst', 'guard'],
    },
    'balanced': {
        'label': 'Баланс',
        'description': 'Самая ровная стратегия, меньше провалов по матчапам.',
        'plan': ['burst', 'guard', 'guard', 'guard', 'burst'],
    },
    'tricky': {
        'label': 'Хитрость',
        'description': 'Чаще ловит соперника на контрах и неожиданных сменах темпа.',
        'plan': ['guard', 'guard', 'burst', 'burst', 'guard'],
    },
}

ROLE_ACTION_STANCE = {
    'Tank': 'guard',
    'Guardian': 'guard',
    'Support': 'guard',
    'Fortune': 'guard',
    'Control': 'burst',
    'Damage': 'burst',
    'Trickster': 'burst',
    'Combo': 'burst',
    'Disruptor': 'burst',
    'Sniper': 'burst',
}

COUNTER_CLASS_MAP = {
    'Tank': {'Executioner', 'Breaker', 'Focus'},
    'Bulwark': {'Executioner', 'Breaker', 'Focus'},
    'Damage': {'Bulwark', 'Aegis'},
    'Executioner': {'Bulwark', 'Aegis'},
    'Control': {'Lucky Star', 'Signal'},
    'Cipher': {'Lucky Star', 'Signal'},
    'Support': {'Mirage', 'Breaker'},
    'Signal': {'Mirage', 'Breaker'},
    'Trickster': {'Signal', 'Cipher'},
    'Mirage': {'Signal', 'Cipher'},
    'Guardian': {'Executioner', 'Sequence'},
    'Aegis': {'Executioner', 'Sequence'},
    'Fortune': {'Bulwark', 'Cipher'},
    'Lucky Star': {'Bulwark', 'Cipher'},
    'Combo': {'Breaker', 'Aegis'},
    'Sequence': {'Breaker', 'Aegis'},
    'Disruptor': {'Sequence', 'Focus'},
    'Breaker': {'Sequence', 'Focus'},
    'Sniper': {'Bulwark', 'Signal'},
    'Focus': {'Bulwark', 'Signal'},
}


def build_card_catalog():
    return [
        {'id': 'basic', 'title': 'Basic Card', 'rarity': 'basic', 'rarity_label': 'Basic', 'pool_min': 60, 'pool_max': 95},
        {'id': 'rare', 'title': 'Rare Card', 'rarity': 'rare', 'rarity_label': 'Rare', 'pool_min': 90, 'pool_max': 130},
        {'id': 'epic', 'title': 'Epic Card', 'rarity': 'epic', 'rarity_label': 'Epic', 'pool_min': 125, 'pool_max': 175},
        {'id': 'mythic', 'title': 'Mythic Card', 'rarity': 'mythic', 'rarity_label': 'Mythic', 'pool_min': 170, 'pool_max': 240},
        {'id': 'legendary', 'title': 'Legendary Card', 'rarity': 'legendary', 'rarity_label': 'Legendary', 'pool_min': 230, 'pool_max': 320},
    ]


def skill_for_card(rarity_key, domain, slot, title=''):
    seed = f'{rarity_key}:{domain}:{slot}:{title}'
    digest = hashlib.sha256(seed.encode()).hexdigest()
    idx = int(digest[:8], 16) % len(CARD_SKILLS)
    skill = CARD_SKILLS[idx]
    return dict(skill)


CARD_CATALOG = build_card_catalog()
CARD_CATALOG_BY_RARITY = {
    rarity: [card for card in CARD_CATALOG if card['rarity'] == rarity] for rarity in RARITY_ORDER
}


def weighted_choice(weights, rng):
    total = sum(max(0, value) for value in weights.values())
    if total <= 0:
        return 'basic'
    roll = rng.uniform(0, total)
    current = 0.0
    for key in RARITY_ORDER:
        current += max(0, weights.get(key, 0))
        if roll <= current:
            return key
    return 'basic'


def rarity_weights_for_domain(base):
    weights = {'basic': 70, 'rare': 19, 'epic': 7, 'mythic': 3, 'legendary': 1}
    tier_id = str(base.get('tier_id') or '').lower()
    rarity = str(base.get('rarity') or '').lower()
    if tier_id == 'tier0' or rarity == 'legendary':
        weights = {'basic': 30, 'rare': 28, 'epic': 21, 'mythic': 13, 'legendary': 8}
    elif tier_id == 'tier1' or rarity == 'epic':
        weights = {'basic': 40, 'rare': 29, 'epic': 18, 'mythic': 9, 'legendary': 4}
    elif tier_id == 'tier2' or rarity == 'rare':
        weights = {'basic': 52, 'rare': 27, 'epic': 14, 'mythic': 5, 'legendary': 2}

    patterns = set(base.get('patterns') or [])
    weights['rare'] += min(12, len(patterns) * 2)
    weights['epic'] += min(8, len(patterns))
    weights['mythic'] += min(5, len(patterns))
    pattern_signal = " ".join(patterns).lower()
    if any(token in pattern_signal for token in ('зерк', 'палиндром', 'ступ', 'календар', 'первые')):
        weights['legendary'] += 2
        weights['mythic'] += 2
        weights['basic'] -= 5
    return weights


def normalize_card_profile(card):
    normalized = dict(card or {})
    rarity_key = str(normalized.get('rarity_key') or normalized.get('rarity') or 'basic').strip().lower()
    if rarity_key not in RARITY_LABELS:
        rarity_key = 'basic'
    normalized['rarity_key'] = rarity_key
    normalized['rarity'] = RARITY_LABELS[rarity_key]
    normalized['pool_value'] = int(normalized.get('pool_value') or normalized.get('base_power') or normalized.get('score') or 0)
    normalized['base_power'] = normalized['pool_value']
    normalized['score'] = normalized['pool_value']
    skill = normalized.get('skill')
    if not isinstance(skill, dict) or not skill.get('key'):
        skill = skill_for_card(
            rarity_key,
            normalized.get('domain') or 'deck',
            int(normalized.get('slot') or 0),
            normalized.get('title') or '',
        )
    normalized['skill'] = skill
    normalized['skill_key'] = skill['key']
    normalized['skill_name'] = skill['name']
    normalized['skill_description'] = skill['description']
    return normalized


def domain_bonus_pool(domain):
    base = score_from_domain(domain)
    metadata = base.get('metadata') or {}
    if not metadata:
        return 0
    score = int(metadata.get('score') or 2500)
    return max(0, score - 2500)


def deck_power_pool(cards, domain=None):
    return 2500 + domain_bonus_pool(domain)


def default_discipline_build(pool):
    pool = max(0, int(pool))
    base = pool // len(DISCIPLINE_KEYS)
    build = {key: base for key in DISCIPLINE_KEYS}
    remainder = pool - base * len(DISCIPLINE_KEYS)
    for idx in range(remainder):
        build[DISCIPLINE_KEYS[idx % len(DISCIPLINE_KEYS)]] += 1
    return build


def sanitize_discipline_build(payload, pool):
    pool = max(0, int(pool))
    values = {}
    total = 0
    for key in DISCIPLINE_KEYS:
        try:
            value = int((payload or {}).get(key, 0))
        except (TypeError, ValueError):
            value = 0
        value = max(0, value)
        values[key] = value
        total += value
    if total <= pool:
        return values
    if total <= 0:
        return default_discipline_build(pool)
    ratio = pool / total
    scaled = {}
    scaled_total = 0
    for key in DISCIPLINE_KEYS:
        scaled_value = int(values[key] * ratio)
        scaled[key] = scaled_value
        scaled_total += scaled_value
    idx = 0
    while scaled_total < pool:
        key = DISCIPLINE_KEYS[idx % len(DISCIPLINE_KEYS)]
        if values[key] > 0:
            scaled[key] += 1
            scaled_total += 1
        idx += 1
        if idx > 1000:
            break
    return scaled


def load_deck_build(wallet, domain, cards):
    ensure_runtime_tables()
    pool = deck_power_pool(cards, domain)
    default_build = default_discipline_build(pool)
    if not wallet or not domain:
        return {'pool': pool, 'points': default_build}
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT attack, defense, luck, speed, magic
            FROM deck_builds
            WHERE wallet = ? AND domain = ?
            ''',
            (wallet, domain),
        ).fetchone()
    if row is None:
        return {'pool': pool, 'points': default_build}
    return {'pool': pool, 'points': sanitize_discipline_build(dict(row), pool)}


def save_deck_build(wallet, domain, cards, payload):
    ensure_runtime_tables()
    pool = deck_power_pool(cards, domain)
    points = sanitize_discipline_build(payload, pool)
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO deck_builds (wallet, domain, attack, defense, luck, speed, magic, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet, domain) DO UPDATE SET
                attack = excluded.attack,
                defense = excluded.defense,
                luck = excluded.luck,
                speed = excluded.speed,
                magic = excluded.magic,
                updated_at = excluded.updated_at
            ''',
            (
                wallet,
                domain,
                points['attack'],
                points['defense'],
                points['luck'],
                points['speed'],
                points['magic'],
                now_iso(),
            ),
        )
        conn.commit()
    return {'pool': pool, 'points': points}


def materialize_card(card_template, domain, slot):
    rarity = card_template['rarity']
    pool_value = random.randint(int(card_template['pool_min']), int(card_template['pool_max']))
    score = pool_value
    skill = skill_for_card(rarity, domain, slot, card_template['title'])
    return {
        'id': f"{card_template['id']}-{slot}",
        'slot': slot,
        'title': card_template['title'],
        'ability': skill['description'],
        'domain': domain,
        'pool_value': pool_value,
        'base_power': pool_value,
        'score': score,
        'rarity': card_template['rarity_label'],
        'rarity_key': rarity,
        'skill': skill,
        'skill_key': skill['key'],
        'skill_name': skill['name'],
        'skill_description': skill['description'],
        'patterns': [],
    }


def pack_pity_status(wallet, pack_type):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT opens_without_legendary
            FROM pack_pity
            WHERE wallet = ? AND pack_type = ?
            ''',
            (wallet, pack_type),
        ).fetchone()
    return int(row['opens_without_legendary']) if row else 0


def update_pack_pity(wallet, pack_type, cards):
    pity_value = 0 if any(str(card.get('rarity_key')) == 'legendary' for card in (cards or [])) else pack_pity_status(wallet, pack_type) + 1
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO pack_pity (wallet, pack_type, opens_without_legendary, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(wallet, pack_type) DO UPDATE SET
                opens_without_legendary = excluded.opens_without_legendary,
                updated_at = excluded.updated_at
            ''',
            (wallet, pack_type, pity_value, now_iso()),
        )
        conn.commit()
    return pity_value


def pack_config(pack_type):
    return PACK_TYPES.get(str(pack_type or '').strip().lower()) or PACK_TYPES['common']


def generate_pack(domain, count=None, seed_value=None, pack_type='common', guarantee_legendary=False, wallet=None):
    base = score_from_domain(domain, wallet=wallet)
    seed_source = seed_value or f'deck:{domain}'
    rng = random.Random(hashlib.sha256(str(seed_source).encode()).hexdigest())
    config = pack_config(pack_type)
    count = int(count or config['count'])
    weights = rarity_weights_for_domain(base)
    for rarity_key, weight in (config.get('weights') or {}).items():
        weights[rarity_key] = max(weights.get(rarity_key, 0), int(weight))
    if config.get('lucky_bonus'):
        metadata = base.get('metadata') or {}
        if metadata.get('superPattern') or (metadata.get('specialCollections') or []):
            weights['legendary'] = weights.get('legendary', 0) + 2
            weights['mythic'] = weights.get('mythic', 0) + 2
    cards = []
    for slot in range(1, count + 1):
        rarity = 'legendary' if guarantee_legendary and slot == count else weighted_choice(weights, rng)
        template = rng.choice(CARD_CATALOG_BY_RARITY[rarity])
        card = materialize_card(template, domain, slot)
        card['patterns'] = base.get('patterns', [])
        card['domain_metadata'] = base.get('metadata')
        cards.append(card)
    return ensure_battle_ready_cards(cards, domain, seed_value=seed_source)


def deck_score(cards):
    return sum(normalize_card_profile(card)['pool_value'] for card in cards)


WIKIGACHI_ROUND_PLAN = [
    ('attack', 'Раунд 1: Первый размен', 'opening'),
    ('defense', 'Раунд 2: Контр-ход', 'counter'),
    ('luck', 'Раунд 3: Риск', 'risk'),
    ('speed', 'Раунд 4: Перехват', 'tempo'),
    ('magic', 'Раунд 5: Финиш', 'finisher'),
]


def card_stat_value(card, stat_name):
    return int(normalize_card_profile(card).get('pool_value', 0))


def build_bonus_value(build_points, focus):
    points = int((build_points or {}).get(focus, 0))
    return max(0, round(points / 2))


def find_card_by_slot(cards, slot):
    try:
        slot_value = int(slot or 0)
    except (TypeError, ValueError):
        slot_value = 0
    normalized = [normalize_card_profile(card) for card in (cards or [])]
    if slot_value > 0:
        selected = next((card for card in normalized if int(card.get('slot') or 0) == slot_value), None)
        if selected:
            return selected
    return normalized[0] if normalized else None


def auto_tactical_slot(cards, build_points=None):
    normalized = [normalize_card_profile(card) for card in (cards or [])]
    if not normalized:
        return 1
    build_points = build_points or {}
    focus_rank = sorted(
        DISCIPLINE_KEYS,
        key=lambda key: int((build_points or {}).get(key, 0)),
        reverse=True,
    )
    preferred = {
        'attack_burst': {'attack', 'magic'},
        'defense_lock': {'defense', 'speed'},
        'wildcard': {'luck', 'magic'},
        'mirror': {focus_rank[0] if focus_rank else 'attack'},
        'tempo': {focus_rank[1] if len(focus_rank) > 1 else focus_rank[0] if focus_rank else 'speed'},
        'underdog': {'luck', 'speed'},
        'anchor': {'defense', 'luck'},
        'overclock': {'speed', 'attack'},
        'oracle': {'magic', 'luck'},
        'reactor': {'attack', 'magic'},
    }
    def score(card):
        skill_key = card.get('skill_key')
        return (
            len(preferred.get(skill_key, set()).intersection(focus_rank[:2])),
            int(card.get('pool_value', 0)),
        )
    return max(normalized, key=score).get('slot', 1)


def apply_skill_bonus(skill_key, focus, phase, base_self, base_opp, card_self, card_opp, round_index, previous_outcome):
    card_self = normalize_card_profile(card_self)
    card_opp = normalize_card_profile(card_opp)
    diff = base_opp - base_self
    own_pool = int(card_self.get('pool_value', 0))
    opp_pool = int(card_opp.get('pool_value', 0))
    if skill_key == 'underdog':
        if diff > 0:
            return min(18, 8 + diff // 18), 'Андердог включился'
        if own_pool < opp_pool:
            return 6, 'Меньшая карта выжала максимум'
    if skill_key == 'tempo':
        if previous_outcome == 'loss':
            return 14, 'Темп после проигранного раунда'
        if round_index == 0:
            return 4, 'Разгон темпа'
    if skill_key == 'mirror':
        if base_opp > base_self:
            return 10, 'Зеркало украло перевес'
        if own_pool < opp_pool:
            return 6, 'Зеркало сыграло от меньшей карты'
    if skill_key == 'attack_burst':
        if focus in {'attack', 'magic'}:
            return 12, 'Пролом попал в профильный раунд'
    if skill_key == 'defense_lock':
        if focus in {'defense', 'speed'}:
            return 12, 'Замок закрыл линию'
    if skill_key == 'wildcard':
        if focus in {'luck', 'magic'}:
            return 15, 'Джокер перевернул ход'
        if diff > 6:
            return 5, 'Джокер вытянул минимум'
    if skill_key == 'anchor':
        if focus in {'defense', 'luck'} or abs(diff) <= 8:
            return 11, 'Якорь стабилизировал размен'
        if previous_outcome == 'loss':
            return 5, 'Якорь не дал матчу развалиться'
    if skill_key == 'overclock':
        if phase in {'tempo', 'finisher'} or round_index >= 3:
            return 13, 'Оверклок вышел на пик'
        if focus == 'speed':
            return 6, 'Оверклок разогнал карту'
    if skill_key == 'oracle':
        if phase in {'risk', 'counter'}:
            return 12, 'Оракул прочитал рискованный раунд'
        if base_opp >= base_self:
            return 5, 'Оракул нашёл безопасную линию'
    if skill_key == 'reactor':
        if own_pool >= opp_pool:
            return 10, 'Реактор усилил уже сильную карту'
        if focus in {'attack', 'magic'}:
            return 6, 'Реактор подпитал профильный раунд'
    return 0, ''


def matchup_strategy_bonus(card_self, card_opp, phase, round_index):
    card_self = normalize_card_profile(card_self)
    card_opp = normalize_card_profile(card_opp)
    own_pool = int(card_self.get('pool_value', 0))
    opp_pool = int(card_opp.get('pool_value', 0))
    diff = own_pool - opp_pool
    rarity_weight = {
        'basic': 1,
        'rare': 2,
        'epic': 3,
        'mythic': 4,
        'legendary': 5,
    }
    own_rarity = rarity_weight.get(card_self.get('rarity_key'), 1)
    opp_rarity = rarity_weight.get(card_opp.get('rarity_key'), 1)
    if phase == 'opening':
        return max(-3, min(7, diff // 24 + own_rarity - 2))
    if phase == 'counter':
        return max(-2, min(7, (opp_pool - own_pool) // 28 + 4))
    if phase == 'risk':
        return 5 if own_pool <= opp_pool else 2
    if phase == 'tempo':
        return max(1, 3 + round_index + (1 if own_rarity >= opp_rarity else 0))
    if phase == 'finisher':
        return max(0, min(8, own_pool // 42))
    return 0


def featured_card_round_bonus(featured_card, opposing_featured_card, focus, phase, round_index, previous_outcome):
    featured_card = normalize_card_profile(featured_card)
    opposing_featured_card = normalize_card_profile(opposing_featured_card)
    own_pool = int(featured_card.get('pool_value', 0))
    opp_pool = int(opposing_featured_card.get('pool_value', 0))
    rarity_weight = {
        'basic': 1,
        'rare': 2,
        'epic': 3,
        'mythic': 4,
        'legendary': 5,
    }
    rarity_edge = rarity_weight.get(featured_card.get('rarity_key'), 1) - rarity_weight.get(opposing_featured_card.get('rarity_key'), 1)
    base = max(10, min(26, own_pool // 14 + rarity_edge * 2))
    skill_key = featured_card.get('skill_key')
    note = 'Тактическая карта держит темп'
    if skill_key == 'underdog':
        if own_pool <= opp_pool:
            return base + 8, 'Тактический андердог перевернул размен'
        return base, 'Тактический андердог давит за счет тайминга'
    if skill_key == 'tempo':
        if previous_outcome == 'loss':
            return base + 9, 'Тактический темп наказал за прошлый раунд'
        return base + 3, 'Тактический темп разгоняет матч'
    if skill_key == 'mirror':
        if opp_pool >= own_pool:
            return base + 7, 'Тактическое зеркало украло мощь соперника'
        return base + 2, 'Тактическое зеркало держит баланс'
    if skill_key == 'attack_burst':
        if focus in {'attack', 'magic'} or phase == 'finisher':
            return base + 8, 'Тактический пролом решает профильный раунд'
        return base, 'Тактический пролом давит присутствием'
    if skill_key == 'defense_lock':
        if focus in {'defense', 'speed'} or phase == 'counter':
            return base + 8, 'Тактический замок ломает атаку соперника'
        return base, 'Тактический замок держит линию'
    if skill_key == 'wildcard':
        if focus in {'luck', 'magic'} or phase == 'risk':
            return base + 10, 'Тактический джокер перевернул раунд'
        return base + 2, 'Тактический джокер давит неожиданностью'
    if skill_key == 'anchor':
        if focus in {'defense', 'luck'} or abs(own_pool - opp_pool) <= 20:
            return base + 8, 'Тактический якорь удержал тяжёлый размен'
        return base + 3, 'Тактический якорь стабилизирует бой'
    if skill_key == 'overclock':
        if phase in {'tempo', 'finisher'} or round_index >= 3:
            return base + 9, 'Тактический оверклок включился в нужный момент'
        return base + 3, 'Тактический оверклок набирает скорость'
    if skill_key == 'oracle':
        if phase in {'risk', 'counter'}:
            return base + 8, 'Тактический оракул прочитал ход соперника'
        return base + 3, 'Тактический оракул держит прогноз'
    if skill_key == 'reactor':
        if own_pool >= opp_pool or focus in {'attack', 'magic'}:
            return base + 8, 'Тактический реактор подпитал давление'
        return base + 2, 'Тактический реактор держит заряд'
    return base, note


def featured_match_bonus(featured_card):
    featured_card = normalize_card_profile(featured_card)
    rarity_weight = {
        'basic': 20,
        'rare': 40,
        'epic': 70,
        'mythic': 95,
        'legendary': 130,
    }
    return int(featured_card.get('pool_value', 0)) + rarity_weight.get(featured_card.get('rarity_key'), 20)


def default_action_plan():
    return list(STRATEGY_PRESETS['balanced']['plan'])


def action_energy_cost(action_key, active_ability=None):
    if action_key == 'ability':
        return int((active_ability or {}).get('cost', 3) or 3)
    return int((ACTION_RULES.get(action_key) or ACTION_RULES['guard']).get('cost', 1) or 1)


def battle_domain_metadata(domain, wallet=None):
    return get_domain_metadata_payload(domain, wallet=wallet) or {}


def ability_state_from_metadata(metadata):
    active = dict((metadata or {}).get('activeAbility') or {})
    cooldown = int(active.get('cooldown', 0) or 0)
    charges = int(active.get('charges', 0) or 0)
    role = str((metadata or {}).get('role') or '')
    profile = {
        'Tank': {'extra_charges': 0, 'cooldown_delta': 1, 'passive_proc_mul': 1.0, 'active_proc_mul': 0.92},
        'Guardian': {'extra_charges': 1, 'cooldown_delta': 0, 'passive_proc_mul': 1.12, 'active_proc_mul': 0.94},
        'Damage': {'extra_charges': 0, 'cooldown_delta': 0, 'passive_proc_mul': 1.0, 'active_proc_mul': 1.05},
        'Sniper': {'extra_charges': 0, 'cooldown_delta': 0, 'passive_proc_mul': 1.04, 'active_proc_mul': 1.08},
        'Control': {'extra_charges': 1, 'cooldown_delta': 0, 'passive_proc_mul': 1.08, 'active_proc_mul': 0.98},
        'Disruptor': {'extra_charges': 1, 'cooldown_delta': 0, 'passive_proc_mul': 1.1, 'active_proc_mul': 0.96},
        'Trickster': {'extra_charges': 0, 'cooldown_delta': -1, 'passive_proc_mul': 1.16, 'active_proc_mul': 0.9},
        'Support': {'extra_charges': 1, 'cooldown_delta': 0, 'passive_proc_mul': 1.18, 'active_proc_mul': 0.94},
        'Fortune': {'extra_charges': 1, 'cooldown_delta': 0, 'passive_proc_mul': 1.22, 'active_proc_mul': 0.9},
        'Combo': {'extra_charges': 1, 'cooldown_delta': -1, 'passive_proc_mul': 1.06, 'active_proc_mul': 1.02},
    }.get(role, {'extra_charges': 0, 'cooldown_delta': 0, 'passive_proc_mul': 1.0, 'active_proc_mul': 1.0})
    if charges <= 0:
        charges = 1 if active else 0
    charges += int(profile.get('extra_charges', 0))
    if active:
        cooldown = max(1, cooldown + int(profile.get('cooldown_delta', 0)))
    return {
        'cooldown_remaining': 0,
        'charges_remaining': charges,
        'used_once': False,
        'active': active,
        'profile': profile,
    }


def ability_ready(ability_state, energy):
    active = dict((ability_state or {}).get('active') or {})
    if not active:
        return False
    if int((ability_state or {}).get('charges_remaining', 0)) <= 0:
        return False
    if int((ability_state or {}).get('cooldown_remaining', 0)) > 0:
        return False
    if bool(active.get('once_per_battle')) and bool((ability_state or {}).get('used_once')):
        return False
    return int(energy or 0) >= int(active.get('cost', 3) or 3)


def available_actions_for_state(energy, ability_state):
    actions = [key for key in ('burst', 'guard') if action_energy_cost(key) <= int(energy or 0)]
    if ability_ready(ability_state, energy):
        actions.append('ability')
    return actions or ['guard']


def effective_action_key(action_key, metadata):
    if action_key != 'ability':
        return action_key
    role = str((metadata or {}).get('role') or '')
    return ROLE_ACTION_STANCE.get(role, 'burst')


def energy_roll_bonus(action_key, rng):
    if action_key == 'burst':
        return rng.randint(8, 12), rng.random() < rng.uniform(0.05, 0.12)
    if action_key == 'guard':
        return rng.randint(3, 6), rng.random() < rng.uniform(0.05, 0.08)
    return rng.randint(6, 10), rng.random() < rng.uniform(0.08, 0.15)


def deterministic_probability(seed_value, probability):
    chance = max(0.0, min(1.0, float(probability or 0.0)))
    if chance <= 0:
        return False
    if chance >= 1:
        return True
    digest = hashlib.sha256(str(seed_value).encode()).hexdigest()
    roll = int(digest[:8], 16) / 0xFFFFFFFF
    return roll <= chance


def class_counter_bonus(own_meta, opp_meta, action_key):
    own_class = str((own_meta or {}).get('class') or (own_meta or {}).get('className') or '')
    opp_class = str((opp_meta or {}).get('class') or (opp_meta or {}).get('className') or '')
    counters = COUNTER_CLASS_MAP.get(own_class) or set()
    role = str((own_meta or {}).get('role') or '')
    class_matrix = {
        'Bulwark': {'Executioner': {'guard': 6}, 'Focus': {'guard': 5, 'ability': 4}},
        'Executioner': {'Bulwark': {'burst': 6, 'ability': 5}, 'Aegis': {'burst': 5}},
        'Cipher': {'Sequence': {'ability': 6}, 'Lucky Star': {'ability': 4, 'guard': 2}},
        'Signal': {'Executioner': {'guard': 4}, 'Focus': {'guard': 5, 'ability': 3}},
        'Mirage': {'Focus': {'guard': 4, 'ability': 4}, 'Executioner': {'guard': 3}},
        'Aegis': {'Executioner': {'guard': 5}, 'Focus': {'guard': 4, 'ability': 4}},
        'Lucky Star': {'Mirage': {'burst': 4, 'ability': 5}, 'Breaker': {'ability': 3}},
        'Sequence': {'Signal': {'burst': 4, 'ability': 4}, 'Lucky Star': {'burst': 3}},
        'Breaker': {'Sequence': {'ability': 6}, 'Cipher': {'ability': 5}, 'Signal': {'burst': 5}},
        'Focus': {'Bulwark': {'burst': 5, 'ability': 6}, 'Aegis': {'burst': 4, 'ability': 5}},
    }
    role_bias = {
        'Tank': {'guard': 2},
        'Guardian': {'guard': 3},
        'Damage': {'burst': 2, 'ability': 2},
        'Sniper': {'burst': 3, 'ability': 2},
        'Control': {'ability': 2},
        'Disruptor': {'ability': 3},
        'Fortune': {'ability': 1, 'guard': 1},
        'Combo': {'burst': 2},
    }.get(role, {})
    matrix_bonus = int((((class_matrix.get(own_class) or {}).get(opp_class) or {}).get(action_key, 0)) or 0)
    base_bonus = 0
    if opp_class in counters:
        base_bonus = 5 if action_key in {'burst', 'ability'} else 3
    total_bonus = base_bonus + matrix_bonus + int(role_bias.get(action_key, 0) or 0)
    if total_bonus <= 0:
        return 0, ''
    return total_bonus, f'{own_class} давит {opp_class}'


def role_focus_bonus(metadata, focus, phase, action_key):
    role = str((metadata or {}).get('role') or '')
    profile = {
        'Tank': ({'defense', 'speed'}, {'counter'}, {'guard'}),
        'Guardian': ({'defense', 'luck'}, {'counter', 'tempo'}, {'guard', 'ability'}),
        'Damage': ({'attack', 'magic'}, {'opening', 'finisher'}, {'burst', 'ability'}),
        'Sniper': ({'attack', 'magic'}, {'finisher', 'risk'}, {'burst', 'ability'}),
        'Control': ({'luck', 'magic'}, {'counter', 'risk'}, {'guard', 'ability'}),
        'Disruptor': ({'speed', 'magic'}, {'counter', 'tempo'}, {'ability'}),
        'Support': ({'defense', 'luck'}, {'tempo', 'finisher'}, {'guard', 'ability'}),
        'Fortune': ({'luck', 'magic'}, {'risk', 'finisher'}, {'ability'}),
        'Combo': ({'attack', 'speed'}, {'opening', 'tempo'}, {'burst', 'ability'}),
        'Trickster': ({'luck', 'speed'}, {'risk', 'counter'}, {'guard', 'ability'}),
    }.get(role)
    if not profile:
        return 0, ''
    focus_set, phase_set, action_set = profile
    bonus = 0
    if focus in focus_set:
        bonus += 2
    if phase in phase_set:
        bonus += 1
    if action_key in action_set:
        bonus += 1
    if bonus <= 0:
        return 0, ''
    return bonus, f'{role} играет от {focus}'


def passive_ability_bonus(metadata, ability_state, trigger, *, previous_outcome=None, action_key=None, proc_seed=''):
    passive = dict((metadata or {}).get('passiveAbility') or {})
    if not passive:
        return 0, ''
    profile = dict((ability_state or {}).get('profile') or {})
    proc_probability = max(0.1, min(1.0, float(passive.get('probability', 1.0) or 1.0) * float(profile.get('passive_proc_mul', 1.0) or 1.0)))
    passive_trigger = str(passive.get('trigger') or '')
    if passive_trigger == 'on_round_loss' and previous_outcome == 'loss' and trigger == 'pre_round':
        if not deterministic_probability(f'{proc_seed}:loss', proc_probability):
            return 0, ''
        return int(passive.get('power', 0) or 0) + 2, passive.get('name', 'Passive')
    if passive_trigger == 'after_guard_win' and previous_outcome == 'win' and action_key == 'guard':
        if not deterministic_probability(f'{proc_seed}:guard-win', proc_probability):
            return 0, ''
        return int(passive.get('power', 0) or 0) + 1, passive.get('name', 'Passive')
    if passive_trigger == 'on_round_win' and previous_outcome == 'win' and trigger == 'pre_round':
        if not deterministic_probability(f'{proc_seed}:win', proc_probability):
            return 0, ''
        return int(passive.get('power', 0) or 0), passive.get('name', 'Passive')
    if passive_trigger == 'on_attack_roll' and action_key in {'burst', 'ability'} and trigger == 'roll':
        if not deterministic_probability(f'{proc_seed}:roll', proc_probability):
            return 0, ''
        return int(passive.get('power', 0) or 0), passive.get('name', 'Passive')
    return 0, ''


def active_ability_bonus(metadata, ability_state, phase, focus, action_key, *, proc_seed=''):
    active = dict((ability_state or {}).get('active') or {})
    if action_key != 'ability' or not active:
        return 0, ''
    role = str((metadata or {}).get('role') or '')
    profile = dict((ability_state or {}).get('profile') or {})
    base = int(active.get('power', 0) or 0) + 4
    proc_probability = max(0.55, min(1.0, float(active.get('probability', 1.0) or 1.0) * float(profile.get('active_proc_mul', 1.0) or 1.0)))
    if role in {'Tank', 'Guardian', 'Support'} and focus in {'defense', 'luck', 'speed'}:
        base += 3
    elif role in {'Damage', 'Sniper', 'Combo'} and focus in {'attack', 'magic'}:
        base += 4
    elif role in {'Control', 'Disruptor', 'Trickster'} and phase in {'counter', 'risk', 'tempo'}:
        base += 4
    if deterministic_probability(f'{proc_seed}:active', proc_probability):
        return base, active.get('name', 'Ability')
    return max(2, base // 2), f"{active.get('name', 'Ability')} частично"


def spend_ability_state(ability_state, action_key):
    state = dict(ability_state or {})
    active = dict(state.get('active') or {})
    cooldown_remaining = max(0, int(state.get('cooldown_remaining', 0)) - 1)
    state['cooldown_remaining'] = cooldown_remaining
    if action_key == 'ability' and active:
        state['charges_remaining'] = max(0, int(state.get('charges_remaining', 0)) - 1)
        state['cooldown_remaining'] = int(active.get('cooldown', 0) or 0)
        if bool(active.get('once_per_battle')):
            state['used_once'] = True
    return state


def choose_bot_round_action(planned_action, energy, ability_state, metadata, phase, round_index=0, previous_outcome=None, rng_seed='', allow_ability=True):
    actions = available_actions_for_state(energy, ability_state)
    if not allow_ability:
        actions = [action for action in actions if action != 'ability']
    if not actions:
        return 'guard'
    role = str((metadata or {}).get('role') or '')
    difficulty_level = max(0, min(4, int((metadata or {}).get('_bot_difficulty_level', 0) or 0)))
    rng = random.Random(hashlib.sha256(f'bot-live:{rng_seed}:{round_index}:{phase}:{previous_outcome}:{planned_action}'.encode()).hexdigest())
    weights = {action: 1 for action in actions}
    if planned_action in actions:
        weights[planned_action] += 3 + difficulty_level
    if 'guard' in actions and phase in {'control', 'setup'}:
        weights['guard'] += 2
    if 'burst' in actions and phase in {'pressure', 'risk', 'finisher'}:
        weights['burst'] += 2
    if previous_outcome == 'loss' and 'burst' in actions:
        weights['burst'] += 2
    if previous_outcome == 'win' and 'guard' in actions:
        weights['guard'] += 1
    if difficulty_level >= 2 and 'burst' in actions and phase in {'pressure', 'finisher'}:
        weights['burst'] += difficulty_level - 1
    if difficulty_level >= 3 and 'guard' in actions and previous_outcome == 'loss':
        weights['guard'] += 1
    if allow_ability and 'ability' in actions:
        ability_weight = 0
        if phase in {'risk', 'finisher'}:
            ability_weight += 2
        if role in {'Control', 'Disruptor', 'Damage', 'Sniper'}:
            ability_weight += 1
        if previous_outcome == 'loss':
            ability_weight += 1
        ability_weight += min(2, difficulty_level)
        if ability_weight > 0:
            weights['ability'] += ability_weight
    total_weight = sum(max(0, int(value)) for value in weights.values())
    if total_weight <= 0:
        return actions[0]
    roll = rng.uniform(0, total_weight)
    cursor = 0.0
    for action in actions:
        cursor += max(0, int(weights.get(action, 0)))
        if roll <= cursor:
            return action
    return actions[-1]


def resolve_battle_round(*, seed_value, idx, focus, label, phase, card_a, card_b, build_a, build_b, featured_a, featured_b, action_a, action_b, strategy_key_a, strategy_key_b, prev_a, prev_b, domain_meta_a=None, domain_meta_b=None, ability_state_a=None, ability_state_b=None):
    ability_state_a = dict(ability_state_a or {})
    ability_state_b = dict(ability_state_b or {})
    domain_meta_a = dict(domain_meta_a or {})
    domain_meta_b = dict(domain_meta_b or {})
    synergy_a = dict(domain_meta_a.get('_synergy') or {})
    synergy_b = dict(domain_meta_b.get('_synergy') or {})
    effective_action_a = effective_action_key(action_a, domain_meta_a)
    effective_action_b = effective_action_key(action_b, domain_meta_b)
    value_a = max(0, round(build_bonus_value(build_a, focus) / 7))
    value_b = max(0, round(build_bonus_value(build_b, focus) / 7))
    if focus == 'attack':
        value_a += int(synergy_a.get('attack', 0))
        value_b += int(synergy_b.get('attack', 0))
    if focus == 'defense':
        value_a += int(synergy_a.get('defense', 0))
        value_b += int(synergy_b.get('defense', 0))
    if focus == 'luck':
        value_a += int(synergy_a.get('luck', 0))
        value_b += int(synergy_b.get('luck', 0))
    card_boost_a = matchup_strategy_bonus(card_a, card_b, phase, idx)
    card_boost_b = matchup_strategy_bonus(card_b, card_a, phase, idx)
    action_bonus_a, action_bonus_b, action_note_a, action_note_b = action_round_resolution(effective_action_a, effective_action_b)
    strategy_bonus_a, strategy_note_a = strategy_round_bonus(strategy_key_a, focus, phase, idx, action_a, prev_a, featured_a or card_a)
    strategy_bonus_b, strategy_note_b = strategy_round_bonus(strategy_key_b, focus, phase, idx, action_b, prev_b, featured_b or card_b)
    skill_bonus_a, skill_note_a = apply_skill_bonus((featured_a or {}).get('skill_key'), focus, phase, value_a, value_b, featured_a or card_a, featured_b or card_b, idx, prev_a)
    skill_bonus_b, skill_note_b = apply_skill_bonus((featured_b or {}).get('skill_key'), focus, phase, value_b, value_a, featured_b or card_b, featured_a or card_a, idx, prev_b)
    featured_bonus_a, featured_note_a = featured_card_round_bonus(featured_a or card_a, featured_b or card_b, focus, phase, idx, prev_a)
    featured_bonus_b, featured_note_b = featured_card_round_bonus(featured_b or card_b, featured_a or card_a, focus, phase, idx, prev_b)
    passive_bonus_a, passive_note_a = passive_ability_bonus(domain_meta_a, ability_state_a, 'pre_round', previous_outcome=prev_a, action_key=action_a, proc_seed=f'{seed_value}:{idx}:a:pre')
    passive_bonus_b, passive_note_b = passive_ability_bonus(domain_meta_b, ability_state_b, 'pre_round', previous_outcome=prev_b, action_key=action_b, proc_seed=f'{seed_value}:{idx}:b:pre')
    active_bonus_a, active_note_a = active_ability_bonus(domain_meta_a, ability_state_a, phase, focus, action_a, proc_seed=f'{seed_value}:{idx}:a')
    active_bonus_b, active_note_b = active_ability_bonus(domain_meta_b, ability_state_b, phase, focus, action_b, proc_seed=f'{seed_value}:{idx}:b')
    counter_bonus_a, counter_note_a = class_counter_bonus(domain_meta_a, domain_meta_b, action_a)
    counter_bonus_b, counter_note_b = class_counter_bonus(domain_meta_b, domain_meta_a, action_b)
    role_bonus_a, role_note_a = role_focus_bonus(domain_meta_a, focus, phase, action_a)
    role_bonus_b, role_note_b = role_focus_bonus(domain_meta_b, focus, phase, action_b)
    roll_rng = random.Random(hashlib.sha256(f"{seed_value}:{idx}:{action_a}:{action_b}".encode()).hexdigest())
    roll_bonus_a, crit_a = energy_roll_bonus(action_a, roll_rng)
    roll_bonus_b, crit_b = energy_roll_bonus(action_b, roll_rng)
    passive_roll_a, passive_roll_note_a = passive_ability_bonus(domain_meta_a, ability_state_a, 'roll', previous_outcome=prev_a, action_key=action_a, proc_seed=f'{seed_value}:{idx}:a:roll')
    passive_roll_b, passive_roll_note_b = passive_ability_bonus(domain_meta_b, ability_state_b, 'roll', previous_outcome=prev_b, action_key=action_b, proc_seed=f'{seed_value}:{idx}:b:roll')
    if crit_a:
        roll_bonus_a += 6
    if crit_b:
        roll_bonus_b += 6
    swing_rng = random.Random(hashlib.sha256(f"{seed_value}:swing:{idx}".encode()).hexdigest())
    swing_a = swing_rng.randint(0, 2)
    swing_b = swing_rng.randint(0, 2)
    domain_bonus_a = passive_bonus_a + active_bonus_a + counter_bonus_a + role_bonus_a + passive_roll_a
    domain_bonus_b = passive_bonus_b + active_bonus_b + counter_bonus_b + role_bonus_b + passive_roll_b
    total_a = value_a + card_boost_a + action_bonus_a + strategy_bonus_a + skill_bonus_a + featured_bonus_a + roll_bonus_a + domain_bonus_a + swing_a
    total_b = value_b + card_boost_b + action_bonus_b + strategy_bonus_b + skill_bonus_b + featured_bonus_b + roll_bonus_b + domain_bonus_b + swing_b
    if total_a > total_b:
        winner = 'a'
        next_prev_a, next_prev_b = 'win', 'loss'
    elif total_b > total_a:
        winner = 'b'
        next_prev_a, next_prev_b = 'loss', 'win'
    else:
        winner = 'draw'
        next_prev_a = next_prev_b = 'draw'
    energy_spent_a = action_energy_cost(action_a, (ability_state_a or {}).get('active'))
    energy_spent_b = action_energy_cost(action_b, (ability_state_b or {}).get('active'))
    return {
        'round': idx + 1,
        'label': label,
        'focus': focus,
        'phase': phase,
        'action_a': action_a,
        'action_b': action_b,
        'action_bonus_a': action_bonus_a,
        'action_bonus_b': action_bonus_b,
        'action_note_a': action_note_a,
        'action_note_b': action_note_b,
        'strategy_key_a': strategy_key_a,
        'strategy_key_b': strategy_key_b,
        'strategy_bonus_a': strategy_bonus_a,
        'strategy_bonus_b': strategy_bonus_b,
        'strategy_note_a': strategy_note_a,
        'strategy_note_b': strategy_note_b,
        'card_a': {'slot': card_a.get('slot'), 'title': card_a.get('title')},
        'card_b': {'slot': card_b.get('slot'), 'title': card_b.get('title')},
        'value_a': value_a,
        'value_b': value_b,
        'boost_a': card_boost_a,
        'boost_b': card_boost_b,
        'skill_bonus_a': skill_bonus_a,
        'skill_bonus_b': skill_bonus_b,
        'skill_note_a': skill_note_a,
        'skill_note_b': skill_note_b,
        'featured_bonus_a': featured_bonus_a,
        'featured_bonus_b': featured_bonus_b,
        'featured_note_a': featured_note_a,
        'featured_note_b': featured_note_b,
        'energy_spent_a': energy_spent_a,
        'energy_spent_b': energy_spent_b,
        'roll_bonus_a': roll_bonus_a,
        'roll_bonus_b': roll_bonus_b,
        'crit_a': crit_a,
        'crit_b': crit_b,
        'domain_bonus_a': domain_bonus_a,
        'domain_bonus_b': domain_bonus_b,
        'domain_note_a': ' • '.join(part for part in [passive_note_a, active_note_a, counter_note_a, role_note_a, passive_roll_note_a] if part),
        'domain_note_b': ' • '.join(part for part in [passive_note_b, active_note_b, counter_note_b, role_note_b, passive_roll_note_b] if part),
        'swing_a': swing_a,
        'swing_b': swing_b,
        'total_a': total_a,
        'total_b': total_b,
        'winner': winner,
        'next_prev_a': next_prev_a,
        'next_prev_b': next_prev_b,
        'next_ability_state_a': spend_ability_state(ability_state_a, action_a),
        'next_ability_state_b': spend_ability_state(ability_state_b, action_b),
    }


def normalize_strategy_key(strategy_key):
    key = str(strategy_key or '').strip().lower()
    return key if key in STRATEGY_PRESETS else 'balanced'


def auto_action_plan(cards, featured_slot=None, strategy_key='balanced'):
    strategy = STRATEGY_PRESETS.get(normalize_strategy_key(strategy_key)) or STRATEGY_PRESETS['balanced']
    plan = list(strategy['plan'])
    featured = find_card_by_slot(cards, featured_slot)
    skill_key = (featured or {}).get('skill_key')
    if skill_key == 'defense_lock':
        plan[1] = 'guard'
        plan[3] = 'guard'
    if skill_key == 'attack_burst':
        plan[0] = 'burst'
        plan[4] = 'burst'
    if skill_key == 'wildcard':
        plan[2] = 'burst'
    if skill_key == 'tempo':
        plan[1] = 'burst'
        plan[3] = 'burst'
    if skill_key == 'mirror':
        plan[0] = 'guard'
        plan[2] = 'guard'
    if skill_key == 'underdog':
        plan[2] = 'burst'
        plan[4] = 'guard'
    return plan


def sanitize_action_plan(plan):
    plan = list(plan or [])
    while len(plan) < len(WIKIGACHI_ROUND_PLAN):
        plan.append(default_action_plan()[len(plan)])
    normalized = []
    for key in plan[:len(WIKIGACHI_ROUND_PLAN)]:
        action_key = str(key or '').strip().lower()
        if action_key not in ACTION_RULES:
            action_key = 'guard'
        normalized.append(action_key)
    return normalized


def action_round_resolution(action_a, action_b):
    meta_a = ACTION_RULES.get(action_a) or ACTION_RULES['guard']
    meta_b = ACTION_RULES.get(action_b) or ACTION_RULES['guard']
    if meta_a['beats'] == action_b and meta_b['beats'] != action_a:
        return 44, 2, f"{meta_a['ru_label']} контрит {meta_b['ru_label']}", f"{meta_b['ru_label']} попал под контр"
    if meta_b['beats'] == action_a and meta_a['beats'] != action_b:
        return 2, 44, f"{meta_a['ru_label']} попал под контр", f"{meta_b['ru_label']} контрит {meta_a['ru_label']}"
    if action_a == action_b:
        return 6, 6, 'Одинаковый ход, размен на равных', 'Одинаковый ход, размен на равных'
    return 8, 8, 'Ходы разошлись без явного контра', 'Ходы разошлись без явного контра'


def strategy_round_bonus(strategy_key, focus, phase, round_index, action_key, previous_outcome, featured_card):
    strategy_key = normalize_strategy_key(strategy_key)
    featured_card = normalize_card_profile(featured_card)
    skill_key = featured_card.get('skill_key')
    if strategy_key == 'attack_boost':
        bonus = 30 if action_key in {'burst', 'ability'} else 10
        if focus in {'attack', 'magic'}:
            bonus += 10
        if phase in {'opening', 'finisher'}:
            bonus += 6
        note = 'Атакующий буст усиливает атакующие окна'
    elif strategy_key == 'defense_boost':
        bonus = 30 if action_key == 'guard' else 10
        if focus in {'defense', 'speed'}:
            bonus += 10
        if phase in {'counter', 'tempo'}:
            bonus += 6
        note = 'Защитный буст усиливает удержание темпа'
    elif strategy_key == 'energy_boost':
        bonus = 22 if action_key == 'ability' else 16
        if phase in {'risk', 'tempo', 'finisher'}:
            bonus += 9
        if previous_outcome == 'loss':
            bonus += 4
        note = 'Энергобуст раскрывает способность домена'
    elif strategy_key == 'aggressive':
        bonus = 34 if action_key == 'burst' else 12
        if phase in {'opening', 'finisher'}:
            bonus += 10
        if previous_outcome == 'win':
            bonus += 6
        if skill_key == 'attack_burst':
            bonus += 10
        note = 'Агрессия давит темпом'
    elif strategy_key == 'tricky':
        bonus = 32 if action_key == 'guard' else 13
        if phase in {'counter', 'risk'}:
            bonus += 10
        if previous_outcome == 'loss':
            bonus += 8
        if skill_key in {'wildcard', 'mirror'}:
            bonus += 10
        note = 'Хитрость ищет контр-ход'
    else:
        bonus = 24
        if action_key == 'guard':
            bonus += 6
        if phase in {'counter', 'tempo'}:
            bonus += 8
        if previous_outcome == 'draw':
            bonus += 5
        if skill_key == 'defense_lock':
            bonus += 8
        note = 'Баланс держит ровный темп'
    return bonus, note


def wikigachi_duel(cards_a, cards_b, seed_value, build_a=None, build_b=None, featured_slot_a=None, featured_slot_b=None, strategy_key_a='balanced', strategy_key_b='balanced', domain_a=None, domain_b=None, wallet_a=None, wallet_b=None):
    rounds = []
    wins_a = 0
    wins_b = 0

    if not cards_a or not cards_b:
        return {'rounds': rounds, 'score_a': 0, 'score_b': 0, 'winner': None, 'tie_breaker': False}

    featured_a = find_card_by_slot(cards_a, featured_slot_a)
    featured_b = find_card_by_slot(cards_b, featured_slot_b)
    domain_meta_a = battle_domain_metadata(domain_a, wallet=wallet_a) if domain_a else {}
    domain_meta_b = battle_domain_metadata(domain_b, wallet=wallet_b) if domain_b else {}
    domain_meta_a['_synergy'] = compute_domain_synergies(wallet_a) if wallet_a else {}
    domain_meta_b['_synergy'] = compute_domain_synergies(wallet_b) if wallet_b else {}
    ability_state_a = ability_state_from_metadata(domain_meta_a)
    ability_state_b = ability_state_from_metadata(domain_meta_b)
    strategy_key_a = normalize_strategy_key(strategy_key_a)
    strategy_key_b = normalize_strategy_key(strategy_key_b)
    action_plan_a = auto_action_plan(cards_a, featured_slot_a, strategy_key_a)
    action_plan_b = auto_action_plan(cards_b, featured_slot_b, strategy_key_b)
    rounds_count = min(len(cards_a), len(cards_b), len(WIKIGACHI_ROUND_PLAN))
    prev_a = None
    prev_b = None

    for idx in range(rounds_count):
        focus, label, phase = WIKIGACHI_ROUND_PLAN[idx]
        card_a = cards_a[idx]
        card_b = cards_b[idx]
        action_a = action_plan_a[idx]
        action_b = action_plan_b[idx]
        if action_a not in available_actions_for_state(3, ability_state_a):
            action_a = 'burst' if 'burst' in available_actions_for_state(3, ability_state_a) else 'guard'
        if action_b not in available_actions_for_state(3, ability_state_b):
            action_b = 'burst' if 'burst' in available_actions_for_state(3, ability_state_b) else 'guard'
        round_data = resolve_battle_round(
            seed_value=f'wikigachi:{seed_value}',
            idx=idx,
            focus=focus,
            label=label,
            phase=phase,
            card_a=card_a,
            card_b=card_b,
            build_a=build_a,
            build_b=build_b,
            featured_a=featured_a or card_a,
            featured_b=featured_b or card_b,
            action_a=action_a,
            action_b=action_b,
            strategy_key_a=strategy_key_a,
            strategy_key_b=strategy_key_b,
            prev_a=prev_a,
            prev_b=prev_b,
            domain_meta_a=domain_meta_a,
            domain_meta_b=domain_meta_b,
            ability_state_a=ability_state_a,
            ability_state_b=ability_state_b,
        )
        total_a = round_data['total_a']
        total_b = round_data['total_b']
        if total_a > total_b:
            round_winner = 'a'
            wins_a += 1
        elif total_b > total_a:
            round_winner = 'b'
            wins_b += 1
        else:
            round_winner = 'draw'
        prev_a = round_data.pop('next_prev_a')
        prev_b = round_data.pop('next_prev_b')
        ability_state_a = round_data.pop('next_ability_state_a')
        ability_state_b = round_data.pop('next_ability_state_b')
        round_data['winner'] = round_winner
        rounds.append(round_data)

    tie_breaker = False
    if wins_a > wins_b:
        winner = 'a'
    elif wins_b > wins_a:
        winner = 'b'
    else:
        tie_breaker = True
        total_a = featured_match_bonus(featured_a) * 2 + deck_score(cards_a)
        total_b = featured_match_bonus(featured_b) * 2 + deck_score(cards_b)
        if total_a > total_b:
            winner = 'a'
        elif total_b > total_a:
            winner = 'b'
        else:
            winner = None

    return {
        'rounds': rounds,
        'score_a': wins_a,
        'score_b': wins_b,
        'winner': winner,
        'tie_breaker': tie_breaker,
        'featured_a': featured_a,
        'featured_b': featured_b,
        'action_plan_a': action_plan_a,
        'action_plan_b': action_plan_b,
        'strategy_key_a': strategy_key_a,
        'strategy_key_b': strategy_key_b,
    }


def load_active_deck_cards(wallet, domain):
    if not wallet or not domain:
        return None
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT cards_json
            FROM pack_opens
            WHERE wallet = ? AND domain = ?
            ORDER BY created_at DESC
            LIMIT 1
            ''',
            (wallet, domain),
        ).fetchone()
    if row and row['cards_json']:
        try:
            parsed = json.loads(row['cards_json'])
            if isinstance(parsed, list) and parsed:
                return ensure_battle_ready_cards(parsed, domain, seed_value=f'load-deck:{wallet}:{domain}')
        except json.JSONDecodeError:
            return None
    return None


def restore_previous_deck_cards(wallet, domain):
    if not wallet or not domain:
        raise ValueError('Нужен кошелёк и домен.')
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT cards_json
            FROM pack_opens
            WHERE wallet = ? AND domain = ?
            ORDER BY created_at DESC
            LIMIT 2
            ''',
            (wallet, domain),
        ).fetchall()
    if len(rows) < 2:
        raise ValueError('Для этого домена пока нет предыдущей колоды.')
    try:
        cards = json.loads(rows[1]['cards_json'] or '[]')
    except json.JSONDecodeError as exc:
        raise ValueError('Не удалось восстановить предыдущую колоду.') from exc
    if not isinstance(cards, list) or not cards:
        raise ValueError('Предыдущая колода повреждена.')
    cards = ensure_battle_ready_cards(cards, domain, seed_value=f'restore:{wallet}:{domain}:{now_iso()}')
    total_score = deck_score(cards)
    pack_id = store_pack_open(wallet, domain, 'restore', cards, total_score)
    return {'cards': cards, 'total_score': total_score, 'pack_id': pack_id}


def latest_opened_domain_for_wallet(wallet):
    if not wallet:
        return None
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT domain
            FROM pack_opens
            WHERE wallet = ?
            ORDER BY created_at DESC
            LIMIT 1
            ''',
            (wallet,),
        ).fetchone()
    return row['domain'] if row and row['domain'] else None


def deck_summary_for_domain(domain, wallet=None):
    if not domain:
        return None
    metadata = get_domain_metadata_payload(domain, wallet=wallet)
    synergies = compute_domain_synergies(wallet) if wallet else {'attack': 0, 'defense': 0, 'luck': 0, 'energy': 0, 'labels': []}
    cards = load_active_deck_cards(wallet, domain) if wallet else None
    if not cards:
        cards = generate_pack(domain)
    cards = [normalize_card_profile(card) for card in cards]
    pool = deck_power_pool(cards, domain)
    build = load_deck_build(wallet, domain, cards) if wallet else {'pool': pool, 'points': default_discipline_build(pool)}
    return {
        'cards': cards,
        'average_attack': round(build['points'].get('attack', 0) / max(1, len(cards)), 1),
        'average_defense': round(build['points'].get('defense', 0) / max(1, len(cards)), 1),
        'average_speed': round(build['points'].get('speed', 0) / max(1, len(cards)), 1),
        'average_magic': round(build['points'].get('magic', 0) / max(1, len(cards)), 1),
        'discipline_build': build['points'],
        'discipline_pool': build['pool'],
        'total_score': deck_score(cards),
        'domain_metadata': metadata,
        'synergies': synergies,
    }


def random_bot_cards(seed_value, count=5):
    rng = random.Random(hashlib.sha256(f'bot:{seed_value}'.encode()).hexdigest())
    rarity_keys = list(RARITY_ORDER)
    cards = []
    for slot in range(1, count + 1):
        rarity_key = rarity_keys[rng.randrange(len(rarity_keys))]
        template = CARD_CATALOG_BY_RARITY[rarity_key][0]
        pool_value = rng.randint(int(template['pool_min']), int(template['pool_max']))
        skill = skill_for_card(rarity_key, f'bot-{seed_value}', slot, template['title'])
        cards.append(
            {
                'slot': slot,
                'title': template['title'],
                'ability': skill['description'],
                'pool_value': pool_value,
                'base_power': pool_value,
                'score': pool_value,
                'rarity': RARITY_LABELS[rarity_key],
                'rarity_key': rarity_key,
                'skill': skill,
                'skill_key': skill['key'],
                'skill_name': skill['name'],
                'skill_description': skill['description'],
            }
        )
    return cards


def bot_cards_slightly_weaker_than_player(player_cards, seed_value, difficulty_level=0):
    rng = random.Random(hashlib.sha256(f'bot-weaker:{seed_value}'.encode()).hexdigest())
    cards = []
    normalized_cards = [normalize_card_profile(card) for card in (player_cards or [])]
    if not normalized_cards:
        return random_bot_cards(seed_value, count=5)

    level = max(0, min(4, int(difficulty_level or 0)))
    scale_ranges = {
        0: (0.80, 0.92),
        1: (0.86, 0.98),
        2: (0.92, 1.03),
        3: (0.98, 1.08),
        4: (1.02, 1.12),
    }
    bias_ranges = {
        0: (-6.0, 4.0),
        1: (-4.0, 5.0),
        2: (-3.0, 6.0),
        3: (-2.0, 7.0),
        4: (0.0, 8.0),
    }
    min_scale, max_scale = scale_ranges[level]
    min_bias, max_bias = bias_ranges[level]

    for slot, source in enumerate(normalized_cards[:5], start=1):
        scale = rng.uniform(min_scale, max_scale)
        score = max(1, int(round(source.get('pool_value', source.get('score', 100)) * scale + rng.uniform(min_bias, max_bias))))
        rarity_key = str(source.get('rarity_key') or 'basic').lower()
        if rarity_key not in RARITY_LABELS:
            rarity_key = 'basic'
        template = CARD_CATALOG_BY_RARITY[rarity_key][0]
        skill = skill_for_card(rarity_key, f'bot-{seed_value}', slot, template['title'])
        cards.append(
            {
                'slot': slot,
                'title': template['title'],
                'ability': skill['description'],
                'pool_value': score,
                'base_power': score,
                'score': score,
                'rarity': RARITY_LABELS[rarity_key],
                'rarity_key': rarity_key,
                'skill': skill,
                'skill_key': skill['key'],
                'skill_name': skill['name'],
                'skill_description': skill['description'],
            }
        )
    return cards


def bot_selected_slot(cards, difficulty_level):
    normalized = [normalize_card_profile(card) for card in (cards or [])]
    if not normalized:
        return 1
    level = max(0, min(4, int(difficulty_level or 0)))
    if level <= 1:
        return weakest_tactical_slot(normalized)
    strongest = max(normalized, key=lambda card: (int(card.get('pool_value', 0)), int(card.get('slot', 0) or 0)))
    if level >= 3:
        return int(strongest.get('slot', 1) or 1)
    mid_sorted = sorted(normalized, key=lambda card: (int(card.get('pool_value', 0)), int(card.get('slot', 0) or 0)))
    return int(mid_sorted[-2].get('slot', 1) or 1) if len(mid_sorted) >= 2 else int(strongest.get('slot', 1) or 1)


def weakest_tactical_slot(cards):
    normalized = [normalize_card_profile(card) for card in (cards or [])]
    if not normalized:
        return 1
    weakest = min(normalized, key=lambda card: (int(card.get('pool_value', 0)), int(card.get('slot', 0) or 0)))
    return int(weakest.get('slot', 1) or 1)


def random_bot_single_card(seed_value):
    return random_bot_cards(seed_value, count=1)[0]


def extract_domain_candidates_from_nft(item):
    fields = []
    metadata = item.get('metadata') or {}
    collection = item.get('collection') or {}
    previews = item.get('previews') or []

    fields.extend(
        [
            item.get('name'),
            item.get('dns'),
            item.get('domain'),
            item.get('description'),
            item.get('address'),
            item.get('content_url'),
            metadata.get('name'),
            metadata.get('domain'),
            metadata.get('dns'),
            metadata.get('description'),
            metadata.get('attributes'),
            collection.get('name'),
            collection.get('description'),
        ]
    )

    for preview in previews:
        fields.append(preview.get('url'))

    candidates = set()
    for field in fields:
        candidates.update(extract_root_ton_domains_from_text(field))

    return sorted(candidates)


def check_dns_domain(domain):
    url = DNS_TON_BASE_URL.format(domain=f'{domain}.ton')
    try:
        response = HTTP.get(url, timeout=8)
        if response.status_code == 200:
            payload = response.json()
            return {'exists': True, 'data': payload}
        return {'exists': False, 'status': response.status_code}
    except requests.RequestException as exc:
        return {'exists': False, 'error': str(exc)}


def fetch_wallet_domains(wallet, force_refresh=False):
    if not valid_wallet_address(wallet):
        raise ValueError('Некорректный адрес кошелька.')

    cache_entry = DOMAIN_CACHE.get(wallet)
    if cache_entry and not force_refresh and cache_entry['expires_at'] > datetime.now().timestamp():
      return cache_entry['domains']

    headers = {}
    if TONAPI_KEY:
        headers['Authorization'] = f'Bearer {TONAPI_KEY}'

    try:
        response = HTTP.get(TONAPI_BASE_URL.format(wallet=wallet), headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f'Ошибка TonAPI: {exc}') from exc

    payload = response.json()
    nft_items = payload.get('nfts') or payload.get('nft_items') or []
    unique_domains = {}

    for item in nft_items:
        for domain in extract_domain_candidates_from_nft(item):
            if domain not in unique_domains:
                base = score_from_domain(domain, wallet=wallet)
                dns_info = check_dns_domain(domain)
                unique_domains[domain] = {
                    'domain': domain,
                    'domain_exists': dns_info.get('exists', False),
                    'validation': {
                        'strict_root_ton': True,
                        'subdomain': False,
                        'dns_exists': dns_info.get('exists', False),
                    },
                    'source_label': item.get('name')
                    or (item.get('metadata') or {}).get('name')
                    or 'TonAPI NFT item',
                    'patterns': base['patterns'],
                    'tier': base['tier'],
                    'rarity': base.get('rarity'),
                    'special_collections': base.get('special_collections', []),
                    'luck': base.get('luck', 0),
                    'score': base['score'],
                    'metadata': base.get('metadata'),
                }

    domains = sorted(unique_domains.values(), key=lambda item: (-item['score'], item['domain']))
    DOMAIN_CACHE[wallet] = {
        'domains': domains,
        'expires_at': datetime.now().timestamp() + DOMAIN_CACHE_TTL,
    }
    return domains


def validate_wallet_owns_domain(wallet, domain):
    normalized = normalize_domain(domain)
    if not valid_wallet_address(wallet) or not normalized:
        return False
    if guest_access_enabled() and normalized == guest_domain_for_wallet(wallet):
        return True
    first_pass = fetch_wallet_domains(wallet, force_refresh=False)
    if not any(item['domain'] == normalized for item in first_pass):
        return False
    second_pass = fetch_wallet_domains(wallet, force_refresh=True)
    return any(item['domain'] == normalized for item in second_pass)


def upsert_telegram_user(user, chat_id):
    telegram_user_id = user.get('id')
    if not telegram_user_id or not chat_id:
        return
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO telegram_users (
                telegram_user_id, chat_id, username, first_name, last_name, wallet, linked_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                chat_id = excluded.chat_id,
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                updated_at = excluded.updated_at
            ''',
            (
                telegram_user_id,
                chat_id,
                user.get('username'),
                user.get('first_name'),
                user.get('last_name'),
                now_iso(),
                now_iso(),
            ),
        )
        conn.commit()


def telegram_wallet_link(wallet):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM telegram_users WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row) if row else None


def telegram_user_link(telegram_user_id):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM telegram_users WHERE telegram_user_id = ?', (telegram_user_id,)).fetchone()
    return dict(row) if row else None


def ensure_telegram_notification_prefs(wallet):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM telegram_notification_prefs WHERE wallet = ?', (wallet,)).fetchone()
        if row is None:
            conn.execute(
                '''
                INSERT INTO telegram_notification_prefs (
                    wallet,
                    notify_duel_invites,
                    notify_daily_reward,
                    notify_win_quest,
                    notify_guild_invites,
                    notify_guild_reward,
                    notify_season_pass,
                    last_daily_notified_on,
                    last_quest_notified_target,
                    last_guild_reward_week,
                    last_season_notified_level,
                    updated_at
                ) VALUES (?, 1, 1, 1, 1, 1, 1, NULL, 0, NULL, 0, ?)
                ''',
                (wallet, now_iso()),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM telegram_notification_prefs WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row)


def telegram_notification_settings(wallet):
    prefs = ensure_telegram_notification_prefs(wallet)
    return {
        'duel_invites': bool(prefs.get('notify_duel_invites', 1)),
        'daily_reward': bool(prefs.get('notify_daily_reward', 1)),
        'win_quest': bool(prefs.get('notify_win_quest', 1)),
        'guild_invites': bool(prefs.get('notify_guild_invites', 1)),
        'guild_reward': bool(prefs.get('notify_guild_reward', 1)),
        'season_pass': bool(prefs.get('notify_season_pass', 1)),
        'last_daily_notified_on': prefs.get('last_daily_notified_on'),
        'last_quest_notified_target': int(prefs.get('last_quest_notified_target', 0) or 0),
        'last_guild_reward_week': prefs.get('last_guild_reward_week'),
        'last_season_notified_level': int(prefs.get('last_season_notified_level', 0) or 0),
    }


def update_telegram_notification_settings(wallet, **fields):
    ensure_telegram_notification_prefs(wallet)
    updates = []
    params = []
    for key, value in fields.items():
        updates.append(f'{key} = ?')
        params.append(value)
    if not updates:
        return telegram_notification_settings(wallet)
    updates.append('updated_at = ?')
    params.append(now_iso())
    params.append(wallet)
    with closing(get_db()) as conn:
        conn.execute(f'UPDATE telegram_notification_prefs SET {", ".join(updates)} WHERE wallet = ?', params)
        conn.commit()
    return telegram_notification_settings(wallet)


def telegram_notify_wallet(wallet, text, reply_markup=None):
    if not TG_BOT_TOKEN or not wallet:
        return False
    link = telegram_wallet_link(wallet)
    if not link or not link.get('chat_id'):
        return False
    try:
        telegram_send_message(link['chat_id'], text, reply_markup=reply_markup)
        return True
    except Exception:
        return False


def telegram_notification_wallets():
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT wallet
            FROM telegram_users
            WHERE wallet IS NOT NULL AND wallet != ''
            ORDER BY updated_at DESC
            '''
        ).fetchall()
    return [row['wallet'] for row in rows if row['wallet']]


def clean_public_text(value, limit=160):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text[:limit]


def looks_like_media_url(value):
    text = clean_public_text(value, 1024)
    if not text:
        return False
    if text.startswith(('http://', 'https://', 'data:image/', '/')):
        return True
    if text.startswith('ipfs://'):
        return True
    return False


def extract_preview_media_url(value, depth=0):
    if depth > 4 or value is None:
        return ''
    if isinstance(value, str):
        return clean_public_text(value, 1024) if looks_like_media_url(value) else ''
    if isinstance(value, dict):
        preferred_keys = (
            'thumbnail_url', 'image_url', 'photo_url', 'preview_url', 'url',
            'static_url', 'png_url', 'webp_url', 'small', 'medium', 'large',
            'thumbnail', 'image', 'photo', 'sticker', 'animation',
        )
        for key in preferred_keys:
            if key in value:
                found = extract_preview_media_url(value.get(key), depth + 1)
                if found:
                    return found
        for nested in value.values():
            found = extract_preview_media_url(nested, depth + 1)
            if found:
                return found
        return ''
    if isinstance(value, (list, tuple)):
        for nested in value:
            found = extract_preview_media_url(nested, depth + 1)
            if found:
                return found
    return ''


def looks_like_telegram_gift_item(*parts):
    text = ' '.join(clean_public_text(part, 256) for part in parts if part).lower()
    if not text:
        return False
    blocked_markers = (
        '.ton',
        'dns',
        'domain',
        'sticker',
        'sticker family',
        'jetton',
        'collection item',
        'username',
    )
    if any(marker in text for marker in blocked_markers):
        return False
    positive_markers = (
        'gift',
        'gifts',
        'telegram gift',
        'nft gift',
        'подар',
        'tele gift',
    )
    return any(marker in text for marker in positive_markers)


def looks_like_wallet_gift_item(*parts):
    text = ' '.join(clean_public_text(part, 256) for part in parts if part).lower()
    if not text:
        return False
    blocked_markers = (
        '.ton',
        'dns',
        'domain',
        'sticker',
        'sticker family',
        'jetton',
        'collection item',
        'username',
        'telegram user',
    )
    if any(marker in text for marker in blocked_markers):
        return False
    positive_markers = (
        'gift',
        'gifts',
        'telegram gift',
        'nft gift',
        'gift box',
        'gift collection',
        'подар',
    )
    return any(marker in text for marker in positive_markers)


def safe_slug(value):
    base = re.sub(r'[^a-z0-9]+', '-', clean_public_text(value.lower(), 48)).strip('-')
    return base or f'guild-{uuid.uuid4().hex[:6]}'


def ensure_player_profile_columns(conn):
    columns = {row['name'] for row in conn.execute("PRAGMA table_info(player_profiles)").fetchall()}
    additions = {
        'profile_title': "ALTER TABLE player_profiles ADD COLUMN profile_title TEXT",
        'favorite_ability': "ALTER TABLE player_profiles ADD COLUMN favorite_ability TEXT",
        'play_style': "ALTER TABLE player_profiles ADD COLUMN play_style TEXT",
        'favorite_strategy': "ALTER TABLE player_profiles ADD COLUMN favorite_strategy TEXT",
        'favorite_role': "ALTER TABLE player_profiles ADD COLUMN favorite_role TEXT",
        'profile_banner_key': "ALTER TABLE player_profiles ADD COLUMN profile_banner_key TEXT",
        'profile_gift_source': "ALTER TABLE player_profiles ADD COLUMN profile_gift_source TEXT",
        'profile_gift_key': "ALTER TABLE player_profiles ADD COLUMN profile_gift_key TEXT",
        'updated_at': "ALTER TABLE player_profiles ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
    }
    for column, statement in additions.items():
        if column not in columns:
            conn.execute(statement)
    conn.execute("UPDATE player_profiles SET updated_at = COALESCE(NULLIF(updated_at, ''), ?) WHERE updated_at IS NULL OR updated_at = ''", (now_iso(),))


def ensure_player_profile(wallet):
    ensure_player(wallet)
    with closing(get_db()) as conn:
        ensure_player_profile_columns(conn)
        row = conn.execute('SELECT * FROM player_profiles WHERE wallet = ?', (wallet,)).fetchone()
        if row is None:
            ts = now_iso()
            conn.execute(
                '''
                INSERT INTO player_profiles (
                    wallet, nickname, avatar, bio, language, visibility,
                    profile_title, favorite_ability, play_style, favorite_strategy,
                    favorite_role, profile_banner_key, profile_gift_source,
                    profile_gift_key, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'public', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (wallet, None, '', None, 'ru', None, None, None, None, None, None, None, None, ts),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM player_profiles WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row)


def player_profile_row(wallet):
    if not wallet:
        return None
    return ensure_player_profile(wallet)


def display_name_for_wallet(wallet):
    profile = player_profile_row(wallet)
    if profile and profile.get('nickname'):
        return profile['nickname']
    link = telegram_wallet_link(wallet)
    if link:
        return link.get('username') or link.get('first_name') or short_wallet(wallet)
    return short_wallet(wallet)


def short_wallet(wallet):
    return f'{wallet[:6]}...{wallet[-6:]}' if wallet and len(wallet) > 12 else wallet


def avatar_for_wallet(wallet):
    return ''


def empty_player_behavior_stats():
    return {
        'matches_total': 0,
        'wins_total': 0,
        'losses_total': 0,
        'draws_total': 0,
        'actions': {'burst': 0, 'guard': 0, 'ability': 0},
        'strategies': {},
        'roles': {},
        'modes': {},
        'domains': {},
        'bot': {
            'matches_total': 0,
            'wins_total': 0,
            'losses_total': 0,
            'draws_total': 0,
            'current_win_streak': 0,
            'max_win_streak': 0,
            'difficulty_level': 0,
        },
        'updated_at': now_iso(),
    }


def ensure_player_behavior_row(wallet):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM player_behavior_stats WHERE wallet = ?', (wallet,)).fetchone()
        if row is None:
            conn.execute(
                'INSERT INTO player_behavior_stats (wallet, stats_json, updated_at) VALUES (?, ?, ?)',
                (wallet, json.dumps(empty_player_behavior_stats(), ensure_ascii=False), now_iso()),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM player_behavior_stats WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row)


def player_behavior_stats(wallet):
    if not wallet:
        return empty_player_behavior_stats()
    row = ensure_player_behavior_row(wallet)
    try:
        stats = json.loads(row.get('stats_json') or '{}')
    except json.JSONDecodeError:
        stats = {}
    merged = empty_player_behavior_stats()
    for key, value in stats.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value
    merged['updated_at'] = row.get('updated_at') or merged.get('updated_at') or now_iso()
    return merged


def save_player_behavior_stats(wallet, stats):
    ensure_runtime_tables()
    payload = empty_player_behavior_stats()
    for key, value in (stats or {}).items():
        if isinstance(payload.get(key), dict) and isinstance(value, dict):
            payload[key].update(value)
        else:
            payload[key] = value
    payload['updated_at'] = now_iso()
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO player_behavior_stats (wallet, stats_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(wallet) DO UPDATE SET
                stats_json = excluded.stats_json,
                updated_at = excluded.updated_at
            ''',
            (wallet, json.dumps(payload, ensure_ascii=False), payload['updated_at']),
        )
        conn.commit()
    return payload


def top_stat_key(mapping, fallback=''):
    items = [(str(key), int(value or 0)) for key, value in (mapping or {}).items() if int(value or 0) > 0]
    if not items:
        return fallback
    items.sort(key=lambda item: (-item[1], item[0]))
    return items[0][0]


def derived_behavior_profile(wallet):
    stats = player_behavior_stats(wallet)
    actions = stats.get('actions') or {}
    strategies = stats.get('strategies') or {}
    roles = stats.get('roles') or {}
    matches_total = int(stats.get('matches_total', 0) or 0)
    favorite_ability = top_stat_key(actions, '')
    favorite_strategy = top_stat_key(strategies, '')
    favorite_role = top_stat_key(roles, '')

    burst_count = int(actions.get('burst', 0) or 0)
    guard_count = int(actions.get('guard', 0) or 0)
    ability_count = int(actions.get('ability', 0) or 0)
    total_action_count = max(1, burst_count + guard_count + ability_count)
    burst_rate = burst_count / total_action_count
    guard_rate = guard_count / total_action_count
    ability_rate = ability_count / total_action_count

    if favorite_strategy in {'tricky'}:
        play_style = 'trickster'
    elif favorite_strategy in {'energy_boost'} or favorite_role == 'fortune' or ability_rate >= 0.28:
        play_style = 'fortune'
    elif burst_rate >= 0.5 or favorite_strategy in {'aggressive', 'attack_boost'}:
        play_style = 'aggressive'
    elif guard_rate >= 0.5 or favorite_strategy in {'defense_boost'} or favorite_role in {'guardian', 'tank', 'control'}:
        play_style = 'control'
    elif favorite_role in {'combo', 'sniper', 'damage'}:
        play_style = 'tempo'
    else:
        play_style = 'balanced'

    return {
        'favorite_ability': favorite_ability,
        'favorite_strategy': favorite_strategy,
        'favorite_role': favorite_role,
        'play_style': play_style,
        'matches_total': matches_total,
        'win_rate': round((int(stats.get('wins_total', 0) or 0) / max(1, matches_total)), 3),
        'action_rates': {
            'burst': round(burst_rate, 3),
            'guard': round(guard_rate, 3),
            'ability': round(ability_rate, 3),
        },
        'stats': stats,
    }


def record_player_behavior(wallet, domain, rounds, strategy_key, result, mode='casual', side='a'):
    if not wallet:
        return empty_player_behavior_stats()
    stats = player_behavior_stats(wallet)
    stats['matches_total'] = int(stats.get('matches_total', 0) or 0) + 1
    result_key = str(result or '').strip().lower()
    if result_key == 'win':
        stats['wins_total'] = int(stats.get('wins_total', 0) or 0) + 1
    elif result_key == 'loss':
        stats['losses_total'] = int(stats.get('losses_total', 0) or 0) + 1
    else:
        stats['draws_total'] = int(stats.get('draws_total', 0) or 0) + 1

    mode_key = str(mode or 'casual').strip().lower() or 'casual'
    stats.setdefault('modes', {})
    stats['modes'][mode_key] = int(stats['modes'].get(mode_key, 0) or 0) + 1

    normalized_domain = normalize_domain(domain)
    if normalized_domain:
        stats.setdefault('domains', {})
        stats['domains'][normalized_domain] = int(stats['domains'].get(normalized_domain, 0) or 0) + 1

    side_key = 'a' if side != 'b' else 'b'
    for round_item in rounds or []:
        action_value = str(round_item.get(f'action_{side_key}') or '').strip().lower()
        if action_value in {'burst', 'guard', 'ability'}:
            stats.setdefault('actions', {})
            stats['actions'][action_value] = int(stats['actions'].get(action_value, 0) or 0) + 1
        round_strategy = str(round_item.get(f'strategy_key_{side_key}') or strategy_key or '').strip().lower()
        if round_strategy:
            stats.setdefault('strategies', {})
            stats['strategies'][round_strategy] = int(stats['strategies'].get(round_strategy, 0) or 0) + 1

    metadata = get_domain_metadata_payload(normalized_domain, wallet=wallet) if normalized_domain else None
    role_key = str((metadata or {}).get('role') or '').strip().lower()
    if role_key:
        stats.setdefault('roles', {})
        stats['roles'][role_key] = int(stats['roles'].get(role_key, 0) or 0) + 1

    return save_player_behavior_stats(wallet, stats)


def bot_difficulty_level_for_streak(streak):
    streak = max(0, int(streak or 0))
    if streak >= 10:
        return 4
    if streak >= 7:
        return 3
    if streak >= 4:
        return 2
    if streak >= 2:
        return 1
    return 0


def player_bot_progress(wallet):
    stats = player_behavior_stats(wallet)
    bot_stats = dict(stats.get('bot') or {})
    streak = int(bot_stats.get('current_win_streak', 0) or 0)
    level = int(bot_stats.get('difficulty_level', bot_difficulty_level_for_streak(streak)) or 0)
    return {
        'matches_total': int(bot_stats.get('matches_total', 0) or 0),
        'wins_total': int(bot_stats.get('wins_total', 0) or 0),
        'losses_total': int(bot_stats.get('losses_total', 0) or 0),
        'draws_total': int(bot_stats.get('draws_total', 0) or 0),
        'current_win_streak': streak,
        'max_win_streak': int(bot_stats.get('max_win_streak', 0) or 0),
        'difficulty_level': max(0, min(4, level)),
    }


def update_player_bot_progress(wallet, result):
    if not wallet:
        return player_bot_progress(wallet)
    stats = player_behavior_stats(wallet)
    bot_stats = dict(stats.get('bot') or {})
    bot_stats['matches_total'] = int(bot_stats.get('matches_total', 0) or 0) + 1
    result_key = str(result or '').strip().lower()
    if result_key == 'win':
        bot_stats['wins_total'] = int(bot_stats.get('wins_total', 0) or 0) + 1
        bot_stats['current_win_streak'] = int(bot_stats.get('current_win_streak', 0) or 0) + 1
        bot_stats['max_win_streak'] = max(
            int(bot_stats.get('max_win_streak', 0) or 0),
            int(bot_stats.get('current_win_streak', 0) or 0),
        )
    elif result_key == 'loss':
        bot_stats['losses_total'] = int(bot_stats.get('losses_total', 0) or 0) + 1
        bot_stats['current_win_streak'] = 0
    else:
        bot_stats['draws_total'] = int(bot_stats.get('draws_total', 0) or 0) + 1
        bot_stats['current_win_streak'] = 0
    bot_stats['difficulty_level'] = bot_difficulty_level_for_streak(bot_stats.get('current_win_streak', 0))
    stats['bot'] = bot_stats
    save_player_behavior_stats(wallet, stats)
    return player_bot_progress(wallet)


def wallet_profile_gifts(wallet, limit=24):
    if not valid_wallet_address(wallet):
        return []
    headers = {}
    if TONAPI_KEY:
        headers['Authorization'] = f'Bearer {TONAPI_KEY}'
    try:
        response = HTTP.get(TONAPI_BASE_URL.format(wallet=wallet), headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    items = payload.get('nfts') or payload.get('nft_items') or []
    result = []
    seen = set()
    for item in items:
        if extract_domain_candidates_from_nft(item):
            continue
        metadata = item.get('metadata') or {}
        previews = item.get('previews') or []
        image_url = (
            extract_preview_media_url(metadata.get('image'))
            or extract_preview_media_url(metadata.get('image_url'))
            or extract_preview_media_url(item.get('image'))
            or extract_preview_media_url(previews)
        )
        image_url = clean_public_text(image_url, 512)
        name = clean_public_text(
            metadata.get('name')
            or item.get('name')
            or metadata.get('description')
            or 'Подарок кошелька',
            64,
        )
        collection_name = clean_public_text(metadata.get('collection') or ((item.get('collection') or {}).get('name')), 64)
        description = clean_public_text(metadata.get('description'), 96)
        searchable = ' '.join(part for part in [name, collection_name, description] if part).lower()
        if '.ton' in searchable:
            continue
        if not looks_like_wallet_gift_item(name, collection_name, description, item.get('type'), metadata.get('content_type')):
            continue
        if not image_url:
            continue
        nft_address = clean_public_text(item.get('address') or metadata.get('address') or '', 128)
        gift_key = nft_address or hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:24]
        full_key = f'wallet:{gift_key}'
        if full_key in seen:
            continue
        seen.add(full_key)
        result.append(
            {
                'source': 'wallet',
                'key': full_key,
                'label': name or 'Подарок кошелька',
                'subtitle': collection_name or 'TON NFT',
                'image_url': image_url,
                'emoji': clean_public_text(metadata.get('emoji') or '', 8),
            }
        )
        if len(result) >= limit:
            break
    return result


def telegram_profile_gifts(wallet, limit=24):
    link = telegram_wallet_link(wallet)
    if not link or not TG_BOT_TOKEN:
        return []
    try:
        response = telegram_api('getUserGifts', {'user_id': int(link['telegram_user_id']), 'limit': int(limit)})
    except Exception:
        return []
    payload = response.get('result') if isinstance(response, dict) else None
    items = []
    if isinstance(payload, dict):
        items = payload.get('gifts') or payload.get('items') or []
    elif isinstance(payload, list):
        items = payload
    result = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        gift = item.get('gift') if isinstance(item.get('gift'), dict) else item
        gift_id = clean_public_text(gift.get('id') or item.get('id') or '', 64)
        label = clean_public_text(
            gift.get('title')
            or gift.get('name')
            or item.get('title')
            or 'Подарок Telegram',
            64,
        )
        subtitle = clean_public_text(gift.get('model') or item.get('type') or 'Telegram Gift', 48)
        image_url = clean_public_text(
            extract_preview_media_url(gift.get('sticker'))
            or extract_preview_media_url(gift.get('image_url'))
            or extract_preview_media_url(gift.get('photo_url'))
            or extract_preview_media_url(gift.get('animation_url'))
            or extract_preview_media_url(item.get('sticker'))
            or extract_preview_media_url(item.get('image_url'))
            or extract_preview_media_url(item.get('photo_url'))
            or extract_preview_media_url(item),
            512,
        )
        if not gift_id and not label:
            continue
        if not image_url:
            continue
        result.append(
            {
                'source': 'telegram',
                'key': f"telegram:{gift_id or hashlib.sha256(json.dumps(gift, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:20]}",
                'label': label or 'Подарок Telegram',
                'subtitle': subtitle,
                'image_url': image_url,
                'emoji': clean_public_text(gift.get('emoji') or item.get('emoji') or '', 8),
            }
        )
    return result


def available_profile_gifts(wallet):
    items = []
    seen = set()
    for source_items in (telegram_profile_gifts(wallet), wallet_profile_gifts(wallet)):
        for item in source_items:
            key = item.get('key')
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def selected_profile_gift(wallet, profile=None):
    row = profile or player_profile_row(wallet) or {}
    source = clean_public_text(row.get('profile_gift_source') or '', 24)
    key = clean_public_text(row.get('profile_gift_key') or '', 128)
    if not source or not key:
        return None
    full_key = key if ':' in key else f'{source}:{key}'
    for item in available_profile_gifts(wallet):
        if item.get('key') == full_key:
            return item
    return None


def cosmetic_nft_draft(wallet):
    items = []
    for item in cosmetic_inventory(wallet):
        items.append(
            {
                'collection_family': item.get('nft_family') or item.get('type'),
                'serial': item.get('serial'),
                'serial_number': item.get('serial_number'),
                'name': item.get('name'),
                'type': item.get('type'),
                'rarity_key': item.get('rarity_key'),
                'emoji': item.get('emoji'),
                'source': item.get('source'),
                'draft_ready': bool(item.get('serial_number')),
            }
        )
    return items


def player_card_snapshot(wallet):
    player = ensure_player(wallet)
    profile = player_profile_row(wallet)
    rewards = reward_summary(wallet)
    analytics = derived_behavior_profile(wallet)
    equipped = rewards.get('equipped_cosmetics') or {}
    profile_banner_key = (profile or {}).get('profile_banner_key') or ((equipped.get('guild') or {}).get('key'))
    selected_gift = selected_profile_gift(wallet, profile=profile)
    return {
        'wallet': wallet,
        'display_name': display_name_for_wallet(wallet),
        'avatar': '',
        'bio': (profile or {}).get('bio') or '',
        'language': (profile or {}).get('language') or 'ru',
        'current_domain': player.get('current_domain'),
        'profile_title': (profile or {}).get('profile_title') or '',
        'favorite_ability': analytics.get('favorite_ability') or (profile or {}).get('favorite_ability') or '',
        'play_style': analytics.get('play_style') or (profile or {}).get('play_style') or '',
        'favorite_strategy': analytics.get('favorite_strategy') or (profile or {}).get('favorite_strategy') or '',
        'favorite_role': analytics.get('favorite_role') or (profile or {}).get('favorite_role') or '',
        'profile_banner_key': profile_banner_key,
        'rating': player.get('rating') or 1000,
        'games_played': player.get('games_played') or 0,
        'season_level': rewards.get('season_level') or 1,
        'equipped_cosmetics': equipped,
        'selected_gift': selected_gift,
        'analytics': analytics,
    }


def public_player_summary(wallet):
    return player_card_snapshot(wallet)


def recent_ranked_matches_for_wallet(wallet, limit=8):
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT domain, opponent_domain, result, rating_before, rating_after, player_score, opponent_score, created_at
            FROM ranked_matches
            WHERE wallet = ?
            ORDER BY datetime(created_at) DESC, rowid DESC
            LIMIT ?
            ''',
            (wallet, int(limit)),
        ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                'domain': row['domain'],
                'opponent_domain': row['opponent_domain'],
                'result': row['result'],
                'rating_before': row['rating_before'],
                'rating_after': row['rating_after'],
                'player_score': row['player_score'],
                'opponent_score': row['opponent_score'],
                'created_at': row['created_at'],
            }
        )
    return result


def public_player_profile(wallet, viewer_wallet=None):
    base = player_card_snapshot(wallet)
    player = ensure_player(wallet)
    rewards = reward_summary(wallet)
    guild_membership = current_guild_membership(wallet)
    favorite_domain = top_stat_key(((base.get('analytics') or {}).get('stats') or {}).get('domains') or {}, player.get('best_domain') or player.get('current_domain') or '')
    return {
        **base,
        'best_domain': player.get('best_domain'),
        'favorite_domain': favorite_domain,
        'ranked_wins': player.get('ranked_wins') or 0,
        'ranked_losses': player.get('ranked_losses') or 0,
        'deck_summary': deck_summary_for_domain(player.get('current_domain'), wallet) if player.get('current_domain') else None,
        'recent_matches': recent_ranked_matches_for_wallet(wallet, limit=8),
        'guild': {
            'id': guild_membership['guild_id'],
            'name': guild_membership['name'],
            'slug': guild_membership['slug'],
            'role': guild_membership['role'],
        } if guild_membership else None,
        'viewer_is_self': viewer_wallet == wallet,
        'available_profile_gifts': available_profile_gifts(wallet) if viewer_wallet == wallet else [],
        'nft_draft': cosmetic_nft_draft(wallet) if viewer_wallet == wallet else [],
    }


def blocked_wallets(owner_wallet):
    with closing(get_db()) as conn:
        rows = conn.execute('SELECT blocked_wallet FROM blocks WHERE owner_wallet = ?', (owner_wallet,)).fetchall()
    return {row['blocked_wallet'] for row in rows}


def ensure_not_blocked(wallet_a, wallet_b):
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT 1 FROM blocks
            WHERE (owner_wallet = ? AND blocked_wallet = ?)
               OR (owner_wallet = ? AND blocked_wallet = ?)
            LIMIT 1
            ''',
            (wallet_a, wallet_b, wallet_b, wallet_a),
        ).fetchone()
    if row is not None:
        raise ValueError('Действие недоступно: между игроками стоит блок.')


def player_last_seen(wallet):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT updated_at FROM players WHERE wallet = ?', (wallet,)).fetchone()
    return row['updated_at'] if row else None


def link_wallet_to_telegram(wallet, telegram_user_id):
    link = telegram_user_link(telegram_user_id)
    if link is None:
        raise ValueError('Сначала привяжи Telegram через сайт или внутри Telegram mini app.')
    with closing(get_db()) as conn:
        conn.execute(
            'UPDATE telegram_users SET wallet = NULL, updated_at = ? WHERE wallet = ? AND telegram_user_id != ?',
            (now_iso(), wallet, telegram_user_id),
        )
        conn.execute(
            'UPDATE telegram_users SET wallet = ?, updated_at = ?, linked_at = COALESCE(linked_at, ?) WHERE telegram_user_id = ?',
            (wallet, now_iso(), now_iso(), telegram_user_id),
        )
        conn.commit()
    ensure_telegram_notification_prefs(wallet)
    try:
        dispatch_wallet_telegram_notifications(wallet)
    except Exception:
        pass
    return telegram_user_link(telegram_user_id)


def validate_telegram_init_data(init_data):
    if not TG_BOT_TOKEN:
        raise ValueError('TG_BOT_TOKEN не настроен.')
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', None)
    auth_date = pairs.get('auth_date')
    if not received_hash or not auth_date:
        raise ValueError('Некорректные Telegram init data.')
    if now_utc().timestamp() - int(auth_date) > TELEGRAM_INITDATA_MAX_AGE:
        raise ValueError('Сессия Telegram устарела. Открой mini app заново.')

    data_check_string = '\n'.join(f'{key}={pairs[key]}' for key in sorted(pairs.keys()))
    secret_key = hmac.new(b'WebAppData', TG_BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError('Не удалось подтвердить Telegram-сессию.')
    if 'user' in pairs:
        pairs['user'] = json.loads(pairs['user'])
    return pairs


def validate_telegram_login_data(payload):
    if not TG_BOT_TOKEN:
        raise ValueError('TG_BOT_TOKEN не настроен.')
    if not isinstance(payload, dict):
        raise ValueError('Некорректные Telegram-данные.')
    normalized = {}
    for key, value in payload.items():
        if value is None:
            continue
        normalized[str(key)] = str(value)
    received_hash = normalized.pop('hash', None)
    auth_date = normalized.get('auth_date')
    telegram_user_id = normalized.get('id')
    if not received_hash or not auth_date or not telegram_user_id:
        raise ValueError('Некорректные Telegram login data.')
    if now_utc().timestamp() - int(auth_date) > TELEGRAM_INITDATA_MAX_AGE:
        raise ValueError('Сессия Telegram устарела. Повтори вход через Telegram.')
    data_check_string = '\n'.join(f'{key}={normalized[key]}' for key in sorted(normalized.keys()))
    secret_key = hashlib.sha256(TG_BOT_TOKEN.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError('Не удалось подтвердить Telegram-login.')
    return {
        'id': int(telegram_user_id),
        'first_name': normalized.get('first_name') or '',
        'last_name': normalized.get('last_name') or '',
        'username': normalized.get('username') or '',
        'photo_url': normalized.get('photo_url') or '',
        'auth_date': int(auth_date),
    }


def resolve_player_reference(reference):
    ref = (reference or '').strip()
    if not ref:
        raise ValueError('Укажи ник или .ton домен соперника.')

    if valid_wallet_address(ref):
        with closing(get_db()) as conn:
            row = conn.execute(
                'SELECT wallet FROM players WHERE wallet = ? LIMIT 1',
                (ref,),
            ).fetchone()
        if row is not None:
            return row['wallet']
        raise ValueError('Игрок с таким кошельком ещё не найден. Пусть он сначала зайдёт в игру.')

    domain = normalize_strict_ton_domain(ref)
    username_ref = clean_public_text(ref.lstrip('@'), 64)
    with closing(get_db()) as conn:
        if domain:
            row = conn.execute(
                '''
                SELECT wallet FROM players
                WHERE current_domain = ? OR best_domain = ?
                ORDER BY updated_at DESC
                LIMIT 1
                ''',
                (domain, domain),
            ).fetchone()
            if row is not None:
                return row['wallet']
        else:
            nickname = clean_public_text(ref, 24)
            if not nickname:
                raise ValueError('Поле соперника принимает только ник или 4-значный домен вида 1234.ton.')
            row = conn.execute(
                '''
                SELECT wallet FROM player_profiles
                WHERE lower(nickname) = lower(?)
                ORDER BY updated_at DESC
                LIMIT 1
                ''',
                (nickname,),
            ).fetchone()
            if row is not None:
                return row['wallet']
            if username_ref:
                row = conn.execute(
                    '''
                    SELECT wallet FROM telegram_users
                    WHERE lower(username) = lower(?) AND wallet IS NOT NULL
                    ORDER BY updated_at DESC
                    LIMIT 1
                    ''',
                    (username_ref,),
                ).fetchone()
                if row is not None:
                    return row['wallet']

    if domain:
        raise ValueError('Игрок с таким доменом ещё не найден. Пусть он сначала зайдёт в игру и выберет домен.')
    raise ValueError('Игрок не найден. Проверь ник/@username/домен или попроси соперника сначала зайти в игру.')


def active_users():
    cutoff = datetime.fromtimestamp(now_utc().timestamp() - ACTIVE_USER_WINDOW_SECONDS, tz=timezone.utc).isoformat()
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT p.wallet, p.rating, p.current_domain, p.updated_at,
                   t.username, t.first_name
            FROM players p
            LEFT JOIN telegram_users t ON t.wallet = p.wallet
            WHERE p.current_domain IS NOT NULL AND p.updated_at >= ?
            ORDER BY p.updated_at DESC
            ''',
            (cutoff,),
        ).fetchall()
    result = []
    for row in rows:
        summary = deck_summary_for_domain(row['current_domain'], row['wallet'])
        result.append(
            {
                **public_player_summary(row['wallet']),
                'domain': row['current_domain'],
                'average_attack': summary['average_attack'],
                'average_defense': summary['average_defense'],
                'total_score': summary['total_score'],
                'updated_at': row['updated_at'],
            }
        )
    return result


def friend_rows(owner_wallet):
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT f.friend_wallet AS wallet, p.current_domain, p.rating, p.updated_at,
                   t.username, t.first_name
            FROM friends f
            LEFT JOIN players p ON p.wallet = f.friend_wallet
            LEFT JOIN telegram_users t ON t.wallet = f.friend_wallet
            WHERE f.owner_wallet = ?
            ORDER BY f.created_at DESC
            ''',
            (owner_wallet,),
        ).fetchall()
    result = []
    for row in rows:
        summary = deck_summary_for_domain(row['current_domain'], row['wallet']) if row['current_domain'] else None
        item = public_player_summary(row['wallet'])
        item.update(
            {
                'display_name': row['username'] or row['first_name'] or item['display_name'],
                'domain': row['current_domain'],
                'average_attack': summary['average_attack'] if summary else None,
                'average_defense': summary['average_defense'] if summary else None,
            }
        )
        result.append(item)
    return result


def add_friend(owner_wallet, friend_reference):
    friend_wallet = resolve_player_reference(friend_reference)
    if friend_wallet == owner_wallet:
        raise ValueError('Себя в друзья добавлять не нужно.')
    ensure_not_blocked(owner_wallet, friend_wallet)
    ensure_player(friend_wallet)
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT OR IGNORE INTO friends (owner_wallet, friend_wallet, created_at) VALUES (?, ?, ?)',
            (owner_wallet, friend_wallet, now_iso()),
        )
        conn.commit()
    return friend_wallet


def remove_friend(owner_wallet, friend_reference):
    friend_wallet = resolve_player_reference(friend_reference)
    with closing(get_db()) as conn:
        conn.execute('DELETE FROM friends WHERE owner_wallet = ? AND friend_wallet = ?', (owner_wallet, friend_wallet))
        conn.execute('DELETE FROM friends WHERE owner_wallet = ? AND friend_wallet = ?', (friend_wallet, owner_wallet))
        conn.commit()
    return friend_wallet


def send_friend_request(sender_wallet, receiver_reference):
    receiver_wallet = resolve_player_reference(receiver_reference)
    if receiver_wallet == sender_wallet:
        raise ValueError('Себя добавлять не нужно.')
    ensure_not_blocked(sender_wallet, receiver_wallet)
    if receiver_wallet in {item['wallet'] for item in friend_rows(sender_wallet)}:
        raise ValueError('Этот игрок уже в друзьях.')
    with closing(get_db()) as conn:
        reverse = conn.execute(
            '''
            SELECT * FROM friend_requests
            WHERE sender_wallet = ? AND receiver_wallet = ? AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
            ''',
            (receiver_wallet, sender_wallet),
        ).fetchone()
        if reverse is not None:
            request_id = reverse['id']
            conn.execute('UPDATE friend_requests SET status = ?, responded_at = ? WHERE id = ?', ('accepted', now_iso(), request_id))
            conn.execute('INSERT OR IGNORE INTO friends (owner_wallet, friend_wallet, created_at) VALUES (?, ?, ?)', (sender_wallet, receiver_wallet, now_iso()))
            conn.execute('INSERT OR IGNORE INTO friends (owner_wallet, friend_wallet, created_at) VALUES (?, ?, ?)', (receiver_wallet, sender_wallet, now_iso()))
            conn.commit()
            return receiver_wallet
        existing = conn.execute(
            '''
            SELECT 1 FROM friend_requests
            WHERE sender_wallet = ? AND receiver_wallet = ? AND status = 'pending'
            LIMIT 1
            ''',
            (sender_wallet, receiver_wallet),
        ).fetchone()
        if existing is not None:
            raise ValueError('Заявка уже отправлена.')
        conn.execute(
            '''
            INSERT INTO friend_requests (id, sender_wallet, receiver_wallet, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            ''',
            (uuid.uuid4().hex[:12], sender_wallet, receiver_wallet, now_iso()),
        )
        conn.commit()
    return receiver_wallet


def friend_request_rows(wallet, direction='incoming'):
    if direction == 'incoming':
        where = 'receiver_wallet = ?'
        wallet_key = 'sender_wallet'
    else:
        where = 'sender_wallet = ?'
        wallet_key = 'receiver_wallet'
    with closing(get_db()) as conn:
        rows = conn.execute(
            f'''
            SELECT id, sender_wallet, receiver_wallet, status, created_at, responded_at
            FROM friend_requests
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT 30
            ''',
            (wallet,),
        ).fetchall()
    result = []
    for row in rows:
        other_wallet = row[wallet_key]
        result.append(
            {
                **public_player_summary(other_wallet),
                'id': row['id'],
                'status': row['status'],
                'created_at': row['created_at'],
                'domain': ensure_player(other_wallet).get('current_domain'),
            }
        )
    return result


def respond_friend_request(receiver_wallet, request_id, action):
    decision = 'accepted' if action == 'accept' else 'declined'
    with closing(get_db()) as conn:
        row = conn.execute(
            'SELECT * FROM friend_requests WHERE id = ? AND receiver_wallet = ? AND status = ?',
            (request_id, receiver_wallet, 'pending'),
        ).fetchone()
        if row is None:
            raise ValueError('Заявка не найдена или уже обработана.')
        sender_wallet = row['sender_wallet']
        ensure_not_blocked(receiver_wallet, sender_wallet)
        conn.execute(
            'UPDATE friend_requests SET status = ?, responded_at = ? WHERE id = ?',
            (decision, now_iso(), request_id),
        )
        if decision == 'accepted':
            conn.execute('INSERT OR IGNORE INTO friends (owner_wallet, friend_wallet, created_at) VALUES (?, ?, ?)', (receiver_wallet, sender_wallet, now_iso()))
            conn.execute('INSERT OR IGNORE INTO friends (owner_wallet, friend_wallet, created_at) VALUES (?, ?, ?)', (sender_wallet, receiver_wallet, now_iso()))
        conn.commit()
    return sender_wallet


def block_player(owner_wallet, target_reference):
    target_wallet = resolve_player_reference(target_reference)
    if target_wallet == owner_wallet:
        raise ValueError('Себя блокировать не нужно.')
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT OR IGNORE INTO blocks (owner_wallet, blocked_wallet, created_at) VALUES (?, ?, ?)',
            (owner_wallet, target_wallet, now_iso()),
        )
        conn.execute('DELETE FROM friends WHERE owner_wallet = ? AND friend_wallet = ?', (owner_wallet, target_wallet))
        conn.execute('DELETE FROM friends WHERE owner_wallet = ? AND friend_wallet = ?', (target_wallet, owner_wallet))
        conn.execute(
            '''
            UPDATE friend_requests
            SET status = 'blocked', responded_at = ?
            WHERE status = 'pending' AND (
                (sender_wallet = ? AND receiver_wallet = ?)
                OR (sender_wallet = ? AND receiver_wallet = ?)
            )
            ''',
            (now_iso(), owner_wallet, target_wallet, target_wallet, owner_wallet),
        )
        conn.commit()
    return target_wallet


def unblock_player(owner_wallet, target_reference):
    target_wallet = resolve_player_reference(target_reference)
    with closing(get_db()) as conn:
        conn.execute('DELETE FROM blocks WHERE owner_wallet = ? AND blocked_wallet = ?', (owner_wallet, target_wallet))
        conn.commit()
    return target_wallet


def create_player_report(reporter_wallet, target_reference, scope, reason=''):
    target_wallet = resolve_player_reference(target_reference)
    if target_wallet == reporter_wallet:
        raise ValueError('Нельзя отправить жалобу на себя.')
    scope_value = str(scope or 'general').strip().lower()[:32] or 'general'
    reason_value = clean_public_text(reason or 'Проверить поведение игрока', 240)
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT INTO reports (id, reporter_wallet, target_wallet, scope, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (uuid.uuid4().hex[:12], reporter_wallet, target_wallet, scope_value, reason_value, now_iso()),
        )
        conn.commit()
    return target_wallet


def social_suggestions(wallet, limit=8):
    friend_wallets = {item['wallet'] for item in friend_rows(wallet)}
    blocked = blocked_wallets(wallet)
    candidates = []
    seen = set()
    for row in active_users():
        other_wallet = row['wallet']
        if other_wallet == wallet or other_wallet in friend_wallets or other_wallet in blocked or other_wallet in seen:
            continue
        seen.add(other_wallet)
        candidates.append(public_player_summary(other_wallet))
        if len(candidates) >= limit:
            return candidates
    for row in global_player_rows(limit=40):
        other_wallet = row['wallet']
        if other_wallet == wallet or other_wallet in friend_wallets or other_wallet in blocked or other_wallet in seen:
            continue
        seen.add(other_wallet)
        candidates.append(public_player_summary(other_wallet))
        if len(candidates) >= limit:
            break
    return candidates


def lobby_messages(limit=30):
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT * FROM lobby_messages ORDER BY created_at DESC LIMIT ?',
            (limit,),
        ).fetchall()
    messages = []
    for row in reversed(rows):
        messages.append(
            {
                'id': row['id'],
                'wallet': row['wallet'],
                'display_name': display_name_for_wallet(row['wallet']),
                'avatar': avatar_for_wallet(row['wallet']),
                'message': row['message'],
                'created_at': row['created_at'],
            }
        )
    return messages


def post_lobby_message(wallet, message):
    text = clean_public_text(message, 240)
    if len(text) < 2:
        raise ValueError('Сообщение слишком короткое.')
    ensure_player(wallet)
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT INTO lobby_messages (id, wallet, message, created_at) VALUES (?, ?, ?, ?)',
            (uuid.uuid4().hex[:12], wallet, text, now_iso()),
        )
        conn.commit()
    return lobby_messages()


def guild_role_rank(role):
    return {'member': 1, 'officer': 2, 'owner': 3}.get(role, 0)


def current_guild_membership(wallet):
    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT gm.guild_id, gm.role, gm.joined_at, g.name, g.slug, g.owner_wallet, g.domain_identity, g.description, g.language, g.is_public, g.created_at, g.updated_at
            FROM guild_members gm
            JOIN guilds g ON g.id = gm.guild_id
            WHERE gm.wallet = ?
            LIMIT 1
            ''',
            (wallet,),
        ).fetchone()
    return dict(row) if row else None


def guild_member_count(guild_id):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT COUNT(*) AS value FROM guild_members WHERE guild_id = ?', (guild_id,)).fetchone()
    return row['value'] if row else 0


def guild_members_rows(guild_id):
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT gm.wallet, gm.role, gm.joined_at, p.current_domain, p.rating
            FROM guild_members gm
            LEFT JOIN players p ON p.wallet = gm.wallet
            WHERE gm.guild_id = ?
            ORDER BY CASE gm.role WHEN 'owner' THEN 1 WHEN 'officer' THEN 2 ELSE 3 END, gm.joined_at ASC
            ''',
            (guild_id,),
        ).fetchall()
    return [
        {
            **public_player_summary(row['wallet']),
            'role': row['role'],
            'joined_at': row['joined_at'],
            'domain': row['current_domain'],
            'rating': row['rating'],
        }
        for row in rows
    ]


def guild_goal_summary(guild_id):
    members = guild_members_rows(guild_id)
    wallets = [item['wallet'] for item in members]
    if not wallets:
        return {
            'weekly_wins': 0,
            'weekly_win_target': 25,
            'weekly_packs': 0,
            'weekly_pack_target': 12,
            'season_points': 0,
            'season_rank_score': 0,
            'war_score': 0,
            'war_target': 140,
            'weekly_reward_ready': False,
            'weekly_quests': [],
            'today_help': [],
        }
    seven_days_ago = datetime.fromtimestamp(now_utc().timestamp() - 7 * 86400, tz=timezone.utc).isoformat()
    placeholders = ','.join('?' for _ in wallets)
    with closing(get_db()) as conn:
        ranked = conn.execute(
            f'''
            SELECT COUNT(*) AS value
            FROM ranked_matches
            WHERE wallet IN ({placeholders}) AND result = 'win' AND created_at >= ?
            ''',
            (*wallets, seven_days_ago),
        ).fetchone()['value']
        telemetry = conn.execute(
            f'''
            SELECT COUNT(*) AS value
            FROM domain_telemetry
            WHERE wallet IN ({placeholders})
              AND created_at >= ?
              AND event_type LIKE '%battle_complete'
              AND payload_json LIKE '%"result": "win"%'
            ''',
            (*wallets, seven_days_ago),
        ).fetchone()['value']
        pack_count = conn.execute(
            f'''
            SELECT COUNT(*) AS value
            FROM pack_opens
            WHERE wallet IN ({placeholders}) AND created_at >= ?
            ''',
            (*wallets, seven_days_ago),
        ).fetchone()['value']
        season_points = conn.execute(
            f'''
            SELECT COALESCE(SUM(season_points), 0) AS value
            FROM player_rewards
            WHERE wallet IN ({placeholders})
            ''',
            wallets,
        ).fetchone()['value']
    weekly_wins = int(ranked or 0) + int(telemetry or 0)
    weekly_pack_target = max(12, len(wallets) * 3)
    weekly_win_target = max(25, len(wallets) * 6)
    war_score = weekly_wins * 4 + int(pack_count or 0) * 3 + int(season_points or 0)
    war_target = max(140, len(wallets) * 45)
    weekly_reward_ready = weekly_wins >= weekly_win_target or int(pack_count or 0) >= weekly_pack_target or war_score >= war_target
    raid_target = max(18, len(wallets) * 4)
    pressure_target = max(8, len(wallets) * 2)
    weekly_quests = [
        {'label': 'Победы недели', 'progress': weekly_wins, 'target': weekly_win_target, 'reward': 'осколки +5'},
        {'label': 'Сундук гильдии', 'progress': int(pack_count or 0), 'target': weekly_pack_target, 'reward': 'редкий токен +1'},
        {'label': 'Война недели', 'progress': war_score, 'target': war_target, 'reward': 'lucky +1 • баннер недели'},
        {'label': 'Рейд клана', 'progress': min(weekly_wins + int(pack_count or 0), raid_target), 'target': raid_target, 'reward': 'след клана'},
        {'label': 'Контроль сезона', 'progress': min(int(season_points or 0), pressure_target * 10), 'target': pressure_target * 10, 'reward': 'сезонные очки +10'},
    ]
    today_help = [
        f'Добейте {max(0, weekly_win_target - weekly_wins)} побед до недельной цели',
        f'Откройте ещё {max(0, weekly_pack_target - pack_count)} паков до сундука гильдии',
        f'Поднимите счёт войны недели до {war_target}',
        f'Закройте рейд клана: {max(0, raid_target - (weekly_wins + int(pack_count or 0)))} шагов',
    ]
    return {
        'weekly_wins': weekly_wins,
        'weekly_win_target': weekly_win_target,
        'weekly_packs': int(pack_count or 0),
        'weekly_pack_target': weekly_pack_target,
        'season_points': int(season_points or 0),
        'season_rank_score': int(season_points or 0) + weekly_wins * 5 + int(pack_count or 0) * 2,
        'war_score': war_score,
        'war_target': war_target,
        'weekly_reward_ready': weekly_reward_ready,
        'weekly_quests': weekly_quests,
        'today_help': today_help,
    }


def guild_messages_rows(guild_id, limit=30):
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT * FROM guild_messages WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?',
            (guild_id, limit),
        ).fetchall()
    return [
        {
            **public_player_summary(row['wallet']),
            'id': row['id'],
            'message': row['message'],
            'created_at': row['created_at'],
        }
        for row in reversed(rows)
    ]


def guild_announcements_rows(guild_id, limit=8):
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT * FROM guild_announcements WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?',
            (guild_id, limit),
        ).fetchall()
    return [
        {
            **public_player_summary(row['wallet']),
            'id': row['id'],
            'message': row['message'],
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def guild_requests_rows(guild_id, status='pending'):
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT * FROM guild_join_requests WHERE guild_id = ? AND status = ? ORDER BY created_at DESC',
            (guild_id, status),
        ).fetchall()
    return [
        {
            **public_player_summary(row['wallet']),
            'id': row['id'],
            'message': row['message'] or '',
            'created_at': row['created_at'],
            'domain': ensure_player(row['wallet']).get('current_domain'),
        }
        for row in rows
    ]


def guild_invites_for_wallet(wallet, status='pending'):
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT gi.*, g.name, g.slug
            FROM guild_invites gi
            JOIN guilds g ON g.id = gi.guild_id
            WHERE gi.invitee_wallet = ? AND gi.status = ?
            ORDER BY gi.created_at DESC
            ''',
            (wallet, status),
        ).fetchall()
    return [
        {
            'id': row['id'],
            'guild_id': row['guild_id'],
            'guild_name': row['name'],
            'guild_slug': row['slug'],
            'inviter_wallet': row['inviter_wallet'],
            'inviter_name': display_name_for_wallet(row['inviter_wallet']),
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def guild_applications_for_wallet(wallet, status='pending'):
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT gjr.*, g.name, g.slug
            FROM guild_join_requests gjr
            JOIN guilds g ON g.id = gjr.guild_id
            WHERE gjr.wallet = ? AND gjr.status = ?
            ORDER BY gjr.created_at DESC
            ''',
            (wallet, status),
        ).fetchall()
    return [
        {
            'id': row['id'],
            'guild_id': row['guild_id'],
            'guild_name': row['name'],
            'guild_slug': row['slug'],
            'message': row['message'] or '',
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def guild_summary_by_id(guild_id, viewer_wallet=None):
    with closing(get_db()) as conn:
        guild = conn.execute('SELECT * FROM guilds WHERE id = ?', (guild_id,)).fetchone()
    if guild is None:
        raise ValueError('Клан не найден.')
    guild = dict(guild)
    members = guild_members_rows(guild_id)
    goals = guild_goal_summary(guild_id)
    viewer_role = None
    if viewer_wallet:
        for item in members:
            if item['wallet'] == viewer_wallet:
                viewer_role = item['role']
                break
    data = {
        'id': guild['id'],
        'slug': guild['slug'],
        'name': guild['name'],
        'owner_wallet': guild['owner_wallet'],
        'owner_name': display_name_for_wallet(guild['owner_wallet']),
        'domain_identity': guild['domain_identity'],
        'description': guild.get('description') or '',
        'language': guild.get('language') or 'ru',
        'is_public': bool(guild.get('is_public')),
        'created_at': guild['created_at'],
        'updated_at': guild['updated_at'],
        'member_count': len(members),
        'members': members,
        'goals': goals,
        'chat': guild_messages_rows(guild_id),
        'announcements': guild_announcements_rows(guild_id),
        'viewer_role': viewer_role,
    }
    if viewer_role and guild_role_rank(viewer_role) >= guild_role_rank('officer'):
        data['pending_requests'] = guild_requests_rows(guild_id)
    return data


def recommended_guilds(limit=6):
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT g.*,
                   COUNT(gm.wallet) AS member_count
            FROM guilds g
            LEFT JOIN guild_members gm ON gm.guild_id = g.id
            WHERE g.is_public = 1
            GROUP BY g.id
            ORDER BY member_count DESC, g.updated_at DESC
            LIMIT ?
            ''',
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        summary = guild_goal_summary(row['id'])
        result.append(
            {
                'id': row['id'],
                'name': row['name'],
                'slug': row['slug'],
                'domain_identity': row['domain_identity'],
                'description': row['description'] or '',
                'language': row['language'] or 'ru',
                'member_count': row['member_count'],
                'weekly_wins': summary['weekly_wins'],
                'season_points': summary['season_points'],
            }
        )
    return result


def browse_guilds(query=''):
    text = clean_public_text(query, 48)
    with closing(get_db()) as conn:
        if text:
            pattern = f'%{text.lower()}%'
            rows = conn.execute(
                '''
                SELECT g.*, COUNT(gm.wallet) AS member_count
                FROM guilds g
                LEFT JOIN guild_members gm ON gm.guild_id = g.id
                WHERE g.is_public = 1 AND (LOWER(g.name) LIKE ? OR LOWER(COALESCE(g.description, '')) LIKE ? OR LOWER(COALESCE(g.language, '')) LIKE ?)
                GROUP BY g.id
                ORDER BY member_count DESC, g.updated_at DESC
                LIMIT 20
                ''',
                (pattern, pattern, pattern),
            ).fetchall()
        else:
            rows = conn.execute(
                '''
                SELECT g.*, COUNT(gm.wallet) AS member_count
                FROM guilds g
                LEFT JOIN guild_members gm ON gm.guild_id = g.id
                WHERE g.is_public = 1
                GROUP BY g.id
                ORDER BY member_count DESC, g.updated_at DESC
                LIMIT 20
                '''
            ).fetchall()
    return [
        {
            'id': row['id'],
            'name': row['name'],
            'slug': row['slug'],
            'domain_identity': row['domain_identity'],
            'description': row['description'] or '',
            'language': row['language'] or 'ru',
            'member_count': row['member_count'],
        }
        for row in rows
    ]


def create_guild(owner_wallet, name, description='', language='ru', is_public=True):
    if current_guild_membership(owner_wallet):
        raise ValueError('Ты уже состоишь в клане.')
    player = ensure_player(owner_wallet)
    guild_name = clean_public_text(name, 40)
    if len(guild_name) < 3:
        raise ValueError('Название клана слишком короткое.')
    guild_id = uuid.uuid4().hex[:12]
    ts = now_iso()
    slug = safe_slug(guild_name)
    with closing(get_db()) as conn:
        slug_taken = conn.execute('SELECT 1 FROM guilds WHERE slug = ? LIMIT 1', (slug,)).fetchone()
        if slug_taken is not None:
            slug = f'{slug}-{guild_id[:4]}'
        conn.execute(
            '''
            INSERT INTO guilds (id, slug, name, owner_wallet, domain_identity, description, language, is_public, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                guild_id,
                slug,
                guild_name,
                owner_wallet,
                player.get('current_domain'),
                clean_public_text(description, 220),
                clean_public_text(language, 12) or 'ru',
                1 if is_public else 0,
                ts,
                ts,
            ),
        )
        conn.execute(
            'INSERT INTO guild_members (guild_id, wallet, role, joined_at) VALUES (?, ?, ?, ?)',
            (guild_id, owner_wallet, 'owner', ts),
        )
        conn.execute(
            'INSERT INTO guild_announcements (id, guild_id, wallet, message, created_at) VALUES (?, ?, ?, ?, ?)',
            (uuid.uuid4().hex[:12], guild_id, owner_wallet, 'Клан создан. Откройте цели недели и начинайте сезон.', ts),
        )
        conn.commit()
    return guild_summary_by_id(guild_id, owner_wallet)


def apply_to_guild(wallet, guild_id, message=''):
    if current_guild_membership(wallet):
        raise ValueError('Сначала выйди из текущего клана.')
    with closing(get_db()) as conn:
        guild = conn.execute('SELECT * FROM guilds WHERE id = ? AND is_public = 1', (guild_id,)).fetchone()
        if guild is None:
            raise ValueError('Клан не найден или закрыт.')
        existing = conn.execute(
            'SELECT 1 FROM guild_join_requests WHERE guild_id = ? AND wallet = ? AND status = ? LIMIT 1',
            (guild_id, wallet, 'pending'),
        ).fetchone()
        if existing is not None:
            raise ValueError('Заявка уже отправлена.')
        conn.execute(
            '''
            INSERT INTO guild_join_requests (id, guild_id, wallet, message, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            ''',
            (uuid.uuid4().hex[:12], guild_id, wallet, clean_public_text(message, 180), now_iso()),
        )
        conn.commit()
    return guild_summary_by_id(guild_id, wallet)


def respond_to_guild_request(actor_wallet, request_id, action):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM guild_join_requests WHERE id = ? AND status = ?', (request_id, 'pending')).fetchone()
        if row is None:
            raise ValueError('Заявка не найдена.')
        membership = current_guild_membership(actor_wallet)
        if membership is None or membership['guild_id'] != row['guild_id']:
            raise ValueError('Нет доступа к этому клану.')
        if guild_role_rank(membership['role']) < guild_role_rank('officer'):
            raise ValueError('Нужна роль офицера или владельца.')
        decision = 'accepted' if action == 'accept' else 'declined'
        conn.execute(
            'UPDATE guild_join_requests SET status = ?, responded_at = ? WHERE id = ?',
            (decision, now_iso(), request_id),
        )
        if decision == 'accepted':
            if current_guild_membership(row['wallet']):
                raise ValueError('Игрок уже вступил в другой клан.')
            conn.execute(
                'INSERT OR IGNORE INTO guild_members (guild_id, wallet, role, joined_at) VALUES (?, ?, ?, ?)',
                (row['guild_id'], row['wallet'], 'member', now_iso()),
            )
        conn.commit()
    return guild_summary_by_id(row['guild_id'], actor_wallet)


def invite_to_guild(inviter_wallet, guild_id, invitee_reference):
    invitee_wallet = resolve_player_reference(invitee_reference)
    if invitee_wallet == inviter_wallet:
        raise ValueError('Себя приглашать не нужно.')
    membership = current_guild_membership(inviter_wallet)
    if membership is None or membership['guild_id'] != guild_id:
        raise ValueError('Ты не состоишь в этом клане.')
    if guild_role_rank(membership['role']) < guild_role_rank('officer'):
        raise ValueError('Инвайтить могут только офицеры и владелец.')
    ensure_not_blocked(inviter_wallet, invitee_wallet)
    if current_guild_membership(invitee_wallet):
        raise ValueError('Игрок уже состоит в клане.')
    invite_id = uuid.uuid4().hex[:12]
    with closing(get_db()) as conn:
        existing = conn.execute(
            '''
            SELECT 1 FROM guild_invites
            WHERE guild_id = ? AND invitee_wallet = ? AND status = 'pending'
            LIMIT 1
            ''',
            (guild_id, invitee_wallet),
        ).fetchone()
        if existing is not None:
            raise ValueError('Приглашение уже отправлено.')
        conn.execute(
            '''
            INSERT INTO guild_invites (id, guild_id, inviter_wallet, invitee_wallet, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            ''',
            (invite_id, guild_id, inviter_wallet, invitee_wallet, now_iso()),
        )
        conn.commit()
    prefs = ensure_telegram_notification_prefs(invitee_wallet)
    if int(prefs.get('notify_guild_invites', 1) or 0):
        guild = guild_summary_by_id(guild_id, inviter_wallet)
        telegram_notify_wallet(
            invitee_wallet,
            f'Приглашение в клан.\nКлан: {guild["name"]}\nПригласил: {display_name_for_wallet(inviter_wallet)}\nОткрой профиль → кланы, чтобы принять или отклонить.',
        )
    return guild_summary_by_id(guild_id, inviter_wallet)


def respond_to_guild_invite(wallet, invite_id, action):
    with closing(get_db()) as conn:
        row = conn.execute(
            'SELECT * FROM guild_invites WHERE id = ? AND invitee_wallet = ? AND status = ?',
            (invite_id, wallet, 'pending'),
        ).fetchone()
        if row is None:
            raise ValueError('Инвайт не найден.')
        if current_guild_membership(wallet):
            raise ValueError('Сначала выйди из текущего клана.')
        decision = 'accepted' if action == 'accept' else 'declined'
        conn.execute(
            'UPDATE guild_invites SET status = ?, responded_at = ? WHERE id = ?',
            (decision, now_iso(), invite_id),
        )
        if decision == 'accepted':
            conn.execute(
                'INSERT OR IGNORE INTO guild_members (guild_id, wallet, role, joined_at) VALUES (?, ?, ?, ?)',
                (row['guild_id'], wallet, 'member', now_iso()),
            )
        conn.commit()
    return guild_summary_by_id(row['guild_id'], wallet)


def post_guild_message(wallet, guild_id, message):
    membership = current_guild_membership(wallet)
    if membership is None or membership['guild_id'] != guild_id:
        raise ValueError('Ты не состоишь в этом клане.')
    text = clean_public_text(message, 240)
    if len(text) < 2:
        raise ValueError('Сообщение слишком короткое.')
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT INTO guild_messages (id, guild_id, wallet, message, created_at) VALUES (?, ?, ?, ?, ?)',
            (uuid.uuid4().hex[:12], guild_id, wallet, text, now_iso()),
        )
        conn.execute('UPDATE guilds SET updated_at = ? WHERE id = ?', (now_iso(), guild_id))
        conn.commit()
    return guild_messages_rows(guild_id)


def post_guild_announcement(wallet, guild_id, message):
    membership = current_guild_membership(wallet)
    if membership is None or membership['guild_id'] != guild_id:
        raise ValueError('Ты не состоишь в этом клане.')
    if guild_role_rank(membership['role']) < guild_role_rank('officer'):
        raise ValueError('Нужна роль офицера или владельца.')
    text = clean_public_text(message, 220)
    if len(text) < 4:
        raise ValueError('Объявление слишком короткое.')
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT INTO guild_announcements (id, guild_id, wallet, message, created_at) VALUES (?, ?, ?, ?, ?)',
            (uuid.uuid4().hex[:12], guild_id, wallet, text, now_iso()),
        )
        conn.execute('UPDATE guilds SET updated_at = ? WHERE id = ?', (now_iso(), guild_id))
        conn.commit()
    return guild_announcements_rows(guild_id)


def update_guild_member_role(actor_wallet, guild_id, target_wallet, role):
    role = clean_public_text(role, 16).lower()
    if role not in {'member', 'officer'}:
        raise ValueError('Можно назначить только member или officer.')
    membership = current_guild_membership(actor_wallet)
    if membership is None or membership['guild_id'] != guild_id or membership['role'] != 'owner':
        raise ValueError('Только владелец может менять роли.')
    with closing(get_db()) as conn:
        row = conn.execute('SELECT wallet FROM guild_members WHERE guild_id = ? AND wallet = ?', (guild_id, target_wallet)).fetchone()
        if row is None:
            raise ValueError('Участник не найден.')
        conn.execute('UPDATE guild_members SET role = ? WHERE guild_id = ? AND wallet = ?', (role, guild_id, target_wallet))
        conn.commit()
    return guild_summary_by_id(guild_id, actor_wallet)


def guild_overview_for_wallet(wallet, query=''):
    membership = current_guild_membership(wallet)
    return {
        'current_guild': guild_summary_by_id(membership['guild_id'], wallet) if membership else None,
        'recommended_guilds': recommended_guilds(),
        'browse_guilds': browse_guilds(query),
        'pending_invites': guild_invites_for_wallet(wallet),
        'pending_applications': guild_applications_for_wallet(wallet),
    }


def duel_invites_for_wallet(wallet, direction='incoming', status='pending'):
    if direction not in {'incoming', 'outgoing'}:
        return []
    where_field = 'invitee_wallet' if direction == 'incoming' else 'inviter_wallet'
    with closing(get_db()) as conn:
        rows = conn.execute(
            f'''
            SELECT *
            FROM duel_invites
            WHERE {where_field} = ? AND status = ?
            ORDER BY created_at DESC
            LIMIT 30
            ''',
            (wallet, status),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['result_json'] = json.loads(item['result_json']) if item.get('result_json') else None
        item = expire_invite_if_needed(item)
        if item['status'] != status:
            continue
        item['inviter_name'] = display_name_for_wallet(item['inviter_wallet'])
        item['invitee_name'] = display_name_for_wallet(item['invitee_wallet'])
        result.append(item)
    return result


def social_overview(wallet):
    ensure_player(wallet)
    profile = player_profile_row(wallet)
    friend_list = friend_rows(wallet)
    rewards = reward_summary(wallet)
    analytics = derived_behavior_profile(wallet)
    equipped = rewards.get('equipped_cosmetics') or {}
    profile_banner_key = (profile or {}).get('profile_banner_key') or ((equipped.get('guild') or {}).get('key'))
    return {
        'profile': {
            'wallet': wallet,
            'display_name': display_name_for_wallet(wallet),
            'nickname': (profile or {}).get('nickname') or '',
            'avatar': '',
            'bio': (profile or {}).get('bio') or '',
            'language': (profile or {}).get('language') or 'ru',
            'visibility': (profile or {}).get('visibility') or 'public',
            'domain': ensure_player(wallet).get('current_domain'),
            'profile_title': (profile or {}).get('profile_title') or '',
            'favorite_ability': analytics.get('favorite_ability') or (profile or {}).get('favorite_ability') or '',
            'play_style': analytics.get('play_style') or (profile or {}).get('play_style') or '',
            'favorite_strategy': analytics.get('favorite_strategy') or (profile or {}).get('favorite_strategy') or '',
            'favorite_role': analytics.get('favorite_role') or (profile or {}).get('favorite_role') or '',
            'profile_banner_key': profile_banner_key,
            'equipped_cosmetics': equipped,
            'selected_gift': selected_profile_gift(wallet, profile=profile),
            'available_profile_gifts': available_profile_gifts(wallet),
            'analytics': analytics,
        },
        'friends': friend_list,
        'incoming_requests': friend_request_rows(wallet, 'incoming'),
        'outgoing_requests': friend_request_rows(wallet, 'outgoing'),
        'blocked': [public_player_summary(item) for item in blocked_wallets(wallet)],
        'suggested_players': social_suggestions(wallet),
        'lobby_messages': lobby_messages(),
        'incoming_duel_invites': duel_invites_for_wallet(wallet, 'incoming', 'pending'),
        'outgoing_duel_invites': duel_invites_for_wallet(wallet, 'outgoing', 'pending'),
        'friend_count': len(friend_list),
        'telegram_notifications': telegram_notification_settings(wallet),
    }


def ensure_player(wallet, best_domain=None, current_domain=None):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM players WHERE wallet = ?', (wallet,)).fetchone()
        if row is None:
            ts = now_iso()
            conn.execute(
                '''
                INSERT INTO players (wallet, rating, games_played, ranked_wins, ranked_losses, best_domain, current_domain, first_seen, updated_at)
                VALUES (?, ?, 0, 0, 0, ?, ?, ?, ?)
                ''',
                (wallet, BASE_RATING, best_domain, current_domain, ts, ts),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM players WHERE wallet = ?', (wallet,)).fetchone()
        else:
            updates = []
            params = []
            if best_domain and (row['best_domain'] is None or score_from_domain(best_domain)['score'] > score_from_domain(row['best_domain'])['score']):
                updates.append('best_domain = ?')
                params.append(best_domain)
            if current_domain:
                updates.append('current_domain = ?')
                params.append(current_domain)
            if updates:
                updates.append('updated_at = ?')
                params.append(now_iso())
                params.append(wallet)
                conn.execute(f'UPDATE players SET {", ".join(updates)} WHERE wallet = ?', params)
                conn.commit()
                row = conn.execute('SELECT * FROM players WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row)


def get_player(wallet):
    player = ensure_player(wallet)
    current_deck = deck_summary_for_domain(player['current_domain'], wallet) if player['current_domain'] else None
    profile = player_profile_row(wallet)
    guild_membership = current_guild_membership(wallet)
    telegram_link = telegram_wallet_link(wallet)
    rewards = reward_summary(wallet)
    analytics = derived_behavior_profile(wallet)
    equipped = rewards.get('equipped_cosmetics') or {}
    profile_banner_key = (profile or {}).get('profile_banner_key') or ((equipped.get('guild') or {}).get('key'))
    return {
        'wallet': player['wallet'],
        'rating': player['rating'],
        'games_played': player['games_played'],
        'ranked_wins': player['ranked_wins'],
        'ranked_losses': player['ranked_losses'],
        'best_domain': player['best_domain'],
        'current_domain': player['current_domain'],
        'telegram_linked': telegram_link is not None,
        'telegram': {
            'id': telegram_link['telegram_user_id'],
            'username': telegram_link['username'],
            'first_name': telegram_link['first_name'],
            'linked_at': telegram_link['linked_at'],
        } if telegram_link else None,
        'telegram_notifications': telegram_notification_settings(wallet),
        'display_name': display_name_for_wallet(wallet),
        'avatar': '',
        'bio': (profile or {}).get('bio') or '',
        'profile_title': (profile or {}).get('profile_title') or '',
        'favorite_ability': analytics.get('favorite_ability') or (profile or {}).get('favorite_ability') or '',
        'play_style': analytics.get('play_style') or (profile or {}).get('play_style') or '',
        'favorite_strategy': analytics.get('favorite_strategy') or (profile or {}).get('favorite_strategy') or '',
        'favorite_role': analytics.get('favorite_role') or (profile or {}).get('favorite_role') or '',
        'profile_banner_key': profile_banner_key,
        'selected_gift': selected_profile_gift(wallet, profile=profile),
        'available_profile_gifts': available_profile_gifts(wallet),
        'analytics': analytics,
        'nft_draft': cosmetic_nft_draft(wallet),
        'deck_summary': current_deck,
        'rewards': rewards,
        'tutorial': tutorial_summary(wallet),
        'synergies': compute_domain_synergies(wallet),
        'guild': {
            'id': guild_membership['guild_id'],
            'name': guild_membership['name'],
            'slug': guild_membership['slug'],
            'role': guild_membership['role'],
        } if guild_membership else None,
    }


def record_non_ranked_game(wallet, domain=None):
    ensure_player(wallet, best_domain=domain, current_domain=domain)
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE players
            SET games_played = games_played + 1,
                current_domain = COALESCE(?, current_domain),
                best_domain = COALESCE(best_domain, ?),
                updated_at = ?
            WHERE wallet = ?
            ''',
            (domain, domain, now_iso(), wallet),
        )
        conn.commit()


def apply_non_ranked_domain_progress(match, mode='casual'):
    for wallet, domain, result in (
        (match['wallet_a'], match['domain_a'], 'win' if match.get('winner') == match['wallet_a'] else ('draw' if match.get('winner') is None else 'loss')),
        (match['wallet_b'], match['domain_b'], 'win' if match.get('winner') == match['wallet_b'] else ('draw' if match.get('winner') is None else 'loss')),
    ):
        grant_match_rewards(wallet, won=result == 'win', ranked=False)
        grant_domain_experience(wallet, domain, 16 if mode == 'casual' else 18, won=result == 'win')
        metadata = get_domain_metadata_payload(domain, wallet=wallet)
        log_domain_telemetry(
            f'{mode}_battle_complete',
            wallet=wallet,
            domain=domain,
            rarity_label=(metadata or {}).get('rarityLabel'),
            payload={
                'result': result,
                'own_score': match['score_a'] if wallet == match['wallet_a'] else match['score_b'],
                'opp_score': match['score_b'] if wallet == match['wallet_a'] else match['score_a'],
                'ability_used': any(
                    (round_item.get('action_a') if wallet == match['wallet_a'] else round_item.get('action_b')) == 'ability'
                    for round_item in match.get('rounds', [])
                ),
                'match_duration_rounds': len(match.get('rounds', [])),
            },
        )
    record_player_behavior(
        match['wallet_a'],
        match['domain_a'],
        match.get('rounds', []),
        match.get('strategy_key_a'),
        'win' if match.get('winner') == match['wallet_a'] else ('draw' if match.get('winner') is None else 'loss'),
        mode=mode,
        side='a',
    )
    record_player_behavior(
        match['wallet_b'],
        match['domain_b'],
        match.get('rounds', []),
        match.get('strategy_key_b'),
        'win' if match.get('winner') == match['wallet_b'] else ('draw' if match.get('winner') is None else 'loss'),
        mode=mode,
        side='b',
    )


def global_player_rows(limit=200):
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT wallet, rating, games_played, ranked_wins, ranked_losses, best_domain, current_domain, first_seen, updated_at
            FROM players
            ORDER BY first_seen ASC, updated_at DESC
            LIMIT ?
            ''',
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = public_player_summary(row['wallet'])
        item.update(dict(row))
        result.append(item)
    return result


def achievements_for_wallet(wallet):
    player = get_player(wallet)
    with closing(get_db()) as conn:
        friend_count = conn.execute(
            'SELECT COUNT(*) AS value FROM friends WHERE owner_wallet = ?',
            (wallet,),
        ).fetchone()['value']
    try:
        domain_count = len(fetch_wallet_domains(wallet))
    except (RuntimeError, ValueError):
        domain_count = 0

    ranked_wins = player.get('ranked_wins') or 0
    games_played = player.get('games_played') or 0
    rating = player.get('rating') or 0
    deck_opened = bool(player.get('current_domain') or player.get('best_domain'))

    return [
        {
            'id': 'first_login',
            'title': 'Первый вход',
            'description': 'Подключить кошелёк и зайти в игру.',
            'unlocked': True,
            'progress': 'Готово',
        },
        {
            'id': 'first_deck',
            'title': 'Первая колода',
            'description': 'Открыть первую колоду из домена.',
            'unlocked': deck_opened,
            'progress': 'Открыта' if deck_opened else '0/1',
        },
        {
            'id': 'collector_3',
            'title': 'Коллекционер',
            'description': 'Иметь 3 домена или больше.',
            'unlocked': domain_count >= 3,
            'progress': f'{domain_count}/3 доменов',
        },
        {
            'id': 'social_3',
            'title': 'Социальный игрок',
            'description': 'Добавить 3 друзей.',
            'unlocked': friend_count >= 3,
            'progress': f'{friend_count}/3 друзей',
        },
        {
            'id': 'ranked_win',
            'title': 'Первая рейтинговая победа',
            'description': 'Выиграть 1 рейтинговый матч.',
            'unlocked': ranked_wins >= 1,
            'progress': f'{ranked_wins}/1 побед',
        },
        {
            'id': 'fighter_10',
            'title': 'Опытный боец',
            'description': 'Сыграть 10 матчей.',
            'unlocked': games_played >= 10,
            'progress': f'{games_played}/10 матчей',
        },
        {
            'id': 'rating_1200',
            'title': 'Рейтинг 1200+',
            'description': 'Поднять рейтинг до 1200.',
            'unlocked': rating >= 1200,
            'progress': f'{rating}/1200',
        },
    ]


def head_to_head_result(wallet_a, domain_a, wallet_b, domain_b, selected_slot_a=None, selected_slot_b=None, strategy_key_a='balanced', strategy_key_b='balanced'):
    cards_a = load_active_deck_cards(wallet_a, domain_a) or generate_pack(domain_a)
    cards_b = load_active_deck_cards(wallet_b, domain_b) or generate_pack(domain_b)
    cards_a = [normalize_card_profile(card) for card in cards_a]
    cards_b = [normalize_card_profile(card) for card in cards_b]
    build_a = load_deck_build(wallet_a, domain_a, cards_a)
    build_b = load_deck_build(wallet_b, domain_b, cards_b)
    selected_slot_a = selected_slot_a or auto_tactical_slot(cards_a, build_a['points'])
    selected_slot_b = selected_slot_b or auto_tactical_slot(cards_b, build_b['points'])
    duel = wikigachi_duel(
        cards_a,
        cards_b,
        f'{wallet_a}:{domain_a}:{wallet_b}:{domain_b}',
        build_a=build_a['points'],
        build_b=build_b['points'],
        featured_slot_a=selected_slot_a,
        featured_slot_b=selected_slot_b,
        strategy_key_a=strategy_key_a,
        strategy_key_b=strategy_key_b,
        domain_a=domain_a,
        domain_b=domain_b,
        wallet_a=wallet_a,
        wallet_b=wallet_b,
    )
    score_a = duel['score_a']
    score_b = duel['score_b']
    if duel['winner'] == 'a':
        winner = wallet_a
    elif duel['winner'] == 'b':
        winner = wallet_b
    else:
        winner = None
    return {
        'wallet_a': wallet_a,
        'wallet_b': wallet_b,
        'domain_a': domain_a,
        'domain_b': domain_b,
        'cards_a': cards_a,
        'cards_b': cards_b,
        'score_a': score_a,
        'score_b': score_b,
        'rounds': duel['rounds'],
        'tie_breaker': duel['tie_breaker'],
        'deck_power_a': deck_score(cards_a),
        'deck_power_b': deck_score(cards_b),
        'build_a': build_a,
        'build_b': build_b,
        'featured_slot_a': selected_slot_a,
        'featured_slot_b': selected_slot_b,
        'featured_card_a': duel.get('featured_a'),
        'featured_card_b': duel.get('featured_b'),
        'action_plan_a': duel.get('action_plan_a'),
        'action_plan_b': duel.get('action_plan_b'),
        'strategy_key_a': duel.get('strategy_key_a'),
        'strategy_key_b': duel.get('strategy_key_b'),
        'winner': winner,
    }


def solo_round_payload(item):
    return {
        'round': item['round'],
        'label': item['label'],
        'focus': item['focus'],
        'phase': item.get('phase'),
        'player_action': item.get('action_a'),
        'opponent_action': item.get('action_b'),
        'player_action_bonus': item.get('action_bonus_a', 0),
        'opponent_action_bonus': item.get('action_bonus_b', 0),
        'player_action_note': item.get('action_note_a', ''),
        'opponent_action_note': item.get('action_note_b', ''),
        'player_strategy_key': item.get('strategy_key_a', 'balanced'),
        'opponent_strategy_key': item.get('strategy_key_b', 'balanced'),
        'player_strategy_bonus': item.get('strategy_bonus_a', 0),
        'opponent_strategy_bonus': item.get('strategy_bonus_b', 0),
        'player_strategy_note': item.get('strategy_note_a', ''),
        'opponent_strategy_note': item.get('strategy_note_b', ''),
        'player_card': item.get('card_a'),
        'opponent_card': item.get('card_b'),
        'player_value': item.get('value_a', 0),
        'opponent_value': item.get('value_b', 0),
        'player_boost': item.get('boost_a', 0),
        'opponent_boost': item.get('boost_b', 0),
        'player_skill_bonus': item.get('skill_bonus_a', 0),
        'opponent_skill_bonus': item.get('skill_bonus_b', 0),
        'player_skill_note': item.get('skill_note_a', ''),
        'opponent_skill_note': item.get('skill_note_b', ''),
        'player_featured_bonus': item.get('featured_bonus_a', 0),
        'opponent_featured_bonus': item.get('featured_bonus_b', 0),
        'player_featured_note': item.get('featured_note_a', ''),
        'opponent_featured_note': item.get('featured_note_b', ''),
        'player_total': item.get('total_a', 0),
        'opponent_total': item.get('total_b', 0),
        'player_energy_spent': item.get('energy_spent_a', 0),
        'opponent_energy_spent': item.get('energy_spent_b', 0),
        'player_roll_bonus': item.get('roll_bonus_a', 0),
        'opponent_roll_bonus': item.get('roll_bonus_b', 0),
        'player_crit': bool(item.get('crit_a')),
        'opponent_crit': bool(item.get('crit_b')),
        'player_domain_bonus': item.get('domain_bonus_a', 0),
        'opponent_domain_bonus': item.get('domain_bonus_b', 0),
        'player_domain_note': item.get('domain_note_a', ''),
        'opponent_domain_note': item.get('domain_note_b', ''),
        'winner': 'draw' if item.get('winner') == 'draw' else ('player' if item.get('winner') == 'a' else 'opponent'),
    }


def build_solo_live_payload(state):
    result_code = state.get('result')
    result_label = state.get('result_label')
    if not result_code:
        if state.get('score_a', 0) > state.get('score_b', 0):
            result_code = 'win'
            result_label = 'Победа'
        elif state.get('score_b', 0) > state.get('score_a', 0):
            result_code = 'lose'
            result_label = 'Поражение'
        else:
            result_code = 'draw'
            result_label = 'Ничья'
    tutorial = state.get('tutorial') or {}
    current_tip = tutorial.get('current_tip') or (((tutorial.get('tips') or []) + [None])[min(int(state.get('current_round', 0)), max(len(tutorial.get('tips') or []) - 1, 0))] if tutorial.get('active') else None)
    return {
        'kind': 'solo',
        'mode': state['mode'],
        'mode_title': state['mode_title'],
        'player_wallet': state['wallet'],
        'opponent_wallet': state.get('opponent_wallet'),
        'player_domain': state['domain'],
        'opponent_domain': state.get('opponent_domain'),
        'player_score': int(state.get('score_a', 0)),
        'opponent_score': int(state.get('score_b', 0)),
        'player_deck_power': state['deck_power_a'],
        'opponent_deck_power': state['deck_power_b'],
        'tie_breaker': bool(state.get('tie_breaker')),
        'rounds': [solo_round_payload(item) for item in state.get('rounds', [])],
        'player_cards': state['player_cards'],
        'opponent_cards': state['opponent_cards'],
        'player_featured_card': state.get('featured_a'),
        'opponent_featured_card': state.get('featured_b'),
        'selected_slot': state.get('selected_slot_a'),
        'strategy_key': state.get('strategy_key_a', 'balanced'),
        'opponent_strategy_key': state.get('strategy_key_b', 'balanced'),
        'player_build': state.get('build_a', {}),
        'player_build_pool': state.get('build_pool_a', 0),
        'opponent_build': state.get('build_b', {}),
        'player_domain_metadata': state.get('domain_meta_a'),
        'opponent_domain_metadata': state.get('domain_meta_b'),
        'player_cosmetics': equipped_cosmetics(state['wallet']),
        'opponent_cosmetics': equipped_cosmetics(state.get('opponent_wallet')) if state.get('opponent_wallet') and state.get('opponent_wallet') != 'bot' else {},
        'interactive_energy': int(state.get('energy_a', 0)),
        'interactive_opponent_energy': int(state.get('energy_b', 0)),
        'interactive_active_ability': ((state.get('ability_state_a') or {}).get('active') or {}),
        'interactive_ability_ready': ability_ready(state.get('ability_state_a') or {}, state.get('energy_a', 0)),
        'interactive_ability_state': state.get('ability_state_a') or {},
        'player_synergies': state.get('synergy_a') or {},
        'opponent_synergies': state.get('synergy_b') or {},
        'result': result_code,
        'result_label': result_label,
        'interactive_live': not bool(state.get('complete')),
        'interactive_session_id': state['id'],
        'interactive_round_index': int(state.get('current_round', 0)),
        'interactive_total_rounds': int(state.get('rounds_total', len(WIKIGACHI_ROUND_PLAN))),
        'interactive_available_actions': available_actions_for_state(state.get('energy_a', 0), state.get('ability_state_a') or {}),
        'interactive_hint': current_tip.get('body') if isinstance(current_tip, dict) and current_tip.get('body') else f"Энергия: {int(state.get('energy_a', 0))}. Натиск стоит 2, блок 1, способность домена 3.",
        'tutorial': state.get('tutorial'),
        'reward_summary': state.get('reward_summary'),
        'reward_gain': state.get('reward_gain'),
    }


def create_solo_battle(wallet, domain, mode, mode_title, opponent_wallet, opponent_domain, player_cards, opponent_cards, build_a, build_b, selected_slot_a, selected_slot_b, strategy_key_a='balanced', strategy_key_b='balanced', tutorial=None, bot_difficulty_level=0):
    ensure_runtime_tables()
    player_cards = [normalize_card_profile(card) for card in (player_cards or [])]
    opponent_cards = [normalize_card_profile(card) for card in (opponent_cards or [])]
    featured_a = find_card_by_slot(player_cards, selected_slot_a)
    featured_b = find_card_by_slot(opponent_cards, selected_slot_b)
    domain_meta_a = battle_domain_metadata(domain, wallet=wallet)
    domain_meta_b = battle_domain_metadata(opponent_domain, wallet=opponent_wallet)
    if mode == 'bot':
        domain_meta_b = dict(domain_meta_b or {})
        domain_meta_b['_bot_difficulty_level'] = max(0, min(4, int(bot_difficulty_level or 0)))
    synergy_a = compute_domain_synergies(wallet)
    synergy_b = compute_domain_synergies(opponent_wallet) if opponent_wallet and opponent_wallet != 'bot' else {'attack': 0, 'defense': 0, 'luck': 0, 'energy': 0, 'labels': []}
    session_id = uuid.uuid4().hex
    action_plan_b = auto_action_plan(opponent_cards, selected_slot_b, strategy_key_b)
    rng = random.Random(hashlib.sha256(f'solo-live:{mode}:{wallet}:{domain}:{opponent_domain}:{session_id}'.encode()).hexdigest())
    rounds_total = min(len(player_cards), len(opponent_cards), len(WIKIGACHI_ROUND_PLAN))
    state = {
        'id': session_id,
        'wallet': wallet,
        'domain': domain,
        'mode': mode,
        'mode_title': mode_title,
        'opponent_wallet': opponent_wallet,
        'opponent_domain': opponent_domain,
        'player_cards': player_cards,
        'opponent_cards': opponent_cards,
        'build_a': build_a or {},
        'build_b': build_b or {},
        'build_pool_a': int(sum(int((build_a or {}).get(key, 0)) for key in DISCIPLINE_KEYS)),
        'build_pool_b': int(sum(int((build_b or {}).get(key, 0)) for key in DISCIPLINE_KEYS)),
        'selected_slot_a': selected_slot_a,
        'selected_slot_b': selected_slot_b,
        'featured_a': featured_a,
        'featured_b': featured_b,
        'domain_meta_a': domain_meta_a,
        'domain_meta_b': domain_meta_b,
        'synergy_a': synergy_a,
        'synergy_b': synergy_b,
        'ability_state_a': ability_state_from_metadata(domain_meta_a),
        'ability_state_b': ability_state_from_metadata(domain_meta_b),
        'strategy_key_a': normalize_strategy_key(strategy_key_a),
        'strategy_key_b': normalize_strategy_key(strategy_key_b),
        'opponent_action_plan': action_plan_b,
        'current_round': 0,
        'rounds_total': rounds_total,
        'energy_a': 3 + int(synergy_a.get('energy', 0)),
        'energy_b': 3 + int(synergy_b.get('energy', 0)),
        'score_a': 0,
        'score_b': 0,
        'bot_difficulty_level': max(0, min(4, int(bot_difficulty_level or 0))) if mode == 'bot' else 0,
        'prev_a': None,
        'prev_b': None,
        'rounds': [],
        'swing_pairs': [[rng.randint(0, 2), rng.randint(0, 2)] for _ in range(rounds_total)],
        'deck_power_a': deck_score(player_cards),
        'deck_power_b': deck_score(opponent_cards),
        'complete': False,
        'tie_breaker': False,
        'tutorial': tutorial or None,
    }
    if tutorial and state.get('ability_state_a') and state['ability_state_a'].get('active'):
        state['ability_state_a']['cooldown_remaining'] = 0
        state['ability_state_a']['charges_remaining'] = max(1, int(state['ability_state_a'].get('charges_remaining', 1) or 1))
    ts = now_iso()
    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO solo_battles (id, wallet, mode, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (session_id, wallet, mode, json.dumps(state, ensure_ascii=False), ts, ts),
        )
        conn.commit()
    return build_solo_live_payload(state)


def load_solo_battle(session_id):
    ensure_runtime_tables()
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM solo_battles WHERE id = ?', (session_id,)).fetchone()
    if row is None:
        raise ValueError('Бой не найден.')
    try:
        state = json.loads(row['state_json'])
    except json.JSONDecodeError as exc:
        raise ValueError('Повреждено состояние боя.') from exc
    return state


def save_solo_battle(state):
    with closing(get_db()) as conn:
        conn.execute(
            'UPDATE solo_battles SET state_json = ?, updated_at = ? WHERE id = ?',
            (json.dumps(state, ensure_ascii=False), now_iso(), state['id']),
        )
        conn.commit()


def finalize_solo_battle_state(state):
    if state.get('score_a', 0) > state.get('score_b', 0):
        state['winner'] = 'a'
        state['result'] = 'win'
        state['result_label'] = 'Победа'
        return
    if state.get('score_b', 0) > state.get('score_a', 0):
        state['winner'] = 'b'
        state['result'] = 'lose'
        state['result_label'] = 'Поражение'
        return
    state['tie_breaker'] = True
    total_a = featured_match_bonus(state.get('featured_a')) * 2 + state['deck_power_a']
    total_b = featured_match_bonus(state.get('featured_b')) * 2 + state['deck_power_b']
    if total_a > total_b:
        state['winner'] = 'a'
        state['result'] = 'win'
        state['result_label'] = 'Победа'
    elif total_b > total_a:
        state['winner'] = 'b'
        state['result'] = 'lose'
        state['result_label'] = 'Поражение'
    else:
        state['winner'] = None
        state['result'] = 'draw'
        state['result_label'] = 'Ничья'


def tutorial_config_for_domain(domain_meta, selected_slot):
    active_name = (((domain_meta or {}).get('activeAbility') or {}).get('name')) or 'Способность домена'
    return {
        'active': True,
        'step_title': 'Боевой туториал',
        'step_index': 0,
        'recommended_actions': ['guard', 'burst', 'ability'],
        'bot_actions': ['burst', 'guard', 'guard'],
        'tips': [
            {
                'title': 'Шаг 1. Удержи первый удар',
                'body': 'Снизу твоя колода. Сверху колода бота. Сейчас бот откроет Натиском, поэтому жми Блок.',
                'focus': 'action',
            },
            {
                'title': 'Шаг 2. Дожми перевес',
                'body': 'Порядок колоды уже работает на тебя. Во втором раунде жми Натиск и забирай темп.',
                'focus': 'order',
            },
            {
                'title': 'Шаг 3. Используй тактическую карту',
                'body': f'Твоя тактическая карта в слоте {selected_slot or 1}. Заверши бой через {active_name}.',
                'focus': 'featured',
            },
        ],
        'skip_allowed': True,
        'first_success': True,
        'reward_label': 'Награда за обучение: +5 осколков и +1 редкий токен',
    }


def apply_solo_battle_action(session_id, wallet, action_key):
    state = load_solo_battle(session_id)
    if wallet != state.get('wallet'):
        raise ValueError('Нет доступа к этому бою.')
    if state.get('complete'):
        payload = build_solo_live_payload(state)
        payload['interactive_live'] = False
        return payload

    raw_action_key = str(action_key or '').strip().lower()
    action_key = raw_action_key if raw_action_key in ACTION_RULES else sanitize_action_plan([raw_action_key])[0]
    idx = int(state.get('current_round', 0))
    rounds_total = int(state.get('rounds_total', 0))
    if idx >= rounds_total:
        state['complete'] = True
        finalize_solo_battle_state(state)
        save_solo_battle(state)
        return build_solo_live_payload(state)

    focus, label, phase = WIKIGACHI_ROUND_PLAN[idx]
    player_cards = [normalize_card_profile(card) for card in state.get('player_cards', [])]
    opponent_cards = [normalize_card_profile(card) for card in state.get('opponent_cards', [])]
    card_a = player_cards[idx]
    card_b = opponent_cards[idx]
    ability_state_a = dict(state.get('ability_state_a') or {})
    ability_state_b = dict(state.get('ability_state_b') or {})
    domain_meta_a = dict(state.get('domain_meta_a') or {})
    domain_meta_b = dict(state.get('domain_meta_b') or {})
    domain_meta_a['_synergy'] = dict(state.get('synergy_a') or {})
    domain_meta_b['_synergy'] = dict(state.get('synergy_b') or {})
    tutorial = dict(state.get('tutorial') or {})
    state['energy_a'] = 3
    state['energy_b'] = 3
    prev_a = state.get('prev_a')
    prev_b = state.get('prev_b')
    if action_key not in available_actions_for_state(state.get('energy_a', 0), ability_state_a):
        raise ValueError('Недостаточно энергии или способность недоступна.')
    planned_action_b = (state.get('opponent_action_plan') or default_action_plan())[idx]
    if tutorial.get('active'):
        planned_action_b = ((tutorial.get('bot_actions') or ['burst', 'guard', 'guard']) + ['guard'])[idx]
    action_b = choose_bot_round_action(
        planned_action_b,
        state.get('energy_b', 0),
        ability_state_b,
        domain_meta_b,
        phase,
        round_index=idx,
        previous_outcome=prev_b,
        rng_seed=session_id,
        allow_ability=False,
    )
    build_a = state.get('build_a') or {}
    build_b = state.get('build_b') or {}
    featured_a = normalize_card_profile(state.get('featured_a') or card_a)
    featured_b = normalize_card_profile(state.get('featured_b') or card_b)
    effective_action_a = effective_action_key(action_key, domain_meta_a)
    effective_action_b = effective_action_key(action_b, domain_meta_b)
    value_a = max(0, round(build_bonus_value(build_a, focus) / 7))
    value_b = max(0, round(build_bonus_value(build_b, focus) / 7))
    card_boost_a = matchup_strategy_bonus(card_a, card_b, phase, idx)
    card_boost_b = matchup_strategy_bonus(card_b, card_a, phase, idx)
    action_bonus_a, action_bonus_b, action_note_a, action_note_b = action_round_resolution(effective_action_a, effective_action_b)
    strategy_bonus_a, strategy_note_a = strategy_round_bonus(state.get('strategy_key_a'), focus, phase, idx, action_key, prev_a, featured_a or card_a)
    strategy_bonus_b, strategy_note_b = strategy_round_bonus(state.get('strategy_key_b'), focus, phase, idx, action_b, prev_b, featured_b or card_b)
    skill_bonus_a, skill_note_a = apply_skill_bonus((featured_a or {}).get('skill_key'), focus, phase, value_a, value_b, featured_a or card_a, featured_b or card_b, idx, prev_a)
    skill_bonus_b, skill_note_b = apply_skill_bonus((featured_b or {}).get('skill_key'), focus, phase, value_b, value_a, featured_b or card_b, featured_a or card_a, idx, prev_b)
    featured_bonus_a, featured_note_a = featured_card_round_bonus(featured_a or card_a, featured_b or card_b, focus, phase, idx, prev_a)
    featured_bonus_b, featured_note_b = featured_card_round_bonus(featured_b or card_b, featured_a or card_a, focus, phase, idx, prev_b)
    passive_bonus_a, passive_note_a = passive_ability_bonus(domain_meta_a, ability_state_a, 'pre_round', previous_outcome=prev_a, action_key=action_key, proc_seed=f'{session_id}:{idx}:a:pre')
    passive_bonus_b, passive_note_b = passive_ability_bonus(domain_meta_b, ability_state_b, 'pre_round', previous_outcome=prev_b, action_key=action_b, proc_seed=f'{session_id}:{idx}:b:pre')
    active_bonus_a, active_note_a = active_ability_bonus(domain_meta_a, ability_state_a, phase, focus, action_key, proc_seed=f'{session_id}:{idx}:a')
    active_bonus_b, active_note_b = active_ability_bonus(domain_meta_b, ability_state_b, phase, focus, action_b, proc_seed=f'{session_id}:{idx}:b')
    counter_bonus_a, counter_note_a = class_counter_bonus(domain_meta_a, domain_meta_b, action_key)
    counter_bonus_b, counter_note_b = class_counter_bonus(domain_meta_b, domain_meta_a, action_b)
    roll_rng = random.Random(hashlib.sha256(f"solo-roll:{session_id}:{idx}:{action_key}:{action_b}".encode()).hexdigest())
    roll_bonus_a, crit_a = energy_roll_bonus(action_key, roll_rng)
    roll_bonus_b, crit_b = energy_roll_bonus(action_b, roll_rng)
    passive_roll_a, passive_roll_note_a = passive_ability_bonus(domain_meta_a, ability_state_a, 'roll', previous_outcome=prev_a, action_key=action_key, proc_seed=f'{session_id}:{idx}:a:roll')
    passive_roll_b, passive_roll_note_b = passive_ability_bonus(domain_meta_b, ability_state_b, 'roll', previous_outcome=prev_b, action_key=action_b, proc_seed=f'{session_id}:{idx}:b:roll')
    tutorial_hint = None
    tutorial_bonus_a = 0
    tutorial_bonus_b = 0
    tutorial_followed = False
    if tutorial.get('active'):
        recommended = ((tutorial.get('recommended_actions') or ['guard', 'burst', 'ability']) + ['guard'])[idx]
        tutorial_followed = action_key == recommended
        tutorial_bonus_a = 18 if tutorial_followed else 4
        tutorial_bonus_b = -4 if tutorial_followed else 0
        tip = ((tutorial.get('tips') or []) + [{'title': '', 'body': ''}])[idx]
        tutorial_hint = {
            'recommended_action': recommended,
            'followed': tutorial_followed,
            'title': tip.get('title') or '',
            'body': tip.get('body') or '',
        }
    if crit_a:
        roll_bonus_a += 6
    if crit_b:
        roll_bonus_b += 6
    swing_a, swing_b = (state.get('swing_pairs') or [[0, 0]])[idx]
    domain_bonus_a = passive_bonus_a + active_bonus_a + counter_bonus_a + passive_roll_a
    domain_bonus_b = passive_bonus_b + active_bonus_b + counter_bonus_b + passive_roll_b
    total_a = value_a + card_boost_a + action_bonus_a + strategy_bonus_a + skill_bonus_a + featured_bonus_a + roll_bonus_a + domain_bonus_a + swing_a + tutorial_bonus_a
    total_b = value_b + card_boost_b + action_bonus_b + strategy_bonus_b + skill_bonus_b + featured_bonus_b + roll_bonus_b + domain_bonus_b + swing_b + tutorial_bonus_b

    if total_a > total_b:
        winner = 'a'
        state['score_a'] = int(state.get('score_a', 0)) + 1
        state['prev_a'] = 'win'
        state['prev_b'] = 'loss'
    elif total_b > total_a:
        winner = 'b'
        state['score_b'] = int(state.get('score_b', 0)) + 1
        state['prev_a'] = 'loss'
        state['prev_b'] = 'win'
    else:
        winner = 'draw'
        state['prev_a'] = 'draw'
        state['prev_b'] = 'draw'

    energy_spent_a = action_energy_cost(action_key, (ability_state_a or {}).get('active'))
    energy_spent_b = action_energy_cost(action_b, (ability_state_b or {}).get('active'))
    state['energy_a'] = max(0, 3 - energy_spent_a)
    state['energy_b'] = max(0, 3 - energy_spent_b)
    state['ability_state_a'] = spend_ability_state(ability_state_a, action_key)
    state['ability_state_b'] = spend_ability_state(ability_state_b, action_b)

    state.setdefault('rounds', []).append(
        {
            'round': idx + 1,
            'label': label,
            'focus': focus,
            'phase': phase,
            'action_a': action_key,
            'action_b': action_b,
            'action_bonus_a': action_bonus_a,
            'action_bonus_b': action_bonus_b,
            'action_note_a': action_note_a,
            'action_note_b': action_note_b,
            'strategy_key_a': state.get('strategy_key_a', 'balanced'),
            'strategy_key_b': state.get('strategy_key_b', 'balanced'),
            'strategy_bonus_a': strategy_bonus_a,
            'strategy_bonus_b': strategy_bonus_b,
            'strategy_note_a': strategy_note_a,
            'strategy_note_b': strategy_note_b,
            'card_a': {'slot': card_a.get('slot'), 'title': card_a.get('title')},
            'card_b': {'slot': card_b.get('slot'), 'title': card_b.get('title')},
            'value_a': value_a,
            'value_b': value_b,
            'boost_a': card_boost_a,
            'boost_b': card_boost_b,
            'skill_bonus_a': skill_bonus_a,
            'skill_bonus_b': skill_bonus_b,
            'skill_note_a': skill_note_a,
            'skill_note_b': skill_note_b,
            'featured_bonus_a': featured_bonus_a,
            'featured_bonus_b': featured_bonus_b,
            'featured_note_a': featured_note_a,
            'featured_note_b': featured_note_b,
            'energy_spent_a': energy_spent_a,
            'energy_spent_b': energy_spent_b,
            'roll_bonus_a': roll_bonus_a,
            'roll_bonus_b': roll_bonus_b,
            'crit_a': crit_a,
            'crit_b': crit_b,
            'domain_bonus_a': domain_bonus_a,
            'domain_bonus_b': domain_bonus_b,
            'domain_note_a': ' • '.join(part for part in [passive_note_a, active_note_a, counter_note_a, passive_roll_note_a] if part),
            'domain_note_b': ' • '.join(part for part in [passive_note_b, active_note_b, counter_note_b, passive_roll_note_b] if part),
            'tutorial_bonus_a': tutorial_bonus_a,
            'tutorial_bonus_b': tutorial_bonus_b,
            'tutorial_hint': tutorial_hint,
            'swing_a': swing_a,
            'swing_b': swing_b,
            'total_a': total_a,
            'total_b': total_b,
            'winner': winner,
        }
    )
    state['current_round'] = idx + 1
    if tutorial.get('active'):
        tutorial['step_index'] = state['current_round']
        if state['current_round'] < len(tutorial.get('tips') or []):
          tutorial['current_tip'] = tutorial['tips'][state['current_round']]
        state['tutorial'] = tutorial
    if state['current_round'] >= rounds_total:
        state['complete'] = True
        finalize_solo_battle_state(state)
        record_non_ranked_game(state['wallet'], state['domain'])
        won = state.get('winner') == 'a'
        rewards_after = grant_match_rewards(state['wallet'], won=won, ranked=False)
        state['reward_summary'] = rewards_after
        state['reward_gain'] = {
            'pack_shards': 2 if won else 1,
            'rare_tokens': 0,
            'lucky_tokens': 0,
            'season_points': 4 if won else 2,
        }
        if tutorial.get('active'):
            if won:
                tutorial_rewards, tutorial_gain = grant_tutorial_reward(state['wallet'])
                state['reward_summary'] = tutorial_rewards
                state['reward_gain'] = {
                    'pack_shards': int(state['reward_gain'].get('pack_shards', 0)) + int(tutorial_gain.get('pack_shards', 0)),
                    'rare_tokens': int(state['reward_gain'].get('rare_tokens', 0)) + int(tutorial_gain.get('rare_tokens', 0)),
                    'lucky_tokens': int(state['reward_gain'].get('lucky_tokens', 0)) + int(tutorial_gain.get('lucky_tokens', 0)),
                    'season_points': int(state['reward_gain'].get('season_points', 0)) + int(tutorial_gain.get('season_points', 0)),
                }
                update_tutorial_progress(state['wallet'], completed_at=now_iso(), wins=int(ensure_tutorial_progress(state['wallet']).get('wins', 0) or 0) + 1)
                tutorial['completed'] = True
                tutorial['completion_prompt'] = 'Первый успех зафиксирован. Забери награду и переходи в обычный или рейтинговый бой.'
            else:
                tutorial['completion_prompt'] = 'Туториал можно пройти ещё раз. Следуй подсказкам, и первый бой будет значительно проще.'
            state['tutorial'] = tutorial
        grant_domain_experience(state['wallet'], state['domain'], 18, won=won)
        log_domain_telemetry(
            'tutorial_complete' if tutorial.get('active') else 'solo_battle_complete',
            wallet=state['wallet'],
            domain=state['domain'],
            rarity_label=(domain_meta_a or {}).get('rarityLabel'),
            payload={
                'mode': state.get('mode'),
                'result': state.get('result'),
                'score_a': state.get('score_a'),
                'score_b': state.get('score_b'),
                'ability_used': any(round_item.get('action_a') == 'ability' for round_item in state.get('rounds', [])),
                'match_duration_rounds': len(state.get('rounds', [])),
            },
        )
        record_player_behavior(
            state['wallet'],
            state['domain'],
            state.get('rounds', []),
            state.get('strategy_key_a'),
            'win' if won else 'loss',
            mode=state.get('mode'),
            side='a',
        )
        if state.get('mode') == 'bot':
            update_player_bot_progress(
                state['wallet'],
                'win' if won else ('draw' if state.get('winner') is None else 'loss'),
            )
    else:
        state['energy_a'] = 3
        state['energy_b'] = 3
    save_solo_battle(state)
    return build_solo_live_payload(state)


def apply_ranked_result_duel(match):
    player_a = ensure_player(match['wallet_a'], best_domain=match['domain_a'], current_domain=match['domain_a'])
    player_b = ensure_player(match['wallet_b'], best_domain=match['domain_b'], current_domain=match['domain_b'])
    rating_a_before = player_a['rating']
    rating_b_before = player_b['rating']

    score_a = 1.0 if match['winner'] == match['wallet_a'] else 0.0 if match['winner'] == match['wallet_b'] else 0.5
    score_b = 1.0 - score_a if score_a != 0.5 else 0.5
    expected_a = 1 / (1 + 10 ** ((rating_b_before - rating_a_before) / 400))
    expected_b = 1 / (1 + 10 ** ((rating_a_before - rating_b_before) / 400))
    rating_a_after = max(100, rating_a_before + round(RATING_K_FACTOR * (score_a - expected_a)))
    rating_b_after = max(100, rating_b_before + round(RATING_K_FACTOR * (score_b - expected_b)))

    def result_label(wallet):
        if match['winner'] is None:
            return 'draw'
        return 'win' if match['winner'] == wallet else 'loss'

    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE players
            SET rating = ?, games_played = games_played + 1,
                ranked_wins = ranked_wins + ?,
                ranked_losses = ranked_losses + ?,
                best_domain = COALESCE(best_domain, ?),
                current_domain = ?,
                updated_at = ?
            WHERE wallet = ?
            ''',
            (
                rating_a_after,
                1 if result_label(match['wallet_a']) == 'win' else 0,
                1 if result_label(match['wallet_a']) == 'loss' else 0,
                match['domain_a'],
                match['domain_a'],
                now_iso(),
                match['wallet_a'],
            ),
        )
        conn.execute(
            '''
            UPDATE players
            SET rating = ?, games_played = games_played + 1,
                ranked_wins = ranked_wins + ?,
                ranked_losses = ranked_losses + ?,
                best_domain = COALESCE(best_domain, ?),
                current_domain = ?,
                updated_at = ?
            WHERE wallet = ?
            ''',
            (
                rating_b_after,
                1 if result_label(match['wallet_b']) == 'win' else 0,
                1 if result_label(match['wallet_b']) == 'loss' else 0,
                match['domain_b'],
                match['domain_b'],
                now_iso(),
                match['wallet_b'],
            ),
        )
        for wallet, domain, opponent_domain, result, before, after, own_score, opp_score in (
            (
                match['wallet_a'],
                match['domain_a'],
                match['domain_b'],
                result_label(match['wallet_a']),
                rating_a_before,
                rating_a_after,
                match['score_a'],
                match['score_b'],
            ),
            (
                match['wallet_b'],
                match['domain_b'],
                match['domain_a'],
                result_label(match['wallet_b']),
                rating_b_before,
                rating_b_after,
                match['score_b'],
                match['score_a'],
            ),
        ):
            conn.execute(
                '''
                INSERT INTO ranked_matches (
                    id, wallet, domain, opponent_domain, result, rating_before, rating_after,
                    player_score, opponent_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    uuid.uuid4().hex,
                    wallet,
                    domain,
                    opponent_domain,
                    result,
                    before,
                    after,
                    own_score,
                    opp_score,
                    now_iso(),
                ),
            )
        conn.commit()

    for wallet, domain, result in (
        (match['wallet_a'], match['domain_a'], result_label(match['wallet_a'])),
        (match['wallet_b'], match['domain_b'], result_label(match['wallet_b'])),
    ):
        grant_match_rewards(wallet, won=result == 'win', ranked=True)
        grant_domain_experience(wallet, domain, 24, won=result == 'win')
        metadata = get_domain_metadata_payload(domain, wallet=wallet)
        log_domain_telemetry(
            'ranked_battle_complete',
            wallet=wallet,
            domain=domain,
            rarity_label=(metadata or {}).get('rarityLabel'),
            payload={
                'result': result,
                'own_score': match['score_a'] if wallet == match['wallet_a'] else match['score_b'],
                'opp_score': match['score_b'] if wallet == match['wallet_a'] else match['score_a'],
                'ability_used': any(
                    (round_item.get('action_a') if wallet == match['wallet_a'] else round_item.get('action_b')) == 'ability'
                    for round_item in match.get('rounds', [])
                ),
                'match_duration_rounds': len(match.get('rounds', [])),
            },
        )
    record_player_behavior(
        match['wallet_a'],
        match['domain_a'],
        match.get('rounds', []),
        match.get('strategy_key_a'),
        result_label(match['wallet_a']),
        mode='ranked',
        side='a',
    )
    record_player_behavior(
        match['wallet_b'],
        match['domain_b'],
        match.get('rounds', []),
        match.get('strategy_key_b'),
        result_label(match['wallet_b']),
        mode='ranked',
        side='b',
    )

    return (
        get_player(match['wallet_a']),
        get_player(match['wallet_b']),
        rating_a_before,
        rating_a_after,
        rating_b_before,
        rating_b_after,
    )


def invite_result_payload(invite, match, viewer_wallet, player_a=None, player_b=None, rating_meta=None):
    result_labels = {
        'win': 'Победа',
        'loss': 'Поражение',
        'draw': 'Ничья',
    }
    viewer_is_a = viewer_wallet == match['wallet_a']
    own_wallet = match['wallet_a'] if viewer_is_a else match['wallet_b']
    opp_wallet = match['wallet_b'] if viewer_is_a else match['wallet_a']
    own_domain = match['domain_a'] if viewer_is_a else match['domain_b']
    opp_domain = match['domain_b'] if viewer_is_a else match['domain_a']
    own_score = match['score_a'] if viewer_is_a else match['score_b']
    opp_score = match['score_b'] if viewer_is_a else match['score_a']
    own_deck_power = match['deck_power_a'] if viewer_is_a else match['deck_power_b']
    opp_deck_power = match['deck_power_b'] if viewer_is_a else match['deck_power_a']

    if match['winner'] is None:
        own_result = 'draw'
    else:
        own_result = 'win' if match['winner'] == own_wallet else 'loss'

    rounds = []
    for item in match.get('rounds', []):
        rounds.append(
            {
                'round': item['round'],
                'label': item['label'],
                'focus': item['focus'],
                'player_action': item.get('action_a') if viewer_is_a else item.get('action_b'),
                'opponent_action': item.get('action_b') if viewer_is_a else item.get('action_a'),
                'player_action_bonus': item.get('action_bonus_a', 0) if viewer_is_a else item.get('action_bonus_b', 0),
                'opponent_action_bonus': item.get('action_bonus_b', 0) if viewer_is_a else item.get('action_bonus_a', 0),
                'player_action_note': item.get('action_note_a', '') if viewer_is_a else item.get('action_note_b', ''),
                'opponent_action_note': item.get('action_note_b', '') if viewer_is_a else item.get('action_note_a', ''),
                'player_strategy_key': item.get('strategy_key_a', 'balanced') if viewer_is_a else item.get('strategy_key_b', 'balanced'),
                'opponent_strategy_key': item.get('strategy_key_b', 'balanced') if viewer_is_a else item.get('strategy_key_a', 'balanced'),
                'player_strategy_bonus': item.get('strategy_bonus_a', 0) if viewer_is_a else item.get('strategy_bonus_b', 0),
                'opponent_strategy_bonus': item.get('strategy_bonus_b', 0) if viewer_is_a else item.get('strategy_bonus_a', 0),
                'player_strategy_note': item.get('strategy_note_a', '') if viewer_is_a else item.get('strategy_note_b', ''),
                'opponent_strategy_note': item.get('strategy_note_b', '') if viewer_is_a else item.get('strategy_note_a', ''),
                'player_card': item['card_a'] if viewer_is_a else item['card_b'],
                'opponent_card': item['card_b'] if viewer_is_a else item['card_a'],
                'player_value': item['value_a'] if viewer_is_a else item['value_b'],
                'opponent_value': item['value_b'] if viewer_is_a else item['value_a'],
                'player_boost': item.get('boost_a', 0) if viewer_is_a else item.get('boost_b', 0),
                'opponent_boost': item.get('boost_b', 0) if viewer_is_a else item.get('boost_a', 0),
                'player_skill_bonus': item.get('skill_bonus_a', 0) if viewer_is_a else item.get('skill_bonus_b', 0),
                'opponent_skill_bonus': item.get('skill_bonus_b', 0) if viewer_is_a else item.get('skill_bonus_a', 0),
                'player_skill_note': item.get('skill_note_a', '') if viewer_is_a else item.get('skill_note_b', ''),
                'opponent_skill_note': item.get('skill_note_b', '') if viewer_is_a else item.get('skill_note_a', ''),
                'player_featured_bonus': item.get('featured_bonus_a', 0) if viewer_is_a else item.get('featured_bonus_b', 0),
                'opponent_featured_bonus': item.get('featured_bonus_b', 0) if viewer_is_a else item.get('featured_bonus_a', 0),
                'player_featured_note': item.get('featured_note_a', '') if viewer_is_a else item.get('featured_note_b', ''),
                'opponent_featured_note': item.get('featured_note_b', '') if viewer_is_a else item.get('featured_note_a', ''),
                'player_energy_spent': item.get('energy_spent_a', 0) if viewer_is_a else item.get('energy_spent_b', 0),
                'opponent_energy_spent': item.get('energy_spent_b', 0) if viewer_is_a else item.get('energy_spent_a', 0),
                'player_roll_bonus': item.get('roll_bonus_a', 0) if viewer_is_a else item.get('roll_bonus_b', 0),
                'opponent_roll_bonus': item.get('roll_bonus_b', 0) if viewer_is_a else item.get('roll_bonus_a', 0),
                'player_domain_bonus': item.get('domain_bonus_a', 0) if viewer_is_a else item.get('domain_bonus_b', 0),
                'opponent_domain_bonus': item.get('domain_bonus_b', 0) if viewer_is_a else item.get('domain_bonus_a', 0),
                'player_domain_note': item.get('domain_note_a', '') if viewer_is_a else item.get('domain_note_b', ''),
                'opponent_domain_note': item.get('domain_note_b', '') if viewer_is_a else item.get('domain_note_a', ''),
                'player_total': item['total_a'] if viewer_is_a else item['total_b'],
                'opponent_total': item['total_b'] if viewer_is_a else item['total_a'],
                'winner': (
                    'draw'
                    if item['winner'] == 'draw'
                    else 'player'
                    if ((item['winner'] == 'a') == viewer_is_a)
                    else 'opponent'
                ),
            }
        )

    own_cards = match['cards_a'] if viewer_is_a else match['cards_b']
    opp_cards = match['cards_b'] if viewer_is_a else match['cards_a']
    own_build = match.get('build_a') if viewer_is_a else match.get('build_b')
    opp_build = match.get('build_b') if viewer_is_a else match.get('build_a')
    own_featured = match.get('featured_card_a') if viewer_is_a else match.get('featured_card_b')
    opp_featured = match.get('featured_card_b') if viewer_is_a else match.get('featured_card_a')
    cosmetics_a = equipped_cosmetics(match['wallet_a'])
    cosmetics_b = equipped_cosmetics(match['wallet_b'])
    arena_a = (cosmetics_a.get('arena') or {})
    arena_b = (cosmetics_b.get('arena') or {})
    player_a = player_a or ensure_player(match['wallet_a'])
    player_b = player_b or ensure_player(match['wallet_b'])
    rating_a = int((player_a or {}).get('rating', 1000) or 1000)
    rating_b = int((player_b or {}).get('rating', 1000) or 1000)
    chosen_arena = {}
    if arena_a.get('key') and arena_b.get('key'):
        chosen_arena = arena_a if rating_a >= rating_b else arena_b
    elif arena_a.get('key'):
        chosen_arena = arena_a
    elif arena_b.get('key'):
        chosen_arena = arena_b

    mode_title = 'Дуэль'
    if invite['mode'] == 'ranked':
        mode_title = 'Рейтинговый матч'
    elif invite['mode'] == 'casual':
        mode_title = 'Обычный матч'

    payload = {
        'kind': 'solo',
        'mode': invite['mode'],
        'mode_title': mode_title,
        'player_wallet': own_wallet,
        'opponent_wallet': opp_wallet,
        'player_domain': own_domain,
        'opponent_domain': opp_domain,
        'player_score': own_score,
        'opponent_score': opp_score,
        'player_deck_power': own_deck_power,
        'opponent_deck_power': opp_deck_power,
        'tie_breaker': bool(match.get('tie_breaker')),
        'rounds': rounds,
        'player_cards': own_cards,
        'opponent_cards': opp_cards,
        'player_featured_card': own_featured,
        'opponent_featured_card': opp_featured,
        'selected_slot': (own_featured or {}).get('slot'),
        'action_plan': match.get('action_plan_a') if viewer_is_a else match.get('action_plan_b'),
        'opponent_action_plan': match.get('action_plan_b') if viewer_is_a else match.get('action_plan_a'),
        'strategy_key': match.get('strategy_key_a', 'balanced') if viewer_is_a else match.get('strategy_key_b', 'balanced'),
        'opponent_strategy_key': match.get('strategy_key_b', 'balanced') if viewer_is_a else match.get('strategy_key_a', 'balanced'),
        'player_build': (own_build or {}).get('points') if isinstance(own_build, dict) else {},
        'player_build_pool': (own_build or {}).get('pool') if isinstance(own_build, dict) else 0,
        'opponent_build': (opp_build or {}).get('points') if isinstance(opp_build, dict) else {},
        'player_domain_metadata': get_domain_metadata_payload(own_domain, wallet=own_wallet),
        'opponent_domain_metadata': get_domain_metadata_payload(opp_domain, wallet=opp_wallet),
        'result': own_result if own_result != 'loss' else 'lose',
        'result_label': result_labels[own_result],
        'reward_summary': reward_summary(own_wallet),
        'reward_gain': {
            'pack_shards': 2 if own_result == 'win' else 1,
            'rare_tokens': 0,
            'lucky_tokens': 0,
            'season_points': (5 if invite['mode'] == 'ranked' else 4) if own_result == 'win' else (3 if invite['mode'] == 'ranked' else 2),
        },
        'player_cosmetics': cosmetics_a if viewer_is_a else cosmetics_b,
        'opponent_cosmetics': cosmetics_b if viewer_is_a else cosmetics_a,
        'battle_arena_cosmetic': chosen_arena,
    }
    if rating_meta:
        if viewer_is_a:
            payload['rating_before'] = rating_meta['rating_a_before']
            payload['rating_after'] = rating_meta['rating_a_after']
        else:
            payload['rating_before'] = rating_meta['rating_b_before']
            payload['rating_after'] = rating_meta['rating_b_after']
    return payload


def clamp_invite_timeout(seconds):
    return max(MIN_INVITE_TIMEOUT_SECONDS, min(MAX_INVITE_TIMEOUT_SECONDS, int(seconds)))


def load_invite(invite_id):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM duel_invites WHERE id = ?', (invite_id,)).fetchone()
    if row is None:
        raise ValueError('Приглашение не найдено.')
    invite = dict(row)
    invite['result_json'] = json.loads(invite['result_json']) if invite['result_json'] else None
    return invite


def save_invite_result(invite_id, result):
    with closing(get_db()) as conn:
        conn.execute(
            'UPDATE duel_invites SET result_json = ?, responded_at = ?, status = ? WHERE id = ?',
            (json.dumps(result, ensure_ascii=False), now_iso(), 'completed', invite_id),
        )
        conn.commit()


def expire_invite_if_needed(invite):
    if invite['status'] == 'pending' and parse_iso(invite['expires_at']) <= now_utc():
        with closing(get_db()) as conn:
            conn.execute(
                'UPDATE duel_invites SET status = ?, responded_at = ? WHERE id = ?',
                ('expired', now_iso(), invite['id']),
            )
            conn.commit()
        invite['status'] = 'expired'
        inviter_link = telegram_wallet_link(invite['inviter_wallet'])
        if inviter_link:
            telegram_send_message(
                inviter_link['chat_id'],
                f'Приглашение на матч {invite["id"]} истекло. Соперник не ответил за {invite["timeout_seconds"]} сек.',
            )
    return invite


def invite_reply_markup(invite_id):
    return {
        'inline_keyboard': [[
            {'text': 'Принять', 'callback_data': f'invite_accept:{invite_id}'},
            {'text': 'Отклонить', 'callback_data': f'invite_decline:{invite_id}'},
        ]]
    }


def create_duel_invite(mode, inviter_wallet, inviter_domain, invitee_wallet, timeout_seconds):
    timeout_seconds = clamp_invite_timeout(timeout_seconds)
    invitee_player = ensure_player(invitee_wallet)
    invitee_domain = invitee_player['current_domain'] or invitee_player['best_domain']
    if not invitee_domain:
        raise ValueError('У соперника ещё нет выбранного реального домена для игры.')
    invitee_link = telegram_wallet_link(invitee_wallet)
    if invitee_link is None:
        raise ValueError('Соперник не привязал Telegram к своему кошельку.')
    invitee_prefs = ensure_telegram_notification_prefs(invitee_wallet)
    if not int(invitee_prefs.get('notify_duel_invites', 1) or 0):
        raise ValueError('У соперника отключены Telegram-уведомления о приглашениях в бой.')

    invite_id = uuid.uuid4().hex[:8].upper()
    expires_at = now_utc().timestamp() + timeout_seconds
    mode_phrase = 'дуэль'
    if mode == 'ranked':
        mode_phrase = 'рейтинговую игру'
    elif mode == 'casual':
        mode_phrase = 'обычную игру'
    message = (
        f'Вас приглашают на {mode_phrase}.\n'
        f'Домен соперника: {inviter_domain}.ton\n'
        f'Ваш домен: {invitee_domain}.ton\n'
        f'Время на ответ: {timeout_seconds} сек.'
    )
    response = telegram_api(
        'sendMessage',
        {
            'chat_id': invitee_link['chat_id'],
            'text': message,
            'reply_markup': invite_reply_markup(invite_id),
        },
    )
    telegram_message_id = response['result']['message_id']

    with closing(get_db()) as conn:
        conn.execute(
            '''
            INSERT INTO duel_invites (
                id, mode, inviter_wallet, inviter_domain, invitee_wallet, invitee_domain,
                status, timeout_seconds, created_at, expires_at, telegram_message_id, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ''',
            (
                invite_id,
                mode,
                inviter_wallet,
                inviter_domain,
                invitee_wallet,
                invitee_domain,
                'pending',
                timeout_seconds,
                now_iso(),
                datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
                telegram_message_id,
            ),
        )
        conn.commit()

    inviter_link = telegram_wallet_link(inviter_wallet)
    if inviter_link:
        telegram_send_message(
            inviter_link['chat_id'],
            f'Приглашение {invite_id} отправлено. Ожидаем ответ соперника {timeout_seconds} сек.',
        )

    return load_invite(invite_id)


def cleanup_matchmaking_queue(conn):
    threshold = datetime.fromtimestamp(
        now_utc().timestamp() - MATCHMAKING_SEARCH_TTL_SECONDS,
        tz=timezone.utc,
    ).isoformat()
    conn.execute(
        '''
        UPDATE matchmaking_queue
        SET status = 'expired', updated_at = ?
        WHERE status = 'searching' AND created_at < ?
        ''',
        (now_iso(), threshold),
    )
    conn.execute(
        'DELETE FROM matchmaking_cooldowns WHERE expires_at <= ?',
        (now_iso(),),
    )


def set_matchmaking_cooldown(conn, wallet_a, wallet_b, seconds=MATCHMAKING_REMATCH_COOLDOWN_SECONDS):
    if not wallet_a or not wallet_b or wallet_a == wallet_b:
        return
    expires_at = datetime.fromtimestamp(now_utc().timestamp() + max(1, int(seconds)), tz=timezone.utc).isoformat()
    for left, right in ((wallet_a, wallet_b), (wallet_b, wallet_a)):
        conn.execute(
            '''
            INSERT INTO matchmaking_cooldowns (wallet_a, wallet_b, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(wallet_a, wallet_b) DO UPDATE SET expires_at = excluded.expires_at
            ''',
            (left, right, expires_at),
        )


def matchmaking_cooldown_left(conn, wallet_a, wallet_b):
    row = conn.execute(
        '''
        SELECT expires_at
        FROM matchmaking_cooldowns
        WHERE wallet_a = ? AND wallet_b = ?
        ''',
        (wallet_a, wallet_b),
    ).fetchone()
    if row is None:
        return 0
    left = int(parse_iso(row['expires_at']).timestamp() - now_utc().timestamp())
    return max(0, left)


def mode_title_for(mode):
    if mode == 'ranked':
        return 'Рейтинговый матч'
    if mode == 'casual':
        return 'Обычный матч'
    if mode == 'duel':
        return 'Дуэль'
    return 'Матч'


def build_ready_match_payload(
    *,
    mode,
    viewer_wallet,
    viewer_domain,
    opponent_wallet,
    opponent_domain,
    player_cards,
    opponent_cards,
    player_build_points,
    opponent_build_points,
    selected_slot,
    opponent_selected_slot,
    strategy_key='balanced',
    opponent_strategy_key='balanced',
):
    viewer_cards = [normalize_card_profile(card) for card in (player_cards or [])]
    enemy_cards = [normalize_card_profile(card) for card in (opponent_cards or [])]
    selected_slot = selected_slot or auto_tactical_slot(viewer_cards, player_build_points or {})
    opponent_selected_slot = opponent_selected_slot or auto_tactical_slot(enemy_cards, opponent_build_points or {})
    featured_a = find_card_by_slot(viewer_cards, selected_slot)
    featured_b = find_card_by_slot(enemy_cards, opponent_selected_slot)
    viewer_player = ensure_player(viewer_wallet, best_domain=viewer_domain, current_domain=viewer_domain)
    opponent_player = ensure_player(opponent_wallet, best_domain=opponent_domain, current_domain=opponent_domain)
    cosmetics_viewer = equipped_cosmetics(viewer_wallet)
    cosmetics_opponent = equipped_cosmetics(opponent_wallet)
    arena_viewer = (cosmetics_viewer.get('arena') or {})
    arena_opponent = (cosmetics_opponent.get('arena') or {})
    chosen_arena = {}
    if arena_viewer.get('key') and arena_opponent.get('key'):
        chosen_arena = arena_viewer if int(viewer_player.get('rating', 1000) or 1000) >= int(opponent_player.get('rating', 1000) or 1000) else arena_opponent
    elif arena_viewer.get('key'):
        chosen_arena = arena_viewer
    elif arena_opponent.get('key'):
        chosen_arena = arena_opponent
    return {
        'kind': 'solo',
        'mode': mode,
        'mode_title': mode_title_for(mode),
        'player_wallet': viewer_wallet,
        'opponent_wallet': opponent_wallet,
        'player_domain': viewer_domain,
        'opponent_domain': opponent_domain,
        'player_score': 0,
        'opponent_score': 0,
        'player_deck_power': deck_score(viewer_cards),
        'opponent_deck_power': deck_score(enemy_cards),
        'tie_breaker': False,
        'rounds': [],
        'player_cards': viewer_cards,
        'opponent_cards': enemy_cards,
        'player_featured_card': featured_a,
        'opponent_featured_card': featured_b,
        'selected_slot': selected_slot,
        'action_plan': [],
        'opponent_action_plan': [],
        'strategy_key': normalize_strategy_key(strategy_key),
        'opponent_strategy_key': normalize_strategy_key(opponent_strategy_key),
        'player_build': player_build_points or {},
        'player_build_pool': int(sum(int((player_build_points or {}).get(key, 0)) for key in DISCIPLINE_KEYS)),
        'opponent_build': opponent_build_points or {},
        'player_domain_metadata': get_domain_metadata_payload(viewer_domain, wallet=viewer_wallet),
        'opponent_domain_metadata': get_domain_metadata_payload(opponent_domain, wallet=opponent_wallet),
        'result': 'draw',
        'result_label': 'Ожидание старта',
        'reward_summary': reward_summary(viewer_wallet),
        'reward_gain': {'pack_shards': 0, 'rare_tokens': 0, 'lucky_tokens': 0, 'season_points': 0},
        'player_cosmetics': cosmetics_viewer,
        'opponent_cosmetics': cosmetics_opponent,
        'battle_arena_cosmetic': chosen_arena,
    }


def create_battle_session(conn, wallet_a, wallet_b, payload_a, payload_b):
    session_id = uuid.uuid4().hex
    ts = now_iso()
    payload_a = dict(payload_a or {})
    payload_b = dict(payload_b or {})
    payload_a['battle_session_id'] = session_id
    payload_b['battle_session_id'] = session_id
    payload_a['requires_ready'] = True
    payload_b['requires_ready'] = True
    conn.execute(
        '''
        INSERT INTO battle_sessions (
            id, wallet_a, wallet_b, payload_a_json, payload_b_json,
            ready_a, ready_b, started_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 0, 0, NULL, ?, ?)
        ''',
        (
            session_id,
            wallet_a,
            wallet_b,
            json.dumps(payload_a, ensure_ascii=False),
            json.dumps(payload_b, ensure_ascii=False),
            ts,
            ts,
        ),
    )
    return session_id, payload_a, payload_b


def battle_session_payload(row, viewer_wallet):
    is_a = viewer_wallet == row['wallet_a']
    raw = row['payload_a_json'] if is_a else row['payload_b_json']
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def battle_session_snapshot(row, viewer_wallet):
    is_a = viewer_wallet == row['wallet_a']
    self_ready = bool(row['ready_a']) if is_a else bool(row['ready_b'])
    opp_ready = bool(row['ready_b']) if is_a else bool(row['ready_a'])
    payload = battle_session_payload(row, viewer_wallet)
    started = bool(row['started_at']) and bool(payload) and not bool(payload.get('requires_ready'))
    snapshot = {
        'id': row['id'],
        'ready_self': self_ready,
        'ready_opponent': opp_ready,
        'ready_count': int(bool(row['ready_a'])) + int(bool(row['ready_b'])),
        'started': started,
        'started_at': row['started_at'],
    }
    if started:
        snapshot['payload'] = payload
    return snapshot


def finalize_battle_session(conn, row):
    payload_a = json.loads(row['payload_a_json']) if row['payload_a_json'] else {}
    payload_b = json.loads(row['payload_b_json']) if row['payload_b_json'] else {}
    wallet_a = row['wallet_a']
    wallet_b = row['wallet_b']
    domain_a = payload_a.get('player_domain')
    domain_b = payload_b.get('player_domain')
    mode = payload_a.get('mode') or payload_b.get('mode') or 'casual'
    selected_slot_a = payload_a.get('selected_slot')
    selected_slot_b = payload_b.get('selected_slot')
    strategy_key_a = payload_a.get('strategy_key') or 'balanced'
    strategy_key_b = payload_b.get('strategy_key') or 'balanced'
    cards_a = [normalize_card_profile(card) for card in (payload_a.get('player_cards') or load_active_deck_cards(wallet_a, domain_a) or generate_pack(domain_a))]
    cards_b = [normalize_card_profile(card) for card in (payload_a.get('opponent_cards') or load_active_deck_cards(wallet_b, domain_b) or generate_pack(domain_b))]
    build_a = payload_a.get('player_build') if isinstance(payload_a.get('player_build'), dict) else load_deck_build(wallet_a, domain_a, cards_a).get('points', {})
    build_b = payload_a.get('opponent_build') if isinstance(payload_a.get('opponent_build'), dict) else load_deck_build(wallet_b, domain_b, cards_b).get('points', {})
    selected_slot_a = selected_slot_a or auto_tactical_slot(cards_a, build_a)
    selected_slot_b = selected_slot_b or auto_tactical_slot(cards_b, build_b)
    # После ready запускаем live-сессию с выбором действий в раундах.
    fresh_a = create_solo_battle(
        wallet=wallet_a,
        domain=domain_a,
        mode=mode,
        mode_title=mode_title_for(mode),
        opponent_wallet=wallet_b,
        opponent_domain=domain_b,
        player_cards=cards_a,
        opponent_cards=cards_b,
        build_a=build_a,
        build_b=build_b,
        selected_slot_a=selected_slot_a,
        selected_slot_b=selected_slot_b,
        strategy_key_a=strategy_key_a,
        strategy_key_b=strategy_key_b,
    )
    fresh_b = create_solo_battle(
        wallet=wallet_b,
        domain=domain_b,
        mode=mode,
        mode_title=mode_title_for(mode),
        opponent_wallet=wallet_a,
        opponent_domain=domain_a,
        player_cards=cards_b,
        opponent_cards=cards_a,
        build_a=build_b,
        build_b=build_a,
        selected_slot_a=selected_slot_b,
        selected_slot_b=selected_slot_a,
        strategy_key_a=strategy_key_b,
        strategy_key_b=strategy_key_a,
    )
    fresh_a['battle_session_id'] = row['id']
    fresh_b['battle_session_id'] = row['id']
    fresh_a['requires_ready'] = False
    fresh_b['requires_ready'] = False
    conn.execute(
        'UPDATE battle_sessions SET payload_a_json = ?, payload_b_json = ?, started_at = ?, updated_at = ? WHERE id = ?',
        (
            json.dumps(fresh_a, ensure_ascii=False),
            json.dumps(fresh_b, ensure_ascii=False),
            now_iso(),
            now_iso(),
            row['id'],
        ),
    )
    return fresh_a, fresh_b


def finalize_battle_session_by_id(session_id):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
        if row is None:
            raise ValueError('Боевая сессия не найдена.')
        payload_a = json.loads(row['payload_a_json']) if row['payload_a_json'] else {}
        needs_finalize = bool(row['ready_a']) and bool(row['ready_b']) and bool(payload_a.get('requires_ready', True))
        if needs_finalize:
            finalize_battle_session(conn, row)
            conn.commit()
            row = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
    return row


def mark_battle_ready(session_id, wallet, selected_slot=None, strategy_key=None):
    def mark_once():
        should_finalize_local = False
        with closing(get_db()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row_local = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
            if row_local is None:
                raise ValueError('Боевая сессия не найдена.')
            if wallet not in {row_local['wallet_a'], row_local['wallet_b']}:
                raise ValueError('Нет доступа к этой сессии.')
            is_a = wallet == row_local['wallet_a']
            payload_key = 'payload_a_json' if is_a else 'payload_b_json'
            current_payload = json.loads(row_local[payload_key]) if row_local[payload_key] else {}
            if selected_slot:
                current_payload['selected_slot'] = int(selected_slot)
            if strategy_key is not None:
                current_payload['strategy_key'] = normalize_strategy_key(strategy_key)
            if selected_slot or strategy_key is not None:
                conn.execute(
                    f'UPDATE battle_sessions SET {payload_key} = ?, updated_at = ? WHERE id = ?',
                    (json.dumps(current_payload, ensure_ascii=False), now_iso(), session_id),
                )
            if is_a:
                conn.execute('UPDATE battle_sessions SET ready_a = 1, updated_at = ? WHERE id = ?', (now_iso(), session_id))
            else:
                conn.execute('UPDATE battle_sessions SET ready_b = 1, updated_at = ? WHERE id = ?', (now_iso(), session_id))
            row_local = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
            if row_local and row_local['started_at'] is None and row_local['ready_a'] and row_local['ready_b']:
                claimed = conn.execute(
                    'UPDATE battle_sessions SET started_at = ?, updated_at = ? WHERE id = ? AND started_at IS NULL',
                    (now_iso(), now_iso(), session_id),
                )
                should_finalize_local = claimed.rowcount == 1
                row_local = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
            conn.commit()
        return row_local, should_finalize_local

    row, should_finalize = run_with_sqlite_retry(mark_once, attempts=5, base_delay=0.05)
    if should_finalize:
        row = run_with_sqlite_retry(lambda: finalize_battle_session_by_id(session_id), attempts=5, base_delay=0.08)
    return battle_session_snapshot(row, wallet)


def get_battle_ready_status(session_id, wallet):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
    if row is None:
        raise ValueError('Боевая сессия не найдена.')
    if wallet not in {row['wallet_a'], row['wallet_b']}:
        raise ValueError('Нет доступа к этой сессии.')
    try:
        payload_a = json.loads(row['payload_a_json']) if row['payload_a_json'] else {}
    except json.JSONDecodeError:
        payload_a = {}
    should_heal = bool(row['ready_a']) and bool(row['ready_b']) and bool(payload_a.get('requires_ready', True))
    if should_heal:
        try:
            row = run_with_sqlite_retry(lambda: finalize_battle_session_by_id(session_id), attempts=3, base_delay=0.08)
        except sqlite3.OperationalError:
            pass
    return battle_session_snapshot(row, wallet)


def latest_matchmaking_row(conn, wallet, mode):
    return conn.execute(
        '''
        SELECT * FROM matchmaking_queue
        WHERE wallet = ? AND mode = ?
        ORDER BY created_at DESC
        LIMIT 1
        ''',
        (wallet, mode),
    ).fetchone()


def upsert_searching_matchmaking(conn, wallet, domain, mode, selected_slot=None):
    ts = now_iso()
    existing = conn.execute(
        '''
        SELECT * FROM matchmaking_queue
        WHERE wallet = ? AND mode = ? AND status = 'searching'
        ORDER BY created_at DESC
        LIMIT 1
        ''',
        (wallet, mode),
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE matchmaking_queue SET domain = ?, selected_slot = ?, updated_at = ? WHERE id = ?',
            (domain, selected_slot, ts, existing['id']),
        )
        return existing['id']
    queue_id = uuid.uuid4().hex
    conn.execute(
        '''
        INSERT INTO matchmaking_queue (
            id, mode, wallet, domain, selected_slot, status, opponent_wallet, result_json, created_at, updated_at, consumed_at
        ) VALUES (?, ?, ?, ?, ?, 'searching', NULL, NULL, ?, ?, NULL)
        ''',
        (queue_id, mode, wallet, domain, selected_slot, ts, ts),
    )
    return queue_id


def settle_matchmaking_pair(mode, wallet, domain, opponent_row, selected_slot=None):
    opponent_wallet = opponent_row['wallet']
    opponent_domain = opponent_row['domain']
    cards_a = load_active_deck_cards(wallet, domain) or generate_pack(domain)
    cards_b = load_active_deck_cards(opponent_wallet, opponent_domain) or generate_pack(opponent_domain)
    cards_a = [normalize_card_profile(card) for card in cards_a]
    cards_b = [normalize_card_profile(card) for card in cards_b]
    build_a = load_deck_build(wallet, domain, cards_a)
    build_b = load_deck_build(opponent_wallet, opponent_domain, cards_b)
    selected_slot_a = selected_slot or auto_tactical_slot(cards_a, build_a['points'])
    selected_slot_b = opponent_row['selected_slot'] or auto_tactical_slot(cards_b, build_b['points'])
    own_payload = build_ready_match_payload(
        mode=mode,
        viewer_wallet=wallet,
        viewer_domain=domain,
        opponent_wallet=opponent_wallet,
        opponent_domain=opponent_domain,
        player_cards=cards_a,
        opponent_cards=cards_b,
        player_build_points=build_a['points'],
        opponent_build_points=build_b['points'],
        selected_slot=selected_slot_a,
        opponent_selected_slot=selected_slot_b,
        strategy_key='balanced',
        opponent_strategy_key='balanced',
    )
    opp_payload = build_ready_match_payload(
        mode=mode,
        viewer_wallet=opponent_wallet,
        viewer_domain=opponent_domain,
        opponent_wallet=wallet,
        opponent_domain=domain,
        player_cards=cards_b,
        opponent_cards=cards_a,
        player_build_points=build_b['points'],
        opponent_build_points=build_a['points'],
        selected_slot=selected_slot_b,
        opponent_selected_slot=selected_slot_a,
        strategy_key='balanced',
        opponent_strategy_key='balanced',
    )
    ts = now_iso()
    queue_id = uuid.uuid4().hex
    with closing(get_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute(
            'SELECT * FROM matchmaking_queue WHERE id = ?',
            (opponent_row['id'],),
        ).fetchone()
        if (
            current is None
            or current['status'] != 'pairing'
            or current['opponent_wallet'] != wallet
        ):
            conn.rollback()
            return None
        _, own_payload, opp_payload = create_battle_session(conn, wallet, opponent_wallet, own_payload, opp_payload)
        set_matchmaking_cooldown(conn, wallet, opponent_wallet)
        conn.execute(
            '''
            UPDATE matchmaking_queue
            SET status = 'matched', opponent_wallet = ?, result_json = ?, updated_at = ?
            WHERE id = ? AND status = 'pairing'
            ''',
            (wallet, json.dumps(opp_payload, ensure_ascii=False), ts, opponent_row['id']),
        )
        conn.execute(
            '''
            INSERT INTO matchmaking_queue (
                id, mode, wallet, domain, selected_slot, status, opponent_wallet, result_json, created_at, updated_at, consumed_at
            ) VALUES (?, ?, ?, ?, NULL, 'matched', ?, ?, ?, ?, NULL)
            ''',
            (queue_id, mode, wallet, domain, opponent_wallet, json.dumps(own_payload, ensure_ascii=False), ts, ts),
        )
        conn.commit()
    return queue_id, own_payload, opponent_wallet


def finalize_invite(invite):
    return accept_duel_invite(invite['id'], invite['invitee_wallet'])


def set_invite_status(invite_id, status):
    with closing(get_db()) as conn:
        conn.execute(
            'UPDATE duel_invites SET status = ?, responded_at = ? WHERE id = ?',
            (status, now_iso(), invite_id),
        )
        conn.commit()
    return load_invite(invite_id)


def accept_duel_invite(invite_id, invitee_wallet):
    with closing(get_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM duel_invites WHERE id = ?', (invite_id,)).fetchone()
        if row is None:
            raise ValueError('Приглашение не найдено.')
        invite = dict(row)
        if invite['invitee_wallet'] != invitee_wallet:
            raise ValueError('Это приглашение адресовано не вам.')
        if invite['status'] == 'pending' and parse_iso(invite['expires_at']) <= now_utc():
            conn.execute(
                'UPDATE duel_invites SET status = ?, responded_at = ? WHERE id = ?',
                ('expired', now_iso(), invite_id),
            )
            conn.commit()
            raise ValueError('Время на принятие приглашения истекло.')
        if invite['status'] == 'accepted' and invite.get('result_json'):
            conn.commit()
            return load_invite(invite_id)
        if invite['status'] not in {'pending', 'pairing'}:
            conn.commit()
            raise ValueError(f'Приглашение уже {invite["status"]}.')
        if invite['status'] == 'pending':
            claimed = conn.execute(
                'UPDATE duel_invites SET status = ?, responded_at = ? WHERE id = ? AND status = ?',
                ('pairing', None, invite_id, 'pending'),
            )
            if claimed.rowcount != 1:
                conn.commit()
                raise ValueError('Приглашение уже обновлено, обнови статус и попробуй снова.')
        conn.commit()

    inviter_cards = load_active_deck_cards(invite['inviter_wallet'], invite['inviter_domain']) or generate_pack(invite['inviter_domain'])
    invitee_cards = load_active_deck_cards(invite['invitee_wallet'], invite['invitee_domain']) or generate_pack(invite['invitee_domain'])
    inviter_cards = [normalize_card_profile(card) for card in inviter_cards]
    invitee_cards = [normalize_card_profile(card) for card in invitee_cards]
    inviter_build = load_deck_build(invite['inviter_wallet'], invite['inviter_domain'], inviter_cards)
    invitee_build = load_deck_build(invite['invitee_wallet'], invite['invitee_domain'], invitee_cards)
    inviter_slot = auto_tactical_slot(inviter_cards, inviter_build['points'])
    invitee_slot = auto_tactical_slot(invitee_cards, invitee_build['points'])
    inviter_payload = build_ready_match_payload(
        mode=invite['mode'],
        viewer_wallet=invite['inviter_wallet'],
        viewer_domain=invite['inviter_domain'],
        opponent_wallet=invite['invitee_wallet'],
        opponent_domain=invite['invitee_domain'],
        player_cards=inviter_cards,
        opponent_cards=invitee_cards,
        player_build_points=inviter_build['points'],
        opponent_build_points=invitee_build['points'],
        selected_slot=inviter_slot,
        opponent_selected_slot=invitee_slot,
        strategy_key='balanced',
        opponent_strategy_key='balanced',
    )
    invitee_payload = build_ready_match_payload(
        mode=invite['mode'],
        viewer_wallet=invite['invitee_wallet'],
        viewer_domain=invite['invitee_domain'],
        opponent_wallet=invite['inviter_wallet'],
        opponent_domain=invite['inviter_domain'],
        player_cards=invitee_cards,
        opponent_cards=inviter_cards,
        player_build_points=invitee_build['points'],
        opponent_build_points=inviter_build['points'],
        selected_slot=invitee_slot,
        opponent_selected_slot=inviter_slot,
        strategy_key='balanced',
        opponent_strategy_key='balanced',
    )

    with closing(get_db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT * FROM duel_invites WHERE id = ?', (invite_id,)).fetchone()
        if current is None:
            raise ValueError('Приглашение не найдено.')
        if current['status'] == 'accepted' and current['result_json']:
            conn.commit()
            return load_invite(invite_id)
        if current['status'] != 'pairing':
            conn.commit()
            raise ValueError(f'Приглашение уже {current["status"]}.')
        _, inviter_payload, invitee_payload = create_battle_session(
            conn,
            invite['inviter_wallet'],
            invite['invitee_wallet'],
            inviter_payload,
            invitee_payload,
        )
        result_json = {'for_inviter': inviter_payload, 'for_invitee': invitee_payload}
        conn.execute(
            'UPDATE duel_invites SET status = ?, responded_at = ?, result_json = ? WHERE id = ?',
            ('accepted', now_iso(), json.dumps(result_json, ensure_ascii=False), invite_id),
        )
        conn.commit()
    return load_invite(invite_id)


def respond_duel_invite(wallet, invite_id, action):
    action = (action or '').strip().lower()
    if action not in {'accept', 'decline'}:
        raise ValueError('Некорректное действие для приглашения.')
    invite = expire_invite_if_needed(load_invite(invite_id))
    if invite['invitee_wallet'] != wallet:
        raise ValueError('Это приглашение адресовано другому игроку.')
    if action == 'decline':
        if invite['status'] != 'pending':
            raise ValueError(f'Приглашение уже {invite["status"]}.')
        invite = set_invite_status(invite_id, 'declined')
        inviter_link = telegram_wallet_link(invite['inviter_wallet'])
        if inviter_link:
            try:
                telegram_send_message(inviter_link['chat_id'], f'Соперник отклонил приглашение {invite_id}.')
            except Exception:
                pass
        return invite, None
    invite = accept_duel_invite(invite_id, wallet)
    result = invite['result_json']['for_invitee'] if invite.get('result_json') else None
    inviter_link = telegram_wallet_link(invite['inviter_wallet'])
    invitee_link = telegram_wallet_link(invite['invitee_wallet'])
    if inviter_link:
        try:
            telegram_send_message(
                inviter_link['chat_id'],
                f'Приглашение {invite_id} принято. Открой mini app и нажми «Готов», чтобы запустить матч.',
            )
        except Exception:
            pass
    if invitee_link:
        try:
            telegram_send_message(
                invitee_link['chat_id'],
                f'Вы приняли приглашение {invite_id}. Открой mini app и нажми «Готов».',
            )
        except Exception:
            pass
    return invite, result


def room_snapshot(room_id, viewer_wallet=None):
    with closing(get_db()) as conn:
        room = conn.execute('SELECT * FROM team_rooms WHERE id = ?', (room_id,)).fetchone()
        if room is None:
            raise ValueError('Комната не найдена.')
        players = conn.execute(
            'SELECT * FROM team_room_players WHERE room_id = ? ORDER BY joined_at ASC',
            (room_id,),
        ).fetchall()

    return {
        'id': room['id'],
        'owner_wallet': room['owner_wallet'],
        'max_players': room['max_players'],
        'status': room['status'],
        'is_owner': viewer_wallet == room['owner_wallet'],
        'players': [dict(player) for player in players],
    }


def create_team_room(wallet, domain, username, max_players):
    room_id = uuid.uuid4().hex[:6].upper()
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT INTO team_rooms (id, owner_wallet, max_players, status, created_at) VALUES (?, ?, ?, ?, ?)',
            (room_id, wallet, max_players, 'waiting', now_iso()),
        )
        conn.execute(
            'INSERT INTO team_room_players (room_id, wallet, username, domain, joined_at) VALUES (?, ?, ?, ?, ?)',
            (room_id, wallet, username, domain, now_iso()),
        )
        conn.commit()
    return room_snapshot(room_id, wallet)


def join_team_room(room_id, wallet, domain, username):
    with closing(get_db()) as conn:
        room = conn.execute('SELECT * FROM team_rooms WHERE id = ?', (room_id,)).fetchone()
        if room is None:
            raise ValueError('Комната не найдена.')
        if room['status'] != 'waiting':
            raise ValueError('Матч в этой комнате уже завершён.')
        players = conn.execute('SELECT COUNT(*) AS total FROM team_room_players WHERE room_id = ?', (room_id,)).fetchone()
        if players['total'] >= room['max_players']:
            raise ValueError('Комната уже заполнена.')

        existing = conn.execute(
            'SELECT * FROM team_room_players WHERE room_id = ? AND wallet = ?',
            (room_id, wallet),
        ).fetchone()
        if existing is None:
            conn.execute(
                'INSERT INTO team_room_players (room_id, wallet, username, domain, joined_at) VALUES (?, ?, ?, ?, ?)',
                (room_id, wallet, username, domain, now_iso()),
            )
            conn.commit()
    return room_snapshot(room_id, wallet)


def start_team_room(room_id, requester_wallet):
    snapshot = room_snapshot(room_id, requester_wallet)
    if not snapshot['is_owner']:
        raise ValueError('Запустить матч может только создатель комнаты.')
    if snapshot['status'] != 'waiting':
        raise ValueError('Матч уже завершён.')
    if len(snapshot['players']) < 2:
        raise ValueError('Для командного матча нужно минимум 2 игрока.')

    teams = [
        {'name': TEAM_NAMES[0], 'players': [], 'score': 0},
        {'name': TEAM_NAMES[1], 'players': [], 'score': 0},
    ]

    for index, player in enumerate(snapshot['players']):
        team = teams[index % 2]
        cards = load_active_deck_cards(player['wallet'], player['domain']) or generate_pack(player['domain'])
        total = deck_score(cards)
        team['players'].append(
            {
                'wallet': player['wallet'],
                'username': player['username'],
                'domain': player['domain'],
                'deck_score': total,
            }
        )
        team['score'] += total

    winner = teams[0]['name'] if teams[0]['score'] >= teams[1]['score'] else teams[1]['name']

    with closing(get_db()) as conn:
        conn.execute('UPDATE team_rooms SET status = ? WHERE id = ?', ('completed', room_id))
        conn.commit()

    return room_snapshot(room_id, requester_wallet), {
        'kind': 'team',
        'winner': winner,
        'teams': teams,
    }


def telegram_api(method, payload):
    if not TG_BOT_TOKEN:
        raise RuntimeError('TG_BOT_TOKEN не настроен.')
    url = f'https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}'
    response = HTTP.post(url, json=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError(data.get('description', 'Telegram API error'))
    return data


def telegram_send_message(chat_id, text, reply_markup=None):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'disable_web_page_preview': True,
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    telegram_api('sendMessage', payload)


def telegram_answer_callback(callback_query_id, text, show_alert=False):
    telegram_api(
        'answerCallbackQuery',
        {
            'callback_query_id': callback_query_id,
            'text': text,
            'show_alert': show_alert,
        },
    )


def telegram_clear_inline_keyboard(chat_id, message_id):
    telegram_api(
        'editMessageReplyMarkup',
        {
            'chat_id': chat_id,
            'message_id': message_id,
            'reply_markup': {'inline_keyboard': []},
        },
    )


def telegram_welcome_markup():
    if not TG_WEBAPP_URL:
        return None
    return {
        'keyboard': [[{'text': 'Open tondomaingame', 'web_app': {'url': TG_WEBAPP_URL}}]],
        'resize_keyboard': True,
    }


def handle_invite_callback(callback_query):
    callback_id = callback_query.get('id')
    from_user = callback_query.get('from') or {}
    message = callback_query.get('message') or {}
    chat_id = (message.get('chat') or {}).get('id')
    data = callback_query.get('data') or ''
    if ':' not in data:
        telegram_answer_callback(callback_id, 'Неизвестное действие.', True)
        return

    action, invite_id = data.split(':', 1)
    try:
        invite = expire_invite_if_needed(load_invite(invite_id))
    except ValueError:
        telegram_answer_callback(callback_id, 'Приглашение не найдено.', True)
        return

    invitee_link = telegram_wallet_link(invite['invitee_wallet'])
    if invitee_link is None or invitee_link['telegram_user_id'] != from_user.get('id'):
        telegram_answer_callback(callback_id, 'Это приглашение адресовано не вам.', True)
        return

    if invite['status'] != 'pending':
        telegram_answer_callback(callback_id, f'Приглашение уже {invite["status"]}.', True)
        return

    if action == 'invite_decline':
        try:
            invite, _ = respond_duel_invite(invite['invitee_wallet'], invite_id, 'decline')
        except ValueError as exc:
            telegram_answer_callback(callback_id, str(exc), True)
            return
        if chat_id and invite['telegram_message_id']:
            telegram_clear_inline_keyboard(chat_id, invite['telegram_message_id'])
        telegram_answer_callback(callback_id, 'Приглашение отклонено.')
        return

    if action == 'invite_accept':
        try:
            invite, _ = respond_duel_invite(invite['invitee_wallet'], invite_id, 'accept')
        except ValueError as exc:
            telegram_answer_callback(callback_id, str(exc), True)
            return
        if chat_id and invite['telegram_message_id']:
            telegram_clear_inline_keyboard(chat_id, invite['telegram_message_id'])
        telegram_answer_callback(callback_id, 'Вызов принят. Открой mini app и нажми «Готов».')
        return

    telegram_answer_callback(callback_id, 'Неизвестное действие.', True)


def handle_telegram_message(message):
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if not chat_id:
        return

    from_user = message.get('from') or {}
    if from_user:
        upsert_telegram_user(from_user, chat_id)

    text = (message.get('text') or '').strip()
    web_app_data = (message.get('web_app_data') or {}).get('data')

    if web_app_data:
        try:
            payload = json.loads(web_app_data)
        except json.JSONDecodeError:
            payload = {'raw': web_app_data}
        telegram_send_message(
            chat_id,
            'Получен результат из mini app:\n' + json.dumps(payload, ensure_ascii=False, indent=2),
        )
        return

    if text.startswith('/start link_') and not text.startswith('/start link_wallet'):
        if not from_user or not from_user.get('id'):
            telegram_send_message(chat_id, 'Не удалось определить Telegram-пользователя. Попробуй снова.')
            return
        wallet = text.replace('/start', '', 1).strip()[5:].strip()
        if not valid_wallet_address(wallet):
            telegram_send_message(
                chat_id,
                'Не удалось прочитать кошелёк из ссылки. Используй команду /link_wallet <ton_wallet>.',
                telegram_welcome_markup(),
            )
            return
        try:
            ensure_player(wallet)
            link_wallet_to_telegram(wallet, from_user.get('id'))
        except ValueError as exc:
            telegram_send_message(chat_id, str(exc), telegram_welcome_markup())
            return
        telegram_send_message(
            chat_id,
            f'Кошелёк {wallet[:6]}...{wallet[-6:]} успешно привязан. Можешь возвращаться в игру.',
            telegram_welcome_markup(),
        )
        return

    if text.startswith('/start link_wallet'):
        telegram_send_message(
            chat_id,
            'Для привязки Telegram к игре используй команду:\n/link_wallet <ton_wallet>\n\nПример:\n/link_wallet EQC...',
            telegram_welcome_markup(),
        )
        return

    if text.startswith('/start') or text.startswith('/app'):
        telegram_send_message(
            chat_id,
            'tondomaingame готов. Открой mini app кнопкой ниже, подключи TON-кошелёк и начинай матч.',
            telegram_welcome_markup(),
        )
        return

    if text.startswith('/link_wallet') or text.startswith('/link'):
        if not from_user or not from_user.get('id'):
            telegram_send_message(chat_id, 'Не удалось определить Telegram-пользователя. Попробуй ещё раз.')
            return
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            link = telegram_user_link(from_user.get('id')) if from_user.get('id') else None
            linked_wallet = link['wallet'] if link and link.get('wallet') else None
            suffix = f'\nТекущий привязанный кошелёк: {linked_wallet}' if linked_wallet else ''
            telegram_send_message(
                chat_id,
                'Использование: /link_wallet <ton_wallet>\nПример: /link_wallet EQC...' + suffix,
            )
            return
        wallet = parts[1].strip()
        if not valid_wallet_address(wallet):
            telegram_send_message(chat_id, 'Некорректный TON-кошелёк. Проверь адрес и попробуй снова.')
            return
        try:
            ensure_player(wallet)
            link_wallet_to_telegram(wallet, from_user.get('id'))
        except ValueError as exc:
            telegram_send_message(chat_id, str(exc))
            return
        telegram_send_message(
            chat_id,
            f'Telegram успешно привязан к кошельку {wallet[:6]}...{wallet[-6:]}. Теперь можно получать приглашения.',
        )
        return

    if text.startswith('/leaderboard'):
        with closing(get_db()) as conn:
            rows = conn.execute(
                'SELECT wallet, rating, ranked_wins FROM players ORDER BY rating DESC, ranked_wins DESC LIMIT 5'
            ).fetchall()
        if not rows:
            telegram_send_message(chat_id, 'Рейтинг пока пуст.')
            return
        lines = ['Топ рейтинга:']
        for index, row in enumerate(rows, start=1):
            lines.append(f'{index}. {row["wallet"][:6]}...{row["wallet"][-6:]} — {row["rating"]}')
        telegram_send_message(chat_id, '\n'.join(lines))
        return

    if text.startswith('/rating'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            telegram_send_message(chat_id, 'Использование: /rating <wallet_address>')
            return
        wallet = parts[1].strip()
        if not valid_wallet_address(wallet):
            telegram_send_message(chat_id, 'Некорректный адрес кошелька.')
            return
        player = get_player(wallet)
        telegram_send_message(
            chat_id,
            f'Рейтинг кошелька {wallet[:6]}...{wallet[-6:]}: {player["rating"]}\nМатчей: {player["games_played"]}',
        )
        return

    telegram_send_message(
        chat_id,
        'Команды:\n/start\n/app\n/link_wallet <wallet>\n/leaderboard\n/rating <wallet>\n\nДля игры открой mini app.',
        telegram_welcome_markup(),
    )


@app.route('/')
def index():
    return render_template_string(
        PAGE_TEMPLATE,
        marketplace_links=MARKETPLACE_LINKS,
        telegram_bot_username=TG_BOT_USERNAME,
        telegram_webapp_url=TG_WEBAPP_URL,
    )


@app.route('/tonconnect-manifest.json')
def tonconnect_manifest():
    manifest = dict(TONCONNECT_MANIFEST)
    manifest['url'] = request.host_url.rstrip('/')
    return jsonify(manifest)


@app.route('/vendor/tonconnect-ui.min.js')
def tonconnect_vendor_script():
    cached_body = TONCONNECT_SCRIPT_CACHE.get('body')
    if cached_body:
        return Response(cached_body, mimetype=TONCONNECT_SCRIPT_CACHE.get('content_type') or 'application/javascript')

    sources = [
        'https://cdn.jsdelivr.net/npm/@tonconnect/ui@2.0.9/dist/tonconnect-ui.min.js',
        'https://unpkg.com/@tonconnect/ui@2.0.9/dist/tonconnect-ui.min.js',
    ]
    last_error = None
    for src in sources:
        try:
            response = HTTP.get(src, timeout=12)
            response.raise_for_status()
            body = response.text
            if body and 'TonConnectUI' in body:
                TONCONNECT_SCRIPT_CACHE['body'] = body
                TONCONNECT_SCRIPT_CACHE['content_type'] = response.headers.get('content-type', 'application/javascript; charset=utf-8')
                return Response(body, mimetype=TONCONNECT_SCRIPT_CACHE['content_type'])
        except Exception as exc:
            last_error = exc
            continue
    return Response(f'/* TonConnect load failed: {last_error} */', status=502, mimetype='application/javascript')


@app.route('/api/health')
def api_health():
    return jsonify({'ok': True, 'time': now_iso()})


@app.route('/api/player/<wallet>')
def api_player(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    return jsonify({'player': get_player(wallet)})


@app.route('/api/player/public/<wallet>')
def api_public_player(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    viewer_wallet = (request.args.get('viewer') or '').strip()
    if viewer_wallet and not valid_wallet_address(viewer_wallet):
        viewer_wallet = None
    return jsonify({'player': public_player_profile(wallet, viewer_wallet=viewer_wallet)})


@app.route('/api/player/register', methods=['POST'])
def api_player_register():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    ensure_player(wallet)
    return jsonify({'ok': True, 'player': get_player(wallet)})


@app.route('/api/profile', methods=['POST'])
def api_profile_update():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    ensure_player(wallet)
    nickname = clean_public_text(payload.get('nickname'), 24)
    bio = clean_public_text(payload.get('bio'), 160)
    profile_title = clean_public_text(payload.get('profile_title'), 40)
    favorite_ability = clean_public_text(payload.get('favorite_ability'), 24).lower() or None
    play_style = clean_public_text(payload.get('play_style'), 24).lower() or None
    favorite_strategy = clean_public_text(payload.get('favorite_strategy'), 24).lower() or None
    favorite_role = clean_public_text(payload.get('favorite_role'), 24).lower() or None
    profile_banner_key = clean_public_text(payload.get('profile_banner_key'), 64) or None
    profile_gift_source = clean_public_text(payload.get('profile_gift_source'), 24) or None
    profile_gift_key = clean_public_text(payload.get('profile_gift_key'), 128) or None
    language = clean_public_text(payload.get('language') or 'ru', 12) or 'ru'
    visibility = clean_public_text(payload.get('visibility') or 'public', 12) or 'public'
    valid_abilities = {'burst', 'guard', 'ability'}
    valid_play_styles = {'aggressive', 'balanced', 'control', 'tempo', 'fortune', 'trickster'}
    valid_strategies = {'attack_boost', 'defense_boost', 'energy_boost', 'aggressive', 'balanced', 'tricky'}
    valid_roles = {'tank', 'damage', 'control', 'support', 'trickster', 'guardian', 'fortune', 'combo', 'disruptor', 'sniper'}
    if favorite_ability not in valid_abilities:
        favorite_ability = None
    if play_style not in valid_play_styles:
        play_style = None
    if favorite_strategy not in valid_strategies:
        favorite_strategy = None
    if favorite_role not in valid_roles:
        favorite_role = None
    if profile_banner_key:
        owned_guild_keys = {
            item['key']
            for item in cosmetic_inventory(wallet)
            if item.get('type') == 'guild'
        }
        if profile_banner_key not in owned_guild_keys:
            return json_error('Баннер профиля должен быть открыт в инвентаре.')
    if profile_gift_source or profile_gift_key:
        available_gifts = available_profile_gifts(wallet)
        normalized_key = profile_gift_key or ''
        if normalized_key and ':' not in normalized_key and profile_gift_source:
            normalized_key = f'{profile_gift_source}:{normalized_key}'
        selected = next((item for item in available_gifts if item.get('key') == normalized_key), None)
        if not selected:
            return json_error('Выбранный подарок недоступен для профиля.')
        profile_gift_source = selected.get('source')
        profile_gift_key = selected.get('key')
    else:
        profile_gift_source = None
        profile_gift_key = None
    with closing(get_db()) as conn:
        ensure_player_profile_columns(conn)
        conn.execute(
            '''
            UPDATE player_profiles
            SET nickname = ?, avatar = ?, bio = ?, language = ?, visibility = ?,
                profile_title = ?, favorite_ability = ?, play_style = ?,
                favorite_strategy = ?, favorite_role = ?, profile_banner_key = ?,
                profile_gift_source = ?, profile_gift_key = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                nickname or None,
                '',
                bio or None,
                language,
                visibility,
                profile_title or None,
                favorite_ability,
                play_style,
                favorite_strategy,
                favorite_role,
                profile_banner_key,
                profile_gift_source,
                profile_gift_key,
                now_iso(),
                wallet,
            ),
        )
        conn.commit()
    return jsonify({'ok': True, 'player': get_player(wallet), 'social': social_overview(wallet)})


@app.route('/api/cosmetics/equip', methods=['POST'])
def api_cosmetics_equip():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    cosmetic_key = clean_public_text(payload.get('cosmetic_key') or '', 64)
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        inventory, equipped = equip_cosmetic(wallet, cosmetic_key)
    except ValueError as error:
        return json_error(str(error))
    return jsonify({
        'ok': True,
        'inventory': inventory,
        'equipped': equipped,
        'player': get_player(wallet),
    })


@app.route('/api/deck/<wallet>')
def api_deck(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    player = get_player(wallet)
    domain = player['current_domain'] or player['best_domain']
    if not domain:
        return json_error('У игрока ещё нет сохранённой колоды.', 404)
    summary = deck_summary_for_domain(domain, wallet)
    return jsonify({'wallet': wallet, 'domain': domain, 'deck': summary})


@app.route('/api/decks/<wallet>')
def api_decks(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    try:
        domains = wallet_domains_for_game(wallet, allow_fallback=True)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    player = ensure_player(wallet, domains[0]['domain'] if domains else None, None)
    available_domains = {item['domain'] for item in domains}
    preferred_current = player.get('current_domain')
    if preferred_current not in available_domains:
        preferred_current = latest_opened_domain_for_wallet(wallet)
    if preferred_current in available_domains and preferred_current != player.get('current_domain'):
        player = ensure_player(wallet, player.get('best_domain') or preferred_current, preferred_current)
    decks = []
    for item in domains:
        summary = deck_summary_for_domain(item['domain'], wallet)
        decks.append(
            {
                'domain': item['domain'],
                'tier': item.get('tier'),
                'rarity': item.get('rarity'),
                'luck': item.get('luck', 0),
                'score': item.get('score', summary['total_score']),
                'special_collections': item.get('special_collections') or [],
                'metadata': item.get('metadata') or summary.get('domain_metadata'),
                'deck': summary,
                'is_active': player.get('current_domain') == item['domain'],
            }
        )
    return jsonify({'wallet': wallet, 'current_domain': player.get('current_domain'), 'decks': decks})


@app.route('/api/deck/select', methods=['POST'])
def api_deck_select():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    if not domain:
        return json_error('Выбери домен для активной колоды.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не найден в подключённом кошельке.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    ensure_player(wallet, domain, domain)
    summary = deck_summary_for_domain(domain, wallet)
    return jsonify({'ok': True, 'wallet': wallet, 'domain': domain, 'deck': summary, 'player': get_player(wallet)})


@app.route('/api/deck-build')
def api_deck_build():
    wallet = (request.args.get('wallet') or '').strip()
    domain = normalize_domain(request.args.get('domain'))
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не найден в подключённом кошельке.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    cards = load_active_deck_cards(wallet, domain) or generate_pack(domain)
    cards = [normalize_card_profile(card) for card in cards]
    build = load_deck_build(wallet, domain, cards)
    return jsonify({'wallet': wallet, 'domain': domain, 'build': build, 'cards': cards})


@app.route('/api/deck-build', methods=['POST'])
def api_deck_build_save():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    points = payload.get('points') or {}
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не найден в подключённом кошельке.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    cards = load_active_deck_cards(wallet, domain) or generate_pack(domain)
    cards = [normalize_card_profile(card) for card in cards]
    build = save_deck_build(wallet, domain, cards, points)
    return jsonify({'ok': True, 'wallet': wallet, 'domain': domain, 'build': build})


@app.route('/api/deck/shuffle', methods=['POST'])
def api_deck_shuffle():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не найден в подключённом кошельке.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    cards = load_active_deck_cards(wallet, domain) or generate_pack(domain)
    cards = shuffle_deck_cards(cards, f'shuffle:{wallet}:{domain}:{now_iso()}')
    total = deck_score(cards)
    store_pack_open(wallet, domain, 'shuffle', cards, total)
    build = load_deck_build(wallet, domain, cards)
    deck = deck_summary_for_domain(domain, wallet)
    return jsonify({'ok': True, 'wallet': wallet, 'domain': domain, 'cards': cards, 'total_score': total, 'build': build, 'deck': deck})


@app.route('/api/telegram/link', methods=['POST'])
def api_telegram_link():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    init_data = (payload.get('init_data') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи TON-кошелёк.')
    if not init_data:
        return json_error('Привязка Telegram доступна только внутри Telegram mini app.')
    try:
        telegram_data = validate_telegram_init_data(init_data)
        user = telegram_data.get('user') or {}
        if user and user.get('id'):
            upsert_telegram_user(user, user['id'])
        link = link_wallet_to_telegram(wallet, user['id'])
        ensure_player(wallet)
    except (ValueError, KeyError) as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'telegram': link, 'player': get_player(wallet)})


@app.route('/api/telegram/site-link', methods=['POST'])
def api_telegram_site_link():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    telegram_payload = payload.get('telegram') or {}
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи TON-кошелёк.')
    try:
        telegram_user = validate_telegram_login_data(telegram_payload)
        upsert_telegram_user(telegram_user, telegram_user['id'])
        link = link_wallet_to_telegram(wallet, telegram_user['id'])
        ensure_player(wallet)
        try:
            telegram_send_message(link['chat_id'], f'Telegram привязан к кошельку {wallet[:6]}...{wallet[-6:]}. Уведомления активированы.')
        except Exception:
            pass
    except (ValueError, KeyError) as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'telegram': link, 'player': get_player(wallet), 'settings': telegram_notification_settings(wallet)})


@app.route('/api/telegram/notifications/<wallet>')
def api_telegram_notifications(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    ensure_player(wallet)
    return jsonify({'wallet': wallet, 'settings': telegram_notification_settings(wallet)})


@app.route('/api/telegram/notifications', methods=['POST'])
def api_telegram_notifications_update():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    ensure_player(wallet)
    field_map = {
        'duel_invites': 'notify_duel_invites',
        'daily_reward': 'notify_daily_reward',
        'win_quest': 'notify_win_quest',
        'guild_invites': 'notify_guild_invites',
        'guild_reward': 'notify_guild_reward',
        'season_pass': 'notify_season_pass',
    }
    updates = {}
    for public_key, db_key in field_map.items():
        if public_key in payload:
            updates[db_key] = 1 if payload.get(public_key) else 0
    settings = update_telegram_notification_settings(wallet, **updates)
    return jsonify({'ok': True, 'wallet': wallet, 'settings': settings})


@app.route('/api/leaderboard')
def api_leaderboard():
    with closing(get_db()) as conn:
        rows = conn.execute(
            '''
            SELECT wallet, rating, games_played, ranked_wins, ranked_losses, best_domain
            FROM players
            ORDER BY rating DESC, ranked_wins DESC, games_played DESC
            LIMIT 10
            '''
        ).fetchall()
    return jsonify({'players': [dict(row) for row in rows]})


@app.route('/api/active-users')
def api_active_users():
    return jsonify({'players': active_users()})


@app.route('/api/players/global')
def api_players_global():
    return jsonify({'players': global_player_rows()})


@app.route('/api/achievements/<wallet>')
def api_achievements(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    ensure_player(wallet)
    return jsonify({'wallet': wallet, 'achievements': achievements_for_wallet(wallet)})


@app.route('/api/friends/<wallet>')
def api_friends(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    return jsonify({'friends': friend_rows(wallet)})


@app.route('/api/tutorial/<wallet>')
def api_tutorial(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    return jsonify({'wallet': wallet, 'tutorial': tutorial_summary(wallet)})


@app.route('/api/tutorial/skip', methods=['POST'])
def api_tutorial_skip():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    return jsonify({'ok': True, 'tutorial': mark_tutorial_skipped(wallet), 'player': get_player(wallet)})


@app.route('/api/tutorial/start', methods=['POST'])
def api_tutorial_start():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    selected_slot = int(payload.get('selected_slot') or 0) or None
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не принадлежит подключённому кошельку.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    tutorial = tutorial_summary(wallet)
    if tutorial.get('completed'):
        return json_error('Туториал уже завершён.', 400)
    player_cards = load_active_deck_cards(wallet, domain) or generate_pack(domain)
    player_cards = [normalize_card_profile(card) for card in player_cards]
    player_build = load_deck_build(wallet, domain, player_cards)
    base_seed = f'tutorial:{wallet}:{domain}:{today_utc_str()}'
    tutorial_cards = player_cards[:3]
    bot_cards = bot_cards_slightly_weaker_than_player(player_cards, base_seed)
    bot_cards = [dict(card, pool_value=max(42, int(card.get('pool_value', 0) * 0.8))) for card in bot_cards[:3]]
    tutorial_slot = selected_slot or auto_tactical_slot(tutorial_cards, player_build['points'])
    if not any(int(card.get('slot', 0)) == int(tutorial_slot) for card in tutorial_cards):
        tutorial_slot = int((tutorial_cards[0] or {}).get('slot', 1))
    tutorial_meta = tutorial_config_for_domain(battle_domain_metadata(domain, wallet=wallet), tutorial_slot)
    tutorial_meta['current_tip'] = tutorial_meta['tips'][0]
    mark_tutorial_started(wallet)
    log_domain_telemetry('tutorial_start', wallet=wallet, domain=domain, payload={'slot': tutorial_slot})
    result = create_solo_battle(
        wallet=wallet,
        domain=domain,
        mode='tutorial',
        mode_title='Боевой туториал',
        opponent_wallet='bot',
        opponent_domain=None,
        player_cards=tutorial_cards,
        opponent_cards=bot_cards,
        build_a=player_build['points'],
        build_b=default_discipline_build(max(1100, int(player_build['pool'] * 0.62))),
        selected_slot_a=tutorial_slot,
        selected_slot_b=weakest_tactical_slot(bot_cards),
        strategy_key_a='balanced',
        strategy_key_b='balanced',
        tutorial=tutorial_meta,
    )
    return jsonify({'result': result, 'player': get_player(wallet), 'tutorial': tutorial_summary(wallet)})


@app.route('/api/friends', methods=['POST'])
def api_add_friend():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    reference = (payload.get('reference') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        friend_wallet = add_friend(wallet, reference)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'friend_wallet': friend_wallet, 'friends': friend_rows(wallet)})


@app.route('/api/social/<wallet>')
def api_social(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    return jsonify({'wallet': wallet, 'social': social_overview(wallet)})


@app.route('/api/friends/request', methods=['POST'])
def api_friend_request():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    reference = (payload.get('reference') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        friend_wallet = send_friend_request(wallet, reference)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'friend_wallet': friend_wallet, 'social': social_overview(wallet)})


@app.route('/api/friends/respond', methods=['POST'])
def api_friend_request_respond():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    request_id = (payload.get('request_id') or '').strip()
    action = (payload.get('action') or '').strip().lower()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    if action not in {'accept', 'decline'}:
        return json_error('Некорректное действие.')
    try:
        sender_wallet = respond_friend_request(wallet, request_id, action)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'sender_wallet': sender_wallet, 'social': social_overview(wallet)})


@app.route('/api/friends/remove', methods=['POST'])
def api_friend_remove():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    reference = (payload.get('reference') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        friend_wallet = remove_friend(wallet, reference)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'friend_wallet': friend_wallet, 'social': social_overview(wallet)})


@app.route('/api/blocks', methods=['POST'])
def api_block_player():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    reference = (payload.get('reference') or '').strip()
    unblock = bool(payload.get('unblock'))
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        target_wallet = unblock_player(wallet, reference) if unblock else block_player(wallet, reference)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'target_wallet': target_wallet, 'social': social_overview(wallet)})


@app.route('/api/report', methods=['POST'])
def api_report_player():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    reference = (payload.get('reference') or '').strip()
    scope = (payload.get('scope') or 'general').strip()
    reason = payload.get('reason') or ''
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        target_wallet = create_player_report(wallet, reference, scope, reason)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'target_wallet': target_wallet})


@app.route('/api/lobby-chat', methods=['GET', 'POST'])
def api_lobby_chat():
    if request.method == 'GET':
        return jsonify({'messages': lobby_messages()})
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        messages = post_lobby_message(wallet, payload.get('message'))
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'messages': messages})


@app.route('/api/guilds/overview/<wallet>')
def api_guilds_overview(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    return jsonify({'wallet': wallet, 'guilds': guild_overview_for_wallet(wallet, request.args.get('q', ''))})


@app.route('/api/guilds/create', methods=['POST'])
def api_guilds_create():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        guild = create_guild(
            wallet,
            payload.get('name'),
            payload.get('description') or '',
            payload.get('language') or 'ru',
            payload.get('is_public', True),
        )
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'guild': guild, 'player': get_player(wallet), 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/guilds/apply', methods=['POST'])
def api_guilds_apply():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    guild_id = (payload.get('guild_id') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        guild = apply_to_guild(wallet, guild_id, payload.get('message') or '')
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'guild': guild, 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/guilds/request/respond', methods=['POST'])
def api_guilds_request_respond():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    request_id = (payload.get('request_id') or '').strip()
    action = (payload.get('action') or '').strip().lower()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    if action not in {'accept', 'decline'}:
        return json_error('Некорректное действие.')
    try:
        guild = respond_to_guild_request(wallet, request_id, action)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'guild': guild, 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/guilds/invite', methods=['POST'])
def api_guilds_invite():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    guild_id = (payload.get('guild_id') or '').strip()
    reference = (payload.get('reference') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        guild = invite_to_guild(wallet, guild_id, reference)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'guild': guild, 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/guilds/invite/respond', methods=['POST'])
def api_guilds_invite_respond():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    invite_id = (payload.get('invite_id') or '').strip()
    action = (payload.get('action') or '').strip().lower()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    if action not in {'accept', 'decline'}:
        return json_error('Некорректное действие.')
    try:
        guild = respond_to_guild_invite(wallet, invite_id, action)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'guild': guild, 'player': get_player(wallet), 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/guilds/chat', methods=['POST'])
def api_guilds_chat():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    guild_id = (payload.get('guild_id') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        chat = post_guild_message(wallet, guild_id, payload.get('message'))
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'chat': chat, 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/guilds/announcement', methods=['POST'])
def api_guilds_announcement():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    guild_id = (payload.get('guild_id') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    try:
        announcements = post_guild_announcement(wallet, guild_id, payload.get('message'))
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'announcements': announcements, 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/guilds/member/role', methods=['POST'])
def api_guilds_member_role():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    guild_id = (payload.get('guild_id') or '').strip()
    target_wallet = (payload.get('target_wallet') or '').strip()
    role = (payload.get('role') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи кошелёк.')
    if not valid_wallet_address(target_wallet):
        return json_error('Некорректный адрес участника.')
    try:
        guild = update_guild_member_role(wallet, guild_id, target_wallet, role)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'guild': guild, 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/wallet/domains', methods=['POST'])
@limiter.limit('15/minute')
def api_wallet_domains():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Укажи корректный TON-кошелёк.')
    try:
        domains = wallet_domains_for_game(wallet, force_refresh=True, allow_fallback=True)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    available_domains = {item['domain'] for item in domains}
    preferred_current = latest_opened_domain_for_wallet(wallet)
    if preferred_current not in available_domains:
        preferred_current = None
    ensure_player(wallet, domains[0]['domain'] if domains else None, preferred_current)
    return jsonify({'wallet': wallet, 'domains': domains, 'marketplaces': MARKETPLACE_LINKS})


@app.route('/api/domain/explain')
def api_domain_explain():
    domain = normalize_domain(request.args.get('domain'))
    wallet = (request.args.get('wallet') or '').strip() or None
    if not domain:
        return json_error('Нужен 4-значный .ton домен.')
    try:
        progress = load_domain_progress(wallet, domain) if wallet else None
        payload = explainDomainUniqueness(domain, progress=progress)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify(payload)


@app.route('/api/pack', methods=['POST'])
def api_pack():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    source = (payload.get('source') or 'daily').strip().lower()
    payment_id = (payload.get('payment_id') or '').strip()
    pack_type = str(payload.get('pack_type') or ('common' if source == 'daily' else ('lucky' if source == 'paid' else 'common'))).strip().lower()
    if not valid_wallet_address(wallet):
        return json_error('Кошелёк не подключен.')
    if not domain:
        return json_error('Нужно выбрать реальный домен.')
    if source not in {'daily', 'paid', 'reward'}:
        return json_error('Неизвестный тип открытия пака.')
    if pack_type not in PACK_TYPES:
        return json_error('Неизвестный тип пака.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Выбранный домен не найден в подключённом кошельке.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)

    if source == 'daily' and not can_open_daily_pack(wallet, domain):
        return json_error('Ежедневный пак уже открыт. Попробуй снова завтра или открой платный пак.', 403)
    if source == 'daily' and pack_type != 'common':
        return json_error('Ежедневное открытие работает только для обычного пака.', 400)
    if pack_type == 'cosmetic' and source != 'reward':
        return json_error('Косметический пак открывается только из наград.', 400)

    if source == 'paid':
        if not payment_id:
            return json_error('Нужен подтверждённый платёж для открытия платного пака.', 403)
        with closing(get_db()) as conn:
            payment = conn.execute('SELECT * FROM pack_payments WHERE id = ?', (payment_id,)).fetchone()
        if payment is None or payment['wallet'] != wallet or payment['domain'] != domain or payment['status'] != 'confirmed':
            return json_error('Платёж не подтверждён.', 403)
        pack_type = str(pack_type or 'lucky').strip().lower()

    rewards = reward_summary(wallet)
    if source == 'reward':
        try:
            rewards = spend_pack_currency(wallet, pack_type)
        except ValueError as exc:
            return json_error(str(exc), 400)

    seed = f'{domain}:{wallet}:{source}:{payment_id or now_iso()}'
    guarantee_legendary = pack_pity_status(wallet, pack_type) >= PACK_PITY_THRESHOLD - 1 if pack_type != 'cosmetic' else False
    cosmetic_reward = None
    if pack_type == 'cosmetic':
        selected = draw_cosmetic_pack_item(f'{seed}:cosmetic')
        if not selected:
            return json_error('Каталог косметики недоступен.', 500)
        grant_cosmetic(wallet, selected['key'], 'cosmetic_pack')
        cosmetic_reward = {
            'key': selected['key'],
            'name': selected['name'],
            'type': selected['type'],
            'emoji': selected.get('emoji'),
            'rarity_key': cosmetic_item_rarity(selected),
        }
        cards = [{
            'domain': domain,
            'slot': 1,
            'title': selected['name'],
            'rarity': cosmetic_item_rarity(selected).capitalize(),
            'rarity_key': cosmetic_item_rarity(selected),
            'pool_value': 0,
            'base_power': 0,
            'ability': f'Открыт предмет: {selected["name"]}',
            'skill_name': selected['type'],
        }]
        total = 0
    else:
        cards = generate_pack(domain, seed_value=seed, pack_type=pack_type, guarantee_legendary=guarantee_legendary, wallet=wallet)
        total = deck_score(cards)
    pack_id = store_pack_open(wallet, domain, source, cards, total, payment_id=payment_id or None)
    ensure_player(wallet, domain, domain)
    pity_after = update_pack_pity(wallet, pack_type, cards) if pack_type != 'cosmetic' else 0
    progress = grant_domain_experience(wallet, domain, 12 if source == 'paid' else 6, won=False)
    metadata = get_domain_metadata_payload(domain, wallet=wallet)
    log_domain_telemetry(
        'pack_open',
        wallet=wallet,
        domain=domain,
        rarity_label=metadata.get('rarityLabel') if metadata else None,
        payload={
            'source': source,
            'pack_type': pack_type,
            'guarantee_legendary': guarantee_legendary,
            'pity_after': pity_after,
            'total_score': total,
            'rarities': [card.get('rarity_key') for card in cards],
            'cosmetic_reward': cosmetic_reward,
        },
    )
    rewards = reward_summary(wallet)
    return jsonify(
        {
            'wallet': wallet,
            'domain': domain,
            'cards': cards,
            'total_score': total,
            'pack_id': pack_id,
            'source': source,
            'pack_type': pack_type,
            'guarantee_legendary': guarantee_legendary,
            'pity_after': pity_after,
            'cosmetic_reward': cosmetic_reward,
            'domain_metadata': metadata,
            'progress': progress,
            'rewards': rewards,
        }
    )


@app.route('/api/deck/restore-previous', methods=['POST'])
def api_restore_previous_deck():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    if not valid_wallet_address(wallet):
        return json_error('Кошелёк не подключен.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Выбранный домен не найден в подключённом кошельке.', 403)
        restored = restore_previous_deck_cards(wallet, domain)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except (RuntimeError, OSError) as exc:
        return json_error(str(exc), 502)
    return jsonify(
        {
            'wallet': wallet,
            'domain': domain,
            'cards': restored['cards'],
            'total_score': restored['total_score'],
            'pack_id': restored['pack_id'],
        }
    )


@app.route('/api/cards/catalog')
def api_cards_catalog():
    skill_strengths = {
        'underdog': 'когда твоя карта слабее или бой идет тяжело',
        'tempo': 'после проигранного раунда и в длинных сериях',
        'mirror': 'против более сильной карты соперника',
        'attack_burst': 'в агрессивных разменах и на добивании',
        'defense_lock': 'против натиска и быстрых атак',
        'wildcard': 'в рискованных и непредсказуемых раундах',
        'anchor': 'в ровных защитных разменах и тяжелых матчапах',
        'overclock': 'в темпе, скорости и к финалу матча',
        'oracle': 'в чтении контров и рискованных раундах',
        'reactor': 'когда нужно усилить уже сильную карту и дожать перевес',
    }
    skills = [
        {
            'key': skill['key'],
            'name': skill['name'],
            'description': skill['description'],
            'strong_against': skill_strengths.get(skill['key'], 'в ситуативных разменах'),
        }
        for skill in CARD_SKILLS
    ]
    pack_sort_order = {'common': 0, 'rare': 1, 'epic': 2, 'lucky': 3, 'cosmetic': 4}
    pack_types = sorted([
        {
            'key': key,
            'label': value['label'],
            'count': value['count'],
            'weights': value['weights'],
            'lucky_bonus': bool(value.get('lucky_bonus')),
            'costs': value.get('costs') or {},
        }
        for key, value in PACK_TYPES.items()
    ], key=lambda item: pack_sort_order.get(item['key'], 99))
    return jsonify({'cards': CARD_CATALOG, 'skills': skills, 'pack_types': pack_types, 'pity_threshold': PACK_PITY_THRESHOLD, 'total': len(CARD_CATALOG)})


@app.route('/api/telemetry/<wallet>')
def api_domain_telemetry(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    return jsonify({'wallet': wallet, 'summary': telemetry_summary(wallet=wallet)})


@app.route('/api/rewards/<wallet>')
def api_rewards(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    ensure_player(wallet)
    return jsonify({'wallet': wallet, 'rewards': reward_summary(wallet)})


@app.route('/api/rewards/daily', methods=['POST'])
def api_rewards_daily():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    try:
        rewards = claim_daily_reward(wallet)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'wallet': wallet, 'rewards': rewards})


@app.route('/api/rewards/quest', methods=['POST'])
def api_rewards_quest():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    try:
        rewards = claim_win_quest_reward(wallet)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'wallet': wallet, 'rewards': rewards})


@app.route('/api/rewards/season-pass-claim', methods=['POST'])
def api_rewards_season_pass_claim():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    reward_tier = (payload.get('tier') or '').strip().lower()
    try:
        level = int(payload.get('level'))
    except (TypeError, ValueError):
        return json_error('Нужен корректный уровень пропуска.', 400)
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    try:
        rewards = claim_season_pass_reward(wallet, level, reward_tier)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'wallet': wallet, 'rewards': rewards})


@app.route('/api/rewards/season-task', methods=['POST'])
def api_rewards_season_task():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    task_key = (payload.get('task_key') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    try:
        rewards = claim_season_task_reward(wallet, task_key)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'wallet': wallet, 'rewards': rewards})


@app.route('/api/pack/payment-intent', methods=['POST'])
def api_pack_payment_intent():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи TON-кошелёк.')
    if not domain:
        return json_error('Выбери домен перед оплатой.')
    if not PACK_RECEIVER_WALLET:
        return json_error('Не настроен адрес получателя платежа (PACK_RECEIVER_WALLET).', 500)
    payment_id, memo = create_pack_payment(wallet, domain)
    return jsonify(
        {
            'ok': True,
            'payment_id': payment_id,
            'amount_nano': PACK_PRICE_NANO,
            'amount_ton': PACK_PRICE_NANO / 1_000_000_000,
            'receiver_wallet': PACK_RECEIVER_WALLET,
            'memo': memo,
            'payload_base64': base64.b64encode(memo.encode()).decode(),
            'valid_until': int(now_utc().timestamp()) + 600,
        }
    )


@app.route('/api/pack/payment-confirm', methods=['POST'])
def api_pack_payment_confirm():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    payment_id = (payload.get('payment_id') or '').strip()
    tx_hash = (payload.get('tx_hash') or '').strip() or None
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи TON-кошелёк.')
    if not payment_id:
        return json_error('Не указан payment_id.')
    try:
        payment = confirm_pack_payment(payment_id, wallet, tx_hash=tx_hash)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'payment': payment})


@app.route('/api/pass/payment-intent', methods=['POST'])
def api_pass_payment_intent():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи TON-кошелёк.')
    if not SEASON_PASS_RECEIVER_WALLET:
        return json_error('Не настроен адрес получателя оплаты пропуска.', 500)
    rewards = reward_summary(wallet)
    if rewards.get('premium_pass_active'):
        return json_error('Премиум-пропуск уже активен.')
    payment_id, memo = create_season_pass_payment(wallet)
    return jsonify(
        {
            'ok': True,
            'payment_id': payment_id,
            'amount_nano': SEASON_PASS_PRICE_NANO,
            'amount_ton': SEASON_PASS_PRICE_NANO / 1_000_000_000,
            'receiver_wallet': SEASON_PASS_RECEIVER_WALLET,
            'memo': memo,
            'payload_base64': base64.b64encode(memo.encode()).decode(),
            'valid_until': int(now_utc().timestamp()) + 600,
        }
    )


@app.route('/api/pass/payment-confirm', methods=['POST'])
def api_pass_payment_confirm():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    payment_id = (payload.get('payment_id') or '').strip()
    tx_hash = (payload.get('tx_hash') or '').strip() or None
    if not valid_wallet_address(wallet):
        return json_error('Сначала подключи TON-кошелёк.')
    if not payment_id:
        return json_error('Не указан payment_id.')
    try:
        payment, rewards = confirm_season_pass_payment(payment_id, wallet, tx_hash=tx_hash)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'payment': payment, 'rewards': rewards})


@app.route('/api/guilds/reward/claim', methods=['POST'])
def api_guild_reward_claim():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    guild_id = (payload.get('guild_id') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not guild_id:
        return json_error('Не указан guild_id.')
    try:
        rewards = claim_guild_weekly_reward(wallet, guild_id)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'rewards': rewards, 'guilds': guild_overview_for_wallet(wallet)})


@app.route('/api/matchmaking/<mode>/search', methods=['POST'])
@limiter.exempt
def api_matchmaking_search(mode):
    if mode not in {'ranked', 'casual'}:
        return json_error('Неизвестный режим матчмейкинга.', 404)
    ensure_runtime_tables()

    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    selected_slot = int(payload.get('selected_slot') or 0) or None
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не принадлежит подключённому кошельку.', 403)
        ensure_player(wallet, domain, domain)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502 if isinstance(exc, RuntimeError) else 400)

    def search_once():
        with closing(get_db()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            cleanup_matchmaking_queue(conn)
            latest = latest_matchmaking_row(conn, wallet, mode)
            if latest and latest['status'] == 'matched' and latest['result_json'] and not latest['consumed_at']:
                result = json.loads(latest['result_json'])
                conn.execute(
                    "UPDATE matchmaking_queue SET consumed_at = ?, status = 'completed', updated_at = ? WHERE id = ?",
                    (now_iso(), now_iso(), latest['id']),
                )
                conn.commit()
                return {'status': 'matched', 'result': result}

            opponents = conn.execute(
                '''
                SELECT * FROM matchmaking_queue
                WHERE mode = ?
                  AND status = 'searching'
                  AND wallet != ?
                ORDER BY created_at ASC
                LIMIT 25
                ''',
                (mode, wallet),
            ).fetchall()

            opponent = None
            min_cooldown = 0
            for candidate in opponents:
                cooldown_left = matchmaking_cooldown_left(conn, wallet, candidate['wallet'])
                if cooldown_left <= 0:
                    opponent = candidate
                    break
                if min_cooldown == 0 or cooldown_left < min_cooldown:
                    min_cooldown = cooldown_left

            if opponent:
                ts = now_iso()
                claimed = conn.execute(
                    '''
                    UPDATE matchmaking_queue
                    SET status = 'pairing', opponent_wallet = ?, updated_at = ?
                    WHERE id = ? AND status = 'searching'
                    ''',
                    (wallet, ts, opponent['id']),
                )
                if claimed.rowcount == 1:
                    conn.commit()
                    try:
                        settled = settle_matchmaking_pair(mode, wallet, domain, opponent, selected_slot=selected_slot)
                    except sqlite3.Error:
                        conn.execute(
                            '''
                            UPDATE matchmaking_queue
                            SET status = 'searching', opponent_wallet = NULL, updated_at = ?
                            WHERE id = ? AND status = 'pairing'
                            ''',
                            (now_iso(), opponent['id']),
                        )
                        conn.commit()
                        raise
                    if settled is not None:
                        queue_id, own_payload, opponent_wallet = settled
                        return {
                            'status': 'matched',
                            'queue_id': queue_id,
                            'opponent_wallet': opponent_wallet,
                            'result': own_payload,
                        }
                    conn.execute(
                        '''
                        UPDATE matchmaking_queue
                        SET status = 'searching', opponent_wallet = NULL, updated_at = ?
                        WHERE id = ? AND status = 'pairing'
                        ''',
                        (now_iso(), opponent['id']),
                    )

            queue_id = upsert_searching_matchmaking(conn, wallet, domain, mode, selected_slot=selected_slot)
            conn.commit()
            response = {'status': 'searching', 'queue_id': queue_id}
            if min_cooldown > 0:
                response['cooldown_seconds'] = min_cooldown
            return response

    try:
        response = run_with_sqlite_retry(search_once, attempts=6, base_delay=0.06)
        response['player'] = get_player(wallet)
        return jsonify(response)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка очереди матчмейкинга: {exc}', 500)


@app.route('/api/matchmaking/<mode>/status')
@limiter.exempt
def api_matchmaking_status(mode):
    if mode not in {'ranked', 'casual'}:
        return json_error('Неизвестный режим матчмейкинга.', 404)
    ensure_runtime_tables()
    wallet = (request.args.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно передать свой кошелёк.')
    def status_once():
        with closing(get_db()) as conn:
            cleanup_matchmaking_queue(conn)
            row = latest_matchmaking_row(conn, wallet, mode)
            if row is None:
                return {'status': 'idle'}
            if row['status'] == 'searching':
                waited = int(max(0, now_utc().timestamp() - parse_iso(row['created_at']).timestamp()))
                opponents = conn.execute(
                    '''
                    SELECT wallet FROM matchmaking_queue
                    WHERE mode = ? AND status = 'searching' AND wallet != ?
                    ORDER BY created_at ASC
                    LIMIT 25
                    ''',
                    (mode, wallet),
                ).fetchall()
                min_cooldown = 0
                for candidate in opponents:
                    cooldown_left = matchmaking_cooldown_left(conn, wallet, candidate['wallet'])
                    if cooldown_left > 0 and (min_cooldown == 0 or cooldown_left < min_cooldown):
                        min_cooldown = cooldown_left
                response = {'status': 'searching', 'waited_seconds': waited}
                if min_cooldown > 0:
                    response['cooldown_seconds'] = min_cooldown
                return response
            if row['status'] == 'matched' and row['result_json']:
                result = json.loads(row['result_json'])
                conn.execute('BEGIN IMMEDIATE')
                conn.execute(
                    "UPDATE matchmaking_queue SET consumed_at = ?, status = 'completed', updated_at = ? WHERE id = ?",
                    (now_iso(), now_iso(), row['id']),
                )
                conn.commit()
                return {'status': 'matched', 'result': result}
            return {'status': row['status']}

    try:
        response = run_with_sqlite_retry(status_once, attempts=6, base_delay=0.06)
        if response.get('status') == 'matched':
            response['player'] = get_player(wallet)
        return jsonify(response)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка очереди матчмейкинга: {exc}', 500)


@app.route('/api/matchmaking/<mode>/cancel', methods=['POST'])
@limiter.exempt
def api_matchmaking_cancel(mode):
    if mode not in {'ranked', 'casual'}:
        return json_error('Неизвестный режим матчмейкинга.', 404)
    ensure_runtime_tables()
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    def cancel_once():
        with closing(get_db()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(
                '''
                UPDATE matchmaking_queue
                SET status = 'cancelled', updated_at = ?
                WHERE wallet = ? AND mode = ? AND status = 'searching'
                ''',
                (now_iso(), wallet, mode),
            )
            conn.commit()

    try:
        run_with_sqlite_retry(cancel_once, attempts=6, base_delay=0.06)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка отмены поиска: {exc}', 500)
    return jsonify({'ok': True, 'status': 'cancelled'})


@app.route('/api/battle-ready', methods=['POST'])
@limiter.exempt
def api_battle_ready():
    ensure_runtime_tables()
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    session_id = (payload.get('session_id') or '').strip()
    selected_slot = int(payload.get('selected_slot') or 0) or None
    strategy_key = payload.get('strategy_key') or 'balanced'
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not session_id:
        return json_error('Не указан session_id.')
    try:
        status = mark_battle_ready(session_id, wallet, selected_slot=selected_slot, strategy_key=strategy_key)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка боевой сессии: {exc}', 500)
    return jsonify({'ok': True, 'status': status})


@app.route('/api/battle-ready/status')
@limiter.exempt
def api_battle_ready_status():
    ensure_runtime_tables()
    wallet = (request.args.get('wallet') or '').strip()
    session_id = (request.args.get('session_id') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно передать кошелёк.')
    if not session_id:
        return json_error('Не указан session_id.')
    try:
        status = get_battle_ready_status(session_id, wallet)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка статуса боевой сессии: {exc}', 500)
    return jsonify({'status': status})


@app.route('/api/match/<mode>', methods=['POST'])
def api_match(mode):
    if mode != 'duel':
        return json_error('Неизвестный режим.', 404)

    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    opponent_reference = (payload.get('opponent_wallet') or '').strip()
    timeout_seconds = payload.get('timeout_seconds') or DEFAULT_INVITE_TIMEOUT_SECONDS
    delivery = (payload.get('delivery') or 'site').strip().lower()
    selected_slot = int(payload.get('selected_slot') or 0) or None

    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    if valid_wallet_address(opponent_reference):
        return json_error('Для дуэли укажи ник или .ton домен соперника (кошелёк отключён в этом режиме).', 400)
    try:
        opponent_wallet = resolve_player_reference(opponent_reference)
        if opponent_wallet == wallet:
            return json_error('Нельзя отправить вызов самому себе.')
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не принадлежит подключённому кошельку.', 403)
        ensure_player(wallet, domain, domain)

        opponent_player = ensure_player(opponent_wallet)
        opponent_domain = opponent_player.get('current_domain') or opponent_player.get('best_domain')
        if not opponent_domain:
            return json_error('У соперника ещё нет выбранного домена для боя.', 400)

        if delivery == 'site':
            player_cards = load_active_deck_cards(wallet, domain) or generate_pack(domain)
            player_cards = [normalize_card_profile(card) for card in player_cards]
            opponent_cards = load_active_deck_cards(opponent_wallet, opponent_domain) or generate_pack(opponent_domain)
            opponent_cards = [normalize_card_profile(card) for card in opponent_cards]
            player_build = load_deck_build(wallet, domain, player_cards)
            opponent_build = load_deck_build(opponent_wallet, opponent_domain, opponent_cards)
            selected_slot = selected_slot or auto_tactical_slot(player_cards, player_build['points'])
            result = create_solo_battle(
                wallet=wallet,
                domain=domain,
                mode='duel',
                mode_title='Дуэль',
                opponent_wallet=opponent_wallet,
                opponent_domain=opponent_domain,
                player_cards=player_cards,
                opponent_cards=opponent_cards,
                build_a=player_build['points'],
                build_b=opponent_build['points'],
                selected_slot_a=selected_slot,
                selected_slot_b=auto_tactical_slot(opponent_cards, opponent_build['points']),
                strategy_key_a='balanced',
                strategy_key_b='balanced',
            )
            return jsonify({'result': result, 'player': get_player(wallet), 'delivery': 'site'})

        invite = create_duel_invite('duel', wallet, domain, opponent_wallet, timeout_seconds)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502 if isinstance(exc, RuntimeError) else 400)

    return jsonify({'invite': invite, 'player': get_player(wallet), 'delivery': 'telegram'})


@app.route('/api/match/bot', methods=['POST'])
def api_match_bot():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    selected_slot = int(payload.get('selected_slot') or 0) or None
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не принадлежит подключённому кошельку.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)

    player_cards = load_active_deck_cards(wallet, domain) or generate_pack(domain)
    player_cards = [normalize_card_profile(card) for card in player_cards]
    player_build = load_deck_build(wallet, domain, player_cards)
    bot_progress = player_bot_progress(wallet)
    bot_difficulty_level = int(bot_progress.get('difficulty_level', 0) or 0)
    base_seed = f'bot-duel:{wallet}:{domain}:{now_iso()}'
    bot_cards = bot_cards_slightly_weaker_than_player(player_cards, base_seed, difficulty_level=bot_difficulty_level)
    pool_scale = {0: 0.86, 1: 0.92, 2: 0.98, 3: 1.04, 4: 1.08}.get(bot_difficulty_level, 0.92)
    bot_pool_floor = {0: 1750, 1: 1880, 2: 1980, 3: 2080, 4: 2180}.get(bot_difficulty_level, 1880)
    bot_pool = max(bot_pool_floor, int(round(player_build['pool'] * pool_scale)))
    bot_build = {'pool': bot_pool, 'points': default_discipline_build(bot_pool)}
    selected_slot = selected_slot or auto_tactical_slot(player_cards, player_build['points'])
    bot_strategy_key = 'balanced'
    if bot_difficulty_level >= 4:
        bot_strategy_key = 'attack_boost'
    elif bot_difficulty_level >= 2:
        bot_strategy_key = 'defense_boost'
    result = create_solo_battle(
        wallet=wallet,
        domain=domain,
        mode='bot',
        mode_title='Матч с ботом',
        opponent_wallet='bot',
        opponent_domain=None,
        player_cards=player_cards,
        opponent_cards=bot_cards,
        build_a=player_build['points'],
        build_b=bot_build['points'],
        selected_slot_a=selected_slot,
        selected_slot_b=bot_selected_slot(bot_cards, bot_difficulty_level),
        strategy_key_a='balanced',
        strategy_key_b=bot_strategy_key,
        bot_difficulty_level=bot_difficulty_level,
    )
    result['bot_difficulty'] = {
        'level': bot_difficulty_level,
        'player_bot_win_streak': int(bot_progress.get('current_win_streak', 0) or 0),
    }
    return jsonify(
        {
            'result': result,
            'bot_cards': bot_cards,
            'bot_difficulty': result['bot_difficulty'],
            'player': get_player(wallet),
        }
    )


@app.route('/api/match/one-card', methods=['POST'])
def api_match_one_card():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    card_slot = int(payload.get('card_slot') or 0)
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    if card_slot < 1 or card_slot > 5:
        return json_error('Нужно выбрать карту из слотов 1-5.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не принадлежит подключённому кошельку.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)

    cards = load_active_deck_cards(wallet, domain) or generate_pack(domain)
    cards = [normalize_card_profile(card) for card in cards]
    player_card = next((card for card in cards if card['slot'] == card_slot), None)
    if player_card is None:
        return json_error('Карта не найдена в колоде.', 400)
    bot_card = normalize_card_profile(random_bot_single_card(f'onecard:{wallet}:{domain}:{now_iso()}'))
    player_build = load_deck_build(wallet, domain, cards)
    bot_pool = 2200
    bot_build = {'pool': bot_pool, 'points': default_discipline_build(bot_pool)}
    result = create_solo_battle(
        wallet=wallet,
        domain=domain,
        mode='onecard',
        mode_title='Дуэль одной картой',
        opponent_wallet='bot',
        opponent_domain=None,
        player_cards=[player_card],
        opponent_cards=[bot_card],
        build_a=player_build['points'],
        build_b=bot_build['points'],
        selected_slot_a=player_card['slot'],
        selected_slot_b=bot_card['slot'],
        strategy_key_a='balanced',
        strategy_key_b='balanced',
    )
    return jsonify(
        {
            'result': result,
            'player': get_player(wallet),
        }
    )


@app.route('/api/solo-battle/action', methods=['POST'])
def api_solo_battle_action():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    session_id = (payload.get('session_id') or '').strip()
    action_key = payload.get('action') or 'channel'
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not session_id:
        return json_error('Не указан session_id.')
    try:
        result = apply_solo_battle_action(session_id, wallet, action_key)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'result': result, 'player': get_player(wallet)})


@app.route('/api/solo-battle/status')
@limiter.exempt
def api_solo_battle_status():
    wallet = (request.args.get('wallet') or '').strip()
    session_id = (request.args.get('session_id') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not session_id:
        return json_error('Не указан session_id.')
    try:
        state = load_solo_battle(session_id)
    except ValueError as exc:
        return json_error(str(exc), 404)
    if wallet != state.get('wallet'):
        return json_error('Нет доступа к этому бою.', 403)
    return jsonify({'result': build_solo_live_payload(state)})


@app.route('/api/match-invite/<invite_id>')
@limiter.exempt
def api_match_invite(invite_id):
    wallet = (request.args.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно передать свой кошелёк.')
    try:
        invite = run_with_sqlite_retry(
            lambda: expire_invite_if_needed(load_invite(invite_id)),
            attempts=4,
            base_delay=0.06,
        )
    except ValueError as exc:
        return json_error(str(exc), 404)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка чтения приглашения: {exc}', 500)

    if wallet not in {invite['inviter_wallet'], invite['invitee_wallet']}:
        return json_error('Нет доступа к этому приглашению.', 403)

    result = None
    if invite['result_json']:
        result = invite['result_json']['for_inviter'] if wallet == invite['inviter_wallet'] else invite['result_json']['for_invitee']

    return jsonify({'invite': invite, 'result': result, 'player': get_player(wallet)})


@app.route('/api/match-invite/respond', methods=['POST'])
@limiter.exempt
def api_match_invite_respond():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    invite_id = (payload.get('invite_id') or '').strip().upper()
    action = (payload.get('action') or '').strip().lower()
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not invite_id:
        return json_error('Не указан invite_id.')
    if action not in {'accept', 'decline'}:
        return json_error('Некорректное действие.')
    try:
        invite, result = run_with_sqlite_retry(
            lambda: respond_duel_invite(wallet, invite_id, action),
            attempts=5,
            base_delay=0.06,
        )
    except ValueError as exc:
        return json_error(str(exc), 400)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка обработки приглашения: {exc}', 500)
    response = {
        'ok': True,
        'invite': invite,
        'player': get_player(wallet),
        'social': social_overview(wallet),
    }
    if result:
        response['result'] = result
    return jsonify(response)


@app.route('/api/team-room/create', methods=['POST'])
def api_team_room_create():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    username = (payload.get('username') or '').strip() or wallet[:6]
    max_players = int(payload.get('max_players') or 2)

    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    if max_players < 2 or max_players > 4:
        return json_error('Командный режим поддерживает от 2 до 4 игроков.')

    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Командную комнату можно создать только с реальным доменом из кошелька.', 403)
        room = create_team_room(wallet, domain, username, max_players)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502 if isinstance(exc, RuntimeError) else 400)

    return jsonify({'room': room})


@app.route('/api/team-room/join', methods=['POST'])
def api_team_room_join():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    username = (payload.get('username') or '').strip() or wallet[:6]
    room_id = (payload.get('room_id') or '').strip().upper()

    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    if not room_id:
        return json_error('Укажи код комнаты.')

    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Подключённый домен не найден в кошельке.', 403)
        room = join_team_room(room_id, wallet, domain, username)
    except RuntimeError as exc:
        return json_error(str(exc), 502)
    except ValueError as exc:
        return json_error(str(exc), 400)

    return jsonify({'room': room})


@app.route('/api/team-room/<room_id>')
def api_team_room(room_id):
    wallet = (request.args.get('wallet') or '').strip()
    try:
        room = room_snapshot(room_id.upper(), wallet)
    except ValueError as exc:
        return json_error(str(exc), 404)
    return jsonify({'room': room})


@app.route('/api/team-room/start', methods=['POST'])
def api_team_room_start():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    room_id = (payload.get('room_id') or '').strip().upper()
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not room_id:
        return json_error('Не указан код комнаты.')
    try:
        room, result = start_team_room(room_id, wallet)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return jsonify({'room': room, 'result': result})


@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    if TG_WEBHOOK_SECRET:
        header_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if header_secret != TG_WEBHOOK_SECRET:
            return json_error('Unauthorized', 403)

    update = request.get_json(silent=True) or {}
    message = update.get('message')
    callback_query = update.get('callback_query')
    if message:
        try:
            handle_telegram_message(message)
        except Exception as exc:  # pragma: no cover
            return json_error(str(exc), 500)
    if callback_query:
        try:
            handle_invite_callback(callback_query)
        except Exception as exc:  # pragma: no cover
            return json_error(str(exc), 500)
    return jsonify({'ok': True})


@app.route('/telegram/setup')
def telegram_setup():
    if not TG_SETUP_TOKEN:
        return json_error('TG_SETUP_TOKEN не настроен.', 400)
    if request.args.get('token') != TG_SETUP_TOKEN:
        return json_error('Неверный setup token.', 403)
    if not TG_BOT_TOKEN:
        return json_error('TG_BOT_TOKEN не настроен.', 400)

    webhook_url = request.host_url.rstrip('/') + '/telegram/webhook'
    payload = {'url': webhook_url}
    if TG_WEBHOOK_SECRET:
        payload['secret_token'] = TG_WEBHOOK_SECRET
    result = telegram_api('setWebhook', payload)
    return jsonify({'ok': True, 'webhook_url': webhook_url, 'telegram': result})


@app.route('/telegram/dispatch')
def telegram_dispatch():
    if not TG_SETUP_TOKEN:
        return json_error('TG_SETUP_TOKEN не настроен.', 400)
    if request.args.get('token') != TG_SETUP_TOKEN:
        return json_error('Неверный dispatch token.', 403)
    telegram_notification_scan_once()
    return jsonify({'ok': True, 'scanned': len(telegram_notification_wallets())})


init_db()
ensure_telegram_notification_worker()


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'settings':
        raise SystemExit(handle_settings_cli(sys.argv[2:]))
    app.run(host=HOST, port=PORT, debug=DEBUG)
