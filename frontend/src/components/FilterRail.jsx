import { MagnifyingGlass, X } from '@phosphor-icons/react';
import { EMPTY_FILTERS, isDefaultFilters } from '../lib/filters.js';
import { styledTiers } from '../lib/priority.js';
import { int } from '../lib/format.js';
import './FilterRail.css';

function Group({ title, children, note, noteId }) {
  return (
    <fieldset className="filter-group" aria-describedby={note ? noteId : undefined}>
      <legend className="label filter-group__legend">{title}</legend>
      {children}
      {note && (
        <p className="filter-group__note" id={noteId}>
          {note}
        </p>
      )}
    </fieldset>
  );
}

/** A checkbox whose accessible name is the option, its description and its segment count. */
function Check({ checked, onChange, children, hint, swatch, n }) {
  return (
    <label className={`filter-option${checked ? ' filter-option--on' : ''}`}>
      <input type="checkbox" className="filter-option__input" checked={checked} onChange={onChange} />
      {swatch && <span className="filter-option__swatch" style={{ background: swatch }} aria-hidden="true" />}
      <span className="filter-option__text">
        {children}
        {hint && <span className="filter-option__hint">{hint}</span>}
      </span>
      {n !== undefined && (
        <span className="filter-option__n mono">
          {int(n)}
          <span className="sr-only"> segments</span>
        </span>
      )}
    </label>
  );
}

const GROUPS = [
  { key: 'tiers', title: 'National rank group', note: 'Exact, non-overlapping bands of national rank.' },
  { key: 'roadClasses', title: 'Road class' },
  { key: 'sufficiency', title: 'Recorded collisions, 2023–25' },
  { key: 'flags', title: 'Warnings', note: 'Combined with AND: a segment must carry every selected warning.' },
  { key: 'stability', title: 'Rank stability (20 refits)' },
  { key: 'rate', title: 'Per-vehicle rate' },
  { key: 'explanation', title: 'Model explanation' },
];

export default function FilterRail({ filters, onChange, options, tiers, resultCount, totalCount, idPrefix = 'rail' }) {
  const toggle = (key, value) => {
    const list = filters[key];
    onChange({ ...filters, [key]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] });
  };
  const swatch = Object.fromEntries(styledTiers(tiers).map((t) => [t.key, t.color]));
  const labelOf = (key, value) => options[key]?.find((o) => o.key === value)?.label ?? value;
  const chips = [
    ...(filters.query.trim()
      ? [{ key: 'q', label: `“${filters.query.trim()}”`, clear: () => onChange({ ...filters, query: '' }) }]
      : []),
    ...GROUPS.flatMap((g) => filters[g.key].map((v) => ({ key: `${g.key}:${v}`, label: labelOf(g.key, v), clear: () => toggle(g.key, v) }))),
  ];
  const isDefault = isDefaultFilters(filters);

  return (
    <div className="filter-rail" role="search" aria-label="Find and filter road segments">
      <div className="filter-rail__head">
        <h2 className="panel-title">Find and filter</h2>
        <p className="filter-rail__count readout" id={`${idPrefix}-count`}>
          {int(resultCount)} of {int(totalCount)} loaded segments
        </p>
      </div>

      {chips.length > 0 && (
        <div className="filter-chips" role="group" aria-label="Active filters">
          {chips.map((chip) => (
            <button key={chip.key} className="chip" onClick={chip.clear} aria-label={`Remove filter: ${chip.label}`}>
              <span className="chip__label" aria-hidden="true">
                {chip.label}
              </span>
              <X size={12} weight="bold" aria-hidden="true" />
            </button>
          ))}
        </div>
      )}

      <div className="filter-rail__scroll">
        <div className="filter-group">
          <label className="label filter-group__legend" htmlFor={`${idPrefix}-search`}>
            Search by road, place or segment ID
          </label>
          <div className="filter-search">
            <MagnifyingGlass size={15} weight="bold" aria-hidden="true" />
            <input
              id={`${idPrefix}-search`}
              className="input filter-search__input"
              type="search"
              value={filters.query}
              onChange={(e) => onChange({ ...filters, query: e.target.value })}
              placeholder="A57, Water Street, B5339-8AD45E53257A-00"
              autoComplete="off"
              aria-describedby={`${idPrefix}-search-help ${idPrefix}-count`}
            />
          </div>
          <p className="filter-group__note" id={`${idPrefix}-search-help`}>
            Matches road number, street name, location text or segment ID among the loaded segments. Results update as
            you type; use the segment list to open one.
          </p>
        </div>

        {GROUPS.map((g) => {
          const opts = options[g.key] ?? [];
          if (!opts.length) {
            if (g.key === 'explanation') {
              return (
                <Group key={g.key} title={g.title}>
                  <p className="filter-group__note">Not available from this data source.</p>
                </Group>
              );
            }
            return null;
          }
          return (
            <Group key={g.key} title={g.title} note={g.note} noteId={`${idPrefix}-${g.key}-note`}>
              {opts.map((o) => (
                <Check
                  key={o.key}
                  checked={filters[g.key].includes(o.key)}
                  onChange={() => toggle(g.key, o.key)}
                  swatch={g.key === 'tiers' ? swatch[o.key] : undefined}
                  hint={o.hint}
                  n={o.n}
                >
                  {o.label}
                </Check>
              ))}
            </Group>
          );
        })}
        <p className="filter-group__note filter-rail__nofilter">
          No region or local-authority filter: the release has no reliable administrative field.
        </p>
      </div>

      <div className="filter-rail__foot">
        <button
          className="btn-tertiary"
          onClick={() => onChange(EMPTY_FILTERS)}
          disabled={isDefault}
          aria-describedby={isDefault ? `${idPrefix}-reset-help` : undefined}
        >
          Reset filters
        </button>
        {isDefault && (
          <span className="sr-only" id={`${idPrefix}-reset-help`}>
            No filters are active, so there is nothing to reset.
          </span>
        )}
      </div>
    </div>
  );
}
