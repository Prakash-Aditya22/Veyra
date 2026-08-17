/*
  DEMONSTRATION FIXTURE, dataset-level series.

  These two series describe every record in the coverage window, not only the
  records that fell inside a detected cluster. They are therefore not affected
  by the explorer's filters, and the charts that use them say so beneath their
  titles.

  Both series total 21,847, matching DATASET.records in ./blackspots.js.
*/

/** Calendar-month totals aggregated across 2019 to 2024. */
export const BY_MONTH = [
  { month: 'Jan', count: 1642 },
  { month: 'Feb', count: 1518 },
  { month: 'Mar', count: 1687 },
  { month: 'Apr', count: 1739 },
  { month: 'May', count: 1804 },
  { month: 'Jun', count: 1926 },
  { month: 'Jul', count: 2081 },
  { month: 'Aug', count: 2043 },
  { month: 'Sep', count: 1897 },
  { month: 'Oct', count: 1854 },
  { month: 'Nov', count: 1893 },
  { month: 'Dec', count: 1763 },
];

/** Severity split by year of record. */
export const BY_YEAR_SEVERITY = [
  { year: '2019', fatal: 412, serious: 1104, slight: 2183 },
  { year: '2020', fatal: 298, serious: 842, slight: 1687 },
  { year: '2021', fatal: 371, serious: 1023, slight: 2054 },
  { year: '2022', fatal: 438, serious: 1187, slight: 2361 },
  { year: '2023', fatal: 461, serious: 1246, slight: 2438 },
  { year: '2024', fatal: 447, serious: 1198, slight: 2097 },
];

/** Model-run summary, quoted on the methodology block of the landing page. */
export const MODEL_RUN = {
  algorithm: 'DBSCAN on projected coordinates',
  epsilonMetres: 180,
  minSamples: 12,
  silhouette: 0.61,
  classifier: 'Gradient-boosted trees, severity three-class',
  macroF1: 0.73,
  recallFatal: 0.68,
};
