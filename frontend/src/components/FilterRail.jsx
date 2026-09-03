import { X } from '@phosphor-icons/react';
import { TIER_FILTERS, EMPTY_FILTERS, isDefaultFilters } from '../lib/filters.js';
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

function Check({ checked, onChange, children, swatch, wrap = false }) {
  return (
    <label
      className={`filter-option${checked ? ' filter-option--on' : ''}${
        wrap ? ' filter-option--wrap' : ''
      }`}
    >
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
    ...filters.tiers.map((t) => ({
      key: `tier:${t}`,
      label: TIER_FILTERS.find((x) => x.key === t).label,
      clear: () => toggle('tiers', t),
    })),
    ...(filters.includeThin
      ? [
          {
            key: 'thin',
            label: 'Thinly-evidenced included',
            clear: () => onChange({ ...filters, includeThin: false }),
          },
        ]
      : []),
    ...(filters.road.trim()
      ? [
          {
            key: 'road',
            label: filters.road.trim(),
            clear: () => onChange({ ...filters, road: '' }),
          },
        ]
      : []),
  ];

  return (
    <div className="filter-rail">
      <div className="filter-rail__head">
        <h2 className="panel-title">Filters</h2>
        <p className="filter-rail__count readout">
          {resultCount} of {totalCount} segments in view
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
        <Group title="Risk tier">
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

        <Group title="Evidence">
          <Check
            wrap
            checked={filters.includeThin}
            onChange={() => onChange({ ...filters, includeThin: !filters.includeThin })}
          >
            Include thinly-evidenced segments (fewer than 6 recorded crashes)
          </Check>
          <p className="filter-group__note">
            86% of segments rest on fewer than six recorded crashes, and the tier
            boundaries are calibrated against the ones that clear the floor.
            Included segments are drawn dimmed.
          </p>
        </Group>

        <Group title="Road">
          <label className="field filter-rail__field">
            <span className="sr-only">Filter by road number or stretch</span>
            <input
              className="input"
              type="text"
              value={filters.road}
              placeholder="A23, M1, ..."
              autoComplete="off"
              onChange={(e) => onChange({ ...filters, road: e.target.value })}
            />
          </label>
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
