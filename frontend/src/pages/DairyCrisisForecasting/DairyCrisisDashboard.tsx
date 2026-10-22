import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { FarmLevelDashboard } from './FarmLevelDashboard';
import './dairyCrisis.css';
import './farmIntelligence.css';

export const DairyCrisisDashboard: React.FC = () => {
  const { pathname } = useLocation();

  // Keep old farm/national and crisis-forecasting bookmarks working.
  if (pathname !== '/risk-management') return <Navigate to="/risk-management" replace />;

  return (
    <div className="dairy-crisis-workspace-only">
      <FarmLevelDashboard />
    </div>
  );
};

export default DairyCrisisDashboard;
