/**
 * App — Root component with navigation and routing.
 */

import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import RecoveryQueue from './pages/RecoveryQueue';
import MetricsPage from './pages/Metrics';
import ExplainPage from './pages/Explain';
import SimulatePage from './pages/Simulate';
import { LayoutList, BarChart3, Network, PlayCircle } from 'lucide-react';

const queryClient = new QueryClient();

function AppLayout() {
  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="app-header__brand">
          <div className="app-header__logo">R</div>
          <div>
            <div className="app-header__title">RecoverIQ</div>
            <div className="app-header__subtitle">AI Revenue Recovery</div>
          </div>
        </div>
        <nav className="app-nav">
          <NavLink
            to="/queue"
            className={({ isActive }) =>
              `app-nav__link ${isActive ? 'app-nav__link--active' : ''}`
            }
          >
            <LayoutList size={16} />
            Queue
          </NavLink>
          <NavLink
            to="/metrics"
            className={({ isActive }) =>
              `app-nav__link ${isActive ? 'app-nav__link--active' : ''}`
            }
          >
            <BarChart3 size={16} />
            Metrics
          </NavLink>
          <NavLink
            to="/explain"
            className={({ isActive }) =>
              `app-nav__link ${isActive ? 'app-nav__link--active' : ''}`
            }
          >
            <Network size={16} />
            Explain
          </NavLink>
          <NavLink
            to="/simulate"
            className={({ isActive }) =>
              `app-nav__link ${isActive ? 'app-nav__link--active' : ''}`
            }
          >
            <PlayCircle size={16} />
            Simulate
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/queue" element={<RecoveryQueue />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/explain" element={<ExplainPage />} />
          <Route path="/simulate" element={<SimulatePage />} />
          <Route path="*" element={<Navigate to="/queue" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppLayout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
