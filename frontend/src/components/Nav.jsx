import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { List, X } from '@phosphor-icons/react';
import { DATASET } from '../data/blackspots.js';
import './Nav.css';

const LINKS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/explorer', label: 'Explorer' },
  { to: '/rankings', label: 'Rankings' },
  { to: '/statistics', label: 'Statistics' },
];

export default function Nav() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  // Close the sheet on navigation, otherwise it covers the screen the user
  // just asked for.
  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <header className="nav">
      <div className="nav__inner">
        <NavLink to="/" className="nav__brand" end>
          <span className="nav__mark" aria-hidden="true">
            <svg viewBox="0 0 20 20" width="20" height="20" fill="none">
              <path
                d="M10 1.5 18.5 17H1.5L10 1.5Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path d="M10 7.5v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <circle cx="10" cy="14" r="0.9" fill="currentColor" />
            </svg>
          </span>
          <span className="nav__wordmark">Blackspot Atlas</span>
        </NavLink>

        <nav className="nav__links" aria-label="Primary">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                `nav__link${isActive ? ' nav__link--active' : ''}`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </nav>

        {/*
          Dataset status, not a live feed. The dot breathes to show the panel is
          reporting current state; the label states plainly that clusters are
          precomputed.
        */}
        <div className="nav__status" title={`Clusters computed ${DATASET.computedOn}`}>
          <span className="nav__dot" aria-hidden="true" />
          <span className="nav__status-text mono">
            Precomputed {DATASET.computedOn}
          </span>
        </div>

        <button
          className="nav__toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="nav-sheet"
          aria-label={open ? 'Close menu' : 'Open menu'}
        >
          {open ? <X size={20} weight="regular" /> : <List size={20} weight="regular" />}
        </button>
      </div>

      {open && (
        <div className="nav__sheet" id="nav-sheet">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                `nav__sheet-link${isActive ? ' nav__sheet-link--active' : ''}`
              }
            >
              {l.label}
            </NavLink>
          ))}
          <p className="nav__sheet-meta mono">Clusters precomputed {DATASET.computedOn}</p>
        </div>
      )}
    </header>
  );
}
