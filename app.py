import hashlib
import hmac
import json
import os
import random
import re
import sqlite3
import sys
import uuid
import calendar
import base64
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
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
MATCHMAKING_SEARCH_TTL_SECONDS = int(os.getenv('MATCHMAKING_SEARCH_TTL_SECONDS', '180'))
MATCHMAKING_REMATCH_COOLDOWN_SECONDS = int(os.getenv('MATCHMAKING_REMATCH_COOLDOWN_SECONDS', '5'))
DB_PATH = Path(os.getenv('APP_DB_PATH', 'tondomaingame.db'))
TEN_K_CONFIG_TTL = int(os.getenv('TEN_K_CONFIG_TTL', '900'))
TEN_K_CONFIG_URL = 'https://10kclub.com/api/clubs/10k/config'
DAILY_FREE_PACKS = int(os.getenv('DAILY_FREE_PACKS', '1'))
PACK_PRICE_NANO = int(os.getenv('PACK_PRICE_NANO', '1000000000'))  # 1 TON
PACK_RECEIVER_WALLET = os.getenv('PACK_RECEIVER_WALLET', '').strip()
ALLOW_GUEST_WITHOUT_DOMAIN = os.getenv('ALLOW_GUEST_WITHOUT_DOMAIN', '0').strip().lower() in {'1', 'true', 'yes', 'on'}
ENV_FILE_PATH = Path(os.getenv('ENV_FILE_PATH', '.env'))
PACK_PITY_THRESHOLD = int(os.getenv('PACK_PITY_THRESHOLD', '20'))

DOMAIN_CACHE = {}
TEN_K_CONFIG_CACHE = {'config': None, 'expires_at': 0.0}

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
}

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
  <script src="https://unpkg.com/@tonconnect/ui@2.0.9/dist/tonconnect-ui.min.js"></script>
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
      max-width: 1240px;
      margin: 0 auto;
      padding: 28px 18px 64px;
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

    .hero p {
      margin: 0;
      max-width: 720px;
      color: var(--muted);
      font-size: 17px;
      line-height: 1.6;
    }

    .badge-row, .stepper, .stats-strip, .links-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .badge, .step-chip, .stat-chip, .market-link {
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.04);
      padding: 9px 14px;
      font-size: 14px;
      color: var(--muted);
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
      background:
        radial-gradient(circle at 50% 22%, rgba(69, 215, 255, 0.16), transparent 30%),
        radial-gradient(circle at 50% 70%, rgba(83, 246, 184, 0.08), transparent 42%),
        linear-gradient(180deg, rgba(7, 18, 33, 0.98), rgba(3, 10, 20, 0.98));
      box-shadow: inset 0 0 0 1px rgba(121, 217, 255, 0.06);
      padding: 16px;
    }

    .arena-shell {
      display: grid;
      gap: 14px;
      --arena-columns: 5;
      --arena-gap: 8px;
      --arena-card-width: calc((100% - (var(--arena-gap) * (var(--arena-columns) - 1))) / var(--arena-columns));
    }

    .arena-rail {
      display: grid;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background: rgba(8, 20, 36, 0.88);
      box-shadow: inset 0 0 0 1px rgba(121, 217, 255, 0.04);
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

    .arena-core {
      position: relative;
      min-height: 332px;
      border-radius: 26px;
      border: 1px solid rgba(121, 217, 255, 0.16);
      background:
        radial-gradient(circle at 50% 50%, rgba(14, 44, 55, 0.44), transparent 42%),
        linear-gradient(180deg, rgba(6, 14, 26, 0.98), rgba(3, 9, 18, 0.98));
      box-shadow:
        inset 0 0 0 1px rgba(255, 255, 255, 0.02),
        inset 0 0 90px rgba(0, 0, 0, 0.18);
      overflow: hidden;
      isolation: isolate;
    }

    .arena-core::before {
      content: "";
      position: absolute;
      inset: 16px;
      border-radius: 20px;
      border: 1px solid rgba(255, 211, 110, 0.08);
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
      stroke: rgba(255, 211, 110, 0.7);
      stroke-width: 2.2;
      stroke-linecap: round;
      stroke-dasharray: 5 10;
      filter: drop-shadow(0 0 6px rgba(255, 211, 110, 0.18));
      animation: arenaDashFlow 2.4s linear infinite;
      opacity: 0.84;
    }

    .arena-route-path.alt {
      stroke: rgba(69, 215, 255, 0.52);
      stroke-dasharray: 4 11;
      animation-duration: 2.8s;
    }

    .arena-route-path.active {
      stroke: rgba(83, 246, 184, 0.9);
      stroke-width: 3;
      filter: drop-shadow(0 0 10px rgba(83, 246, 184, 0.24));
    }

    .arena-choice-hub {
      position: relative;
      z-index: 1;
      min-height: 332px;
      display: grid;
      place-items: center;
      padding: 8px 10px 10px;
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

    .arena-round-choice-strip {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 2;
    }

    .arena-round-choice-slot {
      position: absolute;
      top: 68px;
      transform: translateX(-50%);
      display: grid;
      justify-items: center;
      gap: 8px;
      min-width: 40px;
      pointer-events: none;
    }

    .arena-round-choice-slot.active {
      z-index: 3;
      gap: 24px;
    }

    .arena-round-marker {
      width: 16px;
      height: 16px;
      padding: 0;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(8, 19, 34, 0.94);
      box-shadow: 0 8px 18px rgba(0, 0, 0, 0.16);
      pointer-events: none;
    }

    .arena-round-choice-slot.resolved .arena-round-marker {
      border-color: rgba(255, 211, 110, 0.24);
      color: #ffe59d;
    }

    .arena-round-choice-slot.active .arena-round-marker {
      border-color: rgba(83, 246, 184, 0.42);
      box-shadow: 0 0 0 1px rgba(83, 246, 184, 0.12), 0 10px 20px rgba(0, 0, 0, 0.18);
    }

    .arena-round-state {
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.03);
      color: rgba(213, 235, 255, 0.72);
      font-size: 11px;
      letter-spacing: 0.04em;
      white-space: nowrap;
      pointer-events: none;
      position: relative;
      z-index: 4;
    }

    .arena-round-state.win {
      border-color: rgba(83, 246, 184, 0.34);
      background: rgba(83, 246, 184, 0.12);
      color: #dfffee;
    }

    .arena-round-state.lose {
      border-color: rgba(255, 122, 134, 0.34);
      background: rgba(255, 122, 134, 0.12);
      color: #ffe0e5;
    }

    .arena-round-state.draw {
      border-color: rgba(255, 211, 110, 0.34);
      background: rgba(255, 211, 110, 0.12);
      color: #ffe9ad;
    }

    .arena-round-choice-slot.active .arena-lane-choice-panel {
      margin-top: 24px;
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

    .arena-lane-card strong {
      display: block;
      margin-bottom: 5px;
      font-size: 12px;
      line-height: 1.1;
    }

    .arena-lane-card .arena-slot-meta {
      font-size: 9px;
      line-height: 1.18;
      opacity: 0.9;
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

    .arena-action-sticker svg {
      width: 18px;
      height: 18px;
      display: block;
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
      border: 1px solid rgba(255, 211, 110, 0.34);
      background: rgba(255, 211, 110, 0.1);
      color: #ffe59d;
      font-weight: 800;
      letter-spacing: 0.04em;
      box-shadow: 0 10px 24px rgba(255, 211, 110, 0.1);
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
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      font-weight: 800;
      opacity: 0;
      transform: translateY(12px) scale(0.94);
      transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease, opacity 220ms ease;
    }

    .interactive-action-btn:hover,
    .interactive-action-btn:active {
      transform: translateY(-1px) scale(1.01);
      box-shadow: 0 12px 28px rgba(69, 215, 255, 0.18);
    }

    .interactive-action-btn.burst {
      border-color: rgba(255, 122, 134, 0.42);
      background: linear-gradient(135deg, rgba(255, 122, 134, 0.18), rgba(255, 255, 255, 0.04));
    }

    .interactive-action-btn.guard {
      border-color: rgba(83, 246, 184, 0.42);
      background: linear-gradient(135deg, rgba(83, 246, 184, 0.18), rgba(255, 255, 255, 0.04));
    }

    .interactive-action-btn.channel,
    .interactive-action-btn.ability {
      border-color: rgba(69, 215, 255, 0.42);
      background: linear-gradient(135deg, rgba(69, 215, 255, 0.18), rgba(255, 255, 255, 0.04));
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
      display: none;
    }

    .mobile-nav button.active {
      border-color: rgba(83, 246, 184, 0.58);
      background: linear-gradient(135deg, rgba(69, 215, 255, 0.2), rgba(83, 246, 184, 0.18));
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
      grid-template-columns: repeat(2, minmax(0, 1fr));
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

      .arena-rail {
        padding: 7px 6px;
      }

      .arena-rail .tiny {
        min-width: 0;
        overflow-wrap: anywhere;
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
        left: 8px;
        right: 8px;
        bottom: calc(8px + env(safe-area-inset-bottom));
        display: grid;
        grid-template-columns: repeat(5, 1fr);
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
        min-height: 232px;
      }

      .arena-choice-hub {
        min-height: 232px;
        padding: 8px 0 8px;
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
        top: 48px;
      }

      .arena-round-choice-slot.active {
        gap: 10px;
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

      .arena-lane-choice-panel {
        width: min(134px, 23vw);
        min-width: 116px;
        padding: 8px 7px 8px;
        border-radius: 14px;
        max-width: 100%;
      }

      .arena-round-choice-slot.active .arena-lane-choice-panel {
        margin-top: 12px;
        transform: none;
      }

      .arena-round-choice-slot.clash-resolving .arena-lane-choice-panel {
        transform: translateY(8px) scale(0.94);
      }

      .arena-round-choice-slot:first-child .arena-lane-choice-panel {
        transform: translateX(10%);
      }

      .arena-round-choice-slot:last-child .arena-lane-choice-panel {
        transform: translateX(-10%);
      }

      .arena-round-choice-slot.active:first-child .arena-lane-choice-panel,
      .arena-round-choice-slot.active:last-child .arena-lane-choice-panel {
        transform: none;
      }

      .arena-lane-choice-panel .interactive-battle-title {
        font-size: 11px;
      }

      .interactive-battle-metrics {
        grid-template-columns: 1fr;
        gap: 5px;
      }

      .interactive-battle-metric {
        min-height: 34px;
        padding: 5px 6px;
      }

      .interactive-battle-metric strong {
        font-size: 10px;
      }

      .interactive-battle-metric span,
      .interactive-battle-prompt {
        font-size: 9px;
      }

      .arena-lane-choice-panel .interactive-battle-actions {
        grid-template-columns: repeat(2, minmax(0, 42px));
        gap: 8px;
      }

      .arena-lane-choice-panel .interactive-action-btn {
        min-height: 42px;
        font-size: 8px;
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
    }

    body.tma-app .shell {
      overflow-x: hidden;
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
      left: 8px;
      right: 8px;
      bottom: calc(8px + env(safe-area-inset-bottom));
      display: grid;
      grid-template-columns: repeat(5, 1fr);
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
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow">TON 10K Club Battle Flow</div>
          <h1>tondomaingame</h1>
          <p>
            Подключи кошелек для проверки владение доменом для начала игры.
          </p>
        </div>
        <div class="badge-row">
          <div class="badge" id="wallet-badge">Кошелёк не подключен</div>
        </div>
      </div>

      <div class="stepper">
        <div class="step-chip active" data-step-chip="wallet">1. Кошелёк</div>
        <div class="step-chip" data-step-chip="pack">2. Распаковка</div>
        <div class="step-chip" data-step-chip="modes">3. Режимы игры</div>
        <div class="step-chip" data-step-chip="profile">4. Профиль</div>
        <div class="step-chip" data-step-chip="achievements">5. Достижения</div>
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
            </div>
            <div class="wallet-flow-note">Подключи кошелёк, проверь свои `.ton` домены и сразу переходи к готовой колоде. Если карты для домена уже были открыты, они подтянутся автоматически.</div>
            <div class="wallet-quick-actions">
              <button id="check-domains-btn" disabled>Проверить наличие доменов</button>
              <button class="secondary" id="wallet-open-pack-btn" disabled>К распаковке</button>
            </div>
            <div class="tiny" style="margin-top:8px; color: var(--warning);">Чтобы откалибровать экран в TMA, нажми «Проверить наличие доменов».</div>
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
            <button id="buy-pack-btn" disabled>Открыть пак за 1 TON</button>
          </div>

          <div class="result-box" id="pack-economy-box" style="margin-top:12px;">
            <strong>Экономика паков</strong>
            <div class="tiny" id="pack-rewards-summary">Подключи кошелёк, чтобы видеть осколки, токены и сезонный прогресс.</div>
            <div class="tiny" id="pack-season-summary" style="margin-top:6px;">Сезон: -</div>
            <div class="actions" style="margin-top:10px;">
              <button class="secondary" id="claim-daily-reward-btn" disabled>Забрать дейлик</button>
              <button class="secondary" id="claim-quest-reward-btn" disabled>Забрать квест побед</button>
            </div>
            <div class="actions" style="margin-top:10px;">
              <button class="secondary reward-pack-btn" data-reward-pack="common" disabled>Обычный пак за 3 осколка</button>
              <button class="secondary reward-pack-btn" data-reward-pack="rare" disabled>Редкий пак за 1 редкий токен</button>
              <button class="secondary reward-pack-btn" data-reward-pack="epic" disabled>Эпический пак за 6 осколков + 1 редкий токен</button>
              <button class="secondary reward-pack-btn" data-reward-pack="lucky" disabled>Счастливый пак за 1 lucky-токен</button>
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
          <div id="mobile-profile-summary" class="deck-list"></div>
          <div id="mobile-rewards-panel" class="deck-list" style="margin-top:14px;"></div>
          <div class="actions" style="margin-top:14px;">
            <button class="secondary" id="mobile-show-deck-btn">Моя колода</button>
          </div>
          <div id="mobile-deck-view" class="deck-list" style="margin-top:14px;"></div>
          <h3 style="margin-top:20px;">Рейтинг</h3>
          <div id="mobile-leaderboard" class="leaderboard"></div>
          <h3 style="margin-top:20px;">Общая база игроков</h3>
          <div id="mobile-global-players-list" class="global-players-list"></div>
        </section>

        <section class="panel view" id="view-achievements">
          <h2>Достижения</h2>
          <p class="muted">Открывай достижения за игру, коллекцию доменов и рейтинг.</p>
          <div class="actions">
            <button id="refresh-achievements-btn" disabled>Обновить достижения</button>
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
    <button id="nav-wallet">Кошелёк</button>
    <button id="nav-pack">Карты</button>
    <button id="nav-modes">Игра</button>
    <button id="nav-profile">Профиль</button>
    <button id="nav-achievements">Достижения</button>
  </nav>

  <script>
    const state = {
      wallet: null,
      domains: [],
      domainsChecked: false,
      selectedDomain: null,
      cards: [],
      pendingPackSource: null,
      pendingPackPaymentId: null,
      packOpening: false,
      selectedBattleSlot: null,
      playerProfile: null,
      lastResult: null,
      roomId: null,
      room: null,
      activeUsers: [],
      friends: [],
      ownedDecks: [],
      allPlayers: [],
      achievements: [],
      cardCatalog: [],
      packTypes: [],
      packPityThreshold: 20,
      matchmakingMode: null,
      matchmakingPolling: false,
      disciplineBuild: null,
      battleLaunchInFlight: false,
      lastReplayTapAt: 0,
      interactiveActionInFlight: false
    };

    const telegramBotUsername = {{ telegram_bot_username|tojson }};
    const telegramWebappUrl = {{ telegram_webapp_url|tojson }};
    const marketplaceLinks = {{ marketplace_links|tojson }};

    const walletBadge = document.getElementById('wallet-badge');
    const walletStatus = document.getElementById('wallet-status');
    const walletQuickWallet = document.getElementById('wallet-quick-wallet');
    const walletQuickDomain = document.getElementById('wallet-quick-domain');
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
    const mobileLeaderboard = document.getElementById('mobile-leaderboard');
    const mobileDeckView = document.getElementById('mobile-deck-view');
    const mobileGlobalPlayersList = document.getElementById('mobile-global-players-list');
    const ownedDecksList = document.getElementById('owned-decks-list');
    const walletOwnedDecksList = document.getElementById('wallet-owned-decks-list');
    const globalPlayersList = document.getElementById('global-players-list');
    const packShowcase = document.getElementById('pack-showcase');
    const foilPack = document.getElementById('foil-pack');
    const packCounter = document.getElementById('pack-counter');
    const packNote = document.getElementById('pack-note');
    const buyPackBtn = document.getElementById('buy-pack-btn');
    const packRewardsSummary = document.getElementById('pack-rewards-summary');
    const packSeasonSummary = document.getElementById('pack-season-summary');
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
    let tonConnectUI = null;
    let matchmakingPollTimer = null;
    let modeFocusTimer = null;
    let interactiveChoiceTimer = null;
    let interactiveChoiceExpireTimer = null;
    let battleAutostartTimer = null;
    const usageStorageKey = 'tondomaingame_ui_usage_v1';

    function shortAddress(value) {
      if (!value) return '-';
      return `${value.slice(0, 6)}...${value.slice(-6)}`;
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

    function bindFunctionalControl(node, handler, eventName = 'click') {
      if (!node) {
        return;
      }
      node.addEventListener(eventName, async (event) => {
        await prepareFunctionalInteraction();
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

    function setStatus(element, text, kind = '') {
      element.className = `status ${kind}`.trim();
      element.textContent = text;
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

    function packTypeMeta(packType) {
      return (state.packTypes || []).find((item) => item.key === packType) || null;
    }

    function packCostText(costs) {
      const entries = Object.entries(costs || {}).filter(([, value]) => Number(value || 0) > 0);
      if (!entries.length) return 'free';
      return entries.map(([key, value]) => {
        const label = key === 'pack_shards' ? 'осколка' : (key === 'rare_tokens' ? 'редкий токен' : (key === 'lucky_tokens' ? 'lucky-токен' : key));
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
      const seasonTarget = Number(rewards.season_target || (Number(rewards.season_level || 1) * 12));
      packRewardsSummary.textContent = `Баланс: ${rewards.pack_shards || 0} осколков • ${rewards.rare_tokens || 0} редких токенов • ${rewards.lucky_tokens || 0} lucky-токенов`;
      packSeasonSummary.textContent = `Сезон ${rewards.season_level || 1} • ${rewards.season_points || 0}/${seasonTarget} очков • дейлик ${rewards.daily_available ? 'готов' : 'получен'} • квест ${rewards.quest_ready ? 'готов' : `до цели ${Math.max(0, Number(rewards.next_quest_target || 0) - Number(rewards.wins_for_quest || 0))} побед`}`;
      claimDailyRewardBtn.disabled = !(state.wallet && rewards.daily_available);
      claimQuestRewardBtn.disabled = !(state.wallet && rewards.quest_ready);
      document.querySelectorAll('.reward-pack-btn').forEach((button) => {
        const meta = packTypeMeta(button.dataset.rewardPack);
        const costs = (meta && meta.costs) || {};
        button.textContent = `${meta ? meta.label : button.dataset.rewardPack} за ${packCostText(costs)}`;
        button.disabled = !(state.wallet && state.selectedDomain && canAffordPack(costs, rewards));
      });
    }

    function renderRewardsPanels() {
      const rewards = state.playerProfile && state.playerProfile.rewards ? state.playerProfile.rewards : null;
      const synergies = state.playerProfile && state.playerProfile.synergies ? state.playerProfile.synergies : null;
      const content = rewards ? `
        <div class="user-item">
          <strong>Награды и сезон</strong>
          <div class="tiny">Осколки: ${rewards.pack_shards || 0} • Редкие токены: ${rewards.rare_tokens || 0} • Lucky-токены: ${rewards.lucky_tokens || 0}</div>
          <div class="tiny">Сезон: ур. ${rewards.season_level || 1} • ${rewards.season_points || 0}/${rewards.season_target || 12} очков</div>
          <div class="tiny">Дейлик: ${rewards.daily_available ? 'готов' : 'получен'} • Квест: ${rewards.quest_ready ? 'готов' : `до цели ${Math.max(0, Number(rewards.next_quest_target || 0) - Number(rewards.wins_for_quest || 0))} побед`}</div>
          <div class="tiny">Синергии: ${synergies && synergies.labels && synergies.labels.length ? synergies.labels.join(' • ') : 'нет'}</div>
        </div>
      ` : '<div class="user-item muted">Подключи кошелёк, чтобы видеть награды и сезонный прогресс.</div>';
      if (profileRewardsPanel) profileRewardsPanel.innerHTML = content;
      if (mobileRewardsPanel) mobileRewardsPanel.innerHTML = content;
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
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || data.detail || 'Request failed');
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
      if (name === 'modes') {
        const preferredMode = refreshModeUsageUI();
        if (preferredMode) {
          const preferredCard = document.querySelector(`[data-mode-card="${preferredMode}"]`);
          softCameraFocus(preferredCard);
        }
      }
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
        <div class="leaderboard-item">
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
    }

    function renderActiveUsers(items) {
      state.activeUsers = items;
      if (!items.length) {
        activeUsersList.innerHTML = '<div class="user-item muted">Активные игроки появятся здесь после входа в игру.</div>';
        return;
      }
      activeUsersList.innerHTML = items.map((item) => `
        <div class="user-item">
          <strong>${item.display_name}</strong>
          <div class="tiny">${item.domain}.ton • рейтинг ${item.rating}</div>
          <div class="tiny">Прокачка (сред.): атака ${item.average_attack} • защита ${item.average_defense}</div>
          <div class="actions" style="margin-top:10px;">
            <button class="secondary" onclick="fillOpponent('${item.domain}')">По домену</button>
            <button class="secondary" onclick="fillOpponent('${item.wallet}')">По кошельку</button>
          </div>
        </div>
      `).join('');
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
            <div class="tiny">Вклад в пул: ${card.pool_value || card.base_power || 0}</div>
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
      walletBadge.textContent = state.wallet ? `Подключён: ${shortAddress(state.wallet)}` : 'Кошелёк не подключен';
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
          <div class="tiny">Рейтинг: ${profileRating.textContent} • Матчей: ${profileGames.textContent}</div>
          <div class="tiny">Награды: ${state.playerProfile && state.playerProfile.rewards ? `осколки ${state.playerProfile.rewards.pack_shards} • редкие ${state.playerProfile.rewards.rare_tokens} • lucky ${state.playerProfile.rewards.lucky_tokens}` : '-'}</div>
          <div class="tiny">Сезон: ${state.playerProfile && state.playerProfile.rewards ? `ур. ${state.playerProfile.rewards.season_level} • ${state.playerProfile.rewards.season_points}/${state.playerProfile.rewards.season_target}` : '-'}</div>
          <div class="tiny">Синергии: ${state.playerProfile && state.playerProfile.synergies && state.playerProfile.synergies.labels && state.playerProfile.synergies.labels.length ? state.playerProfile.synergies.labels.join(' • ') : 'нет'}</div>
        </div>
      `;
      document.getElementById('mobile-show-deck-btn').disabled = showDeckBtn.disabled;
      renderRewardsPanels();
      renderPackEconomy();
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
            <span class="wallet-domain-chip">Пул: ${item.deck.discipline_pool || 0}</span>
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
      const markup = state.allPlayers.map((player, index) => `
        <div class="user-item">
          <strong>#${index + 1} ${shortAddress(player.wallet)}</strong>
          <div class="tiny">Домен: ${player.current_domain ? `${player.current_domain}.ton` : 'не выбран'}</div>
          <div class="tiny">Рейтинг: ${player.rating} • Матчей: ${player.games_played}</div>
        </div>
      `).join('');
      globalPlayersList.innerHTML = markup;
      mobileGlobalPlayersList.innerHTML = markup;
    }

    function renderAchievements(items) {
      state.achievements = items || [];
      if (!state.achievements.length) {
        achievementsList.innerHTML = '<div class="user-item muted">Подключи кошелёк, чтобы увидеть достижения.</div>';
        return;
      }
      achievementsList.innerHTML = state.achievements.map((item) => `
        <div class="user-item">
          <strong>${item.unlocked ? '🏆' : '🔒'} ${item.title}</strong>
          <div class="tiny">${item.description}</div>
          <div class="tiny">${item.progress}</div>
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
              <div class="tiny">Вклад в пул: ${card.pool_min}-${card.pool_max}</div>
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
      document.getElementById('check-domains-btn').disabled = !connected;
      document.getElementById('shuffle-deck-btn').disabled = !(connected && hasDomain && hasCards);
      document.getElementById('open-pack-btn').disabled = !(connected && hasDomain);
      buyPackBtn.disabled = !(connected && hasDomain && tonConnectUI);
      document.getElementById('continue-to-modes-btn').disabled = !hasCards;
      document.getElementById('play-ranked-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('play-casual-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('play-bot-btn').disabled = !(connected && hasCards) || searching;
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
      packCards.classList.remove('reveal', 'pack-emerge', 'sequence-prep');
      packCards.innerHTML = cards.map((card) => `
        <article class="game-card">
          <div class="tiny">${card.rarity}</div>
          <h3>${card.title}</h3>
          <p>${card.domain}.ton • слот ${card.slot}</p>
          <div class="team-line"><span>Вклад в пул</span><strong>${card.pool_value || card.base_power || 0}</strong></div>
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
          <div class="tiny">Вклад в пул: ${card.pool_value ?? card.base_power ?? card.score ?? 0}</div>
          <div class="tiny">Скилл: ${card.skill_name || '-'}</div>
        </div>
      `).join('');
    }

    function arenaDeckMarkup(cards, fallbackCard, side = 'player', activeSlot = null, featuredSlot = null) {
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
          <div class="arena-slot-card ${side === 'enemy' ? 'enemy-card' : 'player-card'} ${isActive ? 'active-slot' : ''} ${isFeatured ? 'featured-slot' : ''}">
            <strong>${slot}. ${card.title || 'Карта'}</strong>
            <div class="arena-slot-meta">${card.rarity || '-'}</div>
            <div class="arena-slot-meta">Вклад: ${card.pool_value ?? card.base_power ?? card.score ?? 0}</div>
            <div class="arena-slot-meta">${card.skill_name || '-'}</div>
          </div>
        `;
      }).join('');
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
        return `
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path fill="currentColor" d="M12 2 15.3 5.3 13.8 6.8 12.9 5.9v8.5h-1.8V5.9l-.9.9-1.5-1.5z"/>
            <path fill="currentColor" d="M8.1 13.4h7.8v1.9H8.1z"/>
            <path fill="currentColor" d="M10.2 15.3h3.6v4.2h-3.6z"/>
            <circle cx="12" cy="21" r="1.6" fill="currentColor"/>
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
      const playerSource = battleResult.querySelector('.arena-rail.player .arena-slot-card.active-slot') || battleResult.querySelector('.arena-rail.player .arena-slot-card');
      const enemySource = battleResult.querySelector('.arena-rail.enemy .arena-slot-card.active-slot') || battleResult.querySelector('.arena-rail.enemy .arena-slot-card');
      if (!playerSource || !enemySource) {
        return;
      }
      const playerRect = playerSource.getBoundingClientRect();
      const enemyRect = enemySource.getBoundingClientRect();
      const compactClash = document.body.classList.contains('tma-app') || window.innerWidth <= 700;
      const clashCardWidth = compactClash ? 58 : 88;
      const clashCardHeight = compactClash ? 84 : 128;
      const clashGap = compactClash ? 8 : 18;
      const impactGap = compactClash ? 4 : 8;
      const centerY = coreRect.height * (compactClash ? 0.64 : 0.5);
      const clashLanePadding = compactClash ? 6 : 10;
      const verticalPadding = compactClash ? 56 : 20;
      const laneTargetLeft = Math.max(
        clashLanePadding,
        Math.min(laneCenter - clashCardWidth / 2, coreRect.width - clashCardWidth - clashLanePadding)
      );
      const playerTargetLeft = laneTargetLeft;
      const enemyTargetLeft = laneTargetLeft;
      const rawPlayerTargetTop = centerY - clashCardHeight - clashGap;
      const rawEnemyTargetTop = centerY + clashGap;
      const playerTargetTop = Math.max(verticalPadding, rawPlayerTargetTop);
      const enemyTargetTop = Math.min(coreRect.height - clashCardHeight - verticalPadding, rawEnemyTargetTop);
      const playerAttack = playerActionKey === 'burst';
      const enemyAttack = opponentActionKey === 'burst';
      const playerPrepTop = playerAttack ? playerTargetTop + (compactClash ? 8 : 18) : playerTargetTop;
      const enemyPrepTop = enemyAttack ? enemyTargetTop - (compactClash ? 8 : 18) : enemyTargetTop;
      const rawPlayerImpactTop = playerAttack ? centerY - clashCardHeight - impactGap + (compactClash ? 2 : 12) : playerTargetTop + 1;
      const rawEnemyImpactTop = enemyAttack ? centerY + impactGap - (compactClash ? 2 : 12) : enemyTargetTop - 1;
      const playerImpactTop = Math.max(verticalPadding, rawPlayerImpactTop);
      const enemyImpactTop = Math.min(coreRect.height - clashCardHeight - verticalPadding, rawEnemyImpactTop);
      const playerImpactScale = playerAttack ? (compactClash ? 1.1 : 1.14) : 1.01;
      const enemyImpactScale = enemyAttack ? (compactClash ? 1.1 : 1.14) : 1.01;
      const playerImpactRotate = playerAttack ? '-8deg' : '2deg';
      const enemyImpactRotate = enemyAttack ? '8deg' : '-2deg';
      const playerRecoilY = playerAttack ? playerImpactTop - (compactClash ? 10 : 16) : playerTargetTop;
      const enemyRecoilY = enemyAttack ? enemyImpactTop + (compactClash ? 10 : 16) : enemyTargetTop;
      const playerRecoilScale = playerAttack ? 1.02 : 1;
      const enemyRecoilScale = enemyAttack ? 1.02 : 1;
      const impactCenterY = ((playerImpactTop + clashCardHeight) + enemyImpactTop) / 2;
      const laneReveal = document.createElement('div');
      laneReveal.className = 'arena-lane-clash';
      laneReveal.style.setProperty('--clash-card-width', `${clashCardWidth}px`);
      laneReveal.style.setProperty('--clash-card-height', `${clashCardHeight}px`);
      activeLane.classList.add('clash-resolving');
      if (arenaShell) {
        arenaShell.classList.add('lane-clash-live');
      }
      const playerSourceVisibility = playerSource.style.visibility;
      const playerSourceOpacity = playerSource.style.opacity;
      const enemySourceVisibility = enemySource.style.visibility;
      const enemySourceOpacity = enemySource.style.opacity;
      const playerClone = playerSource.cloneNode(true);
      playerClone.className = `${playerClone.className} arena-lane-card player ${playerActionKey}`.trim();
      playerClone.style.visibility = 'visible';
      playerClone.style.opacity = '1';
      playerClone.style.left = `${playerRect.left - coreRect.left}px`;
      playerClone.style.top = `${Math.max(verticalPadding - 6, playerRect.top - coreRect.top)}px`;
      playerClone.style.width = `${clashCardWidth}px`;
      playerClone.style.height = `${clashCardHeight}px`;
      playerClone.insertAdjacentHTML('beforeend', `<div class="arena-action-sticker ${playerActionKey}">${actionStickerSvg(playerActionKey)}</div>`);
      const enemyClone = enemySource.cloneNode(true);
      enemyClone.className = `${enemyClone.className} arena-lane-card enemy ${opponentActionKey}`.trim();
      enemyClone.style.visibility = 'visible';
      enemyClone.style.opacity = '1';
      enemyClone.style.left = `${enemyRect.left - coreRect.left}px`;
      enemyClone.style.top = `${Math.min(coreRect.height - clashCardHeight - verticalPadding + 6, enemyRect.top - coreRect.top)}px`;
      enemyClone.style.width = `${clashCardWidth}px`;
      enemyClone.style.height = `${clashCardHeight}px`;
      enemyClone.insertAdjacentHTML('beforeend', `<div class="arena-action-sticker ${opponentActionKey}">${actionStickerSvg(opponentActionKey)}</div>`);
      playerSource.style.visibility = 'hidden';
      playerSource.style.opacity = '0';
      enemySource.style.visibility = 'hidden';
      enemySource.style.opacity = '0';
      const impactNode = document.createElement('div');
      impactNode.className = `arena-lane-impact ${resultKey}`;
      impactNode.style.left = `${laneTargetLeft + clashCardWidth / 2}px`;
      impactNode.style.top = `${impactCenterY}px`;
      laneReveal.appendChild(playerClone);
      laneReveal.appendChild(enemyClone);
      laneReveal.appendChild(impactNode);
      arenaCore.appendChild(laneReveal);
      requestAnimationFrame(() => laneReveal.classList.add('visible'));
      playerClone.animate([
        { opacity: 0.96, transform: 'translate3d(0, 0, 0) scale(1)' },
        { opacity: 1, transform: `translate3d(${playerTargetLeft - (playerRect.left - coreRect.left)}px, ${playerPrepTop - (playerRect.top - coreRect.top)}px, 0) scale(1.02)` },
        { opacity: 1, transform: `translate3d(${playerTargetLeft - (playerRect.left - coreRect.left)}px, ${playerImpactTop - (playerRect.top - coreRect.top)}px, 0) rotate(${playerImpactRotate}) scale(${playerImpactScale})` },
        { opacity: 1, transform: `translate3d(${playerTargetLeft - (playerRect.left - coreRect.left)}px, ${playerRecoilY - (playerRect.top - coreRect.top)}px, 0) rotate(0deg) scale(${playerRecoilScale})` }
      ], { duration: 700, easing: 'cubic-bezier(.16,.84,.2,1)', fill: 'forwards' });
      enemyClone.animate([
        { opacity: 0.96, transform: 'translate3d(0, 0, 0) scale(1)' },
        { opacity: 1, transform: `translate3d(${enemyTargetLeft - (enemyRect.left - coreRect.left)}px, ${enemyPrepTop - (enemyRect.top - coreRect.top)}px, 0) scale(1.02)` },
        { opacity: 1, transform: `translate3d(${enemyTargetLeft - (enemyRect.left - coreRect.left)}px, ${enemyImpactTop - (enemyRect.top - coreRect.top)}px, 0) rotate(${enemyImpactRotate}) scale(${enemyImpactScale})` },
        { opacity: 1, transform: `translate3d(${enemyTargetLeft - (enemyRect.left - coreRect.left)}px, ${enemyRecoilY - (enemyRect.top - coreRect.top)}px, 0) rotate(0deg) scale(${enemyRecoilScale})` }
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
      if (arenaShell) {
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
            const marker = round.winner === 'player' ? 'ПОБЕДА' : (round.winner === 'opponent' ? 'ПОРАЖЕНИЕ' : 'НИЧЬЯ');
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
                  <span class="arena-decision-chip action player ${playerActionClass}" style="animation-delay:${delay + 40}ms;">Твой выбор: ${playerAction.ruLabel}</span>
                  <span class="arena-decision-chip action enemy ${opponentActionClass}" style="animation-delay:${delay + 90}ms;">Соперник: ${opponentAction.ruLabel}</span>
                  <span class="arena-decision-chip strategy" style="animation-delay:${delay + 140}ms;">Стратегия: ${playerStrategy.label} / ${opponentStrategy.label}</span>
                  <span class="arena-decision-chip featured" style="animation-delay:${delay + 190}ms;">Тактическая карта: +${round.player_featured_bonus || 0} / +${round.opponent_featured_bonus || 0}</span>
                  <span class="arena-decision-chip outcome" style="animation-delay:${delay + 240}ms;">Итог раунда: ${marker}</span>
                  ${reasonChip('Действие', round.player_action_note, 'player')}
                  ${reasonChip('Контр-эффект', round.player_domain_note, 'featured')}
                  ${reasonChip('Стратегия', round.player_strategy_note, 'strategy')}
                  ${reasonChip('Навык', round.player_skill_note, 'featured')}
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
          <div class="final-label">${resultKey === 'draw' ? 'НИЧЬЯ' : (resultKey === 'win' ? 'ПОБЕДА' : 'ПОРАЖЕНИЕ')}</div>
          <div class="final-sub">${resultLabel || ''}</div>
          <div class="final-buttons">
            <button class="secondary" onclick="viewBattleFlow()">Смотреть ход боя</button>
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
        const interactivePanel = result.interactive_session_id
          ? `
              <div class="arena-round-choice-strip">
                ${Array.from({ length: totalRounds }, (_, index) => {
                  const roundNumber = index + 1;
                  const isActive = result.interactive_live && roundNumber === activeRoundNumber;
                  const isResolved = !result.interactive_live || roundNumber < activeRoundNumber;
                  const roundResult = Array.isArray(result.rounds) ? result.rounds[index] : null;
                  const roundOutcomeClass = roundResult?.winner === 'player' ? 'win' : (roundResult?.winner === 'opponent' ? 'lose' : 'draw');
                  const roundOutcomeLabel = roundResult?.winner === 'player' ? 'Победа' : (roundResult?.winner === 'opponent' ? 'Поражение' : (roundResult ? 'Ничья' : 'Ждёт'));
                  const left = (arenaLanes[index] && arenaLanes[index].percent) || 50;
                  return `
                    <div class="arena-round-choice-slot ${isActive ? 'active' : ''} ${isResolved ? 'resolved' : ''}" style="left:${left}%;">
                      <div class="arena-round-marker"></div>
                      ${isActive ? `
                        <div class="interactive-battle-panel arena-lane-choice-panel" id="interactive-battle-panel">
                          <div class="interactive-battle-head">
                            <div class="interactive-battle-title">Раунд ${roundNumber}</div>
                            <div class="interactive-timer" id="interactive-timer">5 c</div>
                          </div>
                          <div class="interactive-battle-metrics">
                            <div class="interactive-battle-metric">
                              <strong>Энергия ${result.interactive_energy || 0}</strong>
                              <span>${result.interactive_active_ability && result.interactive_active_ability.name ? result.interactive_active_ability.name : 'Базовый режим'}</span>
                            </div>
                            <div class="interactive-battle-metric">
                              <strong>КД ${(result.interactive_ability_state && result.interactive_ability_state.cooldown_remaining) || 0}</strong>
                              <span>Заряды ${(result.interactive_ability_state && result.interactive_ability_state.charges_remaining) || 0}</span>
                            </div>
                          </div>
                          <div class="interactive-battle-prompt" id="interactive-battle-status">${result.interactive_hint || 'Выбери действие'}</div>
                          <div class="interactive-battle-actions">
                            ${(result.interactive_available_actions || ['burst', 'guard']).map((key) => {
                              const meta = actionRuleMeta(key);
                              return `<button type="button" class="interactive-action-btn ${key}" data-action-key="${key}" onclick="handleInteractiveBattleChoice('${key}', event)">${meta.ruLabel}</button>`;
                            }).join('')}
                          </div>
                        </div>
                      ` : `<div class="arena-round-state ${isResolved ? roundOutcomeClass : ''}">${roundOutcomeLabel}</div>`}
                    </div>
                  `;
                }).join('')}
              </div>
            `
          : '';
        const playerActiveSlot = result.interactive_live
          ? Number((result.player_cards || [])[Math.min(result.interactive_round_index || 0, Math.max((result.player_cards || []).length - 1, 0))]?.slot || 0)
          : Number(result.player_featured_card?.slot || result.player_card?.slot || result.rounds?.[Math.max((result.rounds?.length || 1) - 1, 0)]?.player_card?.slot || 0);
        const opponentActiveSlot = result.interactive_live
          ? Number((result.opponent_cards || [])[Math.min(result.interactive_round_index || 0, Math.max((result.opponent_cards || []).length - 1, 0))]?.slot || 0)
          : Number(result.opponent_featured_card?.slot || result.opponent_card?.slot || result.rounds?.[Math.max((result.rounds?.length || 1) - 1, 0)]?.opponent_card?.slot || 0);
        const playerArenaDeck = arenaDeckMarkup(result.player_cards, result.player_card, 'player', playerActiveSlot, result.player_featured_card?.slot || result.selected_slot);
        const opponentArenaDeck = arenaDeckMarkup(result.opponent_cards, result.opponent_card, 'enemy', opponentActiveSlot, result.opponent_featured_card?.slot);
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
          <section class="showdown-main arena-board">
            <div class="arena-shell">
              <div class="arena-rail player">
                <div class="tiny"><strong>Колода пользователя</strong> • ${result.player_domain}.ton</div>
                <div class="arena-deck-grid">
                  ${playerArenaDeck}
                </div>
              </div>
              <div class="arena-core">
                ${arenaRoutes}
                <div class="arena-choice-hub">
                  <div class="prebattle-stage arena-choice-panel" id="prebattle-stage">
                    <div class="tiny" id="prebattle-ready-status">Колоды готовы. Нажми "Готов".</div>
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
              <div class="arena-rail enemy">
                <div class="tiny"><strong>Колода противника</strong> • ${opponentLabel}</div>
                <div class="arena-deck-grid">
                  ${opponentArenaDeck}
                </div>
              </div>
            </div>
          </section>
          <div class="result-actions delayed-outcome post-actions">
            ${ratingLine ? `<div class="tiny" style="width:100%; text-align:center;">${result.rating_before} → ${result.rating_after}</div>` : ''}
            <button class="secondary" onclick="viewBattleFlow()">Смотреть ход боя</button>
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
                startBtn.disabled = false;
                startBtn.textContent = 'Готов';
                if (prebattleReadyStatus) {
                  prebattleReadyStatus.textContent = error.message;
                }
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
              startBtn.disabled = false;
              startBtn.textContent = 'Готов';
              if (prebattleReadyStatus) {
                prebattleReadyStatus.textContent = error.message;
              }
            });
          });
        }
        if (result.autostart_battle && startBtn) {
          battleAutostartTimer = window.setTimeout(() => {
            battleAutostartTimer = null;
            if (document.body.contains(startBtn)) {
              startBtn.click();
            }
          }, 120);
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

    function rebindDomain() {
      state.selectedDomain = null;
      state.cards = [];
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
      switchView('wallet');
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
        renderProfile();
        renderOwnedDecks([], null);
        return;
      }
      const profile = await api(`/api/player/${encodeURIComponent(state.wallet)}`);
      state.playerProfile = profile.player;
      if (!state.selectedDomain && state.playerProfile && state.playerProfile.current_domain) {
        state.selectedDomain = state.playerProfile.current_domain;
      }
      renderProfile();
    }

    async function checkDomains() {
      await prepareFunctionalInteraction();
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

    async function openPack(source = 'daily', paymentId = null, packType = null) {
      await prepareFunctionalInteraction();
      if (state.packOpening) return;
      const resolvedPackType = packType || (source === 'paid' ? 'lucky' : 'common');
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
        state.cards = data.cards;
        state.pendingPackSource = null;
        state.pendingPackPaymentId = null;
        if (state.playerProfile && data.rewards) {
          state.playerProfile.rewards = data.rewards;
        }
        await sleep(1300);
        packShowcase.classList.add('opened');
        packNote.textContent = 'Карты уже летят';
        await renderPack(data.cards, data.total_score);
        packShowcase.classList.remove('cinematic');
        setStatus(document.getElementById('pack-status'), `Колода готова. ${packTypeMeta(resolvedPackType)?.label || resolvedPackType} дал вклад ${data.total_score}.`, 'success');
        updateButtons();
        showDeck();
        await loadDisciplineBuild();
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

    async function openRewardPack(packType) {
      if (!state.wallet || !state.selectedDomain) return;
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

    async function buyPackWithTon() {
      await prepareFunctionalInteraction();
      if (!state.wallet || !state.selectedDomain) return;
      if (!tonConnectUI) {
        setStatus(document.getElementById('pack-status'), 'TonConnect не инициализирован.', 'error');
        return;
      }
      try {
        setStatus(document.getElementById('pack-status'), 'Создаём TON-платёж на 1 TON...', 'warning');
        const intent = await api('/api/pack/payment-intent', {
          method: 'POST',
          body: { wallet: state.wallet, domain: state.selectedDomain }
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
        await api('/api/pack/payment-confirm', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            payment_id: intent.payment_id,
            tx_hash: tx && tx.boc ? tx.boc.slice(0, 120) : ''
          }
        });
        state.pendingPackSource = 'paid';
        state.pendingPackPaymentId = intent.payment_id;
        packShowcase.classList.remove('opened');
        foilPack.classList.remove('opening');
        foilPack.classList.remove('vanishing');
        packNote.textContent = 'Tap pack to open';
        setStatus(document.getElementById('pack-status'), 'Платёж подтверждён. Нажми на пак, чтобы открыть его.', 'success');
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function loadCardCatalog() {
      try {
        const data = await api('/api/cards/catalog');
        state.packTypes = data.pack_types || [];
        state.packPityThreshold = Number(data.pity_threshold || 20);
        renderCardCatalog(data.cards || [], data.skills || []);
        renderPackEconomy();
      } catch (error) {
        cardCatalogList.innerHTML = `<div class="user-item error">${error.message}</div>`;
      }
    }

    async function pollInvite(inviteId) {
      const startedAt = Date.now();
      const maxPollMs = 1000 * 60 * 15;
      const loop = async () => {
        const data = await api(`/api/match-invite/${inviteId}?wallet=${encodeURIComponent(state.wallet)}`);
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
          loadLeaderboard();
          loadActiveUsers();
        }
        if (data.result) {
          state.lastResult = data.result;
          renderBattleResult(data.result);
          loadAchievements();
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = `<strong>Приглашение ${inviteId} завершено.</strong><p class="muted">Соперник принял вызов, матч рассчитан на сервере.</p>`;
          return;
        }
        if (['declined', 'expired', 'completed'].includes(data.invite.status)) {
          inviteResult.style.display = 'block';
          inviteResult.classList.add('duel-anim');
          inviteResult.innerHTML = `<strong>Статус приглашения ${inviteId}: ${data.invite.status}</strong>`;
          return;
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
        stopMatchmakingUI(error.message);
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

    async function playMatch(mode) {
      await prepareFunctionalInteraction();
      bumpUsage(`mode:${mode}`);
      const opponentWallet = document.getElementById('opponent-wallet').value.trim();
      const timeoutSeconds = Number(document.getElementById('invite-timeout').value || 60);
      const delivery = (document.getElementById('match-delivery')?.value || 'site').trim();
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
          <p class="muted">Бот написал сопернику в Telegram. Время на ответ: ${data.invite.timeout_seconds} сек.</p>
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
      if (!state.wallet) {
        renderAchievements([]);
        return;
      }
      try {
        const data = await api(`/api/achievements/${encodeURIComponent(state.wallet)}`);
        renderAchievements(data.achievements || []);
      } catch (error) {
        achievementsList.innerHTML = `<div class="user-item error">${error.message}</div>`;
      }
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
          await loadAchievements();
          await loadDisciplineBuild();
        } else {
          stopMatchmakingUI('');
          state.domainsChecked = false;
          state.domains = [];
          state.selectedDomain = null;
          state.cards = [];
          state.pendingPackSource = null;
          state.pendingPackPaymentId = null;
          state.packOpening = false;
          state.selectedBattleSlot = null;
          renderDomains([]);
          renderProfile();
          renderDeck(null);
          renderOwnedDecks([], null);
          renderAchievements([]);
          renderDisciplineBuild({pool: 0, points: {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0}});
          setStatus(walletStatus, 'Подключи кошелёк через TonConnect.', 'warning');
        }
      };

      tonConnectUI.onStatusChange(async () => {
        await applyConnection();
      });

      await applyConnection();
    }

    bindFunctionalControl(document.getElementById('check-domains-btn'), checkDomains);
    bindFunctionalControl(walletOpenPackBtn, () => switchView('pack'));
    bindFunctionalControl(document.getElementById('back-to-wallet-btn'), () => switchView('wallet'));
    bindFunctionalControl(document.getElementById('rebind-domain-btn'), rebindDomain);
    bindFunctionalControl(document.getElementById('shuffle-deck-btn'), shuffleDeck);
    bindFunctionalControl(document.getElementById('open-pack-btn'), () => openPack('daily'));
    bindFunctionalControl(buyPackBtn, buyPackWithTon);
    bindFunctionalControl(claimDailyRewardBtn, claimDailyReward);
    bindFunctionalControl(claimQuestRewardBtn, claimQuestReward);
    document.querySelectorAll('.reward-pack-btn').forEach((button) => {
      bindFunctionalControl(button, () => openRewardPack(button.dataset.rewardPack));
    });
    bindFunctionalControl(foilPack, () => {
      if (state.packOpening) {
        return;
      }
      if (state.pendingPackSource === 'paid' && state.pendingPackPaymentId) {
        openPack('paid', state.pendingPackPaymentId, 'lucky');
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
    bindFunctionalControl(document.getElementById('nav-wallet'), () => switchView('wallet'));
    bindFunctionalControl(document.getElementById('nav-pack'), () => switchView('pack'));
    bindFunctionalControl(document.getElementById('nav-modes'), () => switchView('modes'));
    bindFunctionalControl(document.getElementById('nav-profile'), () => switchView('profile'));
    bindFunctionalControl(document.getElementById('nav-achievements'), () => switchView('achievements'));
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
    document.addEventListener('pointerdown', (event) => {
      interceptDeckDomainAction(event).catch(() => {});
    }, true);
    document.addEventListener('click', (event) => {
      interceptDeckDomainAction(event).catch(() => {});
    }, true);
    document.addEventListener('pointerdown', (event) => {
      interceptInteractiveBattleAction(event).catch(() => {});
    }, true);
    document.addEventListener('click', (event) => {
      interceptInteractiveBattleAction(event).catch(() => {});
    }, true);
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
    renderProfile();
    renderDisciplineBuild({pool: 0, points: {attack: 0, defense: 0, luck: 0, speed: 0, magic: 0}});
    renderDeck(null);
    renderOwnedDecks([], null);
    renderAchievements([]);
    refreshOneCardSelector();
    switchView('wallet');
    updateButtons();
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
                season_points INTEGER NOT NULL DEFAULT 0,
                season_level INTEGER NOT NULL DEFAULT 1,
                wins_for_quest INTEGER NOT NULL DEFAULT 0,
                wins_claimed INTEGER NOT NULL DEFAULT 0,
                daily_claimed_on TEXT,
                updated_at TEXT NOT NULL
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
                season_points INTEGER NOT NULL DEFAULT 0,
                season_level INTEGER NOT NULL DEFAULT 1,
                wins_for_quest INTEGER NOT NULL DEFAULT 0,
                wins_claimed INTEGER NOT NULL DEFAULT 0,
                daily_claimed_on TEXT,
                updated_at TEXT NOT NULL
            );
            '''
        )
        matchmaking_columns = {row['name'] for row in conn.execute("PRAGMA table_info(matchmaking_queue)").fetchall()}
        if 'selected_slot' not in matchmaking_columns:
            conn.execute('ALTER TABLE matchmaking_queue ADD COLUMN selected_slot INTEGER')
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
                    wallet, pack_shards, rare_tokens, lucky_tokens, season_points,
                    season_level, wins_for_quest, wins_claimed, daily_claimed_on, updated_at
                ) VALUES (?, 0, 0, 0, 0, 1, 0, 0, NULL, ?)
                ''',
                (wallet, now_iso()),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM player_rewards WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row)


def normalize_reward_progress_fields(*, pack_shards, rare_tokens, lucky_tokens, season_points, season_level, wins_for_quest, wins_claimed):
    season_level = max(1, int(season_level or 1))
    season_points = max(0, int(season_points or 0))
    lucky_tokens = max(0, int(lucky_tokens or 0))
    while season_points >= season_level * 12:
        season_points -= season_level * 12
        season_level += 1
        lucky_tokens += 1
    return {
        'pack_shards': max(0, int(pack_shards or 0)),
        'rare_tokens': max(0, int(rare_tokens or 0)),
        'lucky_tokens': lucky_tokens,
        'season_points': season_points,
        'season_level': season_level,
        'wins_for_quest': max(0, int(wins_for_quest or 0)),
        'wins_claimed': max(0, int(wins_claimed or 0)),
    }


def reward_summary(wallet):
    rewards = ensure_player_rewards(wallet)
    rewards['daily_available'] = rewards.get('daily_claimed_on') != today_utc_str()
    rewards['quest_ready'] = int(rewards.get('wins_for_quest', 0)) - int(rewards.get('wins_claimed', 0)) >= 3
    rewards['next_quest_target'] = int(rewards.get('wins_claimed', 0)) + 3
    rewards['season_target'] = max(12, int(rewards.get('season_level', 1)) * 12)
    rewards['season_progress'] = round(int(rewards.get('season_points', 0)) / max(1, rewards['season_target']), 3)
    return rewards


def grant_match_rewards(wallet, *, won=False, ranked=False):
    rewards = ensure_player_rewards(wallet)
    pack_shards = int(rewards.get('pack_shards', 0)) + (2 if won else 1)
    rare_tokens = int(rewards.get('rare_tokens', 0))
    lucky_tokens = int(rewards.get('lucky_tokens', 0))
    season_points = int(rewards.get('season_points', 0)) + (3 if ranked else 2) + (2 if won else 0)
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
        season_points=int(rewards.get('season_points', 0)) + 2,
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
        season_points=rewards.get('season_points', 0),
        season_level=rewards.get('season_level', 1),
        wins_for_quest=rewards.get('wins_for_quest', 0),
        wins_claimed=rewards.get('wins_claimed', 0),
    )
    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE player_rewards
            SET pack_shards = ?, rare_tokens = ?, lucky_tokens = ?, updated_at = ?
            WHERE wallet = ?
            ''',
            (
                normalized['pack_shards'],
                normalized['rare_tokens'],
                normalized['lucky_tokens'],
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
        'pool_total': 2500 + min(900, bounded_domain_edge * 90 + max(0, bonus_score // 80)),
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
    tier_id = str(metadata.get('tierId') or 'regular').lower()
    level = max(1, int(metadata.get('level') or 1))
    bounded = max(0, min(900, round((score - 2500) * 0.06)))
    tier_flat = {'regular': 0, 'tier2': 80, 'tier1': 160, 'tier0': 260}.get(tier_id, 0)
    level_bonus = min(120, (level - 1) * 12)
    return bounded + tier_flat + level_bonus


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


def choose_bot_round_action(planned_action, energy, ability_state, metadata, phase):
    actions = available_actions_for_state(energy, ability_state)
    if 'ability' in actions:
        role = str((metadata or {}).get('role') or '')
        if phase in {'finisher', 'risk'} or role in {'Control', 'Disruptor', 'Damage', 'Sniper'}:
            return 'ability'
    if planned_action in actions:
        return planned_action
    if 'burst' in actions:
        return 'burst'
    return 'guard'


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


def bot_cards_slightly_weaker_than_player(player_cards, seed_value):
    rng = random.Random(hashlib.sha256(f'bot-weaker:{seed_value}'.encode()).hexdigest())
    cards = []
    normalized_cards = [normalize_card_profile(card) for card in (player_cards or [])]
    if not normalized_cards:
        return random_bot_cards(seed_value, count=5)

    for slot, source in enumerate(normalized_cards[:5], start=1):
        # Keep bot close to player power but a bit weaker on average.
        scale = rng.uniform(0.86, 0.94)
        score = max(1, int(round(source.get('pool_value', source.get('score', 100)) * scale + rng.uniform(-4.0, 4.0))))
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
        if field is None:
            continue
        text = json.dumps(field, ensure_ascii=False) if isinstance(field, (dict, list)) else str(field)
        for direct_match in re.findall(r'(?<!\d)(\d{4})\.ton(?!\d)', text.lower()):
            candidates.add(direct_match)

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


def display_name_for_wallet(wallet):
    link = telegram_wallet_link(wallet)
    if link:
        return link.get('username') or link.get('first_name') or short_wallet(wallet)
    return short_wallet(wallet)


def short_wallet(wallet):
    return f'{wallet[:6]}...{wallet[-6:]}' if wallet and len(wallet) > 12 else wallet


def link_wallet_to_telegram(wallet, telegram_user_id):
    link = telegram_user_link(telegram_user_id)
    if link is None:
        raise ValueError('Сначала запусти бота в Telegram через /start, потом открой mini app.')
    with closing(get_db()) as conn:
        conn.execute(
            'UPDATE telegram_users SET wallet = ?, updated_at = ?, linked_at = COALESCE(linked_at, ?) WHERE telegram_user_id = ?',
            (wallet, now_iso(), now_iso(), telegram_user_id),
        )
        conn.commit()
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


def resolve_player_reference(reference):
    ref = (reference or '').strip()
    if not ref:
        raise ValueError('Укажи кошелёк или .ton домен соперника.')
    if valid_wallet_address(reference):
        return reference.strip()

    domain = normalize_strict_ton_domain(ref)
    if not domain:
        raise ValueError('Поле соперника принимает только полный кошелёк или 4-значный домен вида 1234.ton.')

    with closing(get_db()) as conn:
        row = conn.execute(
            '''
            SELECT wallet FROM players
            WHERE current_domain = ? OR best_domain = ?
            ORDER BY updated_at DESC
            LIMIT 1
            ''',
            (domain, domain),
        ).fetchone()
    if row is None:
        raise ValueError('Игрок с таким доменом ещё не найден. Пусть он сначала зайдёт в игру и выберет домен.')
    return row['wallet']


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
                'wallet': row['wallet'],
                'display_name': row['username'] or row['first_name'] or short_wallet(row['wallet']),
                'domain': row['current_domain'],
                'rating': row['rating'],
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
        result.append(
            {
                'wallet': row['wallet'],
                'display_name': row['username'] or row['first_name'] or short_wallet(row['wallet']),
                'domain': row['current_domain'],
                'rating': row['rating'],
                'average_attack': summary['average_attack'] if summary else None,
                'average_defense': summary['average_defense'] if summary else None,
            }
        )
    return result


def add_friend(owner_wallet, friend_reference):
    friend_wallet = resolve_player_reference(friend_reference)
    if friend_wallet == owner_wallet:
        raise ValueError('Себя в друзья добавлять не нужно.')
    ensure_player(friend_wallet)
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT OR IGNORE INTO friends (owner_wallet, friend_wallet, created_at) VALUES (?, ?, ?)',
            (owner_wallet, friend_wallet, now_iso()),
        )
        conn.commit()
    return friend_wallet


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
    return {
        'wallet': player['wallet'],
        'rating': player['rating'],
        'games_played': player['games_played'],
        'ranked_wins': player['ranked_wins'],
        'ranked_losses': player['ranked_losses'],
        'best_domain': player['best_domain'],
        'current_domain': player['current_domain'],
        'telegram_linked': telegram_wallet_link(wallet) is not None,
        'display_name': display_name_for_wallet(wallet),
        'deck_summary': current_deck,
        'rewards': reward_summary(wallet),
        'synergies': compute_domain_synergies(wallet),
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
    return [dict(row) for row in rows]


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
        'interactive_hint': f"Энергия: {int(state.get('energy_a', 0))}. Натиск стоит 2, блок 1, способность домена 3.",
    }


def create_solo_battle(wallet, domain, mode, mode_title, opponent_wallet, opponent_domain, player_cards, opponent_cards, build_a, build_b, selected_slot_a, selected_slot_b, strategy_key_a='balanced', strategy_key_b='balanced'):
    ensure_runtime_tables()
    player_cards = [normalize_card_profile(card) for card in (player_cards or [])]
    opponent_cards = [normalize_card_profile(card) for card in (opponent_cards or [])]
    featured_a = find_card_by_slot(player_cards, selected_slot_a)
    featured_b = find_card_by_slot(opponent_cards, selected_slot_b)
    domain_meta_a = battle_domain_metadata(domain, wallet=wallet)
    domain_meta_b = battle_domain_metadata(opponent_domain, wallet=opponent_wallet)
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
        'prev_a': None,
        'prev_b': None,
        'rounds': [],
        'swing_pairs': [[rng.randint(0, 2), rng.randint(0, 2)] for _ in range(rounds_total)],
        'deck_power_a': deck_score(player_cards),
        'deck_power_b': deck_score(opponent_cards),
        'complete': False,
        'tie_breaker': False,
    }
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
    state['energy_a'] = 3
    state['energy_b'] = 3
    if action_key not in available_actions_for_state(state.get('energy_a', 0), ability_state_a):
        raise ValueError('Недостаточно энергии или способность недоступна.')
    planned_action_b = (state.get('opponent_action_plan') or default_action_plan())[idx]
    action_b = choose_bot_round_action(planned_action_b, state.get('energy_b', 0), ability_state_b, domain_meta_b, phase)
    build_a = state.get('build_a') or {}
    build_b = state.get('build_b') or {}
    featured_a = normalize_card_profile(state.get('featured_a') or card_a)
    featured_b = normalize_card_profile(state.get('featured_b') or card_b)
    prev_a = state.get('prev_a')
    prev_b = state.get('prev_b')
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
    if crit_a:
        roll_bonus_a += 6
    if crit_b:
        roll_bonus_b += 6
    swing_a, swing_b = (state.get('swing_pairs') or [[0, 0]])[idx]
    domain_bonus_a = passive_bonus_a + active_bonus_a + counter_bonus_a + passive_roll_a
    domain_bonus_b = passive_bonus_b + active_bonus_b + counter_bonus_b + passive_roll_b
    total_a = value_a + card_boost_a + action_bonus_a + strategy_bonus_a + skill_bonus_a + featured_bonus_a + roll_bonus_a + domain_bonus_a + swing_a
    total_b = value_b + card_boost_b + action_bonus_b + strategy_bonus_b + skill_bonus_b + featured_bonus_b + roll_bonus_b + domain_bonus_b + swing_b

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
            'swing_a': swing_a,
            'swing_b': swing_b,
            'total_a': total_a,
            'total_b': total_b,
            'winner': winner,
        }
    )
    state['current_round'] = idx + 1
    if state['current_round'] >= rounds_total:
        state['complete'] = True
        finalize_solo_battle_state(state)
        record_non_ranked_game(state['wallet'], state['domain'])
        won = state.get('winner') == 'a'
        grant_domain_experience(state['wallet'], state['domain'], 18, won=won)
        log_domain_telemetry(
            'solo_battle_complete',
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
    snapshot = {
        'id': row['id'],
        'ready_self': self_ready,
        'ready_opponent': opp_ready,
        'ready_count': int(bool(row['ready_a'])) + int(bool(row['ready_b'])),
        'started': bool(row['started_at']),
        'started_at': row['started_at'],
    }
    if row['started_at']:
        snapshot['payload'] = battle_session_payload(row, viewer_wallet)
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
    match = head_to_head_result(
        wallet_a,
        domain_a,
        wallet_b,
        domain_b,
        selected_slot_a=selected_slot_a,
        selected_slot_b=selected_slot_b,
        strategy_key_a=strategy_key_a,
        strategy_key_b=strategy_key_b,
    )
    rating_meta = None
    if mode == 'ranked':
        _, _, rating_a_before, rating_a_after, rating_b_before, rating_b_after = apply_ranked_result_duel(match)
        rating_meta = {
            'rating_a_before': rating_a_before,
            'rating_a_after': rating_a_after,
            'rating_b_before': rating_b_before,
            'rating_b_after': rating_b_after,
        }
    else:
        record_non_ranked_game(wallet_a, domain_a)
        record_non_ranked_game(wallet_b, domain_b)
        apply_non_ranked_domain_progress(match, mode=mode)
    fresh_a = invite_result_payload({'mode': mode}, match, wallet_a, rating_meta=rating_meta)
    fresh_b = invite_result_payload({'mode': mode}, match, wallet_b, rating_meta=rating_meta)
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


def mark_battle_ready(session_id, wallet, selected_slot=None, strategy_key=None):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
        if row is None:
            raise ValueError('Боевая сессия не найдена.')
        if wallet not in {row['wallet_a'], row['wallet_b']}:
            raise ValueError('Нет доступа к этой сессии.')
        is_a = wallet == row['wallet_a']
        payload_key = 'payload_a_json' if is_a else 'payload_b_json'
        current_payload = json.loads(row[payload_key]) if row[payload_key] else {}
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
        row = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
        if row and row['started_at'] is None and row['ready_a'] and row['ready_b']:
            finalize_battle_session(conn, row)
            row = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
        conn.commit()
    return battle_session_snapshot(row, wallet)


def get_battle_ready_status(session_id, wallet):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM battle_sessions WHERE id = ?', (session_id,)).fetchone()
    if row is None:
        raise ValueError('Боевая сессия не найдена.')
    if wallet not in {row['wallet_a'], row['wallet_b']}:
        raise ValueError('Нет доступа к этой сессии.')
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


def settle_matchmaking_pair(conn, mode, wallet, domain, opponent_row, selected_slot=None):
    opponent_wallet = opponent_row['wallet']
    opponent_domain = opponent_row['domain']
    match = head_to_head_result(
        wallet,
        domain,
        opponent_wallet,
        opponent_domain,
        selected_slot_a=selected_slot,
        selected_slot_b=opponent_row['selected_slot'],
    )
    own_payload = invite_result_payload({'mode': mode}, match, wallet, rating_meta=None)
    opp_payload = invite_result_payload({'mode': mode}, match, opponent_wallet, rating_meta=None)
    _, own_payload, opp_payload = create_battle_session(conn, wallet, opponent_wallet, own_payload, opp_payload)
    set_matchmaking_cooldown(conn, wallet, opponent_wallet)
    ts = now_iso()

    conn.execute(
        '''
        UPDATE matchmaking_queue
        SET status = 'matched', opponent_wallet = ?, result_json = ?, updated_at = ?
        WHERE id = ?
        ''',
        (wallet, json.dumps(opp_payload, ensure_ascii=False), ts, opponent_row['id']),
    )
    queue_id = uuid.uuid4().hex
    conn.execute(
        '''
        INSERT INTO matchmaking_queue (
            id, mode, wallet, domain, selected_slot, status, opponent_wallet, result_json, created_at, updated_at, consumed_at
        ) VALUES (?, ?, ?, ?, NULL, 'matched', ?, ?, ?, ?, NULL)
        ''',
        (queue_id, mode, wallet, domain, opponent_wallet, json.dumps(own_payload, ensure_ascii=False), ts, ts),
    )
    return queue_id, own_payload, opponent_wallet


def finalize_invite(invite):
    match = head_to_head_result(
        invite['inviter_wallet'],
        invite['inviter_domain'],
        invite['invitee_wallet'],
        invite['invitee_domain'],
    )
    rating_meta = None
    if invite['mode'] == 'ranked':
        _, _, rating_a_before, rating_a_after, rating_b_before, rating_b_after = apply_ranked_result_duel(match)
        rating_meta = {
            'rating_a_before': rating_a_before,
            'rating_a_after': rating_a_after,
            'rating_b_before': rating_b_before,
            'rating_b_after': rating_b_after,
        }
    else:
        record_non_ranked_game(invite['inviter_wallet'], invite['inviter_domain'])
        record_non_ranked_game(invite['invitee_wallet'], invite['invitee_domain'])
        apply_non_ranked_domain_progress(match, mode=invite['mode'])
    result = {
        'for_inviter': invite_result_payload(invite, match, invite['inviter_wallet'], rating_meta=rating_meta),
        'for_invitee': invite_result_payload(invite, match, invite['invitee_wallet'], rating_meta=rating_meta),
    }
    save_invite_result(invite['id'], result)
    return load_invite(invite['id'])


def set_invite_status(invite_id, status):
    with closing(get_db()) as conn:
        conn.execute(
            'UPDATE duel_invites SET status = ?, responded_at = ? WHERE id = ?',
            (status, now_iso(), invite_id),
        )
        conn.commit()
    return load_invite(invite_id)


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
        invite = set_invite_status(invite_id, 'declined')
        inviter_link = telegram_wallet_link(invite['inviter_wallet'])
        if inviter_link:
            telegram_send_message(inviter_link['chat_id'], f'Соперник отклонил приглашение {invite_id}.')
        if chat_id and invite['telegram_message_id']:
            telegram_clear_inline_keyboard(chat_id, invite['telegram_message_id'])
        telegram_answer_callback(callback_id, 'Приглашение отклонено.')
        return

    if action == 'invite_accept':
        invite = set_invite_status(invite_id, 'accepted')
        invite = finalize_invite(invite)
        inviter_link = telegram_wallet_link(invite['inviter_wallet'])
        invitee_link = telegram_wallet_link(invite['invitee_wallet'])
        if inviter_link:
            telegram_send_message(
                inviter_link['chat_id'],
                'Соперник принял вызов.\n' + json.dumps(invite['result_json']['for_inviter'], ensure_ascii=False, indent=2),
            )
        if invitee_link:
            telegram_send_message(
                invitee_link['chat_id'],
                'Матч завершён.\n' + json.dumps(invite['result_json']['for_invitee'], ensure_ascii=False, indent=2),
            )
        if chat_id and invite['telegram_message_id']:
            telegram_clear_inline_keyboard(chat_id, invite['telegram_message_id'])
        telegram_answer_callback(callback_id, 'Вызов принят. Матч сыгран.')
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


@app.route('/api/health')
def api_health():
    return jsonify({'ok': True, 'time': now_iso()})


@app.route('/api/player/<wallet>')
def api_player(wallet):
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    return jsonify({'player': get_player(wallet)})


@app.route('/api/player/register', methods=['POST'])
def api_player_register():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Некорректный адрес кошелька.')
    ensure_player(wallet)
    return jsonify({'ok': True, 'player': get_player(wallet)})


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
        link = link_wallet_to_telegram(wallet, user['id'])
        ensure_player(wallet)
    except (ValueError, KeyError) as exc:
        return json_error(str(exc), 400)
    return jsonify({'ok': True, 'telegram': link, 'player': get_player(wallet)})


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

    if source == 'paid':
        if not payment_id:
            return json_error('Нужен подтверждённый платёж для открытия платного пака.', 403)
        with closing(get_db()) as conn:
            payment = conn.execute('SELECT * FROM pack_payments WHERE id = ?', (payment_id,)).fetchone()
        if payment is None or payment['wallet'] != wallet or payment['domain'] != domain or payment['status'] != 'confirmed':
            return json_error('Платёж не подтверждён.', 403)
        pack_type = 'lucky'

    rewards = reward_summary(wallet)
    if source == 'reward':
        try:
            rewards = spend_pack_currency(wallet, pack_type)
        except ValueError as exc:
            return json_error(str(exc), 400)

    seed = f'{domain}:{wallet}:{source}:{payment_id or now_iso()}'
    guarantee_legendary = pack_pity_status(wallet, pack_type) >= PACK_PITY_THRESHOLD - 1
    cards = generate_pack(domain, seed_value=seed, pack_type=pack_type, guarantee_legendary=guarantee_legendary, wallet=wallet)
    total = deck_score(cards)
    pack_id = store_pack_open(wallet, domain, source, cards, total, payment_id=payment_id or None)
    ensure_player(wallet, domain, domain)
    pity_after = update_pack_pity(wallet, pack_type, cards)
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
        },
    )
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
            'domain_metadata': metadata,
            'progress': progress,
            'rewards': rewards,
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
    pack_types = [
        {
            'key': key,
            'label': value['label'],
            'count': value['count'],
            'weights': value['weights'],
            'lucky_bonus': bool(value.get('lucky_bonus')),
            'costs': value.get('costs') or {},
        }
        for key, value in PACK_TYPES.items()
    ]
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


@app.route('/api/matchmaking/<mode>/search', methods=['POST'])
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

    try:
        with closing(get_db()) as conn:
            cleanup_matchmaking_queue(conn)
            latest = latest_matchmaking_row(conn, wallet, mode)
            if latest and latest['status'] == 'matched' and latest['result_json'] and not latest['consumed_at']:
                result = json.loads(latest['result_json'])
                conn.execute(
                    "UPDATE matchmaking_queue SET consumed_at = ?, status = 'completed', updated_at = ? WHERE id = ?",
                    (now_iso(), now_iso(), latest['id']),
                )
                conn.commit()
                return jsonify({'status': 'matched', 'result': result, 'player': get_player(wallet)})

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
                conn.commit()
                queue_id, own_payload, opponent_wallet = settle_matchmaking_pair(conn, mode, wallet, domain, opponent, selected_slot=selected_slot)
                conn.commit()
                return jsonify(
                    {
                        'status': 'matched',
                        'queue_id': queue_id,
                        'opponent_wallet': opponent_wallet,
                        'result': own_payload,
                        'player': get_player(wallet),
                    }
                )

            queue_id = upsert_searching_matchmaking(conn, wallet, domain, mode, selected_slot=selected_slot)
            conn.commit()
            response = {'status': 'searching', 'queue_id': queue_id, 'player': get_player(wallet)}
            if min_cooldown > 0:
                response['cooldown_seconds'] = min_cooldown
            return jsonify(response)
    except sqlite3.Error as exc:
        return json_error(f'Ошибка очереди матчмейкинга: {exc}', 500)


@app.route('/api/matchmaking/<mode>/status')
def api_matchmaking_status(mode):
    if mode not in {'ranked', 'casual'}:
        return json_error('Неизвестный режим матчмейкинга.', 404)
    ensure_runtime_tables()
    wallet = (request.args.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно передать свой кошелёк.')
    try:
        with closing(get_db()) as conn:
            cleanup_matchmaking_queue(conn)
            row = latest_matchmaking_row(conn, wallet, mode)
            if row is None:
                return jsonify({'status': 'idle'})
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
                return jsonify(response)
            if row['status'] == 'matched' and row['result_json']:
                result = json.loads(row['result_json'])
                conn.execute(
                    "UPDATE matchmaking_queue SET consumed_at = ?, status = 'completed', updated_at = ? WHERE id = ?",
                    (now_iso(), now_iso(), row['id']),
                )
                conn.commit()
                return jsonify({'status': 'matched', 'result': result, 'player': get_player(wallet)})
            return jsonify({'status': row['status']})
    except sqlite3.Error as exc:
        return json_error(f'Ошибка очереди матчмейкинга: {exc}', 500)


@app.route('/api/matchmaking/<mode>/cancel', methods=['POST'])
def api_matchmaking_cancel(mode):
    if mode not in {'ranked', 'casual'}:
        return json_error('Неизвестный режим матчмейкинга.', 404)
    ensure_runtime_tables()
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    try:
        with closing(get_db()) as conn:
            conn.execute(
                '''
                UPDATE matchmaking_queue
                SET status = 'cancelled', updated_at = ?
                WHERE wallet = ? AND mode = ? AND status = 'searching'
                ''',
                (now_iso(), wallet, mode),
            )
            conn.commit()
    except sqlite3.Error as exc:
        return json_error(f'Ошибка отмены поиска: {exc}', 500)
    return jsonify({'ok': True, 'status': 'cancelled'})


@app.route('/api/battle-ready', methods=['POST'])
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
    return jsonify({'ok': True, 'status': status})


@app.route('/api/battle-ready/status')
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
            match = head_to_head_result(wallet, domain, opponent_wallet, opponent_domain, selected_slot_a=selected_slot)
            record_non_ranked_game(wallet, domain)
            record_non_ranked_game(opponent_wallet, opponent_domain)
            apply_non_ranked_domain_progress(match, mode='duel')
            result = invite_result_payload({'mode': 'duel'}, match, wallet)
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
    base_seed = f'bot-duel:{wallet}:{domain}:{now_iso()}'
    bot_cards = bot_cards_slightly_weaker_than_player(player_cards, base_seed)
    bot_pool = max(1800, int(round(player_build['pool'] * 0.92)))
    bot_build = {'pool': bot_pool, 'points': default_discipline_build(bot_pool)}
    selected_slot = selected_slot or auto_tactical_slot(player_cards, player_build['points'])
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
        selected_slot_b=auto_tactical_slot(bot_cards, bot_build['points']),
        strategy_key_a='balanced',
        strategy_key_b='tricky',
    )
    return jsonify(
        {
            'result': result,
            'bot_cards': bot_cards,
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
    return jsonify({'result': result})


@app.route('/api/solo-battle/status')
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
def api_match_invite(invite_id):
    wallet = (request.args.get('wallet') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Нужно передать свой кошелёк.')
    try:
        invite = expire_invite_if_needed(load_invite(invite_id))
    except ValueError as exc:
        return json_error(str(exc), 404)

    if wallet not in {invite['inviter_wallet'], invite['invitee_wallet']}:
        return json_error('Нет доступа к этому приглашению.', 403)

    result = None
    if invite['result_json']:
        result = invite['result_json']['for_inviter'] if wallet == invite['inviter_wallet'] else invite['result_json']['for_invitee']

    return jsonify({'invite': invite, 'result': result, 'player': get_player(wallet)})


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


init_db()


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'settings':
        raise SystemExit(handle_settings_cli(sys.argv[2:]))
    app.run(host=HOST, port=PORT, debug=DEBUG)
