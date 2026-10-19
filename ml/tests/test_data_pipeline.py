"""Download validation, casualty aggregation and coordinate handling."""
import zipfile

import numpy as np
import pandas as pd
import pytest

from blackspot.download import csv_is_complete, zip_is_complete
from blackspot.stats19 import aggregate_casualties, check_collision_casualty_consistency, to_bng


def test_complete_csv_passes(tmp_path):
    p = tmp_path / "ok.csv"
    p.write_text('a,b,c\n1,"x,y",3\n4,5,6\n')
    assert csv_is_complete(p)[0]


def test_truncated_csv_fails(tmp_path):
    # The real failure: a download that stops mid-record still parses as CSV.
    p = tmp_path / "cut.csv"
    p.write_text("a,b,c\n1,2,3\n4,5")
    ok, why = csv_is_complete(p)
    assert not ok and "2 fields" in why


def test_corrupt_zip_fails(tmp_path):
    p = tmp_path / "z.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("x.csv", "a,b\n" * 1000)
    data = bytearray(p.read_bytes())
    data[60] ^= 0xFF                                   # flip a byte inside the member
    p.write_bytes(bytes(data))
    assert not zip_is_complete(p)[0]


@pytest.fixture
def casualties():
    # collision A: 1 fatal + 1 slight; B: 2 serious (one by adjustment 0.7); C: 1 slight (adj 0.2)
    return pd.DataFrame({
        "collision_index": ["A", "A", "B", "B", "C"],
        "collision_year": [2020] * 5,
        "vehicle_reference": [1, 2, 1, 1, 1],
        "casualty_reference": [1, 2, 1, 2, 1],
        "casualty_severity": [1, 3, 2, 2, 3],
        "casualty_injury_based": [1, 1, 0, 0, 0],
        "casualty_adjusted_severity_serious": [0.0, 0.0, 1.0, 0.7, 0.2],
    })


def test_aggregation_is_collision_grain(casualties):
    agg = aggregate_casualties(casualties).set_index("collision_index")
    assert len(agg) == 3 and agg.index.is_unique
    assert agg.loc["A", "n_cas"] == 2 and agg.loc["A", "n_ksi_cas"] == 1
    assert agg.loc["B", "n_ksi_cas"] == 2
    assert agg.loc["C", "n_ksi_cas"] == 0


def test_adjusted_ksi_counts_fatal_as_one(casualties):
    agg = aggregate_casualties(casualties).set_index("collision_index")
    assert agg.loc["A", "adj_ksi_cas"] == pytest.approx(1.0)     # fatal=1, slight adj 0
    assert agg.loc["B", "adj_ksi_cas"] == pytest.approx(1.7)
    assert agg.loc["C", "adj_ksi_cas"] == pytest.approx(0.2)


def test_join_does_not_multiply_collisions(casualties):
    coll = pd.DataFrame({"collision_index": ["A", "B", "C", "D"],
                         "number_of_casualties": [2, 2, 1, 1],
                         "collision_severity": [1, 2, 3, 3]})
    agg = aggregate_casualties(casualties)
    m = coll.merge(agg, on="collision_index", how="left", validate="one_to_one")
    assert len(m) == len(coll)
    q = check_collision_casualty_consistency(m)
    assert q["without_casualty_rows"] == 1
    assert q["n_cas_equals_number_of_casualties"] == 1.0
    assert q["worst_casualty_equals_collision_severity"] == 1.0


def test_bng_projection_known_point():
    # Ordnance Survey's documented example: Caister water tower
    # (52.6580 N, 1.7162 E) ~ E651409, N313177 (OSGB36 via WGS84, Helmert-level accuracy).
    e, n = to_bng([1.716073973], [52.658007833])
    assert abs(e[0] - 651409.9) < 10 and abs(n[0] - 313177.3) < 10


def test_bng_distances_are_metric():
    e, n = to_bng([-0.1, -0.1], [51.5, 51.509])         # ~1 km north
    assert 990 < np.hypot(e[1] - e[0], n[1] - n[0]) < 1010
