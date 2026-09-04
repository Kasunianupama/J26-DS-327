import React from 'react';

interface SriLankaHeatmapProps {
  selectedRegion?: string;
  onSelectRegion?: (region: string) => void;
}

export const SriLankaHeatmap: React.FC<SriLankaHeatmapProps> = ({ selectedRegion, onSelectRegion }) => {
  // Clean, stylized 9-province vector shapes
  const regions = [
    {
      id: 'Northern',
      name: 'Northern',
      color: '#FBBF24', // Medium Risk (Yellow)
      score: 52,
      path: 'M 110 20 L 140 15 L 155 65 L 110 70 L 95 40 Z',
      labelX: 125,
      labelY: 45,
    },
    {
      id: 'North Central',
      name: 'North Central',
      color: '#EF4444', // Critical Risk (Red)
      score: 68,
      path: 'M 110 70 L 160 65 L 180 120 L 125 155 L 110 110 Z',
      labelX: 140,
      labelY: 105,
    },
    {
      id: 'North Western',
      name: 'North Western',
      color: '#EF4444', // Critical Risk (Red)
      score: 71,
      path: 'M 70 120 L 110 110 L 125 155 L 105 190 L 70 170 L 60 140 Z',
      labelX: 85,
      labelY: 145,
    },
    {
      id: 'Central',
      name: 'Central',
      color: '#F97316', // High Risk (Orange)
      score: 55,
      path: 'M 125 155 L 180 120 L 190 170 L 145 200 L 120 180 Z',
      labelX: 155,
      labelY: 160,
    },
    {
      id: 'Eastern',
      name: 'Eastern',
      color: '#10B981', // Low Risk (Green)
      score: 29,
      path: 'M 180 120 L 220 130 L 210 210 L 190 170 Z',
      labelX: 200,
      labelY: 155,
    },
    {
      id: 'Western',
      name: 'Western',
      color: '#F97316', // High Risk (Orange)
      score: 42,
      path: 'M 70 170 L 105 190 L 120 230 L 75 220 L 65 190 Z',
      labelX: 85,
      labelY: 200,
    },
    {
      id: 'Sabaragamuwa',
      name: 'Sabaragamuwa',
      color: '#FBBF24', // Medium Risk (Yellow)
      score: 46,
      path: 'M 105 190 L 145 200 L 165 240 L 120 230 Z',
      labelX: 130,
      labelY: 215,
    },
    {
      id: 'Uva',
      name: 'Uva',
      color: '#FBBF24', // Medium Risk (Yellow)
      score: 48,
      path: 'M 145 200 L 190 170 L 210 210 L 165 240 Z',
      labelX: 175,
      labelY: 205,
    },
    {
      id: 'Southern',
      name: 'Southern',
      color: '#10B981', // Low Risk (Green)
      score: 34,
      path: 'M 75 220 L 165 240 L 180 270 L 100 275 Z',
      labelX: 130,
      labelY: 255,
    },
  ];

  return (
    <div className="heatmap-side-layout">
      {/* Map Column Left */}
      <div className="heatmap-svg-column">
        <svg viewBox="0 0 260 295" className="heatmap-clean-svg" aria-label="Sri Lanka Risk Heatmap">
          {regions.map((reg) => {
            const isSelected = selectedRegion === reg.id;
            return (
              <g
                key={reg.id}
                className={`heatmap-region ${isSelected ? 'selected' : ''}`}
                onClick={() => onSelectRegion && onSelectRegion(reg.id)}
                style={{ cursor: 'pointer' }}
              >
                <path
                  d={reg.path}
                  fill={reg.color}
                  stroke="#FFFFFF"
                  strokeWidth={isSelected ? '2.5' : '1.5'}
                  opacity={isSelected ? 1 : 0.9}
                >
                  <title>{`${reg.name}: Risk Score ${reg.score}`}</title>
                </path>
                <text
                  x={reg.labelX}
                  y={reg.labelY}
                  fill="#FFFFFF"
                  fontSize="9.5"
                  fontWeight="bold"
                  textAnchor="middle"
                  style={{ pointerEvents: 'none', textShadow: '0px 1px 2px rgba(0,0,0,0.6)' }}
                >
                  {reg.name}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend Column Right (Completely to the side of the map with zero overlap) */}
      <div className="heatmap-legend-column">
        <div className="side-legend-card">
          <div className="legend-card-header font-bold">Risk Level</div>
          <div className="side-legend-item">
            <span className="legend-box bg-critical"></span>
            <span>Critical (76 - 100)</span>
          </div>
          <div className="side-legend-item">
            <span className="legend-box bg-high"></span>
            <span>High (51 - 75)</span>
          </div>
          <div className="side-legend-item">
            <span className="legend-box bg-medium"></span>
            <span>Medium (26 - 50)</span>
          </div>
          <div className="side-legend-item">
            <span className="legend-box bg-low"></span>
            <span>Low (0 - 25)</span>
          </div>
        </div>
      </div>
    </div>
  );
};
