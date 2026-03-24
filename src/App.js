import React, { useState, useEffect } from 'react';
import { TonConnectButton, useTonConnectUI } from '@tonconnect/ui-react';
import './App.css';

function App() {
  const [user, setUser] = useState(null);
  const [cards, setCards] = useState([]);
  const [currentView, setCurrentView] = useState('connect');
  const [domains, setDomains] = useState([]);
  const [selectedDomain, setSelectedDomain] = useState('');
  const [tonConnectUI] = useTonConnectUI();

  useEffect(() => {
    // Initialize Telegram Web App
    if (window.Telegram && window.Telegram.WebApp) {
      const tg = window.Telegram.WebApp;
      tg.ready();
      setUser(tg.initDataUnsafe?.user);
    }

    // Check TonConnect status
    if (tonConnectUI?.connected) {
      fetchDomains();
    }
  }, [tonConnectUI?.connected]);

  const fetchDomains = async () => {
    if (!tonConnectUI?.account?.address) return;
    try {
      const response = await fetch('/api/nft-domains', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet_address: tonConnectUI.account.address })
      });
      const data = await response.json();
      if (data.domains && data.domains.length > 0) {
        setDomains(data.domains);
        setSelectedDomain(data.domains[0]);
        fetchCards(data.domains[0]);
      }
    } catch (error) {
      console.error('Error fetching domains:', error);
    }
  };

  const fetchCards = async (domain) => {
    try {
      const response = await fetch('/api/open-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain })
      });
      const data = await response.json();
      setCards(data.cards);
      setCurrentView('pack');
    } catch (error) {
      console.error('Error fetching cards:', error);
    }
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
        {currentView === 'connect' && (
          <div className="connect">
            <h2>Connect Your Wallet</h2>
            <TonConnectButton />
          </div>
        )}
        {currentView === 'pack' && (
          <div className="pack">
            <h2>Your Cards from {selectedDomain}.ton</h2>
            <div className="cards">
              {cards.map((card, index) => (
                <Card key={index} card={card} onClick={() => viewDomainInfo(card.domain)} />
              ))}
            </div>
            <button onClick={() => setCurrentView('modes')}>Continue to Game Modes</button>
          </div>
        )}
        {currentView === 'modes' && (
          <div className="modes">
            <h2>Choose Game Mode</h2>
            <button onClick={() => setCurrentView('solo')}>Solo</button>
            <button onClick={() => setCurrentView('team')}>Team</button>
            <button onClick={() => setCurrentView('pvp')}>PvP</button>
          </div>
        )}
        {currentView === 'solo' && <SoloMode cards={cards} onBack={() => setCurrentView('modes')} />}
        {currentView === 'team' && <TeamMode cards={cards} onBack={() => setCurrentView('modes')} />}
        {currentView === 'pvp' && <PvPMode cards={cards} onBack={() => setCurrentView('modes')} />}
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

function SoloMode({ cards, onBack }) {
  // Placeholder for solo gameplay
  return (
    <div>
      <h2>Solo Mode</h2>
      <p>Play against AI with your cards.</p>
      <div className="cards">
        {cards.map((c, i) => <Card key={i} card={c} />)}
      </div>
      <button onClick={onBack}>Back</button>
    </div>
  );
}

function TeamMode({ cards, onBack }) {
  // Placeholder for team gameplay
  return (
    <div>
      <h2>Team Mode</h2>
      <p>Team up with friends.</p>
      <div className="cards">
        {cards.map((c, i) => <Card key={i} card={c} />)}
      </div>
      <button onClick={onBack}>Back</button>
    </div>
  );
}

function PvPMode({ cards, onBack }) {
  // Placeholder for PvP gameplay
  return (
    <div>
      <h2>PvP Mode</h2>
      <p>Battle against other players.</p>
      <div className="cards">
        {cards.map((c, i) => <Card key={i} card={c} />)}
      </div>
      <button onClick={onBack}>Back</button>
    </div>
  );
}

export default App;