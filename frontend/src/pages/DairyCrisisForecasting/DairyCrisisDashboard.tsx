import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useUser } from '../../context/UserContext';
import { NLDBNationalDashboard } from './NLDBNationalDashboard';
import { FarmLevelDashboard } from './FarmLevelDashboard';
import './dairyCrisis.css';

export const DairyCrisisDashboard: React.FC = () => {
  const { pathname } = useLocation();
  const { role } = useUser();
  const [selectedFarmId, setSelectedFarmId] = useState<string>('farm-1');

  // Determine active view mode based on URL route or role
  let isNationalView = false;
  if (pathname.includes('/nldb')) {
    isNationalView = true;
  } else if (pathname.includes('/farm')) {
    isNationalView = false;
  } else {
    // Default fallback based on role if navigating directly to /risk-management
    isNationalView = role === 'nldb_management';
  }

  const handleSelectFarm = (farmId: string) => {
    setSelectedFarmId(farmId);
  };

  return (
    <div className="dairy-crisis-workspace-only">
      {isNationalView ? (
        <NLDBNationalDashboard onSelectFarm={handleSelectFarm} />
      ) : (
        <FarmLevelDashboard
          selectedFarmId={selectedFarmId}
          onSelectFarmId={(id) => setSelectedFarmId(id)}
        />
      )}
    </div>
  );
};

export default DairyCrisisDashboard;
