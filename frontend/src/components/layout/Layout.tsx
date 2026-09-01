import {useEffect, useState} from 'react';
import {NavLink, Outlet, useLocation} from 'react-router-dom';
import {useUser} from '../../context/UserContext';

type NavItem = {to: string; label: string; icon: string; end?: boolean};

const navigation: {label: string; items: NavItem[]}[] = [
  {label: 'Overview', items: [{to: '/', label: 'Dashboard', icon: '▦', end: true}, {to: '/herd', label: 'Herd', icon: '♧'}]},
  {label: 'Intelligence', items: [{to: '/predictive', label: 'Predictive intelligence', icon: '⌁'}, {to: '/risks', label: 'Risk intelligence', icon: '⚑'}]},
  {label: 'Actions', items: [{to: '/intervention-simulator', label: 'Intervention simulator', icon: '⌘'}, {to: '/assistant', label: 'Digital agronomist', icon: '☼'}, {to: '/reports', label: 'Reports', icon: '▤'}]},
];

function pageTitle(pathname: string) {
  for (const group of navigation) {
    const match = group.items.find((item) => item.to === pathname || pathname.startsWith(`${item.to}/`));
    if (match) return match.label;
  }
  return 'Workspace';
}

const RAIL_KEY = 'dairyiq.sidebar.collapsed';

export function Layout() {
  const {role, setRole} = useUser();
  const {pathname} = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(RAIL_KEY) === '1'; } catch { return false; }
  });
  const isFullScreenWorkspace = pathname === '/predictive' || pathname.startsWith('/predictive/') || pathname === '/assistant';
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

  return <div className={`shell${collapsed ? ' shell--rail' : ''}`}>
    <header className="mobile-header">
      <NavLink className="mobile-brand" to="/" aria-label="DairyIQ dashboard">DAIRY<span>IQ</span></NavLink>
      <button className="menu-toggle" type="button" aria-expanded={menuOpen} aria-controls="app-navigation" onClick={() => setMenuOpen((open) => !open)}><span aria-hidden="true">{menuOpen ? '×' : '☰'}</span><span className="sr-only">{menuOpen ? 'Close navigation' : 'Open navigation'}</span></button>
    </header>
    {menuOpen && <button className="nav-scrim" type="button" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
    <aside className={menuOpen ? 'open' : ''} aria-label="Application sidebar">
      <div className="sidebar-top"><NavLink className="brand" to="/" aria-label="DairyIQ dashboard">DAIRY<span>IQ</span></NavLink><button className="rail-toggle" type="button" aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}><span aria-hidden="true">{collapsed ? '»' : '«'}</span><span className="sr-only">{collapsed ? 'Expand sidebar' : 'Collapse sidebar'}</span></button></div>
      <p className="brand-tagline">Decision support workspace</p>
      <nav className="app-navigation" id="app-navigation" aria-label="Main navigation">{navigation.map((group) => <section className="nav-group" key={group.label}><p>{group.label}</p>{group.items.map((item) => <NavLink key={item.to} to={item.to} end={item.end} title={item.label} className={({isActive}) => isActive ? 'active' : undefined}><span className="nav-icon" aria-hidden="true">{item.icon}</span><span className="nav-label">{item.label}</span></NavLink>)}</section>)}</nav>
      <NavLink className={({isActive}) => `settings-link${isActive ? ' active' : ''}`} to="/settings"><span className="nav-icon" aria-hidden="true">⚙</span>Settings</NavLink>
      <label className="role-switcher">View as<select value={role} onChange={event => setRole(event.target.value as typeof role)}><option value="farm_worker">Farm worker</option><option value="veterinarian">Veterinarian</option><option value="farm_manager">Farm manager</option><option value="nldb_management">NLDB management</option></select></label>
    </aside>
    <main className={isFullScreenWorkspace ? 'page-main--full' : isWideWorkspace ? 'page-main--wide' : undefined}>{!isFullScreenWorkspace && <div className="page-context"><span>Workspace</span><b>{pageTitle(pathname)}</b></div>}<Outlet/></main>
  </div>;
}
