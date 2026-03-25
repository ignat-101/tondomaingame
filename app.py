import hashlib
import hmac
import json
import os
import random
import re
import sqlite3
import uuid
import calendar
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

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT],
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
DB_PATH = Path(os.getenv('APP_DB_PATH', 'tondomaingame.db'))
TEN_K_CONFIG_TTL = int(os.getenv('TEN_K_CONFIG_TTL', '900'))
TEN_K_CONFIG_URL = 'https://10kclub.com/api/clubs/10k/config'

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
      gap: 12px;
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
      gap: 12px;
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
      overflow: hidden;
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

    @keyframes cardFlipIn {
      0% { opacity: 0; transform: translateY(18px) rotateY(90deg) scale(0.96); }
      60% { opacity: 1; transform: translateY(-4px) rotateY(0deg) scale(1.01); }
      100% { opacity: 1; transform: translateY(0) rotateY(0deg) scale(1); }
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

    .user-item {
      border-radius: 18px;
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
      margin-top: 10px;
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
      grid-template-rows: minmax(150px, 1fr) auto minmax(150px, 1fr) auto;
      gap: 12px;
      background:
        radial-gradient(circle at 50% 10%, rgba(83, 246, 184, 0.16), transparent 38%),
        radial-gradient(circle at 50% 90%, rgba(69, 215, 255, 0.16), transparent 38%),
        linear-gradient(180deg, rgba(4, 11, 20, 0.98), rgba(8, 18, 34, 0.98));
      overflow-x: hidden;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
      overscroll-behavior: contain;
    }

    .showdown-zone {
      min-height: 0;
      display: grid;
      gap: 8px;
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
      border: 1px solid rgba(121, 217, 255, 0.32);
      border-radius: 18px;
      padding: 14px;
      background: rgba(6, 18, 32, 0.84);
      backdrop-filter: blur(3px);
      max-height: 46vh;
      overflow: auto;
      box-shadow: 0 14px 40px rgba(0, 0, 0, 0.3);
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

    @media (max-width: 700px) {
      .showdown-fullscreen {
        padding: 10px 10px calc(12px + env(safe-area-inset-bottom));
        grid-template-rows: minmax(120px, 1fr) auto minmax(120px, 1fr) auto;
      }

      .showdown-score {
        font-size: clamp(18px, 7vw, 30px);
      }

      .showdown-card {
        flex-basis: 152px;
        min-width: 152px;
      }
    }

    .pack-showcase {
      margin-top: 16px;
      border-radius: 24px;
      border: 1px solid rgba(246, 196, 83, 0.45);
      background:
        radial-gradient(circle at top, rgba(246, 196, 83, 0.18), transparent 45%),
        linear-gradient(170deg, rgba(7, 11, 18, 0.96), rgba(5, 9, 16, 0.92));
      padding: 16px 14px 18px;
      text-align: center;
    }

    .pack-counter {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 46px;
      min-width: 260px;
      border-radius: 999px;
      border: 1px solid rgba(246, 196, 83, 0.9);
      color: #f6c453;
      letter-spacing: 0.2em;
      font-weight: 700;
      padding: 0 20px;
      box-shadow: 0 0 26px rgba(246, 196, 83, 0.24);
      margin-bottom: 10px;
    }

    .pack-note {
      color: rgba(238, 246, 255, 0.86);
      margin: 0 0 12px;
      font-size: 15px;
    }

    .foil-pack {
      position: relative;
      width: min(320px, 90%);
      margin: 0 auto;
      border-radius: 18px;
      background: linear-gradient(155deg, #f8f8f8, #d8d8d8 45%, #ececec);
      color: #212121;
      padding: 26px 18px 28px;
      box-shadow: 0 24px 40px rgba(0, 0, 0, 0.32);
      overflow: hidden;
      transition: transform 420ms ease, opacity 420ms ease;
    }

    .foil-pack::before, .foil-pack::after {
      content: "";
      position: absolute;
      left: -1px;
      right: -1px;
      height: 16px;
      background:
        linear-gradient(135deg, transparent 8px, #f6f6f6 0) repeat-x;
      background-size: 16px 16px;
    }

    .foil-pack::before { top: 0; }
    .foil-pack::after {
      bottom: 0;
      transform: rotate(180deg);
    }

    .pack-cap {
      position: absolute;
      left: 0;
      right: 0;
      top: 0;
      height: 58px;
      background: linear-gradient(180deg, #ffffff, #dcdcdc);
      border-bottom: 2px solid rgba(0, 0, 0, 0.18);
      transform-origin: top center;
      z-index: 2;
    }

    .foil-pack.opening .pack-cap {
      animation: tearOpen 880ms cubic-bezier(.2,.82,.2,1) forwards;
    }

    .foil-pack.opening {
      animation: packShake 880ms ease-in-out;
    }

    .pack-showcase.opened .foil-pack {
      transform: translateY(-26px) scale(0.92);
      opacity: 0.18;
    }

    .pack-brand {
      margin-top: 52px;
      font-size: 52px;
      font-weight: 700;
      letter-spacing: 0.06em;
      color: rgba(0, 0, 0, 0.72);
    }

    .pack-sub {
      font-size: 26px;
      color: rgba(0, 0, 0, 0.62);
      margin: 4px 0 12px;
    }

    .pack-tap {
      margin-top: 12px;
      color: #f0f0f0;
      letter-spacing: 0.08em;
      font-size: 24px;
      font-weight: 700;
    }

    .owned-decks {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }

    .global-players-list {
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }

    @keyframes tearOpen {
      0% { transform: translateY(0) rotateX(0deg); opacity: 1; }
      55% { transform: translateY(-12px) rotateX(26deg); opacity: 1; }
      100% { transform: translateY(-40px) rotateX(58deg); opacity: 0; }
    }

    @keyframes packShake {
      0% { transform: translateX(0) rotate(0deg); }
      20% { transform: translateX(-3px) rotate(-1deg); }
      40% { transform: translateX(3px) rotate(1deg); }
      60% { transform: translateX(-2px) rotate(-0.5deg); }
      100% { transform: translateX(0) rotate(0deg); }
    }

    @media (max-width: 920px) {
      body { padding-bottom: 84px; }
      .layout { grid-template-columns: 1fr; }
      .side { display: none; }
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

          <div class="actions">
            <div id="ton-connect"></div>
            <button id="check-domains-btn" disabled>Проверить наличие доменов</button>
          </div>

          <div class="status" id="wallet-status"></div>
          <div class="domain-grid" id="domains-list"></div>
          <div class="result-box" id="marketplaces-box" style="display:none;">
            <strong>Доменов клуба 10K не найдено.</strong>
            <p class="muted">Можно купить 4-значный .ton на площадках и затем вернуться к игре с новым доменом.</p>
            <div class="links-row" id="marketplaces-links"></div>
          </div>
        </section>

        <section class="panel view" id="view-pack">
          <h2>Шаг 2. Распаковка 5 карточек</h2>
          <p class="muted">Карты генерируются из реально найденного домена. Колода фиксируется по связке домен + кошелёк, поэтому её можно воспроизводить и использовать в режимах игры.</p>

          <div class="stats-strip">
            <div class="stat-chip" id="selected-domain-label">Домен не выбран</div>
            <div class="stat-chip" id="pack-score-label">Сумма колоды: -</div>
          </div>

          <div class="actions">
            <button class="secondary" id="back-to-wallet-btn">Назад</button>
            <button class="secondary" id="rebind-domain-btn">Перепривязать домен</button>
            <button id="open-pack-btn" disabled>Открыть 5 карточек</button>
          </div>

          <div class="pack-showcase" id="pack-showcase">
            <div class="pack-counter" id="pack-counter">DAILY PACKS: 9 / 10</div>
            <p class="pack-note" id="pack-note">Tap to open</p>
            <div class="foil-pack" id="foil-pack">
              <div class="pack-cap"></div>
              <div class="pack-brand">TON</div>
              <div class="pack-sub">Domain Cards</div>
            </div>
            <div class="pack-tap">▲ TAP TO OPEN ▲</div>
          </div>

          <div class="status" id="pack-status"></div>
          <div class="card-grid" id="pack-cards"></div>
          <div class="actions">
            <button id="continue-to-modes-btn" disabled>Продолжить</button>
          </div>
        </section>

        <section class="panel view" id="view-modes">
          <h2>Шаг 3. Режимы игры</h2>
          <p class="muted">Бой идёт в формате wiki gachi: 5 раундов по статам (атака, защита, удача, общая сила и финальный натиск). Для рейтингового и обычного матча укажи соперника, задай время на ответ и бот отправит ему приглашение в Telegram.</p>

          <div class="team-card" style="margin-bottom:18px;">
            <h3>PvP через Telegram</h3>
            <div class="row">
              <input id="opponent-wallet" placeholder="Кошелёк или домен соперника">
              <input id="invite-timeout" type="number" min="30" max="600" step="30" value="60" placeholder="Время ответа, сек">
            </div>
            <div class="row">
              <select id="one-card-slot">
                <option value="">Выбери карту для режима одной карты</option>
              </select>
            </div>
            <div class="tiny">Соперник должен заранее написать боту `/start` и открыть mini app хотя бы один раз, чтобы привязать свой кошелёк к Telegram.</div>
          </div>

          <div class="mode-grid">
            <div class="mode-card" data-mode-card="ranked">
              <div class="mode-burst"></div>
              <h3>Рейтинговый</h3>
              <p>5-раундовый бой против реального соперника. После принятия рейтинг пересчитается по ELO.</p>
              <button id="play-ranked-btn" disabled>Отправить рейтинговый вызов</button>
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
              <p>Тот же 5-раундовый формат, но без изменения рейтинга.</p>
              <button id="play-casual-btn" disabled>Отправить обычный вызов</button>
            </div>
            <div class="mode-card" data-mode-card="bot">
              <div class="mode-burst"></div>
              <h3>С ботом</h3>
              <p>Тестовый wiki gachi: 5 раундов против бота с рандомной колодой.</p>
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
          <p class="muted">Бот принимает `/start`, связывает Telegram с кошельком, отправляет реальные приглашения на матч и даёт сопернику ограниченное время на ответ.</p>
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
      playerProfile: null,
      lastResult: null,
      roomId: null,
      room: null,
      activeUsers: [],
      friends: [],
      ownedDecks: [],
      allPlayers: [],
      achievements: []
    };

    const telegramBotUsername = {{ telegram_bot_username|tojson }};
    const telegramWebappUrl = {{ telegram_webapp_url|tojson }};
    const marketplaceLinks = {{ marketplace_links|tojson }};

    const walletBadge = document.getElementById('wallet-badge');
    const telegramBadge = document.getElementById('telegram-badge');
    const walletStatus = document.getElementById('wallet-status');
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
    const globalPlayersList = document.getElementById('global-players-list');
    const packShowcase = document.getElementById('pack-showcase');
    const foilPack = document.getElementById('foil-pack');
    const packCounter = document.getElementById('pack-counter');
    const packNote = document.getElementById('pack-note');
    const oneCardSlot = document.getElementById('one-card-slot');
    const achievementsList = document.getElementById('achievements-list');
    const refreshAchievementsBtn = document.getElementById('refresh-achievements-btn');

    telegramOpenLink.href = telegramBotUsername
      ? `https://t.me/${telegramBotUsername}?startapp=tondomaingame`
      : telegramWebappUrl || window.location.href;
    telegramOpenLink.textContent = telegramBotUsername ? `@${telegramBotUsername}` : 'Открыть мини-апп';

    let tonConnectUI = null;

    function shortAddress(value) {
      if (!value) return '-';
      return `${value.slice(0, 6)}...${value.slice(-6)}`;
    }

    function setStatus(element, text, kind = '') {
      element.className = `status ${kind}`.trim();
      element.textContent = text;
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
      document.querySelectorAll('[data-mode-card]').forEach((card) => {
        card.classList.toggle('active-mode', card.dataset.modeCard === modeName);
      });
      window.clearTimeout(window.__modeFocusTimer);
      window.__modeFocusTimer = window.setTimeout(() => {
        if (modeGrid) {
          modeGrid.classList.remove('mode-focus');
        }
      }, 2200);
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
          <div class="tiny">Средняя атака: ${item.average_attack} • Средняя защита: ${item.average_defense}</div>
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
          <div class="tiny">${item.average_attack ? `Средняя атака: ${item.average_attack} • Средняя защита: ${item.average_defense}` : 'Колода ещё не сохранена'}</div>
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
          <div class="tiny">Средняя атака: ${data.deck.average_attack} • Средняя защита: ${data.deck.average_defense}</div>
          <div class="tiny">Сумма колоды: ${data.deck.total_score}</div>
        </div>
        ${data.deck.cards.map((card) => `
          <div class="user-item">
            <strong>${card.title}</strong>
            <div class="tiny">Слот ${card.slot} • ${card.rarity}</div>
            <div class="tiny">Атака ${card.attack} • Защита ${card.defense} • Сила ${card.score}</div>
          </div>
        `).join('')}
      `;
      deckView.innerHTML = markup;
      mobileDeckView.innerHTML = markup;
    }

    function renderProfile() {
      walletBadge.textContent = state.wallet ? `Подключён: ${shortAddress(state.wallet)}` : 'Кошелёк не подключен';
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
        return;
      }
      ownedDecksList.innerHTML = state.ownedDecks.map((item) => `
        <div class="user-item">
          <strong>${item.domain}.ton ${item.is_active || currentDomain === item.domain ? '(активная)' : ''}</strong>
          <div class="tiny">Тир: ${item.tier || '-'} • Удача: ${item.luck || 0}</div>
          <div class="tiny">Сила колоды: ${item.deck.total_score}</div>
          <div class="actions" style="margin-top:10px;">
            <button class="secondary" onclick="selectDeckDomain('${item.domain}')">Сделать активной</button>
          </div>
        </div>
      `).join('');
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

    function refreshOneCardSelector() {
      oneCardSlot.innerHTML = '<option value="">Выбери карту для режима одной карты</option>';
      if (!state.cards.length) {
        return;
      }
      oneCardSlot.innerHTML += state.cards.map((card) => `
        <option value="${card.slot}">Слот ${card.slot}: ${card.title} (${card.score})</option>
      `).join('');
    }

    function updateButtons() {
      const connected = Boolean(state.wallet);
      const hasDomain = Boolean(state.selectedDomain);
      const hasCards = state.cards.length === 5;
      document.getElementById('check-domains-btn').disabled = !connected;
      document.getElementById('open-pack-btn').disabled = !(connected && hasDomain);
      document.getElementById('continue-to-modes-btn').disabled = !hasCards;
      document.getElementById('play-ranked-btn').disabled = !(connected && hasCards);
      document.getElementById('play-casual-btn').disabled = !(connected && hasCards);
      document.getElementById('play-bot-btn').disabled = !(connected && hasCards);
      document.getElementById('play-onecard-btn').disabled = !(connected && hasCards && oneCardSlot.value);
      document.getElementById('create-room-btn').disabled = !(connected && hasCards);
      document.getElementById('join-room-btn').disabled = !(connected && hasCards);
      telegramLinkBtn.disabled = !connected;
      addFriendBtn.disabled = !connected;
      refreshAchievementsBtn.disabled = !connected;
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
        <div class="domain-card ${state.selectedDomain === domain.domain ? 'selected' : ''}">
          <h3>${domain.domain}.ton</h3>
          <p>Источник: ${domain.source_label}</p>
          <p>Тир: ${domain.tier || '-'} • Удача: ${domain.luck || 0}</p>
          <p>Паттерны: ${domain.patterns.length ? domain.patterns.join(', ') : 'базовый 10K домен'}</p>
          <p>Спецколлекции: ${domain.special_collections && domain.special_collections.length ? domain.special_collections.join(', ') : 'нет'}</p>
          <p>Счёт домена: ${domain.score} • DNS: ${domain.domain_exists ? 'активен' : 'не подтверждён'}</p>
          <button onclick="selectDomain('${domain.domain}')">Выбрать домен</button>
        </div>
      `).join('');
    }

    window.selectDomain = function selectDomain(domain) {
      state.selectedDomain = domain;
      state.cards = [];
      packCards.innerHTML = '';
      packScoreLabel.textContent = 'Сумма колоды: -';
      packShowcase.classList.remove('opened');
      foilPack.classList.remove('opening');
      packNote.textContent = 'Tap to open';
      refreshOneCardSelector();
      renderDomains(state.domains);
      renderProfile();
      updateButtons();
      switchView('pack');
      setStatus(document.getElementById('pack-status'), `Выбран домен ${domain}.ton. Теперь можно открыть колоду.`, 'success');
    };

    function renderPack(cards, total) {
      packCards.classList.remove('reveal');
      packCards.innerHTML = cards.map((card) => `
        <article class="game-card">
          <div class="tiny">${card.rarity}</div>
          <h3>${card.title}</h3>
          <p>${card.domain}.ton • слот ${card.slot}</p>
          <div class="team-line"><span>Атака</span><strong>${card.attack}</strong></div>
          <div class="team-line"><span>Защита</span><strong>${card.defense}</strong></div>
          <div class="team-line"><span>Удача</span><strong>${card.luck || 0}</strong></div>
          <div class="team-line"><span>Сила</span><strong>${card.score}</strong></div>
          <p>${card.ability}</p>
        </article>
      `).join('');
      packScoreLabel.textContent = `Сумма колоды: ${total}`;
      refreshOneCardSelector();
      requestAnimationFrame(() => packCards.classList.add('reveal'));
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
          <div class="tiny">ATK ${card.attack ?? '-'} • DEF ${card.defense ?? '-'} • LUCK ${card.luck ?? 0}</div>
          <div class="tiny">Сила: ${card.score ?? '-'}</div>
        </div>
      `).join('');
    }

    function revealDisciplineRows() {
      const rows = battleResult.querySelectorAll('.discipline-row');
      rows.forEach((row, index) => {
        setTimeout(() => {
          row.classList.add('visible');
        }, 360 + index * 420);
      });
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
        const roundsLine = Array.isArray(result.rounds) && result.rounds.length
          ? `<div class="discipline-list">
              ${result.rounds.map((round) => {
                const roundClass = round.winner === 'player' ? 'win' : (round.winner === 'opponent' ? 'lose' : 'draw');
                const marker = round.winner === 'player' ? 'WIN' : (round.winner === 'opponent' ? 'LOSE' : 'DRAW');
                return `
                  <div class="discipline-row ${roundClass}">
                    <span>${round.label}</span>
                    <span>${round.player_total} : ${round.opponent_total} • ${marker}</span>
                  </div>
                `;
              }).join('')}
            </div>`
          : '';
        const deckPowerLine = result.player_deck_power !== undefined && result.opponent_deck_power !== undefined
          ? `<div class="tiny">Сила колод (тай-брейк): ${result.player_deck_power} vs ${result.opponent_deck_power}${result.tie_breaker ? ' • использован тай-брейк' : ''}</div>`
          : '';
        state.lastReplayMode = result.mode || (result.mode_title === 'Матч с ботом' ? 'bot' : (result.mode_title === 'Рейтинговый матч' ? 'ranked' : 'casual'));
        battleResult.classList.add('showdown-fullscreen');
        document.body.classList.add('showdown-open');
        battleResult.scrollTop = 0;
        battleResult.innerHTML = `
          <section class="showdown-zone showdown-top">
            <div class="tiny"><strong>Твоя колода</strong> • ${result.player_domain}.ton</div>
            <div class="showdown-deck">
              ${showdownDeckMarkup(result.player_cards, result.player_card)}
            </div>
          </section>
          <section class="showdown-center showdown-middle">
            <div class="result-flip">
              <div class="result-flip-card ${resultClass}">
                <div class="result-flip-face ${frontClass}">${frontLabel}</div>
                <div class="result-flip-face back">LOSE</div>
              </div>
            </div>
            <h3>${result.mode_title}</h3>
            <div class="showdown-score">
              <span>${result.player_score}</span>
              <span>:</span>
              <span>${result.opponent_score}</span>
            </div>
            <div class="tiny">Твой домен: ${result.player_domain}.ton • Соперник: ${opponentLabel}</div>
            ${cardLine}
            ${oppCardLine}
            ${roundsLine}
            ${deckPowerLine}
            ${ratingLine}
            <p class="muted">Итог: ${result.result_label}</p>
          </section>
          <section class="showdown-zone showdown-bottom">
            <div class="tiny"><strong>Колода соперника</strong> • ${opponentLabel}</div>
            <div class="showdown-deck">
              ${showdownDeckMarkup(result.opponent_cards, result.opponent_card)}
            </div>
          </section>
          <div class="result-actions">
            <button onclick="repeatLastMode()">Играть ещё раз</button>
            <button class="secondary" onclick="openModes()">К режимам</button>
          </div>
        `;
        revealDisciplineRows();
      }
      telegramShareBtn.disabled = false;
    }

    function openModes() {
      document.body.classList.remove('showdown-open');
      switchView('modes');
    }

    function repeatLastMode() {
      if (state.lastReplayMode === 'bot') {
        playBotMatch();
        return;
      }
      if (state.lastReplayMode === 'onecard') {
        playOneCardMatch();
        return;
      }
      if (state.lastReplayMode === 'ranked' || state.lastReplayMode === 'casual') {
        playMatch(state.lastReplayMode);
        return;
      }
      switchView('modes');
    }

    function rebindDomain() {
      state.selectedDomain = null;
      state.cards = [];
      state.lastResult = null;
      packCards.innerHTML = '';
      packScoreLabel.textContent = 'Сумма колоды: -';
      packShowcase.classList.remove('opened');
      foilPack.classList.remove('opening');
      packNote.textContent = 'Tap to open';
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
        if (data.domains.length) {
          setStatus(walletStatus, `Найдено доменов: ${data.domains.length}. Выбери тот, который хочешь использовать для колоды.`, 'success');
        } else {
          setStatus(walletStatus, 'Подключение прошло успешно, но 10K Club доменов в кошельке не найдено.', 'warning');
        }
        renderDomains(data.domains);
        loadOwnedDecks();
      } catch (error) {
        setStatus(walletStatus, error.message, 'error');
      }
    }

    async function openPack() {
      setStatus(document.getElementById('pack-status'), 'Распаковываем 5 карточек из домена...', 'warning');
      foilPack.classList.remove('opening');
      packShowcase.classList.remove('opened');
      requestAnimationFrame(() => foilPack.classList.add('opening'));
      packNote.textContent = 'Opening...';
      try {
        const data = await api('/api/pack', {
          method: 'POST',
          body: {wallet: state.wallet, domain: state.selectedDomain}
        });
        state.cards = data.cards;
        packShowcase.classList.add('opened');
        packCounter.textContent = `DAILY PACKS: ${Math.max(1, 10 - (new Date().getUTCDate() % 5))} / 10`;
        packNote.textContent = 'Pack opened';
        renderPack(data.cards, data.total_score);
        setStatus(document.getElementById('pack-status'), `Колода готова. ${data.domain}.ton даёт ${data.total_score} очков силы.`, 'success');
        updateButtons();
        showDeck();
        loadOwnedDecks();
        loadActiveUsers();
        loadGlobalPlayers();
        loadAchievements();
        loadProfile();
      } catch (error) {
        foilPack.classList.remove('opening');
        packNote.textContent = 'Tap to open';
        setStatus(document.getElementById('pack-status'), error.message, 'error');
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

    async function playMatch(mode) {
      const opponentWallet = document.getElementById('opponent-wallet').value.trim();
      const timeoutSeconds = Number(document.getElementById('invite-timeout').value || 60);
      animateModeChoice(mode);
      try {
        const data = await api(`/api/match/${mode}`, {
          method: 'POST',
          body: {
            wallet: state.wallet,
            domain: state.selectedDomain,
            opponent_wallet: opponentWallet,
            timeout_seconds: timeoutSeconds
          }
        });
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
            domain: state.selectedDomain
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
      if (!tg || !tg.initData) {
        telegramStatus.textContent = 'Привязка доступна только внутри Telegram mini app.';
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
      } catch (error) {
        deckView.innerHTML = `<div class="user-item error">${error.message}</div>`;
      }
    }

    async function loadOwnedDecks() {
      if (!state.wallet) {
        renderOwnedDecks([], null);
        return;
      }
      try {
        const data = await api(`/api/decks/${encodeURIComponent(state.wallet)}`);
        renderOwnedDecks(data.decks || [], data.current_domain);
      } catch (error) {
        ownedDecksList.innerHTML = `<div class="user-item error">${error.message}</div>`;
      }
    }

    async function selectDeckDomain(domain) {
      if (!state.wallet) return;
      try {
        const data = await api('/api/deck/select', {
          method: 'POST',
          body: { wallet: state.wallet, domain }
        });
        state.selectedDomain = data.domain;
        state.playerProfile = data.player;
        state.cards = data.deck.cards || [];
        renderProfile();
        renderDeck({ wallet: state.wallet, domain: data.domain, deck: data.deck });
        refreshOneCardSelector();
        updateButtons();
        await loadOwnedDecks();
        setStatus(document.getElementById('pack-status'), `Активная колода переключена на ${data.domain}.ton.`, 'success');
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
          state.domainsChecked = false;
          state.domains = [];
          state.selectedDomain = null;
          state.cards = [];
          packCards.innerHTML = '';
          packScoreLabel.textContent = 'Сумма колоды: -';
          packShowcase.classList.remove('opened');
          foilPack.classList.remove('opening');
          packNote.textContent = 'Tap to open';
          renderDomains([]);
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
        } else {
          state.domainsChecked = false;
          state.domains = [];
          state.selectedDomain = null;
          state.cards = [];
          renderDomains([]);
          renderProfile();
          renderFriends([]);
          renderDeck(null);
          renderOwnedDecks([], null);
          renderAchievements([]);
          setStatus(walletStatus, 'Подключи кошелёк через TonConnect.', 'warning');
        }
      };

      tonConnectUI.onStatusChange(async () => {
        await applyConnection();
      });

      await applyConnection();
    }

    document.getElementById('check-domains-btn').addEventListener('click', checkDomains);
    document.getElementById('back-to-wallet-btn').addEventListener('click', () => switchView('wallet'));
    document.getElementById('rebind-domain-btn').addEventListener('click', rebindDomain);
    document.getElementById('open-pack-btn').addEventListener('click', openPack);
    foilPack.addEventListener('click', () => {
      if (!document.getElementById('open-pack-btn').disabled) {
        openPack();
      }
    });
    document.getElementById('continue-to-modes-btn').addEventListener('click', () => switchView('modes'));
    document.getElementById('play-ranked-btn').addEventListener('click', () => playMatch('ranked'));
    document.getElementById('play-casual-btn').addEventListener('click', () => playMatch('casual'));
    document.getElementById('play-bot-btn').addEventListener('click', playBotMatch);
    document.getElementById('play-onecard-btn').addEventListener('click', playOneCardMatch);
    oneCardSlot.addEventListener('change', updateButtons);
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
    renderProfile();
    renderFriends([]);
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

            CREATE TABLE IF NOT EXISTS friends (
                owner_wallet TEXT NOT NULL,
                friend_wallet TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (owner_wallet, friend_wallet)
            );
            '''
        )
        columns = {row['name'] for row in conn.execute("PRAGMA table_info(players)").fetchall()}
        if 'current_domain' not in columns:
            conn.execute('ALTER TABLE players ADD COLUMN current_domain TEXT')
        if 'first_seen' not in columns:
            conn.execute('ALTER TABLE players ADD COLUMN first_seen TEXT')
            conn.execute('UPDATE players SET first_seen = COALESCE(first_seen, updated_at)')
        conn.commit()


def json_error(message, status=400):
    return jsonify({'error': message}), status


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
    attack = sum(int(char) for char in domain) + ATTACK_BASE
    defense = DEFENSE_BASE + (1 if domain.startswith('0') else 0)
    luck = 0
    patterns = []
    tier = 'Tier-3'
    special_collections = []

    try:
        club = classify_domain_with_10k_config(domain)
        patterns = club['patterns']
        tier = club['tier']
        special_collections = club['special_collections']
        base_score = club['base_score']
        bonus_score = club['bonus_score']
        attack += base_score // 700 + bonus_score // 1200
        defense += base_score // 900 + bonus_score // 1800
        luck = 2 + bonus_score // 1500 + len(special_collections)
    except (requests.RequestException, RuntimeError, ValueError, KeyError):
        patterns = detect_10k_patterns(domain)
        for pattern in patterns:
            bonus = PATTERN_BONUSES.get(pattern, {'attack': 0, 'defense': 0})
            attack += bonus['attack']
            defense += bonus['defense']

    score = attack + defense + luck
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


def generate_pack(domain, wallet, count=5):
    base = score_from_domain(domain)
    rng = random.Random(hashlib.sha256(f'{wallet}:{domain}'.encode()).hexdigest())
    cards = []
    for slot in range(1, count + 1):
        luck = max(0, base.get('luck', 0) + rng.randint(-1, 3))
        attack = max(1, base['attack'] + rng.randint(-6, 12) + slot + luck // 2)
        defense = max(1, base['defense'] + rng.randint(-4, 10) + luck // 3)
        score = attack + defense + luck
        cards.append(
            {
                'slot': slot,
                'title': CARD_TITLES[(slot + int(domain[-1])) % len(CARD_TITLES)],
                'ability': CARD_ABILITIES[(slot + int(domain[0])) % len(CARD_ABILITIES)],
                'domain': domain,
                'attack': attack,
                'defense': defense,
                'luck': luck,
                'score': score,
                'rarity': card_rarity(score),
                'patterns': base['patterns'],
            }
        )
    return cards


def deck_score(cards):
    return sum(card['score'] for card in cards)


WIKIGACHI_ROUND_PLAN = [
    ('attack', 'Раунд 1: Атака'),
    ('defense', 'Раунд 2: Защита'),
    ('luck', 'Раунд 3: Удача'),
    ('score', 'Раунд 4: Общая сила'),
    ('attack', 'Раунд 5: Финальный натиск'),
]


def card_stat_value(card, stat_name):
    if stat_name == 'attack':
        return int(card.get('attack', 0))
    if stat_name == 'defense':
        return int(card.get('defense', 0))
    if stat_name == 'luck':
        return int(card.get('luck', 0))
    return int(card.get('score', 0))


def wikigachi_duel(cards_a, cards_b, seed_value):
    rounds = []
    wins_a = 0
    wins_b = 0

    if not cards_a or not cards_b:
        return {'rounds': rounds, 'score_a': 0, 'score_b': 0, 'winner': None, 'tie_breaker': False}

    rng = random.Random(hashlib.sha256(f'wikigachi:{seed_value}'.encode()).hexdigest())
    rounds_count = min(len(cards_a), len(cards_b), len(WIKIGACHI_ROUND_PLAN))

    for idx in range(rounds_count):
        focus, label = WIKIGACHI_ROUND_PLAN[idx]
        card_a = cards_a[idx]
        card_b = cards_b[idx]
        value_a = card_stat_value(card_a, focus)
        value_b = card_stat_value(card_b, focus)

        # Small deterministic swing for a less predictable duel flow.
        swing_a = rng.randint(0, 2)
        swing_b = rng.randint(0, 2)
        total_a = value_a + swing_a
        total_b = value_b + swing_b

        if total_a > total_b:
            round_winner = 'a'
            wins_a += 1
        elif total_b > total_a:
            round_winner = 'b'
            wins_b += 1
        else:
            round_winner = 'draw'

        rounds.append(
            {
                'round': idx + 1,
                'label': label,
                'focus': focus,
                'card_a': {'slot': card_a.get('slot'), 'title': card_a.get('title')},
                'card_b': {'slot': card_b.get('slot'), 'title': card_b.get('title')},
                'value_a': value_a,
                'value_b': value_b,
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
        total_a = deck_score(cards_a)
        total_b = deck_score(cards_b)
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
    }


def deck_summary_for_domain(domain, wallet_seed=None):
    if not domain:
        return None
    seed = wallet_seed or f'summary:{domain}'
    cards = generate_pack(domain, seed)
    return {
        'cards': cards,
        'average_attack': round(sum(card['attack'] for card in cards) / len(cards), 1),
        'average_defense': round(sum(card['defense'] for card in cards) / len(cards), 1),
        'total_score': deck_score(cards),
    }


def random_bot_cards(seed_value, count=5):
    rng = random.Random(hashlib.sha256(f'bot:{seed_value}'.encode()).hexdigest())
    cards = []
    for slot in range(1, count + 1):
        attack = rng.randint(12, 48)
        defense = rng.randint(10, 42)
        luck = rng.randint(0, 12)
        cards.append(
            {
                'slot': slot,
                'title': CARD_TITLES[rng.randrange(len(CARD_TITLES))],
                'ability': CARD_ABILITIES[rng.randrange(len(CARD_ABILITIES))],
                'attack': attack,
                'defense': defense,
                'luck': luck,
                'score': attack + defense + luck,
                'rarity': card_rarity(attack + defense + luck),
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
        stripped = normalize_domain(text)
        if stripped:
            candidates.add(stripped)

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
    domains = fetch_wallet_domains(wallet)
    return any(item['domain'] == domain for item in domains)


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
    ref = (reference or '').strip().lower()
    if not ref:
        raise ValueError('Укажи кошелёк или домен соперника.')
    if valid_wallet_address(reference):
        return reference.strip()

    domain = normalize_domain(ref)
    if not domain:
        raise ValueError('Поле соперника принимает только полный кошелёк или 4-значный .ton домен.')

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


def head_to_head_result(wallet_a, domain_a, wallet_b, domain_b):
    cards_a = generate_pack(domain_a, wallet_a)
    cards_b = generate_pack(domain_b, wallet_b)
    duel = wikigachi_duel(cards_a, cards_b, f'{wallet_a}:{domain_a}:{wallet_b}:{domain_b}')
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
        'winner': winner,
    }


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
                'player_card': item['card_a'] if viewer_is_a else item['card_b'],
                'opponent_card': item['card_b'] if viewer_is_a else item['card_a'],
                'player_value': item['value_a'] if viewer_is_a else item['value_b'],
                'opponent_value': item['value_b'] if viewer_is_a else item['value_a'],
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

    payload = {
        'kind': 'solo',
        'mode': invite['mode'],
        'mode_title': 'Рейтинговый матч' if invite['mode'] == 'ranked' else 'Обычный матч',
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
    message = (
        f'Вас приглашают на {"рейтинговую" if mode == "ranked" else "обычную"} игру.\n'
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
        cards = generate_pack(player['domain'], player['wallet'])
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

    if text.startswith('/start') or text.startswith('/app'):
        telegram_send_message(
            chat_id,
            'tondomaingame готов. Открой mini app кнопкой ниже, подключи TON-кошелёк и начинай матч.',
            telegram_welcome_markup(),
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
        'Команды:\n/start\n/app\n/leaderboard\n/rating <wallet>\n\nДля игры открой mini app.',
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
        domains = fetch_wallet_domains(wallet)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    player = ensure_player(wallet, domains[0]['domain'] if domains else None, None)
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
        domains = fetch_wallet_domains(wallet, force_refresh=True)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)
    ensure_player(wallet, domains[0]['domain'] if domains else None)
    return jsonify({'wallet': wallet, 'domains': domains, 'marketplaces': MARKETPLACE_LINKS})


@app.route('/api/pack', methods=['POST'])
def api_pack():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    if not valid_wallet_address(wallet):
        return json_error('Кошелёк не подключен.')
    if not domain:
        return json_error('Нужно выбрать реальный домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Выбранный домен не найден в подключённом кошельке.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)

    cards = generate_pack(domain, wallet)
    total = deck_score(cards)
    ensure_player(wallet, domain, domain)
    return jsonify({'wallet': wallet, 'domain': domain, 'cards': cards, 'total_score': total})


@app.route('/api/match/<mode>', methods=['POST'])
def api_match(mode):
    if mode not in {'ranked', 'casual'}:
        return json_error('Неизвестный режим.', 404)

    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    opponent_reference = (payload.get('opponent_wallet') or '').strip()
    timeout_seconds = payload.get('timeout_seconds') or DEFAULT_INVITE_TIMEOUT_SECONDS

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
        invite = create_duel_invite(mode, wallet, domain, opponent_wallet, timeout_seconds)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502 if isinstance(exc, RuntimeError) else 400)

    return jsonify({'invite': invite, 'player': get_player(wallet)})


@app.route('/api/match/bot', methods=['POST'])
def api_match_bot():
    payload = request.get_json(silent=True) or {}
    wallet = (payload.get('wallet') or '').strip()
    domain = normalize_domain(payload.get('domain'))
    if not valid_wallet_address(wallet):
        return json_error('Нужно подключить кошелёк.')
    if not domain:
        return json_error('Нужно выбрать домен.')
    try:
        if not validate_wallet_owns_domain(wallet, domain):
            return json_error('Этот домен не принадлежит подключённому кошельку.', 403)
    except (RuntimeError, ValueError) as exc:
        return json_error(str(exc), 502)

    player_cards = generate_pack(domain, wallet)
    bot_cards = random_bot_cards(f'{wallet}:{domain}:{now_iso()}')
    duel = wikigachi_duel(player_cards, bot_cards, f'bot-duel:{wallet}:{domain}:{now_iso()}')
    player_score = duel['score_a']
    bot_score = duel['score_b']
    player_deck_power = deck_score(player_cards)
    bot_deck_power = deck_score(bot_cards)
    if duel['winner'] == 'a':
        result_code = 'win'
        result_label = 'Победа'
    elif duel['winner'] == 'b':
        result_code = 'lose'
        result_label = 'Поражение'
    else:
        result_code = 'draw'
        result_label = 'Ничья'

    rounds = []
    for item in duel['rounds']:
        rounds.append(
            {
                'round': item['round'],
                'label': item['label'],
                'focus': item['focus'],
                'player_card': item['card_a'],
                'opponent_card': item['card_b'],
                'player_value': item['value_a'],
                'opponent_value': item['value_b'],
                'player_total': item['total_a'],
                'opponent_total': item['total_b'],
                'winner': 'draw' if item['winner'] == 'draw' else ('player' if item['winner'] == 'a' else 'opponent'),
            }
        )

    record_non_ranked_game(wallet, domain)
    return jsonify(
        {
            'result': {
                'kind': 'solo',
                'mode': 'bot',
                'mode_title': 'Матч с ботом',
                'player_domain': domain,
                'opponent_domain': None,
                'player_score': player_score,
                'opponent_score': bot_score,
                'player_deck_power': player_deck_power,
                'opponent_deck_power': bot_deck_power,
                'tie_breaker': duel['tie_breaker'],
                'rounds': rounds,
                'player_cards': player_cards,
                'opponent_cards': bot_cards,
                'result': result_code,
                'result_label': result_label,
            },
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

    cards = generate_pack(domain, wallet)
    player_card = next((card for card in cards if card['slot'] == card_slot), None)
    if player_card is None:
        return json_error('Карта не найдена в колоде.', 400)
    bot_card = random_bot_single_card(f'onecard:{wallet}:{domain}:{now_iso()}')
    player_score = player_card['score']
    bot_score = bot_card['score']
    if player_score > bot_score:
        result_code = 'win'
        result_label = 'Победа'
    elif player_score < bot_score:
        result_code = 'lose'
        result_label = 'Поражение'
    else:
        result_code = 'draw'
        result_label = 'Ничья'

    record_non_ranked_game(wallet, domain)
    return jsonify(
        {
            'result': {
                'kind': 'solo',
                'mode': 'onecard',
                'mode_title': 'Дуэль одной картой',
                'player_domain': domain,
                'opponent_domain': None,
                'player_score': player_score,
                'opponent_score': bot_score,
                'result': result_code,
                'result_label': result_label,
                'player_card': player_card,
                'opponent_card': bot_card,
                'player_cards': [player_card],
                'opponent_cards': [bot_card],
            },
            'player': get_player(wallet),
        }
    )


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
    app.run(host=HOST, port=PORT, debug=DEBUG)
