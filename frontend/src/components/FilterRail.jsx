import { X } from '@phosphor-icons/react';
import {
  PERIODS,
  TIER_FILTERS,
  ROAD_TYPES,
  ROAD_CLASSES,
  CONDITIONS,
  EMPTY_FILTERS,
  isDefaultFilters,
} from '../lib/filters.js';
import { TIERS, NO_DATA_TIER } from '../lib/risk.js';
import './FilterRail.css';

function tierColor(key) {
  return (TIERS.find((t) => t.key === key) ?? NO_DATA_TIER).color;
}

function Group({ title, children }) {
  return (
    <fieldset className="filter-group">
      <legend className="label filter-group__legend">{title}</legend>
      {children}
    </fieldset>
  );
}

function Check({ checked, onChange, children, swatch }) {
  return (
    <label className={`filter-option${checked ? ' filter-option--on' : ''}`}>
      <input
        type="checkbox"
        className="filter-option__input"
        checked={checked}
        onChange={onChange}
      />
      {swatch && (
        <span
          className="filter-option__swatch"
          style={{ background: swatch }}
          aria-hidden="true"
        />
      )}
      <span className="filter-option__text">{children}</span>
    </label>
  );
}

export default function FilterRail({ filters, onChange, resultCount, totalCount }) {
  const toggle = (key, value) => {
    const list = filters[key];
    onChange({
      ...filters,
      [key]: list.includes(value)
        ? list.filter((v) => v !== value)
        : [...list, value],
    });
  };

  const activeChips = [
    ...(filters.period !== 'full'
      ? [
          {
            key: `period:${filters.period}`,
            label: PERIODS.find((p) => p.key === filters.period).label,
            clear: () => onChange({ ...filters, period: 'full' }),
          },
        ]
      : []),
    ...filters.tiers.map((t) => ({
      key: `tier:${t}`,
      label: TIER_FILTERS.find((x) => x.key === t).label,
      clear: () => toggle('tiers', t),
    })),
    ...filters.roadTypes.map((t) => ({
      key: `rt:${t}`,
      label: t,
      clear: () => toggle('roadTypes', t),
    })),
    ...filters.roadClasses.map((t) => ({
      key: `rc:${t}`,
      label: t,
      clear: () => toggle('roadClasses', t),
    })),
    ...filters.conditions.map((c) => ({
      key: `cond:${c}`,
      label: CONDITIONS.find((x) => x.key === c).label,
      clear: () => toggle('conditions', c),
    })),
  ];

  return (
    <div className="filter-rail">
      <div className="filter-rail__head">
        <h2 className="panel-title">Filters</h2>
        <p className="filter-rail__count readout">
          {resultCount} of {totalCount} clusters
        </p>
      </div>

      {activeChips.length > 0 && (
        <div className="filter-chips">
          {activeChips.map((chip) => (
            <button key={chip.key} className="chip" onClick={chip.clear}>
              <span className="chip__label">{chip.label}</span>
              <X size={12} weight="bold" aria-label={`Clear ${chip.label}`} />
            </button>
          ))}
        </div>
      )}

      <div className="filter-rail__scroll">
        <Group title="Time period">
          {PERIODS.map((p) => (
            <label
              key={p.key}
              className={`filter-option${filters.period === p.key ? ' filter-option--on' : ''}`}
            >
              <input
                type="radio"
                name="period"
                className="filter-option__input"
                checked={filters.period === p.key}
                onChange={() => onChange({ ...filters, period: p.key })}
              />
              <span className="filter-option__text">{p.label}</span>
            </label>
          ))}
        </Group>

        <Group title="Severity tier">
          {TIER_FILTERS.map((t) => (
            <Check
              key={t.key}
              checked={filters.tiers.includes(t.key)}
              onChange={() => toggle('tiers', t.key)}
              swatch={tierColor(t.key)}
            >
              {t.label}
            </Check>
          ))}
        </Group>

        <Group title="Road type">
          {ROAD_TYPES.map((t) => (
            <Check
              key={t}
              checked={filters.roadTypes.includes(t)}
              onChange={() => toggle('roadTypes', t)}
            >
              {t}
            </Check>
          ))}
        </Group>

        <Group title="Road class">
          {ROAD_CLASSES.map((t) => (
            <Check
              key={t}
              checked={filters.roadClasses.includes(t)}
              onChange={() => toggle('roadClasses', t)}
            >
              {t}
            </Check>
          ))}
        </Group>

        <Group title="Conditions">
          {CONDITIONS.map((c) => (
            <Check
              key={c.key}
              checked={filters.conditions.includes(c.key)}
              onChange={() => toggle('conditions', c.key)}
            >
              {c.label}
            </Check>
          ))}
        </Group>
      </div>

      <div className="filter-rail__foot">
        <button
          className="btn-tertiary"
          onClick={() => onChange(EMPTY_FILTERS)}
          disabled={isDefaultFilters(filters)}
        >
          Reset filters
        </button>
      </div>
    </div>
  );
}
