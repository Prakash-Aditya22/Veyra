# Coverage analysis: how much of Great Britain's KSI burden does the ranking cover?

Source: `coverage_summary.json`, `coverage_buckets.csv`, `coverage_by_stats19_class.csv`
(`pipeline.py coverage`), and `coverage_by_population.csv` (`pipeline.py holdout`). Every
percentage below uses the **national** total for the stated window as its
denominator: all GB collisions, including ones with no location and ones not on
a scored road.

## 1. v1 vs v2 on the same denominator

National KSI **collisions** 2022–2023 = 49,895 (v1's target unit).

| Population | Share of national 2022–23 KSI collisions |
|---|---|
| v1: numbered roads only | 61.2% |
| v1: roads with ≥ 60 crashes in 2019–**2023** (eligibility used the target period) | 45.6% |
| **v1: scored segments** (≥ 1 crash in 2019–21) | **36.8%** |
| v1: held-out test segments (the evaluation denominator) | 10.9% |
| **v2: scored network** (all M/A/B/C/U/N segments, no history condition) | **97.8%** |

Why v1 covered so little:
1. **C and unclassified roads were excluded.** They carry 38.8% of national KSI collisions. STATS19 records no number for them, and v1 keyed roads by number.
2. **Roads with < 60 crashes were excluded**, a threshold applied using target-period crashes.
3. **Road without a 2019–21 crash had no segment**, so KSI on previously crash-free road was invisible by construction.

v2 fixes all three by segmenting the OS Open Roads centreline network and
scoring every segment of every public-road class.

## 2. Where the remaining ~2.3% goes

| Window / outcome | National total | Scored | Access roads (not scored) | No road ≤ 50 m | No coordinates |
|---|---|---|---|---|---|
| 2022–23 adjusted KSI casualties | 57,898.8 | 97.85% | 1.96% | 0.16% | 0.02% |
| 2022–23 reported KSI casualties | 55,185 | 97.90% | 1.94% | 0.15% | 0.02% |
| 2022–23 KSI collisions | 49,895 | 97.83% | 2.00% | 0.15% | 0.02% |
| **2024–25 adjusted KSI casualties (holdout target)** | **58,794.4** | **97.71%** | 2.16% | 0.13% | 0.00% |
| 2024–25 reported KSI casualties | 56,938 | 97.72% | 2.16% | 0.12% | 0.00% |
| 2024–25 KSI collisions | 51,713 | 97.61% | 2.27% | 0.12% | 0.00% |
| 2023–25 adjusted KSI (forecast history) | 87,767.4 | 97.73% | 2.12% | 0.15% | 0.01% |

- **Access roads** are OS Open Roads class "Unknown": restricted local access and secondary access roads (private estates, service roads, car-park access). They stay in the network for assignment, so crashes on them are not pushed onto adjacent public roads, but they are not ranked. Nearly all of this KSI comes from crashes police coded as unclassified (5.9% of unclassified-road KSI).
- **No road within 50 m**: realigned roads since the crash, car parks or land, or location errors. Rates by year are 0.1–0.5%, highest in 2016–18, consistent with a 2026 network applied to older crashes.

## 3. By police-recorded road class (2024–25, adjusted KSI)

| STATS19 class | Share of national KSI | Of which on scored segments |
|---|---|---|
| A | 44.0% | 99.8% |
| Unclassified | 35.1% | 93.9% |
| B | 14.1% | 99.9% |
| C | 3.7% | 99.5% |
| Motorway | 2.8% | 99.9% |
| A(M) | 0.3% | 99.9% |

By OS class of the assigned segment, scored KSI 2024–25 splits A 43.9%,
unclassified 24.1%, B 14.2%, C 11.1%, M 3.1%, Not Classified 1.3%. The police
"C" and "unclassified" codes do not line up with OS classification (see
`data_quality.md` §8), so class-level shares differ between the two schemes
while totals agree.

## 4. Subset performance vs national performance

Coverage is not accuracy. Capture percentages in `model_comparison.csv` are
always *within* a population, and `coverage_by_population.csv` gives that
population's share of the national total. For example, a top-10% capture
measured on `numbered` (M/A/B segments) describes ~62% of national KSI, not all
of Great Britain, and must not be quoted as national performance. The figures
quoted in `final_audit.md` and the README name their population each time.

## 5. Exposure coverage

AADF exists for motorway and A-road links only (minor-road counts are a thin
sample). Segments with an AADF matched in **both** the training and test history
windows form the `exposure` population. On the final holdout that is **131,531
segments, 47,021 km, 42.8% of national adjusted KSI** (2024–25). It was 43.8% on the
2021 development fold. The remaining ~57% (B, C, unclassified roads and
unmatched M/A segments) has **no defensible exposure denominator** and carries
no rate. In the production output, 132,899 M/A segments carry an AADF for the
2023–25 window (`exposure_available`).
