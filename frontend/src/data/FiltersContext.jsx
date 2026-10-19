import { createContext, useContext, useMemo, useState } from 'react';
import { EMPTY_FILTERS } from '../lib/filters.js';

/* One filter state shared by the explorer and the statistics screen, so "the current
   selection" means the same thing on both. */
const FiltersContext = createContext(null);

export function FiltersProvider({ children }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const value = useMemo(() => ({ filters, setFilters }), [filters]);
  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>;
}

export function useFilters() {
  const ctx = useContext(FiltersContext);
  if (!ctx) throw new Error('useFilters must be used inside <FiltersProvider>');
  return ctx;
}
