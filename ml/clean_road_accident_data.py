"""
Cleans Road_Accident_Data.csv (UK STATS19-derived, dates artificially shifted).

Fixes applied:
  1. Recovers the true accident date (fake year swapped back to real 2009/2010).
  2. Replaces the corrupted Accident_Index with a fresh unique accident_id.
  3. Fixes the 'Fetal' -> 'Fatal' typo in Accident_Severity.
  4. Relabels severity classes to Indian MoRTH/IRC convention:
       Slight  -> Minor
       Serious -> Grievous
       Fatal   -> Fatal

Run:
    python clean_road_accident_data.py path/to/Road_Accident_Data.csv path/to/output.csv
"""

import sys
import pandas as pd


def clean(input_path: str, output_path: str) -> pd.DataFrame:
    df = pd.read_csv(input_path, low_memory=False)
    print(f"Loaded {len(df)} rows.")

    # ------------------------------------------------------------------
    # STEP 1: Recover true dates.
    #
    # The date format is M/D/Y, not D/M/Y. Proof: many rows have a value
    # >12 in the second position (e.g. "1/16/2021") -- impossible as a
    # month, so this can only be month-first. Do NOT pass dayfirst=True.
    #
    # The year was shifted (2009/2010 -> 2021/2022) but month/day and
    # Day_of_Week were left untouched, which is what lets us recover it.
    # ------------------------------------------------------------------
    parsed = pd.to_datetime(df["Accident Date"], errors="raise")  # month-first
    months, days = parsed.dt.month, parsed.dt.day

    idx_str = df["Accident_Index"].astype(str)
    intact_mask = idx_str.str.startswith(("2009", "2010"))
    corrupted_mask = ~intact_mask
    print(f"Intact index: {intact_mask.sum()} | Corrupted index: {corrupted_mask.sum()}")

    final_year = pd.Series(index=df.index, dtype="int64")
    final_year[intact_mask] = idx_str[intact_mask].str[:4].astype(int)

    # For rows where Accident_Index is corrupted (~36% of rows, all showing
    # as "2.01E+12"), recover the true year by testing which of the two
    # known candidate years (2009, 2010) makes the reconstructed date's
    # weekday match the untouched Day_of_Week field.
    c_months, c_days = months[corrupted_mask], days[corrupted_mask]
    cand_2009 = pd.to_datetime({"year": 2009, "month": c_months, "day": c_days}).dt.day_name()
    cand_2010 = pd.to_datetime({"year": 2010, "month": c_months, "day": c_days}).dt.day_name()
    target = df.loc[corrupted_mask, "Day_of_Week"]

    match_09, match_10 = (cand_2009 == target), (cand_2010 == target)
    assert (match_09 | match_10).all(), "Found a row that matches neither candidate year"
    assert not (match_09 & match_10).any(), "Found an ambiguous row matching both years"

    resolved = pd.Series(index=df[corrupted_mask].index, dtype="int64")
    resolved[match_09] = 2009
    resolved[match_10] = 2010
    final_year[corrupted_mask] = resolved

    df["True_Accident_Date"] = pd.to_datetime({"year": final_year, "month": months, "day": days})

    # Verify against Day_of_Week for every row before trusting it.
    mismatches = (df["True_Accident_Date"].dt.day_name() != df["Day_of_Week"]).sum()
    print(f"Weekday validation: {mismatches} mismatches (must be 0)")
    assert mismatches == 0, "Date recovery failed validation -- do not proceed"

    df = df.drop(columns=["Accident Date"]).rename(columns={"True_Accident_Date": "Accident_Date"})

    # ------------------------------------------------------------------
    # STEP 2: Fresh unique ID.
    # Accident_Index is unusable as an ID -- 110,304 rows collapsed to the
    # identical corrupted string "2.01E+12" (a text->number->scientific
    # notation artifact). Kept as a reference column, not relied upon.
    # ------------------------------------------------------------------
    df = df.rename(columns={"Accident_Index": "Original_Accident_Index"})
    df.insert(0, "accident_id", range(1, len(df) + 1))

    # ------------------------------------------------------------------
    # STEP 3 & 4: Fix 'Fetal' typo and relabel severity to MoRTH/IRC scheme.
    # ------------------------------------------------------------------
    severity_map = {
        "Slight": "Minor",
        "Serious": "Grievous",
        "Fatal": "Fatal",
        "Fetal": "Fatal",  # typo fix
    }
    df["Accident_Severity"] = df["Accident_Severity"].map(severity_map)
    unmapped = df["Accident_Severity"].isna().sum()
    assert unmapped == 0, f"{unmapped} rows had a severity value outside the expected set"

    # ------------------------------------------------------------------
    # Save.
    # ------------------------------------------------------------------
    lead_cols = ["accident_id", "Accident_Date", "Day_of_Week", "Accident_Severity"]
    other_cols = [c for c in df.columns if c not in lead_cols + ["Original_Accident_Index"]]
    df = df[lead_cols + other_cols + ["Original_Accident_Index"]]

    df.to_csv(output_path, index=False)
    print(f"Saved: {output_path}")
    print(df["Accident_Severity"].value_counts())
    return df


if __name__ == "__main__":
    in_path = sys.argv[1] if len(sys.argv) > 1 else "Road_Accident_Data.csv"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "Road_Accident_Data_Cleaned.csv"
    clean(in_path, out_path)
