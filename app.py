import hashlib
import json
import os
import random
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

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
BASE_RATING = int(os.getenv('BASE_RATING', '1000'))
RATING_K_FACTOR = int(os.getenv('RATING_K_FACTOR', '32'))
DOMAIN_CACHE_TTL = int(os.getenv('DOMAIN_CACHE_TTL', '300'))
DB_PATH = Path(os.getenv('APP_DB_PATH', 'tondomaingame.db'))

DOMAIN_CACHE = {}

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

    @media (max-width: 920px) {
      .layout { grid-template-columns: 1fr; }
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
            Подключи реальный TON-кошелёк, проверь наличие 10K Club доменов, открой 5 карт из найденного домена
            и запусти бой в рейтинговом, командном или обычном режиме.
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
            <button id="open-pack-btn" disabled>Открыть 5 карточек</button>
          </div>

          <div class="status" id="pack-status"></div>
          <div class="card-grid" id="pack-cards"></div>
          <div class="actions">
            <button id="continue-to-modes-btn" disabled>Продолжить</button>
          </div>
        </section>

        <section class="panel view" id="view-modes">
          <h2>Шаг 3. Режимы игры</h2>
          <p class="muted">Рейтинговый режим сохраняет ELO-рейтинг в базе. Обычный режим проводит быстрый матч без рейтинга. Командный режим создаёт комнату на 2-4 игроков с реальными доменами участников.</p>

          <div class="mode-grid">
            <div class="mode-card">
              <h3>Рейтинговый</h3>
              <p>Матч против серверного соперника, после боя рейтинг пересчитывается по ELO.</p>
              <button id="play-ranked-btn" disabled>Играть рейтинговый матч</button>
            </div>
            <div class="mode-card">
              <h3>Командный</h3>
              <p>Создай комнату или войди по коду. Поддерживается от 2 до 4 игроков.</p>
              <button id="show-team-btn">Открыть комнату</button>
            </div>
            <div class="mode-card">
              <h3>Обычный</h3>
              <p>Быстрый матч без изменения рейтинга.</p>
              <button id="play-casual-btn" disabled>Играть обычный матч</button>
            </div>
          </div>

          <div class="result-box" id="battle-result" style="display:none;"></div>

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
      </main>

      <aside class="side">
        <section class="panel">
          <h3>Профиль игрока</h3>
          <div class="kv"><span class="muted">Кошелёк</span><span id="profile-wallet">-</span></div>
          <div class="kv"><span class="muted">Активный домен</span><span id="profile-domain">-</span></div>
          <div class="kv"><span class="muted">Рейтинг</span><span id="profile-rating">1000</span></div>
          <div class="kv"><span class="muted">Сыграно матчей</span><span id="profile-games">0</span></div>
        </section>

        <section class="panel">
          <h3>Telegram бот</h3>
          <p class="muted">Бот умеет открывать мини-апп и получать данные из веб-приложения через webhook. Если приложение открыто внутри Telegram, можно отправить сводку текущего результата обратно боту.</p>
          <div class="actions">
            <a class="market-link" id="telegram-open-link" target="_blank" rel="noopener">Открыть бота</a>
            <button class="secondary" id="telegram-share-btn" disabled>Отправить результат в Telegram</button>
          </div>
          <div class="status tiny" id="telegram-status"></div>
        </section>

        <section class="panel">
          <h3>Топ рейтинга</h3>
          <div class="leaderboard" id="leaderboard"></div>
        </section>
      </aside>
    </div>
  </div>

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
      room: null
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
    const selectedDomainLabel = document.getElementById('selected-domain-label');
    const packScoreLabel = document.getElementById('pack-score-label');
    const packCards = document.getElementById('pack-cards');
    const battleResult = document.getElementById('battle-result');
    const leaderboard = document.getElementById('leaderboard');
    const marketplacesBox = document.getElementById('marketplaces-box');
    const marketplacesLinks = document.getElementById('marketplaces-links');
    const telegramOpenLink = document.getElementById('telegram-open-link');
    const telegramStatus = document.getElementById('telegram-status');
    const telegramShareBtn = document.getElementById('telegram-share-btn');

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
    }

    function renderLeaderBoard(items) {
      if (!items.length) {
        leaderboard.innerHTML = '<div class="leaderboard-item muted">Рейтинг появится после первых матчей.</div>';
        return;
      }
      leaderboard.innerHTML = items.map((item, index) => `
        <div class="leaderboard-item">
          <div class="team-line"><strong>#${index + 1} ${shortAddress(item.wallet)}</strong><strong>${item.rating}</strong></div>
          <div class="tiny">Матчей: ${item.games_played} • Побед: ${item.ranked_wins} • Лучший домен: ${item.best_domain || '-'}</div>
        </div>
      `).join('');
    }

    function renderProfile() {
      walletBadge.textContent = state.wallet ? `Подключён: ${shortAddress(state.wallet)}` : 'Кошелёк не подключен';
      profileWallet.textContent = state.wallet ? shortAddress(state.wallet) : '-';
      profileDomain.textContent = state.selectedDomain ? `${state.selectedDomain}.ton` : '-';
      selectedDomainLabel.textContent = state.selectedDomain ? `Домен: ${state.selectedDomain}.ton` : 'Домен не выбран';

      if (state.playerProfile) {
        profileRating.textContent = state.playerProfile.rating;
        profileGames.textContent = state.playerProfile.games_played;
      } else {
        profileRating.textContent = '1000';
        profileGames.textContent = '0';
      }
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
      document.getElementById('create-room-btn').disabled = !(connected && hasCards);
      document.getElementById('join-room-btn').disabled = !(connected && hasCards);
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
          <p>Паттерны: ${domain.patterns.length ? domain.patterns.join(', ') : 'базовый 10K домен'}</p>
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
      renderDomains(state.domains);
      renderProfile();
      updateButtons();
      switchView('pack');
      setStatus(document.getElementById('pack-status'), `Выбран домен ${domain}.ton. Теперь можно открыть колоду.`, 'success');
    };

    function renderPack(cards, total) {
      packCards.innerHTML = cards.map((card) => `
        <article class="game-card">
          <div class="tiny">${card.rarity}</div>
          <h3>${card.title}</h3>
          <p>${card.domain}.ton • слот ${card.slot}</p>
          <div class="team-line"><span>Атака</span><strong>${card.attack}</strong></div>
          <div class="team-line"><span>Защита</span><strong>${card.defense}</strong></div>
          <div class="team-line"><span>Сила</span><strong>${card.score}</strong></div>
          <p>${card.ability}</p>
        </article>
      `).join('');
      packScoreLabel.textContent = `Сумма колоды: ${total}`;
    }

    function renderBattleResult(result) {
      battleResult.style.display = 'block';
      if (result.kind === 'team') {
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
        `;
      } else {
        const ratingLine = result.rating_after !== undefined
          ? `<div class="team-line"><span>Рейтинг</span><strong>${result.rating_before} → ${result.rating_after}</strong></div>`
          : '';
        battleResult.innerHTML = `
          <h3>${result.mode_title}</h3>
          <div class="team-line"><span>Твой домен</span><strong>${result.player_domain}.ton</strong></div>
          <div class="team-line"><span>Соперник</span><strong>${result.opponent_domain}.ton</strong></div>
          <div class="team-line"><span>Твои очки</span><strong>${result.player_score}</strong></div>
          <div class="team-line"><span>Очки соперника</span><strong>${result.opponent_score}</strong></div>
          ${ratingLine}
          <p class="muted">Результат: ${result.result_label}</p>
        `;
      }
      telegramShareBtn.disabled = false;
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

    async function loadProfile() {
      if (!state.wallet) {
        state.playerProfile = null;
        renderProfile();
        return;
      }
      const profile = await api(`/api/player/${encodeURIComponent(state.wallet)}`);
      state.playerProfile = profile.player;
      renderProfile();
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
      } catch (error) {
        setStatus(walletStatus, error.message, 'error');
      }
    }

    async function openPack() {
      setStatus(document.getElementById('pack-status'), 'Распаковываем 5 карточек из домена...', 'warning');
      try {
        const data = await api('/api/pack', {
          method: 'POST',
          body: {wallet: state.wallet, domain: state.selectedDomain}
        });
        state.cards = data.cards;
        renderPack(data.cards, data.total_score);
        setStatus(document.getElementById('pack-status'), `Колода готова. ${data.domain}.ton даёт ${data.total_score} очков силы.`, 'success');
        updateButtons();
      } catch (error) {
        setStatus(document.getElementById('pack-status'), error.message, 'error');
      }
    }

    async function playMatch(mode) {
      try {
        const data = await api(`/api/match/${mode}`, {
          method: 'POST',
          body: {wallet: state.wallet, domain: state.selectedDomain}
        });
        state.lastResult = data.result;
        renderBattleResult(data.result);
        if (data.player) {
          state.playerProfile = data.player;
          renderProfile();
        }
        await loadLeaderboard();
      } catch (error) {
        battleResult.style.display = 'block';
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
      telegramStatus.textContent = 'Приложение открыто внутри Telegram. После матча можно отправить результат боту.';
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
          renderDomains([]);
        }
        previousWallet = state.wallet;
        updateButtons();
        if (state.wallet) {
          setStatus(walletStatus, `Кошелёк подключен: ${state.wallet}`, 'success');
          await loadProfile();
        } else {
          state.domainsChecked = false;
          state.domains = [];
          state.selectedDomain = null;
          state.cards = [];
          renderDomains([]);
          renderProfile();
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
    document.getElementById('open-pack-btn').addEventListener('click', openPack);
    document.getElementById('continue-to-modes-btn').addEventListener('click', () => switchView('modes'));
    document.getElementById('play-ranked-btn').addEventListener('click', () => playMatch('ranked'));
    document.getElementById('play-casual-btn').addEventListener('click', () => playMatch('casual'));
    document.getElementById('show-team-btn').addEventListener('click', () => {
      document.getElementById('team-panel').style.display = 'block';
      setStatus(document.getElementById('team-status'), 'Создай командную комнату или войди по коду.', 'warning');
    });
    document.getElementById('create-room-btn').addEventListener('click', createRoom);
    document.getElementById('join-room-btn').addEventListener('click', joinRoom);
    document.getElementById('refresh-room-btn').addEventListener('click', refreshRoom);
    document.getElementById('start-room-btn').addEventListener('click', startRoom);
    telegramShareBtn.addEventListener('click', shareTelegram);

    initTelegram();
    initTonConnect().catch((error) => {
      setStatus(walletStatus, `Ошибка TonConnect: ${error.message}`, 'error');
    });
    loadLeaderboard();
    renderProfile();
    updateButtons();
  </script>
</body>
</html>
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


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
            '''
        )
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
    patterns = detect_10k_patterns(domain)
    for pattern in patterns:
        bonus = PATTERN_BONUSES.get(pattern, {'attack': 0, 'defense': 0})
        attack += bonus['attack']
        defense += bonus['defense']

    score = attack + defense
    tier = 'Tier-3'
    for tier_config in TIERS:
        if score >= tier_config['min_score']:
            tier = tier_config['name']
            break

    return {
        'domain': domain,
        'attack': attack,
        'defense': defense,
        'patterns': patterns,
        'tier': tier,
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
        attack = max(1, base['attack'] + rng.randint(-6, 12) + slot)
        defense = max(1, base['defense'] + rng.randint(-4, 10))
        score = attack + defense
        cards.append(
            {
                'slot': slot,
                'title': CARD_TITLES[(slot + int(domain[-1])) % len(CARD_TITLES)],
                'ability': CARD_ABILITIES[(slot + int(domain[0])) % len(CARD_ABILITIES)],
                'domain': domain,
                'attack': attack,
                'defense': defense,
                'score': score,
                'rarity': card_rarity(score),
                'patterns': base['patterns'],
            }
        )
    return cards


def deck_score(cards):
    return sum(card['score'] for card in cards)


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


def ensure_player(wallet, best_domain=None):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT * FROM players WHERE wallet = ?', (wallet,)).fetchone()
        if row is None:
            conn.execute(
                '''
                INSERT INTO players (wallet, rating, games_played, ranked_wins, ranked_losses, best_domain, updated_at)
                VALUES (?, ?, 0, 0, 0, ?, ?)
                ''',
                (wallet, BASE_RATING, best_domain, now_iso()),
            )
            conn.commit()
            row = conn.execute('SELECT * FROM players WHERE wallet = ?', (wallet,)).fetchone()
        elif best_domain and (row['best_domain'] is None or score_from_domain(best_domain)['score'] > score_from_domain(row['best_domain'])['score']):
            conn.execute('UPDATE players SET best_domain = ?, updated_at = ? WHERE wallet = ?', (best_domain, now_iso(), wallet))
            conn.commit()
            row = conn.execute('SELECT * FROM players WHERE wallet = ?', (wallet,)).fetchone()
    return dict(row)


def get_player(wallet):
    player = ensure_player(wallet)
    return {
        'wallet': player['wallet'],
        'rating': player['rating'],
        'games_played': player['games_played'],
        'ranked_wins': player['ranked_wins'],
        'ranked_losses': player['ranked_losses'],
        'best_domain': player['best_domain'],
    }


def choose_opponent_domain(wallet, domain, mode):
    seed = hashlib.sha256(f'{wallet}:{domain}:{mode}'.encode()).hexdigest()
    rng = random.Random(seed)
    while True:
        opponent = f'{rng.randint(0, 9999):04d}'
        if opponent != domain:
            return opponent


def matchup_result(player_domain, wallet, mode):
    player_cards = generate_pack(player_domain, wallet)
    opponent_domain = choose_opponent_domain(wallet, player_domain, mode)
    opponent_cards = generate_pack(opponent_domain, f'cpu:{mode}:{wallet}')
    player_total = deck_score(player_cards)
    opponent_total = deck_score(opponent_cards)
    if player_total > opponent_total:
        result = 'win'
    elif player_total < opponent_total:
        result = 'loss'
    else:
        result = 'draw'
    return {
        'player_cards': player_cards,
        'opponent_cards': opponent_cards,
        'player_score': player_total,
        'opponent_score': opponent_total,
        'opponent_domain': opponent_domain,
        'result': result,
    }


def apply_ranked_result(wallet, domain, match):
    player = ensure_player(wallet, best_domain=domain)
    rating_before = player['rating']
    opponent_rating = BASE_RATING + min(450, max(-250, (match['opponent_score'] - match['player_score']) * 3))
    expected = 1 / (1 + 10 ** ((opponent_rating - rating_before) / 400))
    actual = 1.0 if match['result'] == 'win' else 0.0 if match['result'] == 'loss' else 0.5
    delta = round(RATING_K_FACTOR * (actual - expected))
    rating_after = max(100, rating_before + delta)

    with closing(get_db()) as conn:
        conn.execute(
            '''
            UPDATE players
            SET rating = ?, games_played = games_played + 1,
                ranked_wins = ranked_wins + ?,
                ranked_losses = ranked_losses + ?,
                best_domain = COALESCE(best_domain, ?),
                updated_at = ?
            WHERE wallet = ?
            ''',
            (
                rating_after,
                1 if match['result'] == 'win' else 0,
                1 if match['result'] == 'loss' else 0,
                domain,
                now_iso(),
                wallet,
            ),
        )
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
                match['opponent_domain'],
                match['result'],
                rating_before,
                rating_after,
                match['player_score'],
                match['opponent_score'],
                now_iso(),
            ),
        )
        conn.commit()

    return get_player(wallet), rating_before, rating_after


def build_match_response(mode, wallet, domain):
    match = matchup_result(domain, wallet, mode)
    result_labels = {
        'win': 'Победа',
        'loss': 'Поражение',
        'draw': 'Ничья',
    }

    payload = {
        'kind': 'solo',
        'mode_title': 'Рейтинговый матч' if mode == 'ranked' else 'Обычный матч',
        'player_domain': domain,
        'opponent_domain': match['opponent_domain'],
        'player_score': match['player_score'],
        'opponent_score': match['opponent_score'],
        'result_label': result_labels[match['result']],
    }

    player = get_player(wallet)
    if mode == 'ranked':
        player, rating_before, rating_after = apply_ranked_result(wallet, domain, match)
        payload['rating_before'] = rating_before
        payload['rating_after'] = rating_after

    return {'result': payload, 'player': player}


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


def telegram_welcome_markup():
    if not TG_WEBAPP_URL:
        return None
    return {
        'keyboard': [[{'text': 'Open tondomaingame', 'web_app': {'url': TG_WEBAPP_URL}}]],
        'resize_keyboard': True,
    }


def handle_telegram_message(message):
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if not chat_id:
        return

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
    ensure_player(wallet, domain)
    return jsonify({'wallet': wallet, 'domain': domain, 'cards': cards, 'total_score': total})


@app.route('/api/match/<mode>', methods=['POST'])
def api_match(mode):
    if mode not in {'ranked', 'casual'}:
        return json_error('Неизвестный режим.', 404)

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

    return jsonify(build_match_response(mode, wallet, domain))


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
    if message:
        try:
            handle_telegram_message(message)
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
