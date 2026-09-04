import React, { useState } from 'react';
import {
  SYNTETHIC_FARMS,
  REGIONAL_RISKS,
} from './syntheticData';
import { SriLankaHeatmap } from './SriLankaHeatmap';

interface NLDBNationalDashboardProps {
  onSelectFarm: (farmId: string) => void;
}

export const NLDBNationalDashboard: React.FC<NLDBNationalDashboardProps> = ({ onSelectFarm }) => {
  const [selectedRegionFilter, setSelectedRegionFilter] = useState<string>('All Regions');
  const [selectedRiskFilter, setSelectedRiskFilter] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Filter farms dynamically across all 14 farms
  const filteredFarms = SYNTETHIC_FARMS.filter((farm) => {
    const matchesRegion =
      selectedRegionFilter === 'All Regions' || farm.region === selectedRegionFilter;
    const matchesRisk =
      selectedRiskFilter === 'All' || farm.riskLevel === selectedRiskFilter;
    const matchesSearch =
      farm.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      farm.region.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesRegion && matchesRisk && matchesSearch;
  });

  return (
    <div className="dashboard-content animate-fade-in">
      {/* Top Header Bar */}
      <header className="dashboard-top-header">
        <div className="flex-align-center gap-2">
          <div className="nldb-cow-badge">🐄</div>
          <div>
            <h1 className="header-title">NLDB National Risk Dashboard</h1>
            <p className="header-subtitle">National Dairy Crisis Forecasting & Risk Engine</p>
          </div>
        </div>
        <div className="header-controls">
          <div className="control-field">
            <span className="control-label">Prediction Period</span>
            <select className="header-select font-medium">
              <option>May 25 – May 31, 2026 (Next 7 Days)</option>
              <option>June 01 – June 07, 2026</option>
            </select>
          </div>
          <button className="btn-export" type="button" onClick={() => alert('Exporting NLDB Risk Report PDF...')}>
            <span className="icon">⤓</span> Export Report
          </button>
          <div className="notification-bell" title="6 New Alerts">
            🔔 <span className="bell-badge">6</span>
          </div>
          <div className="user-profile-badge">
            <div className="user-avatar">👤</div>
            <span className="user-name">NLDB Administrator ▾</span>
          </div>
        </div>
      </header>

      {/* Row 1: KPI Cards with Sparklines */}
      <div className="kpi-grid-4">
        {/* Card 1: NDRI */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">NATIONAL DAIRY RISK INDEX (NDRI)</span>
            <button className="info-btn" title="Aggregated risk index across all NLDB farms">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="kpi-score-large text-danger">68</span>
            <span className="kpi-score-max">/ 100</span>
            <span className="badge badge-high-risk ml-auto">High Risk</span>
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 20" className="sparkline-svg">
              <path
                d="M 0 16 Q 30 14, 60 18 T 120 10 T 150 4"
                fill="none"
                stroke="#EF4444"
                strokeWidth="2"
              />
              <circle cx="150" cy="4" r="3" fill="#EF4444" />
            </svg>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-1">
            ↑ 12.5 from last 7 days
          </div>
        </div>

        {/* Card 2: Farms at High Risk */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">FARMS AT HIGH RISK</span>
            <button className="info-btn" title="Farms at High Risk level">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="kpi-val-number text-orange">1</span>
            <span className="kpi-sub-label font-medium">(7% of total farms)</span>
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 20" className="sparkline-svg">
              <path
                d="M 0 15 Q 30 17, 60 12 T 120 14 T 150 8"
                fill="none"
                stroke="#F97316"
                strokeWidth="2"
              />
              <circle cx="150" cy="8" r="3" fill="#F97316" />
            </svg>
          </div>
          <div className="kpi-subtext text-orange font-medium mt-1">
            ↑ 1 from last 7 days
          </div>
        </div>

        {/* Card 3: Farms at Critical Risk */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">FARMS AT CRITICAL RISK</span>
            <button className="info-btn" title="Farms at Critical Risk level">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="kpi-val-number text-danger">2</span>
            <span className="kpi-sub-label font-medium">(14% of total farms)</span>
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 20" className="sparkline-svg">
              <path
                d="M 0 18 Q 30 16, 60 14 T 120 10 T 150 5"
                fill="none"
                stroke="#EF4444"
                strokeWidth="2"
              />
              <circle cx="150" cy="5" r="3" fill="#EF4444" />
            </svg>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-1">
            ↑ 1 from last 7 days
          </div>
        </div>

        {/* Card 4: Total Farms Monitored */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">TOTAL FARMS MONITORED</span>
            <button className="info-btn" title="Total active dairy farms in NLDB network">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="kpi-val-number text-navy">14</span>
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 20" className="sparkline-svg">
              <path
                d="M 0 10 Q 30 12, 60 8 T 120 10 T 150 10"
                fill="none"
                stroke="#3B82F6"
                strokeWidth="2"
              />
            </svg>
          </div>
          <div className="kpi-subtext text-muted mt-1">
            Across all regions in Sri Lanka
          </div>
        </div>
      </div>

      {/* Row 2: Last Updated + Recent Alerts + Top Risk Drivers */}
      <div className="kpi-grid-3 mt-4">
        {/* Card 1: LAST UPDATED */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">LAST UPDATED</span>
            <button className="info-btn" title="Model update cycle">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-col">
            <span className="last-update-time font-semibold">🕒 Today, 08:30 AM</span>
            <span className="model-name mt-1">Model: <strong>XGBoost + SHAP</strong></span>
          </div>
          <div className="kpi-subtext mt-3">
            <span className="badge badge-success">High Confidence</span>
          </div>
        </div>

        {/* Card 2: RECENT ALERTS (3) */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">RECENT ALERTS (3)</span>
            <button className="info-btn" title="National early warning alerts">ⓘ</button>
          </div>
          <div className="warning-list-compact">
            <div className="warning-row">
              <span className="warn-icon text-danger">⚠️</span>
              <div className="warn-content">
                <strong>High heat stress expected in North Central region</strong>
                <span>May 27 – May 30, 2026</span>
              </div>
              <span className="badge badge-critical ml-auto">High</span>
            </div>
            <div className="warning-row">
              <span className="warn-icon text-orange">⚡</span>
              <div className="warn-content">
                <strong>Feed availability may drop in 5 farms</strong>
                <span>Next 5 days</span>
              </div>
              <span className="badge badge-high-risk ml-auto">High</span>
            </div>
            <div className="warning-row">
              <span className="warn-icon text-amber">⚠️</span>
              <div className="warn-content">
                <strong>Water availability is low in Uva region</strong>
                <span>Next 3 days</span>
              </div>
              <span className="badge badge-medium-risk ml-auto">Medium</span>
            </div>
          </div>
          <div className="panel-footer-link mt-2">
            <span className="link-blue" onClick={() => alert('Viewing all national alerts...')}>View all alerts →</span>
          </div>
        </div>

        {/* Card 3: TOP RISK DRIVERS (NATIONAL) */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">TOP RISK DRIVERS (NATIONAL)</span>
            <button className="info-btn" title="Aggregated SHAP Drivers">ⓘ</button>
          </div>
          <div className="shap-horizontal-bars">
            <div className="shap-row">
              <span className="shap-label">High Future THI</span>
              <div className="shap-bar-container">
                <div className="shap-bar shap-positive" style={{ width: '75%' }}></div>
              </div>
              <span className="shap-val text-danger">+0.36</span>
            </div>
            <div className="shap-row">
              <span className="shap-label">Feed Availability</span>
              <div className="shap-bar-container">
                <div className="shap-bar shap-positive" style={{ width: '50%' }}></div>
              </div>
              <span className="shap-val text-danger">+0.24</span>
            </div>
            <div className="shap-row">
              <span className="shap-label">Water Stress</span>
              <div className="shap-bar-container">
                <div className="shap-bar shap-positive" style={{ width: '38%' }}></div>
              </div>
              <span className="shap-val text-danger">+0.18</span>
            </div>
            <div className="shap-row">
              <span className="shap-label">Recent Heat Stress</span>
              <div className="shap-bar-container">
                <div className="shap-bar shap-positive" style={{ width: '25%' }}></div>
              </div>
              <span className="shap-val text-danger">+0.12</span>
            </div>
            <div className="shap-row">
              <span className="shap-label">Operational Delay</span>
              <div className="shap-bar-container">
                <div className="shap-bar shap-positive" style={{ width: '18%' }}></div>
              </div>
              <span className="shap-val text-danger">+0.09</span>
            </div>
          </div>
          <div className="shap-scale-footer">
            <span>Low Impact</span>
            <span>High Impact</span>
          </div>
        </div>
      </div>

      {/* Row 3: Farm Risk Overview Table (All 14 Farms displayed line by line!) + Heatmap */}
      <div className="main-grid-two-col mt-4">
        {/* Farm Risk Overview Table */}
        <div className="panel-card">
          <div className="panel-header">
            <h3 className="panel-title">FARM RISK OVERVIEW</h3>
            <div className="table-controls">
              <select
                className="table-select"
                value={selectedRegionFilter}
                onChange={(e) => setSelectedRegionFilter(e.target.value)}
              >
                <option>All Regions</option>
                {REGIONAL_RISKS.map((r) => (
                  <option key={r.region} value={r.region}>
                    {r.region}
                  </option>
                ))}
              </select>
              <select
                className="table-select"
                value={selectedRiskFilter}
                onChange={(e) => setSelectedRiskFilter(e.target.value)}
              >
                <option value="All">Risk Level: All</option>
                <option value="Critical">Critical</option>
                <option value="High">High</option>
                <option value="Medium">Medium</option>
                <option value="Low">Low</option>
              </select>
              <input
                type="text"
                className="table-search"
                placeholder="Search farm..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          <div className="table-wrapper">
            <table className="risk-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Farm Name</th>
                  <th>Region</th>
                  <th>Risk Score</th>
                  <th>Risk Level</th>
                  <th>Main Risk Factor</th>
                  <th>Trend (7 Days)</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredFarms.map((farm) => (
                  <tr key={farm.id} className="table-row-hover" onClick={() => onSelectFarm(farm.id)}>
                    <td className="font-bold text-center">{farm.rank}</td>
                    <td className="font-semibold">
                      <span className="farm-link-blue">{farm.name}</span>
                    </td>
                    <td>{farm.region}</td>
                    <td>
                      <span
                        className={`risk-score-pill ${
                          farm.riskScore >= 75
                            ? 'pill-critical'
                            : farm.riskScore >= 50
                            ? 'pill-high'
                            : farm.riskScore >= 35
                            ? 'pill-medium'
                            : 'pill-low'
                        }`}
                      >
                        {farm.riskScore}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          farm.riskLevel === 'Critical'
                            ? 'badge-critical'
                            : farm.riskLevel === 'High'
                            ? 'badge-high-risk'
                            : farm.riskLevel === 'Medium'
                            ? 'badge-medium-risk'
                            : 'badge-low-risk'
                        }`}
                      >
                        {farm.riskLevel}
                      </span>
                    </td>
                    <td className="text-muted">{farm.mainRiskFactor}</td>
                    <td>
                      <span className={`trend-text ${farm.riskScore >= 50 ? 'text-danger' : 'text-green'}`}>
                        {farm.riskScore >= 50 ? '↑ High' : '↓ Low'}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn-view-farm"
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectFarm(farm.id);
                        }}
                      >
                        View →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Table Footer: Display all 14 farms count */}
          <div className="table-pagination-row mt-3">
            <span className="pagination-info font-medium text-navy">
              Showing all {filteredFarms.length} of 14 farms
            </span>
          </div>
        </div>

        {/* Farm Risk Heatmap (By Region) Card */}
        <div className="panel-card">
          <div className="panel-header">
            <h3 className="panel-title">FARM RISK HEATMAP (BY REGION)</h3>
            <button className="info-btn" title="Regional SVG risk mapping">ⓘ</button>
          </div>
          <SriLankaHeatmap
            selectedRegion={selectedRegionFilter}
            onSelectRegion={(reg) => setSelectedRegionFilter(reg)}
          />
          <div className="panel-footer-link text-right mt-2">
            <span className="link-blue" onClick={() => alert('Viewing regional breakdown...')}>
              View region details →
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
