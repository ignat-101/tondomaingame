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
      min-height: 100vh;
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
    }

    .hero-top {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
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
      transform-style: preserve-3d;
      transition: transform 420ms cubic-bezier(.2,.8,.2,1), box-shadow 420ms ease, border-color 420ms ease;
    }

    .mode-card::after {
      content: "";
      position: absolute;
      inset: -1px;
      border-radius: 20px;
      background: linear-gradient(135deg, rgba(69, 215, 255, 0.18), rgba(83, 246, 184, 0.14), transparent 70%);
      opacity: 0;
      transition: opacity 320ms ease;
      pointer-events: none;
    }

    .mode-card:hover {
      transform: translateY(-6px) rotateX(7deg) rotateY(-7deg);
      box-shadow: 0 28px 48px rgba(0, 0, 0, 0.28);
    }

    .mode-card.active-mode {
      border-color: rgba(83, 246, 184, 0.58);
      box-shadow: 0 30px 60px rgba(69, 215, 255, 0.22);
      transform: translateY(-18px) translateZ(90px) rotateX(14deg) rotateY(-14deg) scale(1.08);
    }

    .mode-card.active-mode::after {
      opacity: 1;
    }

    .mode-card.active-mode .mode-burst {
      opacity: 1;
      transform: scale(1);
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
      overflow: auto;
      -webkit-overflow-scrolling: touch;
      min-height: auto;
      max-height: 46vh;
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
      animation: scorePulse 860ms cubic-bezier(.2,.82,.2,1) both;
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
      animation: rowPop 420ms cubic-bezier(.2,.82,.2,1);
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
      display: block;
    }

    .interactive-battle-panel {
      display: grid;
      gap: 12px;
      margin: 14px 0 10px;
      padding: 14px;
      border-radius: 18px;
      border: 1px solid rgba(121, 217, 255, 0.2);
      background: linear-gradient(135deg, rgba(8, 23, 43, 0.82), rgba(10, 29, 34, 0.88));
      box-shadow: 0 18px 44px rgba(0, 0, 0, 0.22);
    }

    .interactive-battle-panel.floating {
      position: fixed;
      left: 50%;
      top: 50%;
      z-index: 80;
      width: min(92vw, 460px);
      margin: 0;
      padding: 18px 16px 16px;
      transform: translate(-50%, -50%);
      border-radius: 24px;
      border-color: rgba(121, 217, 255, 0.32);
      background:
        linear-gradient(135deg, rgba(7, 19, 35, 0.96), rgba(10, 31, 39, 0.97)),
        radial-gradient(circle at top, rgba(69, 215, 255, 0.16), transparent 55%);
      box-shadow:
        0 28px 80px rgba(0, 0, 0, 0.48),
        0 0 0 1px rgba(121, 217, 255, 0.08);
      backdrop-filter: blur(18px);
      animation: floatingBattlePanelIn 280ms cubic-bezier(.16,.84,.2,1);
    }

    .interactive-battle-panel.floating::before {
      content: "";
      position: fixed;
      inset: 0;
      z-index: -1;
      background: rgba(3, 9, 18, 0.56);
      backdrop-filter: blur(4px);
    }

    .interactive-battle-title {
      text-align: center;
      font-weight: 800;
      letter-spacing: 0.03em;
      font-size: clamp(18px, 5vw, 24px);
    }

    .interactive-battle-actions {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }

    .interactive-action-btn {
      min-height: 54px;
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.22);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      font-weight: 800;
      transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
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

    .interactive-action-btn.channel {
      border-color: rgba(69, 215, 255, 0.42);
      background: linear-gradient(135deg, rgba(69, 215, 255, 0.18), rgba(255, 255, 255, 0.04));
    }

    @keyframes floatingBattlePanelIn {
      from {
        opacity: 0;
        transform: translate(-50%, -46%) scale(0.92);
      }
      to {
        opacity: 1;
        transform: translate(-50%, -50%) scale(1);
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
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 10px;
      margin: 10px 0 14px;
    }

    .battle-fighter {
      border-radius: 16px;
      border: 1px solid rgba(121, 217, 255, 0.26);
      padding: 12px;
      background: linear-gradient(145deg, rgba(18, 39, 67, 0.9), rgba(8, 16, 30, 0.92));
      box-shadow: inset 0 0 22px rgba(83, 246, 184, 0.08);
      opacity: 0;
      animation: fighterIn 460ms cubic-bezier(.2,.82,.2,1) forwards;
    }

    .battle-fighter strong {
      display: block;
      margin: 4px 0;
      font-size: 18px;
      line-height: 1.2;
    }

    .battle-fighter.enemy {
      text-align: right;
      animation-delay: 100ms;
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
      border-radius: 24px;
      border: 1px solid rgba(255, 255, 255, 0.2);
      background:
        radial-gradient(circle at 50% 0%, rgba(255, 255, 255, 0.12), transparent 38%),
        linear-gradient(180deg, rgba(8, 12, 18, 0.96), rgba(6, 10, 15, 0.94));
      padding: 16px 14px 18px;
      text-align: center;
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
      background: rgba(3, 9, 18, 0.72);
    }

    .pack-counter {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      min-width: 260px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.35);
      color: rgba(245, 245, 245, 0.95);
      letter-spacing: 0.14em;
      font-weight: 700;
      padding: 0 20px;
      box-shadow: 0 0 20px rgba(255, 255, 255, 0.12);
      margin-bottom: 10px;
      text-transform: uppercase;
    }

    .pack-note {
      color: rgba(245, 245, 245, 0.8);
      margin: 0 0 12px;
      font-size: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .foil-pack {
      position: relative;
      width: min(350px, 92%);
      margin: 0 auto;
      border-radius: 18px;
      border: 1px solid rgba(0, 0, 0, 0.22);
      background:
        radial-gradient(circle at 45% 24%, rgba(255, 255, 255, 0.84), rgba(232, 232, 232, 0.98) 52%, rgba(210, 210, 210, 1));
      color: #1e1e1e;
      padding: 72px 22px 58px;
      box-shadow: 0 28px 44px rgba(0, 0, 0, 0.42);
      overflow: visible;
      transition: transform 420ms ease, opacity 420ms ease;
    }

    .pack-showcase.cinematic .foil-pack {
      position: fixed;
      left: 50%;
      top: 50%;
      width: min(88vw, 560px);
      transform: translate(-50%, -50%) scale(1.38);
      z-index: 7100;
    }

    .foil-pack::before, .foil-pack::after {
      content: "";
      position: absolute;
      left: -1px;
      right: -1px;
      height: 16px;
      background:
        linear-gradient(135deg, transparent 8px, #ececec 0) repeat-x;
      background-size: 16px 16px;
    }

    .foil-pack::before { top: 0; }

    .foil-pack::after {
      bottom: 0;
      transform: rotate(180deg);
    }

    .pack-cap {
      position: absolute;
      left: 14px;
      right: 14px;
      top: 18px;
      height: 22px;
      border-top: 2px solid rgba(0, 0, 0, 0.2);
      border-bottom: 2px solid rgba(0, 0, 0, 0.14);
      background: repeating-linear-gradient(
        180deg,
        rgba(255, 255, 255, 0.88),
        rgba(255, 255, 255, 0.88) 2px,
        rgba(228, 228, 228, 0.92) 2px,
        rgba(228, 228, 228, 0.92) 4px
      );
      transform-origin: top center;
      z-index: 4;
    }

    .foil-pack.opening .pack-cap {
      animation: tearOpen 860ms cubic-bezier(.16,.84,.2,1) forwards;
    }

    .foil-pack.opening {
      animation: packShake 560ms ease-in-out;
    }

    .pack-showcase.opened .foil-pack {
      transform: translateY(-26px) scale(0.92);
      opacity: 0.18;
    }

    .foil-pack.vanishing {
      animation: packVanish 1.1s cubic-bezier(.16,.84,.2,1) forwards;
    }

    .pack-emblem {
      width: 132px;
      height: 132px;
      margin: 0 auto 16px;
      border-radius: 50%;
      border: 0;
      background: #1593d8;
      box-shadow: inset 0 -8px 16px rgba(0, 0, 0, 0.12);
      display: grid;
      place-items: center;
    }

    .pack-emblem-ton {
      width: 88px;
      height: 88px;
      display: block;
    }

    .pack-brand {
      margin-top: 8px;
      font-family: "Times New Roman", Georgia, serif;
      font-size: clamp(48px, 9vw, 68px);
      font-weight: 700;
      letter-spacing: 0.02em;
      color: rgba(16, 16, 16, 0.9);
      text-transform: uppercase;
      line-height: 1;
    }

    .pack-sub {
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(24px, 5vw, 34px);
      color: rgba(26, 26, 26, 0.8);
      margin: 8px 0 0;
      line-height: 1.1;
    }

    .pack-tap {
      margin-top: 12px;
      color: rgba(242, 242, 242, 0.92);
      letter-spacing: 0.2em;
      font-size: clamp(18px, 5vw, 26px);
      font-weight: 700;
      text-transform: uppercase;
      font-family: Georgia, "Times New Roman", serif;
    }

    .pack-sequence-layer {
      position: fixed;
      inset: 0;
      z-index: 7000;
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
      border-radius: 20px;
      border: 1px solid rgba(121, 217, 255, 0.4);
      padding: 16px 14px;
      background:
        radial-gradient(circle at top right, rgba(69, 215, 255, 0.22), transparent 32%),
        linear-gradient(180deg, rgba(18, 41, 71, 0.95), rgba(11, 18, 35, 0.98));
      box-shadow: 0 32px 72px rgba(0, 0, 0, 0.56);
      color: var(--text);
      transform: translate(-50%, -50%) scale(0.44);
      opacity: 0;
      transition:
        left 700ms cubic-bezier(.16,.84,.2,1),
        top 700ms cubic-bezier(.16,.84,.2,1),
        transform 700ms cubic-bezier(.16,.84,.2,1),
        opacity 220ms ease;
      overflow: hidden;
    }

    .pack-preview-card.focused {
      opacity: 1;
      transform: translate(-50%, -50%) scale(1);
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

    @keyframes tearOpen {
      0% { transform: translate3d(0, 0, 0) rotate(0deg); opacity: 1; }
      40% { transform: translate3d(-18px, -16px, 0) rotate(-8deg); opacity: 1; }
      100% { transform: translate3d(-140px, -110px, 0) rotate(-26deg); opacity: 0; }
    }

    @keyframes packShake {
      0% { transform: translateX(0) rotate(0deg); }
      20% { transform: translateX(-3px) rotate(-1deg); }
      40% { transform: translateX(3px) rotate(1deg); }
      60% { transform: translateX(-2px) rotate(-0.5deg); }
      100% { transform: translateX(0) rotate(0deg); }
    }

    @keyframes packVanish {
      0% { opacity: 1; transform: translate(-50%, -50%) scale(1.18) rotate(0deg); filter: blur(0); }
      100% { opacity: 0; transform: translate(-50%, -50%) scale(0.08) rotate(-420deg); filter: blur(5px); }
    }

    @media (max-width: 920px) {
      body { padding-bottom: 84px; }
      .layout { grid-template-columns: 1fr; }
      .side { display: none; }
      .mode-grid.mode-focus::before {
        inset: -4px;
        background: rgba(2, 8, 16, 0.38);
        backdrop-filter: blur(2px);
      }
      .mode-card:hover {
        transform: none;
        box-shadow: none;
      }
      .mode-card.active-mode {
        transform: translateY(-4px) scale(1.01);
        box-shadow: 0 12px 30px rgba(69, 215, 255, 0.16);
      }
      .mobile-nav {
        position: fixed;
        left: 12px;
        right: 12px;
        bottom: 12px;
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 10px;
        padding: 10px;
        border-radius: 20px;
        border: 1px solid var(--line);
        background: rgba(7, 16, 25, 0.94);
        backdrop-filter: blur(16px);
        z-index: 20;
      }
      .mobile-nav button {
        min-height: 44px;
        height: 44px;
        padding: 7px 4px;
        font-size: 11px;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        line-height: 1.05;
        white-space: normal;
        word-break: break-word;
        min-width: 0;
      }

      #nav-achievements {
        font-size: 10px;
      }

      .hero {
        padding-bottom: 14px;
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
        padding: 14px;
        border-radius: 18px;
        box-shadow: 0 14px 28px rgba(0, 0, 0, 0.18);
      }

      .wallet-quick-item {
        padding: 12px 14px;
      }

      .wallet-quick-item strong {
        font-size: 14px;
        margin-bottom: 6px;
      }

      .wallet-quick-actions button,
      .wallet-domain-action {
        min-height: 50px;
        font-size: 14px;
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
        border-radius: 18px;
      }

      .domain-grid,
      .owned-decks {
        grid-template-columns: 1fr;
      }

      .wallet-domain-chip {
        min-height: 26px;
        padding: 0 8px;
        font-size: 11px;
      }

      .wallet-domain-mainline,
      .wallet-domain-more summary,
      .wallet-section .tiny,
      .wallet-flow-note {
        font-size: 12px;
      }
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
          <div class="badge" id="telegram-badge">Telegram: ожидание</div>
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

          <div class="pack-showcase" id="pack-showcase">
            <div class="pack-counter" id="pack-counter" style="display:none;"></div>
            <p class="pack-note" id="pack-note">TAP TO OPEN</p>
            <div class="foil-pack" id="foil-pack">
              <div class="pack-cap"></div>
              <div class="pack-emblem" aria-hidden="true">
                <svg class="pack-emblem-ton" viewBox="0 0 88 88" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <polyline points="16,24 44,70 72,24 16,24" stroke="#ffffff" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"></polyline>
                  <line x1="44" y1="24" x2="44" y2="62" stroke="#ffffff" stroke-width="8" stroke-linecap="round"></line>
                </svg>
              </div>
              <div class="pack-sub">Ton Domain Card Pack</div>
            </div>
            <div class="pack-tap">▲ TAP TO OPEN ▲</div>
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

          <div class="team-card" id="duel-invite-panel" style="margin-bottom:18px; display:none;">
            <h3>Дуэль (персональное приглашение)</h3>
            <div class="row">
              <input id="opponent-wallet" placeholder="Домен соперника">
              <input id="invite-timeout" type="number" min="30" max="600" step="30" value="60" placeholder="Время ответа, сек">
              <select id="match-delivery">
                <option value="site">Через сайт</option>
                <option value="telegram">Через Telegram</option>
              </select>
            </div>
            <div class="row">
              <select id="one-card-slot">
                <option value="">Выбери карту для режима одной карты</option>
              </select>
            </div>
            <div class="tiny">Режим "Через сайт" отправляет персональное приглашение в игру через сайт. Режим "Через Telegram" бот отправляет приглашение через Telegram. Для режима Telegram соперник должен заранее написать боту `/start` и открыть mini app хотя бы один раз.</div>
            <div class="actions" style="margin-top:10px;">
              <button id="play-duel-btn" disabled>Отправить дуэль</button>
            </div>
          </div>

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
            <div class="mode-card" data-mode-card="team">
              <div class="mode-burst"></div>
              <h3>Командный</h3>
              <p>Создай комнату или войди по коду. Поддерживается от 2 до 4 игроков.</p>
              <button id="show-team-btn">Открыть комнату</button>
            </div>
            <div class="mode-card" data-mode-card="casual">
              <div class="mode-burst"></div>
              <h3>Обычный</h3>
              <p>Автопоиск соперника среди активных игроков без изменения рейтинга.</p>
              <button id="play-casual-btn" disabled>Найти обычный матч</button>
            </div>
            <div class="mode-card" data-mode-card="duel">
              <div class="mode-burst"></div>
              <h3>Дуэль</h3>
              <p>Отправь персональное приглашение выбранному игроку на бой через сайт или Telegram.</p>
              <button id="play-duel-mode-btn" disabled>Перейти к дуэли</button>
            </div>
            <div class="mode-card" data-mode-card="bot">
              <div class="mode-burst"></div>
              <h3>С ботом</h3>
              <p>Тестовый 5-раундовый бой против бота с рандомной колодой.</p>
              <button id="play-bot-btn" disabled>Играть с ботом</button>
            </div>
            <div class="mode-card" data-mode-card="onecard">
              <div class="mode-burst"></div>
              <h3>Одна карта</h3>
              <p>Выбери одну карту из своей колоды и сыграй дуэль 1x1 против случайной карты соперника.</p>
              <button id="play-onecard-btn" disabled>Играть 1 картой</button>
            </div>
          </div>

          <div class="result-box" id="battle-result" style="display:none;"></div>
          <div class="result-box" id="invite-result" style="display:none;"></div>

          <div class="panel team-card" id="team-panel" style="margin-top:18px; display:none;">
            <h3>Командная комната</h3>
            <div class="team-grid">
              <div class="row">
                <input id="team-username" placeholder="Имя игрока">
                <select id="team-room-size">
                  <option value="2">2 игрока</option>
                  <option value="3">3 игрока</option>
                  <option value="4">4 игрока</option>
                </select>
              </div>
              <div class="actions">
                <button id="create-room-btn" disabled>Создать комнату</button>
                <input id="room-code-input" placeholder="Код комнаты">
                <button class="secondary" id="join-room-btn" disabled>Войти</button>
              </div>
              <div class="actions">
                <button class="secondary" id="refresh-room-btn" disabled>Обновить комнату</button>
                <button id="start-room-btn" disabled>Старт командного матча</button>
              </div>
            </div>
            <div class="status" id="team-status"></div>
            <div class="team-grid" id="team-room-view"></div>
          </div>
        </section>

        <section class="panel view" id="view-profile">
          <h2>Профиль</h2>
          <div id="mobile-profile-summary" class="deck-list"></div>
          <div class="actions" style="margin-top:14px;">
            <button class="secondary" id="mobile-show-deck-btn">Моя колода</button>
            <button class="secondary" id="mobile-link-tg-btn">Привязать Telegram</button>
          </div>
          <div id="mobile-deck-view" class="deck-list" style="margin-top:14px;"></div>
          <h3 style="margin-top:20px;">Друзья</h3>
          <div id="mobile-friends-list" class="friend-list"></div>
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
          <div class="kv"><span class="muted">Telegram</span><span id="profile-telegram">не привязан</span></div>
        </section>

        <section class="panel">
          <h3>Telegram бот</h3>
          <p class="muted">Бот принимает `/start`, отдельную команду `/link_wallet <wallet>` для привязки Telegram к игре, отправляет реальные приглашения на матч и даёт сопернику ограниченное время на ответ.</p>
          <div class="actions">
            <a class="market-link" id="telegram-open-link" target="_blank" rel="noopener">Открыть бота</a>
            <button id="telegram-link-btn" disabled>Привязать Telegram к кошельку</button>
            <button class="secondary" id="telegram-share-btn" disabled>Отправить результат в Telegram</button>
          </div>
          <div class="status tiny" id="telegram-status"></div>
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
          <h3>Друзья</h3>
          <div class="row">
            <input id="friend-reference" placeholder="Кошелёк или домен">
            <button id="add-friend-btn" disabled>Добавить</button>
          </div>
          <div class="friend-list" id="friends-list"></div>
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
      matchmakingMode: null,
      matchmakingPolling: false,
      disciplineBuild: null
    };

    const telegramBotUsername = {{ telegram_bot_username|tojson }};
    const telegramWebappUrl = {{ telegram_webapp_url|tojson }};
    const marketplaceLinks = {{ marketplace_links|tojson }};

    const walletBadge = document.getElementById('wallet-badge');
    const telegramBadge = document.getElementById('telegram-badge');
    const walletStatus = document.getElementById('wallet-status');
    const walletQuickWallet = document.getElementById('wallet-quick-wallet');
    const walletQuickDomain = document.getElementById('wallet-quick-domain');
    const walletOpenPackBtn = document.getElementById('wallet-open-pack-btn');
    const profileWallet = document.getElementById('profile-wallet');
    const profileDomain = document.getElementById('profile-domain');
    const profileRating = document.getElementById('profile-rating');
    const profileGames = document.getElementById('profile-games');
    const profileTelegram = document.getElementById('profile-telegram');
    const selectedDomainLabel = document.getElementById('selected-domain-label');
    const packScoreLabel = document.getElementById('pack-score-label');
    const packCards = document.getElementById('pack-cards');
    const battleResult = document.getElementById('battle-result');
    const inviteResult = document.getElementById('invite-result');
    const leaderboard = document.getElementById('leaderboard');
    const marketplacesBox = document.getElementById('marketplaces-box');
    const marketplacesLinks = document.getElementById('marketplaces-links');
    const telegramOpenLink = document.getElementById('telegram-open-link');
    const telegramStatus = document.getElementById('telegram-status');
    const telegramShareBtn = document.getElementById('telegram-share-btn');
    const telegramLinkBtn = document.getElementById('telegram-link-btn');
    const activeUsersList = document.getElementById('active-users-list');
    const friendsList = document.getElementById('friends-list');
    const deckView = document.getElementById('deck-view');
    const addFriendBtn = document.getElementById('add-friend-btn');
    const showDeckBtn = document.getElementById('show-deck-btn');
    const toggleDeckBtn = document.getElementById('toggle-deck-btn');
    const mobileProfileSummary = document.getElementById('mobile-profile-summary');
    const mobileFriendsList = document.getElementById('mobile-friends-list');
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
    const cardCatalogList = document.getElementById('card-catalog-list');
    const oneCardSlot = document.getElementById('one-card-slot');
    const battleCardSlot = document.getElementById('battle-card-slot');
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
    const duelInvitePanel = document.getElementById('duel-invite-panel');

    telegramOpenLink.href = telegramBotUsername
      ? `https://t.me/${telegramBotUsername}?startapp=tondomaingame`
      : telegramWebappUrl || window.location.href;
    telegramOpenLink.textContent = telegramBotUsername ? `@${telegramBotUsername}` : 'Открыть мини-апп';

    let tonConnectUI = null;
    let matchmakingPollTimer = null;
    let modeFocusTimer = null;

    function shortAddress(value) {
      if (!value) return '-';
      return `${value.slice(0, 6)}...${value.slice(-6)}`;
    }

    function setStatus(element, text, kind = '') {
      element.className = `status ${kind}`.trim();
      element.textContent = text;
    }

    function actionRuleMeta(actionKey) {
      return {
        burst: {ruLabel: 'Натиск', beats: 'Фокус', losesTo: 'Блок'},
        guard: {ruLabel: 'Блок', beats: 'Натиск', losesTo: 'Фокус'},
        channel: {ruLabel: 'Фокус', beats: 'Блок', losesTo: 'Натиск'},
      }[actionKey] || {ruLabel: actionKey || '-', cost: 0, beats: '-', losesTo: '-'};
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
      };
      return mapping[key] || 'Скилл дает ситуативный бонус в зависимости от темпа и контр-хода.';
    }

    function strategyMeta(strategyKey) {
      return {
        aggressive: {label: 'Агрессия', description: 'Больше натиска и давления по раундам.'},
        balanced: {label: 'Баланс', description: 'Ровная стратегия без явных дыр.'},
        tricky: {label: 'Хитрость', description: 'Больше контров и неожиданных разменов.'},
      }[strategyKey] || {label: 'Баланс', description: 'Ровная стратегия без явных дыр.'};
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

    function switchView(name) {
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
    }

    function animateModeChoice(modeName) {
      const modeGrid = document.querySelector('.mode-grid');
      if (modeGrid) {
        modeGrid.classList.add('mode-focus');
      }
      if (duelInvitePanel) {
        duelInvitePanel.style.display = modeName === 'duel' ? 'block' : 'none';
      }
      document.querySelectorAll('[data-mode-card]').forEach((card) => {
        card.classList.toggle('active-mode', card.dataset.modeCard === modeName);
      });
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
      if (duelInvitePanel) {
        duelInvitePanel.style.display = 'none';
      }
      document.getElementById('team-panel').style.display = 'none';
      window.clearTimeout(modeFocusTimer);
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

    function fillOpponent(reference) {
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

    function renderFriends(items) {
      state.friends = items;
      const emptyMarkup = '<div class="user-item muted">Добавь игроков в друзья, чтобы быстро вызывать их на матч.</div>';
      if (!items.length) {
        friendsList.innerHTML = emptyMarkup;
        mobileFriendsList.innerHTML = emptyMarkup;
        return;
      }
      const markup = items.map((item) => `
        <div class="user-item">
          <strong>${item.display_name}</strong>
          <div class="tiny">${item.domain ? `${item.domain}.ton` : 'домен не выбран'} • рейтинг ${item.rating || '-'}</div>
          <div class="tiny">${item.average_attack ? `Прокачка (сред.): атака ${item.average_attack} • защита ${item.average_defense}` : 'Колода ещё не сохранена'}</div>
          <div class="actions" style="margin-top:10px;">
            <button class="secondary" onclick="fillOpponent('${item.domain || item.wallet}')">Выбрать</button>
          </div>
        </div>
      `).join('');
      friendsList.innerHTML = markup;
      mobileFriendsList.innerHTML = markup;
    }

    function renderDeck(data) {
      const emptyMarkup = '<div class="user-item muted">Сначала выбери домен и открой колоду.</div>';
      if (!data) {
        deckView.innerHTML = emptyMarkup;
        mobileDeckView.innerHTML = emptyMarkup;
        return;
      }
      const markup = `
        <div class="user-item">
          <strong>${data.domain}.ton</strong>
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
        profileTelegram.textContent = state.playerProfile.telegram_linked ? 'привязан' : 'не привязан';
        showDeckBtn.disabled = !(state.playerProfile.current_domain || state.playerProfile.best_domain);
      } else {
        profileRating.textContent = '1000';
        profileGames.textContent = '0';
        profileTelegram.textContent = 'не привязан';
        showDeckBtn.disabled = true;
      }

      mobileProfileSummary.innerHTML = `
        <div class="user-item">
          <strong>${state.selectedDomain ? `${state.selectedDomain}.ton` : 'Профиль игрока'}</strong>
          <div class="tiny">Кошелёк: ${state.wallet ? shortAddress(state.wallet) : '-'}</div>
          <div class="tiny">Активный домен: ${state.selectedDomain ? `${state.selectedDomain}.ton` : '-'}</div>
          <div class="tiny">Рейтинг: ${profileRating.textContent} • Матчей: ${profileGames.textContent}</div>
          <div class="tiny">Telegram: ${profileTelegram.textContent}</div>
        </div>
      `;
      document.getElementById('mobile-show-deck-btn').disabled = showDeckBtn.disabled;
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
            <span class="wallet-domain-chip">Тир: ${item.tier || '-'}</span>
            <span class="wallet-domain-chip">Удача: ${item.luck || 0}</span>
            <span class="wallet-domain-chip">Пул: ${item.deck.discipline_pool || 0}</span>
          </div>
          <div class="wallet-domain-mainline">Вклад карт: ${item.deck.total_score} • ${item.deck.cards && item.deck.cards.length ? `карт: ${item.deck.cards.length}` : 'колода еще не открыта'}</div>
          <div class="actions" style="margin-top:10px;">
            <button class="secondary wallet-domain-action" onclick="selectDeckDomain('${item.domain}')">Играть этим доменом</button>
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

    function renderCardCatalog(cards) {
      state.cardCatalog = cards || [];
      if (!state.cardCatalog.length) {
        cardCatalogList.innerHTML = '<div class="user-item muted">Каталог карт загружается...</div>';
        return;
      }
      cardCatalogList.innerHTML = `
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
      oneCardSlot.innerHTML = '<option value="">Выбери карту для режима одной карты</option>';
      if (!state.cards.length) {
        battleCardSlot.innerHTML = '<option value="">Выбери тактическую карту на матч</option>';
        state.selectedBattleSlot = null;
        return;
      }
      oneCardSlot.innerHTML += state.cards.map((card) => `
        <option value="${card.slot}">Слот ${card.slot}: ${card.title} (${card.pool_value || card.score || 0})</option>
      `).join('');
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
      document.getElementById('play-duel-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('play-duel-mode-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('play-bot-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('play-onecard-btn').disabled = !(connected && hasCards && oneCardSlot.value) || searching;
      document.getElementById('create-room-btn').disabled = !(connected && hasCards) || searching;
      document.getElementById('join-room-btn').disabled = !(connected && hasCards) || searching;
      telegramLinkBtn.disabled = !connected;
      addFriendBtn.disabled = !connected;
      refreshAchievementsBtn.disabled = !connected;
      cancelMatchmakingBtn.disabled = !searching;
      saveBuildBtn.disabled = !(connected && hasDomain);
      walletOpenPackBtn.disabled = !(connected && hasDomain);
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
            <span class="wallet-domain-chip">Тир: ${domain.tier || '-'}</span>
            <span class="wallet-domain-chip">Удача: ${domain.luck || 0}</span>
          </div>
          <div class="wallet-domain-mainline">Счёт домена: ${domain.score} • DNS: ${domain.is_guest ? 'гостевой режим' : (domain.domain_exists ? 'активен' : 'не подтверждён')}</div>
          <details class="wallet-domain-more">
            <summary>Подробнее</summary>
            <div class="tiny">Паттерны: ${domain.patterns.length ? domain.patterns.join(', ') : 'базовый 10K домен'}</div>
            <div class="tiny">Спецколлекции: ${domain.special_collections && domain.special_collections.length ? domain.special_collections.join(', ') : 'нет'}</div>
          </details>
          <button class="wallet-domain-action" onclick="selectDomain('${domain.domain}')">${state.selectedDomain === domain.domain ? 'Открыть колоду' : 'Выбрать домен'}</button>
        </div>
      `).join('');
    }

    window.selectDomain = function selectDomain(domain) {
      selectDeckDomain(domain);
    };

    function sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
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
      const startY = packRect.top + 26;

      for (const target of targets) {
        const preview = document.createElement('article');
        preview.className = 'pack-preview-card';
        preview.innerHTML = target.innerHTML;
        preview.style.left = `${startX}px`;
        preview.style.top = `${startY}px`;
        layer.appendChild(preview);

        await sleep(40);
        preview.style.left = `${window.innerWidth * 0.5}px`;
        preview.style.top = `${window.innerHeight * 0.5}px`;
        preview.classList.add('focused');
        layer.classList.add('dimmed');

        await sleep(1500);

        const rect = target.getBoundingClientRect();
        const targetX = rect.left + rect.width / 2;
        const targetY = rect.top + rect.height / 2;
        layer.classList.remove('dimmed');
        preview.style.left = `${targetX}px`;
        preview.style.top = `${targetY}px`;
        preview.style.transform = 'translate(-50%, -50%) scale(0.44)';
        preview.style.opacity = '0.94';

        await sleep(780);
        target.classList.add('sequence-visible');
        preview.remove();
      }

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

    function revealDisciplineRows(startDelay = 0, stepMs = 1000) {
      const rows = battleResult.querySelectorAll('.discipline-row');
      if (!rows.length) {
        return 0;
      }
      const mainPanel = battleResult.querySelector('.showdown-main');
      const toResultKey = (row) => (
        row.classList.contains('win') ? 'win' : (row.classList.contains('lose') ? 'lose' : 'draw')
      );
      rows.forEach((row, index) => {
        const delay = startDelay + index * stepMs;
        setTimeout(() => {
          row.classList.add('visible');
          if (mainPanel) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
          }
          playBattleFx(toResultKey(row), 'round', row);
        }, delay);
      });
      return startDelay + (rows.length - 1) * stepMs;
    }

    function playFinalClimax(resultKey, resultLabel) {
      const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const rows = Array.from(battleResult.querySelectorAll('.discipline-row'));
      if (prefersReduced || !rows.length) {
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
          chips.forEach((chip, index) => {
            setTimeout(() => {
              chip.classList.add('fly');
              playBattleFx(resultKey, 'round');
            }, index * 80);
          });
        });
        setTimeout(() => {
          core.classList.add('visible');
          playBattleFx(resultKey, 'finish');
        }, 860);
        setTimeout(() => {
          resolve();
        }, 2140);
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

    function renderBattleResult(result) {
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
        const resultClass = resultKey === 'win' ? 'to-win' : (resultKey === 'lose' ? 'to-lose' : 'to-draw');
        const frontLabel = resultKey === 'draw' ? 'DRAW' : 'WIN';
        const frontClass = resultKey === 'draw' ? 'draw' : 'front';
        const cardLine = result.player_card
          ? `<div class="tiny">Твоя карта: слот ${result.player_card.slot} • ${result.player_card.title} • сила ${result.player_card.score}</div>`
          : '';
        const oppCardLine = result.opponent_card
          ? `<div class="tiny">Карта соперника: ${result.opponent_card.title} • сила ${result.opponent_card.score}</div>`
          : '';
        const featuredCardLine = result.player_featured_card
          ? `<div class="tiny">Тактическая карта: слот ${result.player_featured_card.slot} • ${result.player_featured_card.title} • ${result.player_featured_card.skill_name || 'скилл'}</div>`
          : '';
        const oppFeaturedCardLine = result.opponent_featured_card
          ? `<div class="tiny">Тактическая карта соперника: слот ${result.opponent_featured_card.slot} • ${result.opponent_featured_card.title} • ${result.opponent_featured_card.skill_name || 'скилл'}</div>`
          : '';
        const roundsLine = Array.isArray(result.rounds) && result.rounds.length
          ? `<div class="discipline-list">
              ${result.rounds.map((round) => {
                const roundClass = round.winner === 'player' ? 'win' : (round.winner === 'opponent' ? 'lose' : 'draw');
                const marker = round.winner === 'player' ? 'WIN' : (round.winner === 'opponent' ? 'LOSE' : 'DRAW');
                const playerCardTitle = round.player_card?.title || 'Твоя карта';
                const opponentCardTitle = round.opponent_card?.title || 'Карта соперника';
                const playerSlot = round.player_card?.slot || '-';
                const opponentSlot = round.opponent_card?.slot || '-';
                const playerStrategy = strategyMeta(round.player_strategy_key || 'balanced');
                const opponentStrategy = strategyMeta(round.opponent_strategy_key || 'balanced');
                const playerCardPower = Number(round.player_value || 0) + Number(round.player_boost || 0) + Number(round.player_skill_bonus || 0);
                const opponentCardPower = Number(round.opponent_value || 0) + Number(round.opponent_boost || 0) + Number(round.opponent_skill_bonus || 0);
                return `
                  <div class="discipline-row ${roundClass}">
                    <span>${round.label}: слот ${playerSlot} (${playerCardTitle}) vs слот ${opponentSlot} (${opponentCardTitle})</span>
                    <span>${round.player_total} : ${round.opponent_total} • ${marker}</span>
                    <span class="tiny">Стратегия: ${playerStrategy.label} / ${opponentStrategy.label} • бонус: +${round.player_strategy_bonus || 0} / +${round.opponent_strategy_bonus || 0}</span>
                    <span class="tiny">Тактическая карта: +${round.player_featured_bonus || 0} / +${round.opponent_featured_bonus || 0}</span>
                    <span class="tiny">Сила карт: +${playerCardPower} / +${opponentCardPower}</span>
                  </div>
                `;
              }).join('')}
            </div>`
          : '';
        const buildLine = result.player_build
          ? `<div class="tiny">Твоя прокачка: ATK ${result.player_build.attack || 0} • DEF ${result.player_build.defense || 0} • LUCK ${result.player_build.luck || 0} • SPD ${result.player_build.speed || 0} • MAG ${result.player_build.magic || 0}</div>`
          : '';
        const deckPowerLine = result.player_deck_power !== undefined && result.opponent_deck_power !== undefined
          ? `<div class="tiny">Сила колод (тай-брейк): ${result.player_deck_power} vs ${result.opponent_deck_power}${result.tie_breaker ? ' • использован тай-брейк' : ''}</div>`
          : '';
        const selectedStrategy = strategyMeta(result.strategy_key || 'balanced');
        const interactivePanel = result.interactive_session_id
          ? `
              <div class="interactive-battle-panel ${result.interactive_live ? 'floating' : 'delayed-outcome'}" id="interactive-battle-panel">
                <div class="interactive-battle-title">
                  ${result.interactive_live
                    ? `Раунд ${Math.min((result.interactive_round_index || 0) + 1, result.interactive_total_rounds || 5)} из ${result.interactive_total_rounds || 5}`
                    : 'Бой завершён'}
                </div>
                <div class="tiny" id="interactive-battle-status" style="text-align:center;">
                  ${result.interactive_live ? (result.interactive_hint || 'Выбери действие и повлияй на исход боя.') : 'Все ходы сыграны. Смотрим развязку матча.'}
                </div>
                ${result.interactive_live ? `
                  <div class="interactive-battle-actions">
                    ${['burst', 'guard', 'channel'].map((key) => {
                      const meta = actionRuleMeta(key);
                      return `<button class="interactive-action-btn ${key}" data-action-key="${key}">${meta.ruLabel}</button>`;
                    }).join('')}
                  </div>
                ` : ''}
              </div>
            `
          : '';
        state.lastReplayMode = result.mode || (result.mode_title === 'Матч с ботом' ? 'bot' : (result.mode_title === 'Рейтинговый матч' ? 'ranked' : 'casual'));
        battleResult.classList.add('showdown-fullscreen');
        battleResult.classList.remove('result-win', 'result-lose', 'result-draw', 'battle-live');
        battleResult.classList.add(resultKey === 'win' ? 'result-win' : (resultKey === 'lose' ? 'result-lose' : 'result-draw'));
        document.body.classList.add('showdown-open');
        battleResult.scrollTop = 0;
        const victoryLine = resultKey === 'win'
          ? `<div class="victory-banner delayed-outcome">Поздравляем! Это победный матч!</div>`
          : '';
        battleResult.innerHTML = `
          <section class="showdown-header">
            <div class="tiny"><strong>Колода пользователя</strong> • ${result.player_domain}.ton</div>
            <div class="showdown-deck">
              ${showdownDeckMarkup(result.player_cards, result.player_card)}
            </div>
          </section>
          <section class="showdown-main">
            <div class="showdown-center showdown-middle">
              <div class="prebattle-stage" id="prebattle-stage">
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
                    ${['aggressive', 'balanced', 'tricky'].map((key) => {
                      const meta = strategyMeta(key);
                      return `<option value="${key}" ${String(result.strategy_key || 'balanced') === key ? 'selected' : ''}>${meta.label}</option>`;
                    }).join('')}
                  </select>
                </div>
                <div class="tiny" style="text-align:center;">Стратегия влияет напрямую на исход матча.</div>
                <div class="tiny" id="prebattle-strategy-help" style="text-align:center;"><strong>${selectedStrategy.label}:</strong> ${selectedStrategy.description}</div>
                <div class="tiny" id="prebattle-action-help">${result.player_featured_card ? skillCounterText(result.player_featured_card) : 'Тактическая карта сильнее всего влияет на раунд.'}</div>
                <div class="showdown-entry-actions">
                  <button id="start-battle-btn">Готов</button>
                  <button class="secondary" onclick="openModes()">К режимам</button>
                </div>
              </div>
              <div class="battle-stage" id="battle-stage">
                <div class="match-outcome delayed-outcome">
                  <div class="result-flip">
                    <div class="result-flip-card ${resultClass}">
                      <div class="result-flip-face ${frontClass}">${frontLabel}</div>
                      <div class="result-flip-face back">LOSE</div>
                    </div>
                  </div>
                  <h3>${result.mode_title}</h3>
                  <div class="battle-cinematic">
                    <div class="battle-fighter player">
                      <div class="tiny">Твоя карта</div>
                      <strong>${result.player_featured_card ? result.player_featured_card.title : (result.player_card ? result.player_card.title : `${result.player_domain}.ton`)}</strong>
                      <div class="tiny">Скилл: ${result.player_featured_card ? result.player_featured_card.skill_name : 'без тактики'}</div>
                    </div>
                    <div class="battle-vs-orb">VS</div>
                    <div class="battle-fighter enemy">
                      <div class="tiny">Карта соперника</div>
                      <strong>${result.opponent_featured_card ? result.opponent_featured_card.title : (result.opponent_card ? result.opponent_card.title : opponentLabel)}</strong>
                      <div class="tiny">Скилл: ${result.opponent_featured_card ? result.opponent_featured_card.skill_name : 'без тактики'}</div>
                    </div>
                  </div>
                  <div class="showdown-score">
                    <span class="count-up" data-count-to="${result.player_score}">0</span>
                    <span>:</span>
                    <span class="count-up" data-count-to="${result.opponent_score}">0</span>
                  </div>
                  <div class="tiny">Твой домен: ${result.player_domain}.ton • Соперник: ${opponentLabel}</div>
                </div>
                ${cardLine}
                ${oppCardLine}
                ${featuredCardLine}
                ${oppFeaturedCardLine}
                ${buildLine}
                ${interactivePanel}
                ${roundsLine}
                ${deckPowerLine}
                ${ratingLine}
                <p class="muted delayed-outcome">Итог: ${result.result_label}</p>
                ${victoryLine}
              </div>
            </div>
          </section>
          <section class="showdown-header">
            <div class="tiny"><strong>Колода противника</strong> • ${opponentLabel}</div>
            <div class="showdown-deck">
              ${showdownDeckMarkup(result.opponent_cards, result.opponent_card)}
            </div>
          </section>
          <div class="result-actions delayed-outcome post-actions">
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
        const interactiveActionButtons = Array.from(battleResult.querySelectorAll('.interactive-action-btn'));
        const wireInteractiveBattle = () => {
          battleResult.querySelectorAll('.discipline-row').forEach((row) => row.classList.add('visible'));
          animateScoreCounters(battleResult);
          if (!liveResult.interactive_live || !interactiveBattlePanel || !interactiveActionButtons.length) {
            return;
          }
          interactiveActionButtons.forEach((button) => {
            button.addEventListener('click', async () => {
              const actionKey = button.dataset.actionKey;
              interactiveActionButtons.forEach((node) => { node.disabled = true; });
              if (interactiveBattleStatus) {
                const meta = actionRuleMeta(actionKey);
                interactiveBattleStatus.textContent = `Ты выбираешь: ${meta.ruLabel}. Считаем размен...`;
              }
              playBattleFx(resultKey, 'start', interactiveBattlePanel);
              try {
                const data = await api('/api/solo-battle/action', {
                  method: 'POST',
                  body: {
                    wallet: state.wallet,
                    session_id: liveResult.interactive_session_id,
                    action: actionKey
                  }
                });
                const nextResult = data.result || {};
                nextResult.autostart_battle = true;
                state.lastResult = nextResult;
                renderBattleResult(nextResult);
              } catch (error) {
                interactiveActionButtons.forEach((node) => { node.disabled = false; });
                if (interactiveBattleStatus) {
                  interactiveBattleStatus.textContent = error.message;
                }
              }
            });
          });
        };
        if (result.battle_session_id && prebattleStage) {
          prebattleStage.classList.add('accept-pop');
          setTimeout(() => prebattleStage.classList.remove('accept-pop'), 760);
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
          startBtn.addEventListener('click', () => {
            const launchBattle = () => {
              startBtn.disabled = true;
              startBtn.textContent = 'Бой идёт...';
              battleResult.classList.add('battle-live');
              setTimeout(() => battleResult.classList.remove('battle-live'), 620);
              playBattleFx(resultKey, 'start');
              const prebattle = battleResult.querySelector('#prebattle-stage');
              const battleStage = battleResult.querySelector('#battle-stage');
              if (prebattle) {
                prebattle.classList.add('hidden');
              }
              if (battleStage) {
                battleStage.classList.add('visible');
              }
              if (liveResult.interactive_session_id) {
                wireInteractiveBattle();
                if (!liveResult.interactive_live) {
                  const finalDelay = revealDisciplineRows(0, 1000);
                  const showOutcome = async () => {
                    await playFinalClimax(resultKey, result.result_label);
                    battleResult.querySelectorAll('.delayed-outcome').forEach((node) => node.classList.add('visible'));
                    animateScoreCounters(battleResult);
                    const mainPanel = battleResult.querySelector('.showdown-main');
                    if (mainPanel) {
                      mainPanel.scrollTo({ top: mainPanel.scrollHeight, behavior: 'smooth' });
                    }
                  };
                  if (finalDelay > 0) {
                    setTimeout(() => { showOutcome(); }, finalDelay);
                  } else {
                    showOutcome();
                  }
                }
                return;
              }
              const finalDelay = revealDisciplineRows(0, 1000);
              const showOutcome = async () => {
                await playFinalClimax(resultKey, result.result_label);
                battleResult.querySelectorAll('.delayed-outcome').forEach((node) => node.classList.add('visible'));
                animateScoreCounters(battleResult);
                const mainPanel = battleResult.querySelector('.showdown-main');
                if (mainPanel) {
                  mainPanel.scrollTo({ top: mainPanel.scrollHeight, behavior: 'smooth' });
                }
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
          setTimeout(() => startBtn.click(), 120);
        }
      }
      telegramShareBtn.disabled = false;
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

    function openModes() {
      clearFinalClimax();
      document.body.classList.remove('showdown-open');
      battleResult.className = 'result-box';
      battleResult.style.display = 'none';
      inviteResult.style.display = 'none';
      switchView('modes');
      resetModeChoice('');
    }

    function openDuelMode() {
      animateModeChoice('duel');
      const input = document.getElementById('opponent-wallet');
      if (input) {
        input.focus();
      }
      matchmakingStatus.textContent = 'Дуэль: укажи домен соперника и отправь приглашение.';
    }

    function repeatLastMode() {
      clearFinalClimax();
      if (state.lastReplayMode === 'bot') {
        playBotMatch();
        return;
      }
      if (state.lastReplayMode === 'onecard') {
        playOneCardMatch();
        return;
      }
      if (state.lastReplayMode === 'ranked' || state.lastReplayMode === 'casual') {
        startMatchmaking(state.lastReplayMode);
        return;
      }
      if (state.lastReplayMode === 'duel') {
        playMatch('duel');
        return;
      }
      switchView('modes');
    }

    function rebindDomain() {
      state.selectedDomain = null;
      state.cards = [];
      state.selectedBattleSlot = null;
      state.lastResult = null;
      packCards.innerHTML = '';
      packScoreLabel.textContent = 'Вклад карт: -';
      packShowcase.classList.remove('opened');
      foilPack.classList.remove('opening');
      packNote.textContent = 'TAP TO OPEN';
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
      const view = document.getElementById('team-room-view');
      state.room = room;
      state.roomId = room.id;
      document.getElementById('room-code-input').value = room.id;
      document.getElementById('refresh-room-btn').disabled = false;
      document.getElementById('start-room-btn').disabled = !(room.is_owner && room.players.length >= 2 && room.status === 'waiting');
      view.innerHTML = `
        <div class="team-card">
          <div class="team-line"><strong>Комната ${room.id}</strong><span>${room.players.length}/${room.max_players}</span></div>
          <div class="tiny">Статус: ${room.status === 'waiting' ? 'ожидание игроков' : 'завершена'}</div>
          ${room.players.map((player) => `
            <div class="team-line">
              <span>${player.username} • ${player.domain}.ton ${player.wallet === room.owner_wallet ? '(owner)' : ''}</span>
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
        renderFriends([]);
        renderOwnedDecks([], null);
        return;
      }
      const profile = await api(`/api/player/${encodeURIComponent(state.wallet)}`);
      state.playerProfile = profile.player;
      if (!state.selectedDomain && state.playerProfile && state.playerProfile.current_domain) {
        state.selectedDomain = state.playerProfile.current_domain;
      }
      renderProfile();
      const friends = await api(`/api/friends/${encodeURIComponent(state.wallet)}`);
      renderFriends(friends.friends);
    }

    async function checkDomains() {
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
          await selectDeckDomain(preferredDomain, {silent: true, switchToPack: false});
          setStatus(walletStatus, `Найдена готовая колода ${preferredDomain}.ton. Она выбрана автоматически.`, 'success');
        } else {
          loadDisciplineBuild();
        }
      } catch (error) {
        setStatus(walletStatus, error.message, 'error');
      }
    }

    async function openPack(source = 'daily', paymentId = null) {
      setStatus(document.getElementById('pack-status'), 'Распаковываем 5 карточек из домена...', 'warning');
      foilPack.classList.remove('opening');
      foilPack.classList.remove('vanishing');
      packShowcase.classList.remove('opened');
      packShowcase.classList.add('cinematic');
      requestAnimationFrame(() => foilPack.classList.add('opening'));
      packNote.textContent = 'Opening...';
      try {
        const data = await api('/api/pack', {
          method: 'POST',
          body: {wallet: state.wallet, domain: state.selectedDomain, source, payment_id: paymentId}
        });
        state.cards = data.cards;
        packShowcase.classList.add('opened');
        packNote.textContent = 'Pack opened';
        await new Promise((resolve) => setTimeout(resolve, 460));
        await renderPack(data.cards, data.total_score);
        foilPack.classList.add('vanishing');
        await sleep(1150);
        packShowcase.classList.remove('cinematic');
        setStatus(document.getElementById('pack-status'), `Колода готова. Вклад карт: ${data.total_score}. Свободный пул пересчитан от домена.`, 'success');
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
        packNote.textContent = 'TAP TO OPEN';
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function buyPackWithTon() {
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
        setStatus(document.getElementById('pack-status'), 'Платёж подтверждён. Открываем платный пак...', 'success');
        await openPack('paid', intent.payment_id);
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function loadCardCatalog() {
      try {
        const data = await api('/api/cards/catalog');
        renderCardCatalog(data.cards || []);
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

    async function startMatchmaking(mode) {
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
        matchmakingStatus.textContent = data.cooldown_seconds
          ? `Повтор с тем же соперником через ${data.cooldown_seconds} сек. Идёт поиск...`
          : 'Идёт поиск соперника...';
        matchmakingPollTimer = window.setTimeout(() => pollMatchmaking(mode), 2200);
      } catch (error) {
        stopMatchmakingUI(error.message);
      }
    }

    async function cancelMatchmaking() {
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

    async function playBotMatch() {
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
        battleResult.className = 'result-box duel-anim';
        battleResult.style.display = 'block';
        document.body.classList.remove('showdown-open');
        battleResult.innerHTML = `<strong class="error">${error.message}</strong>`;
      }
    }

    async function createRoom() {
      const username = document.getElementById('team-username').value.trim() || shortAddress(state.wallet);
      try {
        const data = await api('/api/team-room/create', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            username,
            max_players: Number(document.getElementById('team-room-size').value)
          }
        });
        setStatus(document.getElementById('team-status'), `Комната ${data.room.id} создана. Приглашай игроков по коду.`, 'success');
        renderRoom(data.room);
      } catch (error) {
        setStatus(document.getElementById('team-status'), error.message, 'error');
      }
    }

    async function joinRoom() {
      const username = document.getElementById('team-username').value.trim() || shortAddress(state.wallet);
      const roomId = document.getElementById('room-code-input').value.trim().toUpperCase();
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
        setStatus(document.getElementById('team-status'), `Ты вошёл в комнату ${roomId}.`, 'success');
        renderRoom(data.room);
      } catch (error) {
        setStatus(document.getElementById('team-status'), error.message, 'error');
      }
    }

    async function refreshRoom() {
      if (!state.roomId) return;
      try {
        const data = await api(`/api/team-room/${state.roomId}?wallet=${encodeURIComponent(state.wallet)}`);
        renderRoom(data.room);
      } catch (error) {
        setStatus(document.getElementById('team-status'), error.message, 'error');
      }
    }

    async function startRoom() {
      if (!state.roomId) return;
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
        setStatus(document.getElementById('team-status'), 'Командный матч завершён.', 'success');
      } catch (error) {
        setStatus(document.getElementById('team-status'), error.message, 'error');
      }
    }

    function initTelegram() {
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      if (!tg) {
        telegramBadge.textContent = telegramBotUsername ? 'Telegram: бот готов' : 'Telegram: нужен бот';
        telegramStatus.textContent = telegramBotUsername
          ? 'Можно открыть мини-апп через ссылку на бота.'
          : 'Укажи TG_BOT_USERNAME и TG_BOT_TOKEN, чтобы включить Telegram-режим.';
        return;
      }

      tg.ready();
      tg.expand();
      telegramBadge.textContent = 'Telegram: mini app активен';
      telegramStatus.textContent = 'Приложение открыто внутри Telegram. Можно привязать кошелёк и получать PvP-приглашения от бота.';
    }

    async function linkTelegramWallet() {
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      if (!state.wallet) {
        telegramStatus.textContent = 'Сначала подключи кошелёк.';
        return;
      }
      if (!tg || !tg.initData) {
        if (telegramBotUsername) {
          const payload = encodeURIComponent(`link_${state.wallet}`);
          window.open(`https://t.me/${telegramBotUsername}?start=${payload}`, '_blank');
          telegramStatus.textContent = 'Открыл бота. Нажми Start в Telegram для автоматической привязки кошелька.';
        } else {
          telegramStatus.textContent = 'Привязка доступна в Telegram mini app. Укажи TG_BOT_USERNAME.';
        }
        return;
      }
      try {
        const data = await api('/api/telegram/link', {
          method: 'POST',
          body: {
            wallet: state.wallet,
            init_data: tg.initData
          }
        });
        state.playerProfile = data.player;
        renderProfile();
        telegramStatus.textContent = 'Telegram успешно привязан к кошельку. Теперь тебе могут приходить PvP-приглашения.';
        loadActiveUsers();
      } catch (error) {
        telegramStatus.textContent = error.message;
      }
    }

    async function showDeck() {
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
      const {silent = false, switchToPack = true} = options;
      if (!state.wallet) return;
      try {
        const data = await api('/api/deck/select', {
          method: 'POST',
          body: { wallet: state.wallet, domain }
        });
        state.selectedDomain = data.domain;
        state.playerProfile = data.player;
        state.cards = data.deck.cards || [];
        packShowcase.classList.remove('opened');
        foilPack.classList.remove('opening');
        packNote.textContent = 'TAP TO OPEN';
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
      const slot = Number(oneCardSlot.value || 0);
      if (!slot) {
        setStatus(document.getElementById('pack-status'), 'Для режима одной карты выбери карту из колоды.', 'warning');
        return;
      }
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

    async function addFriend() {
      const reference = document.getElementById('friend-reference').value.trim();
      try {
        const data = await api('/api/friends', {
          method: 'POST',
          body: { wallet: state.wallet, reference }
        });
        renderFriends(data.friends);
        document.getElementById('friend-reference').value = '';
      } catch (error) {
        friendsList.innerHTML = `<div class="user-item error">${error.message}</div>${friendsList.innerHTML}`;
      }
    }

    async function shareTelegram() {
      if (!state.lastResult) return;
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      const payload = {
        type: 'battle_result',
        wallet: state.wallet,
        domain: state.selectedDomain,
        result: state.lastResult
      };

      if (tg && typeof tg.sendData === 'function') {
        tg.sendData(JSON.stringify(payload));
        telegramStatus.textContent = 'Результат отправлен в Telegram через WebApp bridge.';
        return;
      }

      telegramStatus.textContent = telegramBotUsername
        ? `Открой бота @${telegramBotUsername} и запусти мини-апп внутри Telegram, чтобы отправлять результаты автоматически.`
        : 'Для автоматической отправки результата нужен Telegram WebApp.';
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
          state.selectedBattleSlot = null;
          packCards.innerHTML = '';
          packScoreLabel.textContent = 'Вклад карт: -';
          packShowcase.classList.remove('opened');
          foilPack.classList.remove('opening');
          packNote.textContent = 'TAP TO OPEN';
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
          state.selectedBattleSlot = null;
          renderDomains([]);
          renderProfile();
          renderFriends([]);
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

    document.getElementById('check-domains-btn').addEventListener('click', checkDomains);
    walletOpenPackBtn.addEventListener('click', () => switchView('pack'));
    document.getElementById('back-to-wallet-btn').addEventListener('click', () => switchView('wallet'));
    document.getElementById('rebind-domain-btn').addEventListener('click', rebindDomain);
    document.getElementById('shuffle-deck-btn').addEventListener('click', shuffleDeck);
    document.getElementById('open-pack-btn').addEventListener('click', () => openPack('daily'));
    buyPackBtn.addEventListener('click', buyPackWithTon);
    foilPack.addEventListener('click', () => {
      if (!document.getElementById('open-pack-btn').disabled) {
        openPack();
      }
    });
    document.getElementById('continue-to-modes-btn').addEventListener('click', () => switchView('modes'));
    document.getElementById('play-ranked-btn').addEventListener('click', () => startMatchmaking('ranked'));
    document.getElementById('play-casual-btn').addEventListener('click', () => startMatchmaking('casual'));
    document.getElementById('play-duel-btn').addEventListener('click', () => playMatch('duel'));
    document.getElementById('play-duel-mode-btn').addEventListener('click', openDuelMode);
    cancelMatchmakingBtn.addEventListener('click', cancelMatchmaking);
    saveBuildBtn.addEventListener('click', saveDisciplineBuild);
    document.getElementById('play-bot-btn').addEventListener('click', playBotMatch);
    document.getElementById('play-onecard-btn').addEventListener('click', playOneCardMatch);
    oneCardSlot.addEventListener('change', updateButtons);
    battleCardSlot.addEventListener('change', () => {
      state.selectedBattleSlot = Number(battleCardSlot.value || 0) || null;
      updateButtons();
    });
    refreshAchievementsBtn.addEventListener('click', loadAchievements);
    document.getElementById('show-team-btn').addEventListener('click', () => {
      animateModeChoice('team');
      document.getElementById('team-panel').style.display = 'block';
      setStatus(document.getElementById('team-status'), 'Создай командную комнату или войди по коду.', 'warning');
    });
    document.getElementById('create-room-btn').addEventListener('click', createRoom);
    document.getElementById('join-room-btn').addEventListener('click', joinRoom);
    document.getElementById('refresh-room-btn').addEventListener('click', refreshRoom);
    document.getElementById('start-room-btn').addEventListener('click', startRoom);
    telegramLinkBtn.addEventListener('click', linkTelegramWallet);
    telegramShareBtn.addEventListener('click', shareTelegram);
    showDeckBtn.addEventListener('click', showDeck);
    toggleDeckBtn.addEventListener('click', toggleDeck);
    document.getElementById('mobile-show-deck-btn').addEventListener('click', showDeck);
    document.getElementById('mobile-link-tg-btn').addEventListener('click', linkTelegramWallet);
    document.getElementById('nav-wallet').addEventListener('click', () => switchView('wallet'));
    document.getElementById('nav-pack').addEventListener('click', () => switchView('pack'));
    document.getElementById('nav-modes').addEventListener('click', () => switchView('modes'));
    document.getElementById('nav-profile').addEventListener('click', () => switchView('profile'));
    document.getElementById('nav-achievements').addEventListener('click', () => switchView('achievements'));
    addFriendBtn.addEventListener('click', addFriend);
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
    window.selectDeckDomain = selectDeckDomain;

    initTelegram();
    initTonConnect().catch((error) => {
      setStatus(walletStatus, `Ошибка TonConnect: ${error.message}`, 'error');
    });
    loadLeaderboard();
    loadActiveUsers();
    loadGlobalPlayers();
    loadAchievements();
    loadCardCatalog();
    renderProfile();
    renderFriends([]);
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


def guest_domain_payload(wallet):
    domain = guest_domain_for_wallet(wallet)
    base = score_from_domain(domain)
    return {
        'domain': domain,
        'domain_exists': True,
        'source_label': 'Гостевой профиль (игра без домена)',
        'patterns': base['patterns'],
        'tier': base['tier'],
        'special_collections': base.get('special_collections', []),
        'luck': base.get('luck', 0),
        'score': base['score'],
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


def score_from_domain(domain):
    attack = ATTACK_BASE
    defense = DEFENSE_BASE
    luck = 0
    patterns = []
    tier = 'Tier-3'
    special_collections = []
    bonus_score = 0

    try:
        club = classify_domain_with_10k_config(domain)
        patterns = club['patterns']
        tier = club['tier']
        special_collections = club['special_collections']
        bonus_score = int(club.get('bonus_score') or 0)
        luck = len(special_collections)
        attack += bonus_score // 1500
        defense += bonus_score // 1900
    except (requests.RequestException, RuntimeError, ValueError, KeyError):
        patterns = detect_10k_patterns(domain)
        bonus_score = 0

    score = 2500 + bonus_score
    if tier == 'Tier-3':
        for tier_config in TIERS:
            if score >= tier_config['min_score']:
                tier = tier_config['name']
                break

    return {
        'domain': domain,
        'attack': attack,
        'defense': defense,
        'luck': luck,
        'patterns': patterns,
        'tier': tier,
        'special_collections': special_collections,
        'bonus_score': bonus_score,
        'pool_base': 2500,
        'pool_total': 2500 + bonus_score,
        'score': score,
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
]
ACTION_RULES = {
    'burst': {
        'label': 'Burst',
        'ru_label': 'Натиск',
        'beats': 'channel',
        'color': 'rgba(255, 122, 134, 0.9)',
        'description': 'Силен против накопления. Слабее против блока.',
    },
    'guard': {
        'label': 'Guard',
        'ru_label': 'Блок',
        'beats': 'burst',
        'color': 'rgba(83, 246, 184, 0.9)',
        'description': 'Сдерживает натиск. Слабее против подготовки.',
    },
    'channel': {
        'label': 'Channel',
        'ru_label': 'Фокус',
        'beats': 'guard',
        'color': 'rgba(69, 215, 255, 0.9)',
        'description': 'Наказывает блок. Слабее против прямого натиска.',
    },
}
STRATEGY_PRESETS = {
    'aggressive': {
        'label': 'Агрессия',
        'description': 'Сразу давит, лучше на добивании и против пассивной игры.',
        'plan': ['burst', 'burst', 'channel', 'burst', 'guard'],
    },
    'balanced': {
        'label': 'Баланс',
        'description': 'Самая ровная стратегия, меньше провалов по матчапам.',
        'plan': ['burst', 'guard', 'channel', 'guard', 'burst'],
    },
    'tricky': {
        'label': 'Хитрость',
        'description': 'Чаще ловит соперника на контрах и неожиданных сменах темпа.',
        'plan': ['channel', 'guard', 'channel', 'burst', 'channel'],
    },
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
    tier = (base.get('tier') or '').lower()
    if 'tier-0' in tier:
        weights = {'basic': 30, 'rare': 28, 'epic': 21, 'mythic': 13, 'legendary': 8}
    elif 'tier-1' in tier:
        weights = {'basic': 40, 'rare': 29, 'epic': 18, 'mythic': 9, 'legendary': 4}
    elif 'tier-2' in tier:
        weights = {'basic': 52, 'rare': 27, 'epic': 14, 'mythic': 5, 'legendary': 2}

    patterns = set(base.get('patterns') or [])
    weights['rare'] += min(12, len(patterns) * 2)
    weights['epic'] += min(8, len(patterns))
    weights['mythic'] += min(5, len(patterns))
    if patterns.intersection({'mirror', 'all_same', 'first_100', 'zero_frames'}):
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
    normalized = normalize_domain(domain)
    if not normalized:
        return 0
    try:
        club = classify_domain_with_10k_config(normalized)
        return max(0, int(club.get('bonus_score') or 0))
    except (requests.RequestException, RuntimeError, ValueError, KeyError):
        return 0


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


def generate_pack(domain, count=5, seed_value=None):
    base = score_from_domain(domain)
    seed_source = seed_value or f'deck:{domain}'
    rng = random.Random(hashlib.sha256(str(seed_source).encode()).hexdigest())
    weights = rarity_weights_for_domain(base)
    cards = []
    for slot in range(1, count + 1):
        rarity = weighted_choice(weights, rng)
        template = rng.choice(CARD_CATALOG_BY_RARITY[rarity])
        card = materialize_card(template, domain, slot)
        card['patterns'] = base.get('patterns', [])
        cards.append(card)
    return cards


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
    }
    def score(card):
        skill_key = card.get('skill_key')
        return (
            len(preferred.get(skill_key, set()).intersection(focus_rank[:2])),
            int(card.get('pool_value', 0)),
        )
    return max(normalized, key=score).get('slot', 1)


def apply_skill_bonus(skill_key, focus, base_self, base_opp, card_self, card_opp, round_index, previous_outcome):
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
        plan[2] = 'channel'
    if skill_key == 'tempo':
        plan[1] = 'burst'
        plan[3] = 'burst'
    if skill_key == 'mirror':
        plan[0] = 'guard'
        plan[2] = 'channel'
    if skill_key == 'underdog':
        plan[2] = 'burst'
        plan[4] = 'channel'
    return plan


def sanitize_action_plan(plan):
    plan = list(plan or [])
    while len(plan) < len(WIKIGACHI_ROUND_PLAN):
        plan.append(default_action_plan()[len(plan)])
    normalized = []
    for key in plan[:len(WIKIGACHI_ROUND_PLAN)]:
        action_key = str(key or '').strip().lower()
        if action_key not in ACTION_RULES:
            action_key = 'channel'
        normalized.append(action_key)
    return normalized


def action_round_resolution(action_a, action_b):
    meta_a = ACTION_RULES.get(action_a) or ACTION_RULES['channel']
    meta_b = ACTION_RULES.get(action_b) or ACTION_RULES['channel']
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
    if strategy_key == 'aggressive':
        bonus = 34 if action_key == 'burst' else 12
        if phase in {'opening', 'finisher'}:
            bonus += 10
        if previous_outcome == 'win':
            bonus += 6
        if skill_key == 'attack_burst':
            bonus += 10
        note = 'Агрессия давит темпом'
    elif strategy_key == 'tricky':
        bonus = 32 if action_key == 'channel' else 13
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


def wikigachi_duel(cards_a, cards_b, seed_value, build_a=None, build_b=None, featured_slot_a=None, featured_slot_b=None, strategy_key_a='balanced', strategy_key_b='balanced'):
    rounds = []
    wins_a = 0
    wins_b = 0

    if not cards_a or not cards_b:
        return {'rounds': rounds, 'score_a': 0, 'score_b': 0, 'winner': None, 'tie_breaker': False}

    featured_a = find_card_by_slot(cards_a, featured_slot_a)
    featured_b = find_card_by_slot(cards_b, featured_slot_b)
    strategy_key_a = normalize_strategy_key(strategy_key_a)
    strategy_key_b = normalize_strategy_key(strategy_key_b)
    action_plan_a = auto_action_plan(cards_a, featured_slot_a, strategy_key_a)
    action_plan_b = auto_action_plan(cards_b, featured_slot_b, strategy_key_b)
    rng = random.Random(hashlib.sha256(f'wikigachi:{seed_value}'.encode()).hexdigest())
    rounds_count = min(len(cards_a), len(cards_b), len(WIKIGACHI_ROUND_PLAN))
    prev_a = None
    prev_b = None

    for idx in range(rounds_count):
        focus, label, phase = WIKIGACHI_ROUND_PLAN[idx]
        card_a = cards_a[idx]
        card_b = cards_b[idx]
        action_a = action_plan_a[idx]
        action_b = action_plan_b[idx]
        value_a = max(0, round(build_bonus_value(build_a, focus) / 7))
        value_b = max(0, round(build_bonus_value(build_b, focus) / 7))
        card_boost_a = matchup_strategy_bonus(card_a, card_b, phase, idx)
        card_boost_b = matchup_strategy_bonus(card_b, card_a, phase, idx)
        action_bonus_a, action_bonus_b, action_note_a, action_note_b = action_round_resolution(action_a, action_b)
        strategy_bonus_a, strategy_note_a = strategy_round_bonus(strategy_key_a, focus, phase, idx, action_a, prev_a, featured_a or card_a)
        strategy_bonus_b, strategy_note_b = strategy_round_bonus(strategy_key_b, focus, phase, idx, action_b, prev_b, featured_b or card_b)
        skill_bonus_a, skill_note_a = apply_skill_bonus(
            (featured_a or {}).get('skill_key'),
            focus,
            value_a,
            value_b,
            featured_a or card_a,
            featured_b or card_b,
            idx,
            prev_a,
        )
        skill_bonus_b, skill_note_b = apply_skill_bonus(
            (featured_b or {}).get('skill_key'),
            focus,
            value_b,
            value_a,
            featured_b or card_b,
            featured_a or card_a,
            idx,
            prev_b,
        )
        featured_bonus_a, featured_note_a = featured_card_round_bonus(
            featured_a or card_a,
            featured_b or card_b,
            focus,
            phase,
            idx,
            prev_a,
        )
        featured_bonus_b, featured_note_b = featured_card_round_bonus(
            featured_b or card_b,
            featured_a or card_a,
            focus,
            phase,
            idx,
            prev_b,
        )

        # Small deterministic swing for a less predictable duel flow.
        swing_a = rng.randint(0, 2)
        swing_b = rng.randint(0, 2)
        total_a = value_a + card_boost_a + action_bonus_a + strategy_bonus_a + skill_bonus_a + featured_bonus_a + swing_a
        total_b = value_b + card_boost_b + action_bonus_b + strategy_bonus_b + skill_bonus_b + featured_bonus_b + swing_b

        if total_a > total_b:
            round_winner = 'a'
            wins_a += 1
            prev_a = 'win'
            prev_b = 'loss'
        elif total_b > total_a:
            round_winner = 'b'
            wins_b += 1
            prev_a = 'loss'
            prev_b = 'win'
        else:
            round_winner = 'draw'
            prev_a = 'draw'
            prev_b = 'draw'

        rounds.append(
            {
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
                'swing_a': swing_a,
                'swing_b': swing_b,
                'total_a': total_a,
                'total_b': total_b,
                'winner': round_winner,
            }
        )

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
                return [normalize_card_profile(card) for card in parsed]
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
                'title': CARD_TITLES[rng.randrange(len(CARD_TITLES))],
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
        skill = skill_for_card(rarity_key, f'bot-{seed_value}', slot, source.get('title', 'Bot Card'))
        cards.append(
            {
                'slot': slot,
                'title': CARD_TITLES[rng.randrange(len(CARD_TITLES))],
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
                base = score_from_domain(domain)
                dns_info = check_dns_domain(domain)
                unique_domains[domain] = {
                    'domain': domain,
                    'domain_exists': dns_info.get('exists', False),
                    'source_label': item.get('name')
                    or (item.get('metadata') or {}).get('name')
                    or 'TonAPI NFT item',
                    'patterns': base['patterns'],
                    'tier': base['tier'],
                    'special_collections': base.get('special_collections', []),
                    'luck': base.get('luck', 0),
                    'score': base['score'],
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
        'result': result_code,
        'result_label': result_label,
        'interactive_live': not bool(state.get('complete')),
        'interactive_session_id': state['id'],
        'interactive_round_index': int(state.get('current_round', 0)),
        'interactive_total_rounds': int(state.get('rounds_total', len(WIKIGACHI_ROUND_PLAN))),
        'interactive_available_actions': list(ACTION_RULES.keys()),
        'interactive_hint': 'Выбирай действие на каждый раунд. Ход и карта теперь реально двигают матч.',
    }


def create_solo_battle(wallet, domain, mode, mode_title, opponent_wallet, opponent_domain, player_cards, opponent_cards, build_a, build_b, selected_slot_a, selected_slot_b, strategy_key_a='balanced', strategy_key_b='balanced'):
    ensure_runtime_tables()
    player_cards = [normalize_card_profile(card) for card in (player_cards or [])]
    opponent_cards = [normalize_card_profile(card) for card in (opponent_cards or [])]
    featured_a = find_card_by_slot(player_cards, selected_slot_a)
    featured_b = find_card_by_slot(opponent_cards, selected_slot_b)
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
        'strategy_key_a': normalize_strategy_key(strategy_key_a),
        'strategy_key_b': normalize_strategy_key(strategy_key_b),
        'opponent_action_plan': action_plan_b,
        'current_round': 0,
        'rounds_total': rounds_total,
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

    action_key = sanitize_action_plan([action_key])[0]
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
    action_b = (state.get('opponent_action_plan') or default_action_plan())[idx]
    build_a = state.get('build_a') or {}
    build_b = state.get('build_b') or {}
    featured_a = normalize_card_profile(state.get('featured_a') or card_a)
    featured_b = normalize_card_profile(state.get('featured_b') or card_b)
    prev_a = state.get('prev_a')
    prev_b = state.get('prev_b')
    value_a = max(0, round(build_bonus_value(build_a, focus) / 7))
    value_b = max(0, round(build_bonus_value(build_b, focus) / 7))
    card_boost_a = matchup_strategy_bonus(card_a, card_b, phase, idx)
    card_boost_b = matchup_strategy_bonus(card_b, card_a, phase, idx)
    action_bonus_a, action_bonus_b, action_note_a, action_note_b = action_round_resolution(action_key, action_b)
    strategy_bonus_a, strategy_note_a = strategy_round_bonus(state.get('strategy_key_a'), focus, phase, idx, action_key, prev_a, featured_a or card_a)
    strategy_bonus_b, strategy_note_b = strategy_round_bonus(state.get('strategy_key_b'), focus, phase, idx, action_b, prev_b, featured_b or card_b)
    skill_bonus_a, skill_note_a = apply_skill_bonus((featured_a or {}).get('skill_key'), focus, value_a, value_b, featured_a or card_a, featured_b or card_b, idx, prev_a)
    skill_bonus_b, skill_note_b = apply_skill_bonus((featured_b or {}).get('skill_key'), focus, value_b, value_a, featured_b or card_b, featured_a or card_a, idx, prev_b)
    featured_bonus_a, featured_note_a = featured_card_round_bonus(featured_a or card_a, featured_b or card_b, focus, phase, idx, prev_a)
    featured_bonus_b, featured_note_b = featured_card_round_bonus(featured_b or card_b, featured_a or card_a, focus, phase, idx, prev_b)
    swing_a, swing_b = (state.get('swing_pairs') or [[0, 0]])[idx]
    total_a = value_a + card_boost_a + action_bonus_a + strategy_bonus_a + skill_bonus_a + featured_bonus_a + swing_a
    total_b = value_b + card_boost_b + action_bonus_b + strategy_bonus_b + skill_bonus_b + featured_bonus_b + swing_b

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
                'luck': item.get('luck', 0),
                'score': item.get('score', summary['total_score']),
                'special_collections': item.get('special_collections') or [],
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


@app.route('/api/pack', methods=['POST'])
def api_pack():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    source = (payload.get('source') or 'daily').strip().lower()
    payment_id = (payload.get('payment_id') or '').strip()
    if not valid_wallet_address(wallet):
        return json_error('Кошелёк не подключен.')
    if not domain:
        return json_error('Нужно выбрать реальный домен.')
    if source not in {'daily', 'paid'}:
        return json_error('Неизвестный тип открытия пака.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Выбранный домен не найден в подключённом кошельке.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)

    if source == 'daily' and not can_open_daily_pack(wallet, domain):
        return json_error('Ежедневный пак уже открыт. Попробуй снова завтра или открой платный пак.', 403)

    if source == 'paid':
        if not payment_id:
            return json_error('Нужен подтверждённый платёж для открытия платного пака.', 403)
        with closing(get_db()) as conn:
            payment = conn.execute('SELECT * FROM pack_payments WHERE id = ?', (payment_id,)).fetchone()
        if payment is None or payment['wallet'] != wallet or payment['domain'] != domain or payment['status'] != 'confirmed':
            return json_error('Платёж не подтверждён.', 403)

    seed = f'{domain}:{wallet}:{source}:{payment_id or now_iso()}'
    cards = generate_pack(domain, seed_value=seed)
    total = deck_score(cards)
    pack_id = store_pack_open(wallet, domain, source, cards, total, payment_id=payment_id or None)
    ensure_player(wallet, domain, domain)
    return jsonify({'wallet': wallet, 'domain': domain, 'cards': cards, 'total_score': total, 'pack_id': pack_id, 'source': source})


@app.route('/api/cards/catalog')
def api_cards_catalog():
    return jsonify({'cards': CARD_CATALOG, 'total': len(CARD_CATALOG)})


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
