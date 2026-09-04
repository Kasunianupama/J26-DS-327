import {useEffect, useState} from 'react';
import {NavLink, Outlet, useLocation, useNavigate} from 'react-router-dom';
import {useUser} from '../../context/UserContext';

type IconName = 'pulse' | 'sliders' | 'shield-emoji' | 'farm' | 'chart' | 'sparkles' | 'report' | 'settings';
type SubItem = {to: string; label: string; icon: IconName};
type NavItem = {to: string; label: string; icon: IconName; end?: boolean; subItems?: SubItem[]};

const iconPaths: Record<Exclude<IconName, 'shield-emoji'>, React.ReactNode> = {
  pulse: <path d="M3 12h4l2.2-6 4.1 12 2.4-6H21" />,
  sliders: <><path d="M4 7h10" /><path d="M18 7h2" /><path d="M4 17h2" /><path d="M10 17h10" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></>,
  farm: <><path d="m3 10 9-7 9 7" /><path d="M5 9v11h14V9" /><path d="M9 20v-6h6v6" /><path d="M8 10h.01M16 10h.01" /></>,
  chart: <><path d="M4 20V10h4v10" /><path d="M10 20V4h4v16" /><path d="M16 20v-7h4v7" /></>,
  sparkles: <><path d="m12 3 .8 2.2L15 6l-2.2.8L12 9l-.8-2.2L9 6l2.2-.8L12 3Z" /><path d="M5 11 6.2 14 9 15l-2.8 1L5 19l-1.2-3L1 15l2.8-1L5 11Z" /><path d="m18 10 .8 2.2L21 13l-2.2.8L18 16l-.8-2.2L15 13l2.2-.8L18 10Z" /></>,
  report: <><path d="M6 3h9l4 4v14H6Z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h6" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></>,
};

function NavigationIcon({name}: {name: IconName}) {
  if (name === 'shield-emoji') return <span className="nav-icon-emoji" aria-hidden="true">🛡️</span>;

  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {iconPaths[name]}
    </svg>
  );
}

const navigation: {label: string; items: NavItem[]}[] = [
  {label: 'Intelligence', items: [{to: '/predictive', label: 'Predictive intelligence', icon: 'pulse'}]},
  {
    label: 'Actions',
    items: [
      {to: '/intervention-simulator', label: 'Intervention simulator', icon: 'sliders'},
      {
        to: '/risk-management',
        label: 'Risk management',
        icon: 'shield-emoji',
        subItems: [
          {to: '/risk-management/farm', label: 'Farm Dashboard', icon: 'farm'},
          {to: '/risk-management/nldb', label: 'NLDB Dashboard', icon: 'chart'},
        ],
      },
      {to: '/assistant', label: 'Digital agronomist', icon: 'sparkles'},
      {to: '/reports', label: 'Reports', icon: 'report'},
    ],
  },
];

function pageTitle(pathname: string) {
  for (const group of navigation) {
    const match = group.items.find((item) => item.to === pathname || pathname.startsWith(`${item.to}/`));
    if (match) {
      if (match.subItems) {
        const subMatch = match.subItems.find((s) => s.to === pathname);
        if (subMatch) return `${match.label} - ${subMatch.label}`;
      }
      return match.label;
    }
  }
  return 'Workspace';
}

const RAIL_KEY = 'dairyiq.sidebar.collapsed';

export function Layout() {
  const {role, setRole} = useUser();
  const {pathname} = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(RAIL_KEY) === '1'; } catch { return false; }
  });
  const isFullScreenWorkspace = pathname === '/predictive' || pathname.startsWith('/predictive/') || pathname === '/assistant' || pathname.startsWith('/risk-management') || pathname.startsWith('/crisis-forecasting');
  const isWideWorkspace = pathname === '/intervention-simulator' || pathname === '/interventions';

  useEffect(() => {
    try { localStorage.setItem(RAIL_KEY, collapsed ? '1' : '0'); } catch { /* private mode */ }
  }, [collapsed]);
  useEffect(() => setMenuOpen(false), [pathname]);
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => event.key === 'Escape' && setMenuOpen(false);
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, []);

  const handleRoleChange = (newRole: typeof role) => {
    setRole(newRole);
    if (pathname.startsWith('/risk-management')) {
      if (newRole === 'nldb_management') {
        navigate('/risk-management/nldb');
      } else {
        navigate('/risk-management/farm');
      }
    }
  };

  return (
    <div className={`shell${collapsed ? ' shell--rail' : ''}`}>
      <header className="mobile-header">
        <NavLink className="mobile-brand" to="/" aria-label="DairyIQ dashboard">DAIRY<span>IQ</span></NavLink>
        <button className="menu-toggle" type="button" aria-expanded={menuOpen} aria-controls="app-navigation" onClick={() => setMenuOpen((open) => !open)}>
          <span aria-hidden="true">{menuOpen ? '×' : '☰'}</span>
          <span className="sr-only">{menuOpen ? 'Close navigation' : 'Open navigation'}</span>
        </button>
      </header>
      {menuOpen && <button className="nav-scrim" type="button" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
      <aside className={menuOpen ? 'open' : ''} aria-label="Application sidebar">
        <div className="sidebar-top">
          <NavLink className="brand" to="/" aria-label="DairyIQ dashboard">DAIRY<span>IQ</span></NavLink>
          <button className="rail-toggle" type="button" aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              {collapsed ? <><path d="m7 7 5 5-5 5" /><path d="m13 7 5 5-5 5" /></> : <><path d="m17 7-5 5 5 5" /><path d="m11 7-5 5 5 5" /></>}
            </svg>
            <span className="sr-only">{collapsed ? 'Expand sidebar' : 'Collapse sidebar'}</span>
          </button>
        </div>
        <p className="brand-tagline">Decision support workspace</p>
        <nav className="app-navigation" id="app-navigation" aria-label="Main navigation">
          {navigation.map((group) => (
            <section className="nav-group" key={group.label}>
              <p>{group.label}</p>
              {group.items.map((item) => {
                const isItemActive = pathname === item.to || pathname.startsWith(`${item.to}/`);
                return (
                  <div key={item.to} className="nav-item-group">
                    <NavLink
                      to={item.to}
                      end={item.end}
                      title={item.label}
                      className={({isActive}) => (isActive || isItemActive) ? 'active' : undefined}
                    >
                      <span className="nav-icon"><NavigationIcon name={item.icon} /></span>
                      <span className="nav-label">{item.label}</span>
                    </NavLink>
                    {/* Always render subItems visible under Risk management */}
                    {item.subItems && (
                      <div className="nav-sub-menu">
                        {item.subItems.map((sub) => (
                          <NavLink
                            key={sub.to}
                            to={sub.to}
                            title={sub.label}
                            className={({isActive}) => isActive || pathname === sub.to ? 'active nav-sub-link' : 'nav-sub-link'}
                          >
                            <span className="nav-icon"><NavigationIcon name={sub.icon} /></span>
                            <span className="nav-label">{sub.label}</span>
                          </NavLink>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </section>
          ))}
        </nav>
        <NavLink className={({isActive}) => `settings-link${isActive ? ' active' : ''}`} to="/settings" title="Settings">
          <span className="nav-icon"><NavigationIcon name="settings" /></span><span className="nav-label">Settings</span>
        </NavLink>
        <label className="role-switcher">
          View as
          <select value={role} onChange={(e) => handleRoleChange(e.target.value as typeof role)}>
            <option value="farm_worker">Farm worker</option>
            <option value="veterinarian">Veterinarian</option>
            <option value="farm_manager">Farm manager</option>
            <option value="nldb_management">NLDB management</option>
          </select>
        </label>
      </aside>
      <main className={isFullScreenWorkspace ? 'page-main--full' : isWideWorkspace ? 'page-main--wide' : undefined}>
        {!isFullScreenWorkspace && (
          <div className="page-context">
            <span>Workspace</span>
            <b>{pageTitle(pathname)}</b>
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
