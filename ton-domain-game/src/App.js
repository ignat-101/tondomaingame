import React, { useState, useEffect } from 'react';
import './App.css';

function App() {
  const [user, setUser] = useState(null);
  const [cards, setCards] = useState([]);
  const [currentView, setCurrentView] = useState('home');

  useEffect(() => {
    // Initialize Telegram Web App
    if (window.Telegram && window.Telegram.WebApp) {
      const tg = window.Telegram.WebApp;
      tg.ready();
      setUser(tg.initDataUnsafe?.user);
    }
  }, []);

  const openPack = () => {
    const newCards = [];
    for (let i = 0; i < 5; i++) {
      const domain = generateRandomDomain();
      const stats = calculateStats(domain);
      newCards.push({ domain, ...stats });
    }
    setCards(newCards);
    setCurrentView('pack');
  };

  const generateRandomDomain = () => {
    const num = Math.floor(Math.random() * 10000);
    return num.toString().padStart(4, '0');
  };

  const calculateStats = (domain) => {
    const digits = domain.split('').map(Number);
    let attack = digits.reduce((a, b) => a + b, 0);
    let defense = digits.reduce((a, b) => a * b, 1);
    let rarity = 'Common';

    // Simple patterns
    if (domain === domain.split('').reverse().join('')) {
      attack += 20; // Mirror
      rarity = 'Rare';
    }
    if (digits[0] < digits[1] && digits[1] < digits[2] && digits[2] < digits[3]) {
      defense += 15; // Stairs up
      rarity = 'Epic';
    }
    if (digits.every(d => d === digits[0])) {
      attack += 50; // All same
      rarity = 'Legendary';
    }

    // Tier based on score
    const score = attack + defense;
    if (score > 100) rarity = 'Tier-0';
    else if (score > 80) rarity = 'Tier-1';
    else if (score > 60) rarity = 'Tier-2';
    else rarity = 'Tier-3';

    return { attack, defense, rarity };
  };

  const viewDomainInfo = (domain) => {
    window.open(`https://10kclub.com/domain/${domain}.ton`, '_blank');
  };

  return (
    <div className="app">
      <header>
        <h1>TON Domain Game</h1>
        {user && <p>Welcome, {user.first_name}!</p>}
      </header>
      <main>
        {currentView === 'home' && (
          <div>
            <button onClick={openPack}>Open Pack</button>
            <button onClick={() => setCurrentView('battle')}>Battle</button>
            <button onClick={() => setCurrentView('betting')}>Betting</button>
          </div>
        )}
        {currentView === 'pack' && (
          <div className="pack">
            <h2>Your Cards</h2>
            <div className="cards">
              {cards.map((card, index) => (
                <Card key={index} card={card} onClick={() => viewDomainInfo(card.domain)} />
              ))}
            </div>
            <button onClick={() => setCurrentView('home')}>Back</button>
          </div>
        )}
        {currentView === 'battle' && <Battle cards={cards} onBack={() => setCurrentView('home')} />}
        {currentView === 'betting' && <Betting onBack={() => setCurrentView('home')} />}
      </main>
    </div>
  );
}

function Card({ card, onClick }) {
  return (
    <div className="card" onClick={onClick}>
      <h3>{card.domain}.ton</h3>
      <p>Rarity: {card.rarity}</p>
      <p>Attack: {card.attack}</p>
      <p>Defense: {card.defense}</p>
    </div>
  );
}

function Battle({ cards, onBack }) {
  const [opponentCards] = useState([
    { domain: '1111', attack: 40, defense: 40, rarity: 'Tier-0' },
    { domain: '2222', attack: 35, defense: 35, rarity: 'Tier-1' },
  ]);
  const [result, setResult] = useState('');

  const battle = () => {
    const playerScore = cards.reduce((sum, c) => sum + c.attack + c.defense, 0);
    const opponentScore = opponentCards.reduce((sum, c) => sum + c.attack + c.defense, 0);
    setResult(playerScore > opponentScore ? 'You Win!' : 'You Lose!');
  };

  return (
    <div>
      <h2>Battle</h2>
      <div className="battle-field">
        <div>
          <h3>Your Team</h3>
          {cards.map((c, i) => <Card key={i} card={c} />)}
        </div>
        <div>
          <h3>Opponent</h3>
          {opponentCards.map((c, i) => <Card key={i} card={c} />)}
        </div>
      </div>
      <button onClick={battle}>Fight!</button>
      <p>{result}</p>
      <button onClick={onBack}>Back</button>
    </div>
  );
}

function Betting({ onBack }) {
  const [bet, setBet] = useState(0);
  const [result, setResult] = useState('');

  const placeBet = () => {
    const win = Math.random() > 0.5;
    setResult(win ? `You won ${bet * 2} TON!` : 'You lost!');
  };

  return (
    <div>
      <h2>Betting</h2>
      <input type="number" value={bet} onChange={e => setBet(Number(e.target.value))} placeholder="Bet amount in TON" />
      <button onClick={placeBet}>Place Bet</button>
      <p>{result}</p>
      <button onClick={onBack}>Back</button>
    </div>
  );
}

export default App;