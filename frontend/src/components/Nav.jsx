import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { List, X } from '@phosphor-icons/react';
import './Nav.css';

const LINKS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/explorer', label: 'Explorer' },
  { to: '/route', label: 'Route' },
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
        </div>
      )}
    </header>
  );
}
