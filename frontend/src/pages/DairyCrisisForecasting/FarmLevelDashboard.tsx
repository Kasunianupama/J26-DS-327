import React, { useState } from 'react';
import { SYNTETHIC_FARMS, FarmData } from './syntheticData';

interface FarmLevelDashboardProps {
  selectedFarmId: string;
  onSelectFarmId: (farmId: string) => void;
}

export const FarmLevelDashboard: React.FC<FarmLevelDashboardProps> = ({
  selectedFarmId,
  onSelectFarmId,
}) => {
  const farm: FarmData =
    SYNTETHIC_FARMS.find((f) => f.id === selectedFarmId) || SYNTETHIC_FARMS[0];

  const [dateRange, setDateRange] = useState('May 25 – May 31, 2026 (Next 7 Days)');

  // SVG Gauge Arc calculations for Farm Risk Score (0-100)
  const score = farm.riskScore;
  const radius = 45;
  const circumference = Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  return (
    <div className="dashboard-content animate-fade-in">
      {/* Top Header Bar */}
      <header className="dashboard-top-header">
        <div>
          <h1 className="header-title">Dashboard</h1>
          <p className="header-subtitle">Welcome back, Farm Manager</p>
        </div>
        <div className="header-controls">
          <div className="control-field">
            <span className="control-label">Select Farm</span>
            <select
              className="header-select font-semibold"
              value={farm.id}
              onChange={(e) => onSelectFarmId(e.target.value)}
            >
              {SYNTETHIC_FARMS.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} ({f.region})
                </option>
              ))}
            </select>
          </div>
          <div className="control-field">
            <select
              className="header-select font-medium"
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
            >
              <option>May 25 – May 31, 2026 (Next 7 Days)</option>
              <option>June 01 – June 07, 2026</option>
            </select>
          </div>
          <button className="btn-export" type="button" onClick={() => alert('Exporting Farm Risk Report PDF...')}>
            <span className="icon">⤓</span> Export Report
          </button>
          <div className="notification-bell" title="6 New Alerts">
            🔔 <span className="bell-badge">6</span>
          </div>
          <div className="user-profile-badge">
            <div className="user-avatar">👤</div>
            <span className="user-name">Farm Manager ▾</span>
          </div>
        </div>
      </header>

      {/* Row 1: KPI Cards */}
      <div className="kpi-grid-4">
        {/* Card 1: MAIN RISK SCORE */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">MAIN RISK SCORE</span>
            <button className="info-btn" title="Composite forward risk score">ⓘ</button>
          </div>
          <div className="gauge-meter-wrapper">
            <div className="gauge-svg-container">
              <svg viewBox="0 0 120 70" className="gauge-svg">
                <path
                  d="M 15 60 A 45 45 0 0 1 105 60"
                  fill="none"
                  stroke="#E2E8F0"
                  strokeWidth="10"
                  strokeLinecap="round"
                />
                <path
                  d="M 15 60 A 45 45 0 0 1 105 60"
                  fill="none"
                  stroke={score >= 75 ? '#EF4444' : score >= 50 ? '#F97316' : '#10B981'}
                  strokeWidth="10"
                  strokeLinecap="round"
                  strokeDasharray={circumference}
                  strokeDashoffset={strokeDashoffset}
                />
              </svg>
              <div className="gauge-text">
                <span className="gauge-value">{score}</span>
                <span className="gauge-max">/ 100</span>
              </div>
            </div>
            <div className="gauge-badge-box">
              <span className={`badge ${score >= 75 ? 'badge-critical' : score >= 50 ? 'badge-high-risk' : 'badge-low-risk'}`}>
                {farm.riskLevel} Risk
              </span>
            </div>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-1">
            ↑ 12.5 from last 7 days
          </div>
        </div>

        {/* Card 2: RISK LEVEL */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">RISK LEVEL</span>
            <button className="info-btn" title="Categorized risk severity">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <div className="icon-shield-danger">
              <span>!</span>
            </div>
            <span className="kpi-title-large text-navy">{farm.riskLevel}</span>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-2">
            ↑ 1 level from last 7 days
          </div>
        </div>

        {/* Card 3: MAIN RISK FACTOR */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">MAIN RISK FACTOR</span>
            <button className="info-btn" title="Primary driver behind current score">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <div className="weather-icon-box">🌧️</div>
            <div className="main-risk-info">
              <h3 className="risk-factor-title">{farm.mainRiskFactor}</h3>
            </div>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-2">
            Impact: High
          </div>
        </div>

        {/* Card 4: MODEL CONFIDENCE */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title">MODEL CONFIDENCE</span>
            <button className="info-btn" title="Model prediction certainty">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <div className="icon-shield-success">
              <span>✓</span>
            </div>
            <span className="kpi-title-large text-navy">High</span>
          </div>
          <div className="kpi-subtext text-green font-semibold mt-2">
            82% Confidence
          </div>
        </div>
      </div>

      <div className="section-heading-row mt-4">
        <div>
          <h2 className="section-heading-title">Risk Score Breakdown</h2>
          <p className="section-heading-subtitle">Primary model contributors for the selected farm</p>
        </div>
      </div>

      {/* Row 2: Sub-Risk Breakdown Cards with Sparklines */}
      <div className="subrisk-grid-4 mt-4">
        {/* Climate Risk */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title text-blue font-bold">CLIMATE RISK</span>
            <button className="info-btn" title="Climate anomalies & THI">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="subrisk-icon-lg">🌧️</span>
            <span className="subrisk-score-val text-navy">72</span>
            <span className="subrisk-score-max">/ 100</span>
            <span className="badge badge-high-risk ml-auto">High</span>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-1">
            ↑ 8.4 from last 7 days
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 25" className="sparkline-svg">
              <path
                d="M 0 18 Q 30 15, 60 12 T 120 8 T 150 5"
                fill="none"
                stroke="#3B82F6"
                strokeWidth="2"
              />
            </svg>
          </div>
        </div>

        {/* Feed Risk */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title text-green font-bold">FEED RISK</span>
            <button className="info-btn" title="Feed quantity & supply gap">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="subrisk-icon-lg">🍃</span>
            <span className="subrisk-score-val text-navy">64</span>
            <span className="subrisk-score-max">/ 100</span>
            <span className="badge badge-high-risk ml-auto">High</span>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-1">
            ↑ 6.1 from last 7 days
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 25" className="sparkline-svg">
              <path
                d="M 0 20 Q 30 18, 60 14 T 120 10 T 150 6"
                fill="none"
                stroke="#10B981"
                strokeWidth="2"
              />
            </svg>
          </div>
        </div>

        {/* Operational Risk */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title text-purple font-bold">OPERATIONAL RISK</span>
            <button className="info-btn" title="Human & management operational index">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="subrisk-icon-lg">⚙️</span>
            <span className="subrisk-score-val text-navy">58</span>
            <span className="subrisk-score-max">/ 100</span>
            <span className="badge badge-medium-risk ml-auto">Medium</span>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-1">
            ↑ 3.2 from last 7 days
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 25" className="sparkline-svg">
              <path
                d="M 0 15 Q 30 16, 60 12 T 120 14 T 150 10"
                fill="none"
                stroke="#9333EA"
                strokeWidth="2"
              />
            </svg>
          </div>
        </div>

        {/* Farm Vulnerability */}
        <div className="kpi-card">
          <div className="kpi-card-header">
            <span className="kpi-card-title text-navy font-bold">FARM VULNERABILITY</span>
            <button className="info-btn" title="Historical stability & disease index">ⓘ</button>
          </div>
          <div className="kpi-value-row flex-align-center">
            <span className="subrisk-icon-lg">🛡️</span>
            <span className="subrisk-score-val text-navy">66</span>
            <span className="subrisk-score-max">/ 100</span>
            <span className="badge badge-high-risk ml-auto">High</span>
          </div>
          <div className="kpi-subtext text-danger font-medium mt-1">
            ↑ 5.7 from last 7 days
          </div>
          <div className="sparkline-wrapper mt-2">
            <svg viewBox="0 0 150 25" className="sparkline-svg">
              <path
                d="M 0 19 Q 30 15, 60 17 T 120 12 T 150 8"
                fill="none"
                stroke="#F59E0B"
                strokeWidth="2"
              />
            </svg>
          </div>
        </div>
      </div>

      {/* Row 3: Risk Trend + Top Risk Drivers + Early Warnings + Recommended Actions */}
      <div className="kpi-grid-4 mt-4">
        {/* Card 1: RISK TREND (7 DAYS) */}
        <div className="panel-card">
          <div className="panel-header">
            <span className="panel-title">RISK TREND (7 DAYS)</span>
            <button className="info-btn" title="7-Day Risk Score Trajectory">ⓘ</button>
          </div>
          <div className="trend-chart-clean">
            <svg viewBox="0 0 200 100" className="trend-line-svg">
              <g className="trend-grid-lines" aria-hidden="true">
                <line x1="10" y1="10" x2="10" y2="88" />
                <line x1="40" y1="10" x2="40" y2="88" />
                <line x1="70" y1="10" x2="70" y2="88" />
                <line x1="100" y1="10" x2="100" y2="88" />
                <line x1="130" y1="10" x2="130" y2="88" />
                <line x1="160" y1="10" x2="160" y2="88" />
                <line x1="190" y1="10" x2="190" y2="88" />
                <line x1="10" y1="15" x2="190" y2="15" />
                <line x1="10" y1="35" x2="190" y2="35" />
                <line x1="10" y1="55" x2="190" y2="55" />
                <line x1="10" y1="75" x2="190" y2="75" />
              </g>
              <polyline
                fill="none"
                stroke="#3F6DB5"
                strokeWidth="3"
                points="10,67 40,62 70,54 100,27 130,26 160,24 190,18"
              />
              <circle cx="10" cy="67" r="3.5" />
              <circle cx="40" cy="62" r="3.5" />
              <circle cx="70" cy="54" r="3.5" />
              <circle cx="100" cy="27" r="3.5" />
              <circle cx="130" cy="26" r="3.5" />
              <circle cx="160" cy="24" r="3.5" />
              <circle cx="190" cy="18" r="3.5" />
            </svg>
            <div className="chart-x-dates">
              <span>May 25</span>
              <span>May 27</span>
              <span>May 29</span>
              <span>May 31</span>
            </div>
            <div className="chart-legend-bottom">
              <span className="legend-dot bg-blue"></span> Risk Score
            </div>
          </div>
        </div>

        {/* Card 2: TOP RISK DRIVERS (SHAP) */}
        <div className="panel-card">
          <div className="panel-header">
            <span className="panel-title">TOP RISK DRIVERS (SHAP)</span>
            <button className="info-btn" title="SHAP Feature Attribution">ⓘ</button>
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

        {/* Card 3: EARLY WARNINGS */}
        <div className="panel-card">
          <div className="panel-header">
            <span className="panel-title">EARLY WARNINGS</span>
            <button className="info-btn" title="System alerts">ⓘ</button>
          </div>
          <div className="warning-list-compact">
            <div className="warning-row">
              <span className="warn-icon text-danger">⚠️</span>
              <div className="warn-content">
                <strong>High heat stress expected</strong>
                <span>May 27 – May 30, 2026</span>
              </div>
              <span className="badge badge-critical ml-auto">High</span>
            </div>
            <div className="warning-row">
              <span className="warn-icon text-orange">⚡</span>
              <div className="warn-content">
                <strong>Feed availability may drop</strong>
                <span>Next 5 days</span>
              </div>
              <span className="badge badge-high-risk ml-auto">High</span>
            </div>
            <div className="warning-row">
              <span className="warn-icon text-amber">⚠️</span>
              <div className="warn-content">
                <strong>Water availability is low</strong>
                <span>Next 3 days</span>
              </div>
              <span className="badge badge-medium-risk ml-auto">Medium</span>
            </div>
          </div>
          <div className="panel-footer-link">
            <span className="link-blue" onClick={() => alert('Viewing all warnings...')}>View all warnings →</span>
          </div>
        </div>

        {/* Card 4: RECOMMENDED ACTIONS */}
        <div className="panel-card">
          <div className="panel-header">
            <span className="panel-title">RECOMMENDED ACTIONS</span>
            <button className="info-btn" title="Proactive mitigation steps">ⓘ</button>
          </div>
          <div className="recommendations-list-compact">
            <div className="rec-row">
              <span className="rec-check text-green">✓</span>
              <div className="rec-content">
                <strong>Improve feed management</strong>
                <span>Ensure quality and quantity</span>
              </div>
            </div>
            <div className="rec-row">
              <span className="rec-check text-green">✓</span>
              <div className="rec-content">
                <strong>Increase water availability</strong>
                <span>Check storage and supply</span>
              </div>
            </div>
            <div className="rec-row">
              <span className="rec-check text-green">✓</span>
              <div className="rec-content">
                <strong>Provide shade and cooling</strong>
                <span>Reduce heat stress impact</span>
              </div>
            </div>
          </div>
          <div className="panel-footer-link">
            <span className="link-blue" onClick={() => alert('Viewing all recommendations...')}>View all recommendations →</span>
          </div>
        </div>
      </div>

      {/* Footer bar */}
      <footer className="dashboard-footer-bar mt-4">
        <span className="footer-update font-medium">Last updated: Today, 08:30 AM 🔄</span>
        <span className="footer-source font-medium ml-auto">Data source: DairyIQ Risk Engine 🗄️</span>
      </footer>
    </div>
  );
};
