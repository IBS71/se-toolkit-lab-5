import React, { useState } from 'react';
import Dashboard from './Dashboard';

const App: React.FC = () => {
  const [view, setView] = useState<'items' | 'dashboard'>('items');
  return (
    <div>
      <nav style={{ padding: '15px', background: '#eee', gap: '10px', display: 'flex' }}>
        <button onClick={() => setView('items')}>Items Page</button>
        <button onClick={() => setView('dashboard')}>Dashboard</button>
      </nav>
      {view === 'dashboard' ? <Dashboard /> : <div style={{ padding: '20px' }}>Items Page Content</div>}
    </div>
  );
};
export default App;
