from flask import Flask, request, jsonify, render_template_string
import random
import re
import requests
import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()  # Загружаем .env

from config import (
    ATTACK_BASE, DEFENSE_BASE, PATTERN_BONUSES, TIERS,
    TONAPI_BASE_URL, TONAPI_KEY, DNS_TON_BASE_URL,
    HOST, PORT, DEBUG, SSL_CERT_PATH, SSL_KEY_PATH, RATE_LIMIT,
    TG_WEBAPP_URL
)

app = Flask(__name__)

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT]
)

# Перезапись из env
if os.getenv('TONAPI_KEY'):
    TONAPI_KEY = os.getenv('TONAPI_KEY')
if os.getenv('TG_WEBAPP_URL'):
    TG_WEBAPP_URL = os.getenv('TG_WEBAPP_URL')


TONCONNECT_MANIFEST = {
    'name': 'TON 10K Club Domain Game',
    'description': 'A game where TON DNS domains become trading cards',
    'icons': ['https://10kclub.com/favicon.ico'],
    'developer': {
        'name': 'TON 10K Club',
        'url': 'https://10kclub.com',
    },
    'redirect': {
        'success': '/',
        'cancel': '/',
    },
}


def detect_10k_patterns(domain: str):
    """Определяет 10K Club паттерны для домена в формате "0000"."""
    d = [int(x) for x in domain]
    patterns = []

    # mirror (палиндром)
    if domain == domain[::-1]:
        patterns.append('mirror')

    # all same digits
    if len(set(domain)) == 1:
        patterns.append('all_same')

    # stairs up / down
    if d[0] < d[1] < d[2] < d[3]:
        patterns.append('stairs_up')
    if d[0] > d[1] > d[2] > d[3]:
        patterns.append('stairs_down')

    # double repeat (AABB or ABBA и т.п.)
    if d[0] == d[1] and d[2] == d[3] and d[0] != d[2]:
        patterns.append('double_repeat')
    if d[0] == d[3] and d[1] == d[2] and d[0] != d[1]:
        patterns.append('ambigram')

    # special 10k-club категории
    if int(domain) < 100:
        patterns.append('first_100')
    if domain.startswith('0') and domain.endswith('0'):
        patterns.append('zero_frames')

    return patterns


def score_from_domain(domain: str):
    """Считает базовые attack/defense + бонусы по паттернам + tier."""
    # Почему 10k patterns: https://10kclub.com/ (vendor logic)
    # Ключевая задача: сделать расчёт логичным, сбалансированным и учитывающим уникальность.

    # Базовые параметры (можно настроить выше)
    attack = sum(int(d) for d in domain) + ATTACK_BASE
    defense = (1 if domain[0] == '0' else 0) + DEFENSE_BASE  # защита зависит от нулей

    patterns = detect_10k_patterns(domain)
    for p in patterns:
        bonus = PATTERN_BONUSES.get(p, {'attack': 0, 'defense': 0})
        attack += bonus['attack']
        defense += bonus['defense']

    # Редкость
    score = attack + defense
    tier = 'Tier-3'
    for t in TIERS:
        if score >= t['min_score']:
            tier = t['name']
            break

    return {
        'domain': domain,
        'attack': attack,
        'defense': defense,
        'patterns': patterns,
        'tier': tier,
        'score': score,
    }


def random_cards_for_domain(domain: str, count: int = 5):
    """Генерирует count игровых карт для домена.

    Поскольку домен жестко берется из NFT в кошельке, мы сохраняем его как основу.
    Карты отличаются дополнительным модификатором (случайным), чтобы не было одинаковых.
    """
    result = []
    base = score_from_domain(domain)

    for i in range(count):
        modifier = random.randint(-5, 15)
        # можно управлять диапазоном силы здесь
        card_attack = max(1, base['attack'] + modifier)
        card_defense = max(1, base['defense'] + modifier // 2)

        result.append({
            'id': f'{domain}-{i}',
            'domain': domain,
            'attack': card_attack,
            'defense': card_defense,
            'tier': base['tier'],
            'patterns': base['patterns'],
            'score': card_attack + card_defense,
        })

    return result


@app.route('/')
def index():
    # Простой UI, локально / на хосте
    return render_template_string('''
<!doctype html>
<html lang="ru">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#000000">
  <meta name="description" content="TON 10K Club Domain Trading Card Game">
  <meta property="og:title" content="TON 10K Club Game">
  <meta property="og:description" content="Play with your TON DNS domains as trading cards">
  <meta property="og:image" content="https://10kclub.com/favicon.ico">
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body { background: #020810; color: #c4ffd8; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .layout { max-width: 1100px; margin: 0 auto; padding: 18px; }
    .topbar { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid rgba(0,255,0,.2); }
    .logo { color: #54ff9f; font-size: 2rem; font-weight: bold; text-shadow: 0 0 12px rgba(0,255,170, .4); }
    .menu a { color: #8afdfb; text-decoration: none; margin-right: 14px; }
    .menu a:hover { color: #fff; }
    .card { background: linear-gradient(135deg, rgba(0,43,62,0.5), rgba(0,66,100,0.5)); border: 1px solid rgba(0,255,128,.8); border-radius: 10px; padding: 14px; margin: 10px; box-shadow: 0 0 20px rgba(0,255,145,.25); }
    .btn-ghost {
      background: rgba(0, 170, 120, 0.1); color: #9bfdb9; border: 1px solid rgba(0,255,120,0.4); border-radius: 8px; padding: 8px 14px; cursor:pointer;
    }
    .btn-ghost:hover { background: rgba(0,255,145,0.16); }
    input { background: rgba(0,0,0,0.4); color: #d5ffd2; border: 1px solid rgba(0,255,120,0.35); border-radius: 6px; padding: 7px; }
    #cards { display: flex; flex-wrap: wrap; gap: 10px; }
    .info { margin-top: 12px; font-size: 14px; }
    .panel { background: rgba(0,0,0,0.34); border: 1px solid rgba(0,255,170,0.3); padding: 12px; border-radius: 8px; margin-top: 12px; }
  </style>
  <script src="https://unpkg.com/tonconnect/dist/tonconnect.umd.min.js"></script>
</head>
<body>
  <h1>TON 10K Club Domain Game</h1>
  <p>Заполните кошелёк/домен (эмуляция): домен должен браться из NFT на кошельке.</p>

  <label>Wallet address: <input id="wallet" value="EQCP..." /></label><br/><br/>
  <label>Domain from NFT: <input id="nft_domain" value="1111" /></label> (будет перезаписываться при connect)<br/><br/>

  <div class="topbar">
    <div class="logo">10K Club TON Game</div>
    <div class="menu"><a href="https://10kclub.com" target="_blank">10kclub.com</a><a href="https://dns.ton.org" target="_blank">TON DNS</a></div>
  </div>

  <button class="btn-ghost" onclick="connectTonConnect()">Connect TonConnect</button>
  <button class="btn-ghost" onclick="connectWallet()">Connect Wallet (TonAPI)</button>
  <button class="btn-ghost" onclick="openPack()">Open 5 cards for domain</button>

  <div id="info" class="info"></div>
  <div id="cards"></div>

  <script>
    let tonConnect = null;
    let walletDomain = null;

    // Инициализация TonConnect
    function initTonConnect() {
      if (window.TonConnect) {
        tonConnect = new TonConnect({
          manifestUrl: window.location.origin + '/tonconnect-manifest.json'
        });

        // Восстановление сессии
        tonConnect.restoreConnection();

        // Обработчики событий
        tonConnect.onStatusChange((wallet) => {
          if (wallet) {
            document.getElementById('wallet').value = wallet.account.address;
            document.getElementById('info').innerHTML = '<b>Wallet connected:</b> ' + wallet.account.address;
          }
        });

        tonConnect.onDisconnect(() => {
          document.getElementById('wallet').value = '';
          document.getElementById('info').innerHTML = '<b>Wallet disconnected</b>';
        });
      }
    }

    // Полноценная connectWallet через TonConnect
    async function connectTonConnect(){
      if (!tonConnect) {
        alert('TonConnect не инициализирован');
        return;
      }

      try {
        const wallets = await tonConnect.getWallets();
        if (wallets.length === 0) {
          alert('No TON wallets found. Install TonKeeper or another TON wallet.');
          return;
        }

        await tonConnect.connect(wallets[0]);  // Подключаемся к первому доступному кошельку
        // После подключения сработает onStatusChange
      } catch (e) {
        alert('TonConnect error: ' + (e.message || e));
      }
    }

    // Альтернативный connect через TonAPI (для тестирования)
    function connectWallet(){
      const wallet = document.getElementById('wallet').value.trim();
      if (!wallet) {
        alert('Укажите wallet');
        return;
      }

      fetch('/api/nft-domains/' + wallet)
        .then(res => {
          if (!res.ok) { return res.json().then(err => { throw err; }); }
          return res.json();
        })
        .then(data => {
          const domain = data.domain;
          walletDomain = domain;
          document.getElementById('nft_domain').value = domain;
          document.getElementById('info').innerHTML = '<b>Connected:</b> ' + wallet + ', domain ' + domain + '.ton (exists: ' + data.domain_exists + ')';
          return fetch('/api/domain/' + domain);
        })
        .then(res => res.json())
        .then(data => {
          document.getElementById('cards').innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
        })
        .catch(err => {
          document.getElementById('info').innerHTML = '<b>Error:</b> ' + (err.error || JSON.stringify(err));
          console.error('connectWallet error', err);
        });
    }

    function openPack(){
      if (!walletDomain) {
        alert('Сначала подключите кошелёк и домен');
        return;
      }
      fetch('/api/open-pack/' + walletDomain)
        .then(res => res.json())
        .then(data => {
          const html = data.map(c =>
            '<div class="card">'
            + '<h3>'+c.domain+'.ton</h3>'
            + '<p>Attack: '+c.attack+'</p>'
            + '<p>Defense: '+c.defense+'</p>'
            + '<p>Tier: '+c.tier+'</p>'
            + '<p>Patterns: '+c.patterns.join(', ')+'</p>'
            + '<p><a href="https://10kclub.com/domain/'+c.domain+'.ton" target="_blank">10k info</a></p>'
            + '</div>'
          ).join('');
          document.getElementById('cards').innerHTML = html;
        });
    }

    // Инициализация при загрузке
    window.onload = function() {
      initTonConnect();

      // TG Mini App
      if (window.Telegram && window.Telegram.WebApp) {
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();
        console.log('TG WebApp initialized');
      }
    };
  </script>
  </script>
</body>
</html>
''')


@app.route('/tonconnect-manifest.json')
def tonconnect_manifest():
    return jsonify(TONCONNECT_MANIFEST)


@app.route('/api/check-domain/<domain>')
def api_check_domain(domain):
    """Проверяет, существует ли домен на dns.ton.org."""
    domain = domain.zfill(4)[:4] + '.ton'
    url = DNS_TON_BASE_URL.format(domain=domain)
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return jsonify({'exists': True, 'data': data})
        else:
            return jsonify({'exists': False, 'status': r.status_code})
    except requests.RequestException as e:
        return jsonify({'exists': False, 'error': str(e)}), 502


@app.route('/api/open-pack/<domain>')
def api_open_pack(domain):
    domain = domain.zfill(4)[:4]
    pack = random_cards_for_domain(domain, count=5)
    return jsonify(pack)


@app.route('/api/nft-domains/<wallet>')
def api_nft_domains(wallet):
    """Пробуем найти 4-значный domain из NFT на этом кошельке.

    Публичный API TonAPI (free tier) используется здесь как реальный метод.
    Для теста достаточно указать любой TON адрес с NFT, один из них должен
    содержать домен вида 0000.ton, 1111.ton и т. п.
    """
    # простой валидатор адреса
    if not wallet.startswith(('E', 'U', '0')) or len(wallet) < 20:
        return jsonify({'error': 'Invalid wallet address format'}), 400

    # Обратите внимание: для реального production ключ должен быть через env var
    tonapi_url = TONAPI_BASE_URL.format(wallet=wallet)
    headers = {}
    if TONAPI_KEY:
        headers['Authorization'] = f'Bearer {TONAPI_KEY}'

    try:
        r = requests.get(tonapi_url, timeout=8, headers=headers)
        r.raise_for_status()
        nfts = r.json().get('nfts', [])

        # Пытаемся найти 4-значный домен в названии или metadata
        domain_candidates = []
        for nft in nfts:
            name = nft.get('name', '') or nft.get('metadata', {}).get('name', '') or ''
            found = re.findall(r'\b(\d{4})\b', name)
            domain_candidates.extend(found)

            if not found:
                # иногда в uri или description
                txt = ' '.join([str(nft.get('description', '')), str(nft.get('uri', ''))])
                found = re.findall(r'\b(\d{4})\b', txt)
                domain_candidates.extend(found)

        domain_candidates = [d for d in domain_candidates if d]
        domain = domain_candidates[0] if domain_candidates else None

        if not domain:
            # Если не нашли, возвращаем пример (для отладки)
            return jsonify({'warning': 'No 4-digit domain found in NFT metadata', 'nfts_count': len(nfts), 'nfts': nfts[:5]}), 404

        # Проверяем, существует ли домен на dns.ton.org
        check_url = DNS_TON_BASE_URL.format(domain=domain + '.ton')
        try:
            check_r = requests.get(check_url, timeout=5)
            domain_exists = check_r.status_code == 200
        except:
            domain_exists = False

        return jsonify({'wallet': wallet, 'domain': domain, 'source': 'tonapi', 'domain_exists': domain_exists})

    except requests.RequestException as exc:
        return jsonify({'error': 'Failed to fetch NFT data from TON API', 'detail': str(exc)}), 502


if __name__ == '__main__':
    # Для локального тестирования
    if DEBUG:
        app.run(host=HOST, port=PORT, debug=DEBUG)
    else:
        # Production с SSL
        from gunicorn.app.wsgiapp import WSGIApplication
        WSGIApplication("%(prog)s [OPTIONS] [APP_MODULE]").run()

# Для gunicorn: gunicorn --bind 0.0.0.0:5000 --certfile cert.pem --keyfile key.pem app:app
