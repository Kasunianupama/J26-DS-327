/**
 * Component 2 — inline icon set.
 *
 * Stroke icons on a 24 grid, drawn inline so they inherit colour, need no
 * dependency and stay crisp at the 14–20px sizes the workspaces use.
 */

export type IconName =
  | 'outlook' | 'herd' | 'products' | 'confidence' | 'operations'
  | 'droplet' | 'trendDown' | 'trendUp' | 'wallet' | 'calendar'
  | 'search' | 'flag' | 'expand' | 'arrowRight' | 'arrowLeft' | 'spark' | 'scale';

const PATHS: Record<IconName, JSX.Element> = {
  outlook: <><path d="M3 17.5 9 11l4 4 8-8.5" /><path d="M21 6.5h-4.6M21 6.5v4.6" /></>,
  herd: <><path d="M4 10h11a3 3 0 0 1 3 3v2" /><path d="M4 10v7M8.5 15v4M14 15v4M18 15v4" /><path d="M4.2 10 2.5 7.4" /></>,
  products: <><path d="M3.5 7.8 12 3.4l8.5 4.4v8.4L12 20.6 3.5 16.2Z" /><path d="M3.5 7.8 12 12.2l8.5-4.4M12 12.2v8.4" /></>,
  confidence: <><path d="M12 3.2 4.5 6.4v5.1c0 4.3 3.1 7.7 7.5 9.3 4.4-1.6 7.5-5 7.5-9.3V6.4Z" /><path d="m8.8 11.9 2.3 2.3 4.1-4.6" /></>,
  operations: <><path d="M4 6.5h16M4 12h16M4 17.5h10" /><circle cx="17.5" cy="17.5" r="2.4" /></>,
  droplet: <><path d="M12 3.4c3.2 3.6 5.3 6.4 5.3 9a5.3 5.3 0 0 1-10.6 0c0-2.6 2.1-5.4 5.3-9Z" /></>,
  trendDown: <><path d="M3.5 7.5 10 14l3.4-3.4L20.5 17" /><path d="M20.5 12.6V17h-4.4" /></>,
  trendUp: <><path d="M3.5 16.5 10 10l3.4 3.4L20.5 7" /><path d="M20.5 11.4V7h-4.4" /></>,
  wallet: <><path d="M3.6 8.2c0-1.2 1-2.2 2.2-2.2h11.4c1.2 0 2.2 1 2.2 2.2v7.6c0 1.2-1 2.2-2.2 2.2H5.8a2.2 2.2 0 0 1-2.2-2.2Z" /><path d="M19.4 10.6h-3.2a1.4 1.4 0 0 0 0 2.8h3.2" /></>,
  calendar: <><rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2.2" /><path d="M3.6 9.8h16.8M8.2 3.6v3.2M15.8 3.6v3.2" /></>,
  search: <><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.4 15.4 4.2 4.2" /></>,
  flag: <><path d="M5.4 20.4V4.2M5.4 5.1h10.9l-1.7 3.5 1.7 3.5H5.4" /></>,
  expand: <><path d="M9 5h10v10" /><path d="M19 5 5.6 18.4" /></>,
  arrowRight: <><path d="M4.5 12h15M13.6 6.2 19.4 12l-5.8 5.8" /></>,
  arrowLeft: <><path d="M19.5 12h-15M10.4 6.2 4.6 12l5.8 5.8" /></>,
  spark: <><path d="m12 3.4 1.9 4.9 4.9 1.9-4.9 1.9L12 17l-1.9-4.9-4.9-1.9 4.9-1.9Z" /><path d="M18.4 15.6 19.2 18l2.4.8-2.4.8-.8 2.4-.8-2.4-2.4-.8 2.4-.8Z" /></>,
  scale: <><path d="M12 4v16M6.5 7.4h11" /><path d="M6.5 7.4 3.4 14h6.2ZM17.5 7.4 14.4 14h6.2Z" /><path d="M8 20h8" /></>,
};

export function Icon({ name, size = 16, className = '' }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={`pfie-icon ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
