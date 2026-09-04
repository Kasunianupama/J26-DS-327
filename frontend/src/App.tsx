import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom';

import { Layout } from './components/layout/Layout';
import Assistant from './pages/Assistant';
import Placeholder from './pages/Placeholder';
import PredictiveIntelligence from './pages/PredictiveIntelligence';
import InterventionSimulator from './pages/InterventionSimulator';
import DairyCrisisDashboard from './pages/DairyCrisisForecasting/DairyCrisisDashboard';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/predictive" replace />} />
          <Route path="/herd" element={<Navigate to="/predictive" replace />} />

          <Route
            path="/intervention-simulator"
            element={<InterventionSimulator />}
          />
          <Route
            path="/interventions"
            element={<InterventionSimulator />}
          />

          <Route
            path="/predictive/*"
            element={<PredictiveIntelligence />}
          />

          <Route
            path="/risk-management/*"
            element={<DairyCrisisDashboard />}
          />
          <Route
            path="/crisis-forecasting/*"
            element={<DairyCrisisDashboard />}
          />

          <Route path="/assistant" element={<Assistant />} />
          <Route
            path="/risks"
            element={<Placeholder title="Risk Intelligence" />}
          />
          <Route
            path="/reports"
            element={<Placeholder title="Reports" />}
          />
          <Route
            path="/settings"
            element={<Placeholder title="Settings" />}
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}