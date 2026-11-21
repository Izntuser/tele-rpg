import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import { Providers } from './app/providers';
import { AuthGate } from './features/auth/AuthGate';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Providers>
      <AuthGate>
        <App />
      </AuthGate>
    </Providers>
  </StrictMode>,
);
