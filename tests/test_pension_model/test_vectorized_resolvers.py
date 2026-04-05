"""Unit tests for the vectorized config resolvers in plan_config.py.

Each vectorized resolver must produce bit-identical output to the scalar
equivalent across a grid of inputs, for both FRS and TRS plans.
"""
import numpy as np
import pytest

from pension_model.plan_config import (
    load_frs_config,
    load_txtrs_config,
    get_tier,
    get_ben_mult,
    get_reduce_factor,
    resolve_tiers_vec,
    resolve_cola_vec,
    resolve_ben_mult_vec,
    resolve_reduce_factor_vec,
)


# ---------------------------------------------------------------------------
# Grid construction
# ---------------------------------------------------------------------------

def _build_frs_grid():
    """Dense grid of inputs covering FRS tier boundaries and class variations."""
    classes = ["regular", "special", "admin", "eco", "eso", "judges",
               "senior_management"]
    # entry_year: around tier_1→tier_2 boundary (2011) and tier_2→tier_3 (new_year=2022)
    entry_years = [1970, 1990, 2000, 2010, 2011, 2015, 2020, 2021, 2022, 2025, 2030, 2040]
    ages = [20, 25, 30, 40, 50, 55, 58, 60, 62, 65, 68, 70, 75]
    yos_list = [0, 1, 5, 6, 8, 10, 15, 20, 25, 28, 30, 33, 35, 40]

    rows = []
    for cn in classes:
        for ey in entry_years:
            for age in ages:
                for yos in yos_list:
                    if age - yos >= 18 and age - yos <= age:
                        rows.append((cn, ey, age, yos))
    return rows


def _build_trs_grid():
    """Grid for TRS covering grandfathering cutoff (2005) and tier boundaries."""
    classes = ["all"]
    entry_years = [1970, 1980, 1990, 1995, 2000, 2003, 2004, 2005, 2006,
                   2008, 2010, 2011, 2015, 2020, 2024, 2030]
    ages = [20, 25, 30, 40, 50, 55, 60, 62, 65, 70]
    yos_list = [0, 1, 5, 10, 15, 20, 25, 30, 35, 40]

    rows = []
    for cn in classes:
        for ey in entry_years:
            for age in ages:
                for yos in yos_list:
                    if age - yos >= 18:
                        rows.append((cn, ey, age, yos))
    return rows


def _rows_to_arrays(rows):
    cn = np.array([r[0] for r in rows], dtype=object)
    ey = np.array([r[1] for r in rows], dtype=np.int64)
    age = np.array([r[2] for r in rows], dtype=np.int64)
    yos = np.array([r[3] for r in rows], dtype=np.int64)
    return cn, ey, age, yos


# ---------------------------------------------------------------------------
# resolve_tiers_vec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plan_loader,grid_builder", [
    (load_frs_config, _build_frs_grid),
    (load_txtrs_config, _build_trs_grid),
])
def test_resolve_tiers_vec_matches_scalar(plan_loader, grid_builder):
    config = plan_loader()
    rows = grid_builder()
    cn, ey, age, yos = _rows_to_arrays(rows)

    expected = np.array([
        get_tier(config, rows[i][0], int(ey[i]), int(age[i]), int(yos[i]))
        for i in range(len(rows))
    ], dtype=object)

    actual = resolve_tiers_vec(config, cn, ey, age, yos)

    mismatches = np.where(expected != actual)[0]
    if len(mismatches) > 0:
        diffs = [
            (rows[i], expected[i], actual[i])
            for i in mismatches[:10]
        ]
        pytest.fail(
            f"{len(mismatches)} / {len(rows)} mismatches. First 10: {diffs}"
        )


def test_resolve_tiers_vec_entry_age_override_frs():
    """entry_age array overrides age-yos derivation when positive."""
    config = load_frs_config()
    cn = np.array(["regular", "regular"], dtype=object)
    ey = np.array([2000, 2000], dtype=np.int64)
    age = np.array([40, 40], dtype=np.int64)
    yos = np.array([10, 10], dtype=np.int64)
    # Default entry_age = age - yos = 30
    # Override with 25 (earlier entry)
    ea_override = np.array([25, 0], dtype=np.int64)  # second row falls back

    actual = resolve_tiers_vec(config, cn, ey, age, yos, entry_age=ea_override)
    expected = np.array([
        get_tier(config, "regular", 2000, 40, 10, entry_age=25),
        get_tier(config, "regular", 2000, 40, 10, entry_age=30),
    ], dtype=object)
    assert np.array_equal(actual, expected)


# ---------------------------------------------------------------------------
# resolve_cola_vec
# ---------------------------------------------------------------------------

def _scalar_cola(config, tier_str, entry_year, yos):
    """Reproduces the _get_cola closure from build_ann_factor_table_compact."""
    cola_cutoff = config.cola_proration_cutoff_year
    for td in config.tier_defs:
        if td["name"] in tier_str:
            cola_key = td.get("cola_key", "tier_1_active")
            raw_cola = config.cola.get(cola_key, 0.0)
            if (cola_key == "tier_1_active"
                    and not config.cola.get("tier_1_active_constant", False)
                    and cola_cutoff is not None
                    and raw_cola > 0 and yos > 0):
                yos_b4 = min(max(cola_cutoff - entry_year, 0), yos)
                return raw_cola * yos_b4 / yos
            return raw_cola
    return 0.0


@pytest.mark.parametrize("plan_loader,grid_builder", [
    (load_frs_config, _build_frs_grid),
    (load_txtrs_config, _build_trs_grid),
])
def test_resolve_cola_vec_matches_scalar(plan_loader, grid_builder):
    config = plan_loader()
    rows = grid_builder()
    cn, ey, age, yos = _rows_to_arrays(rows)

    # First resolve tiers so we have realistic tier strings
    tiers = resolve_tiers_vec(config, cn, ey, age, yos)

    expected = np.array([
        _scalar_cola(config, tiers[i], int(ey[i]), int(yos[i]))
        for i in range(len(rows))
    ], dtype=np.float64)

    actual = resolve_cola_vec(config, tiers, ey, yos)

    assert np.allclose(actual, expected, equal_nan=True), \
        f"COLA mismatch. Max diff: {np.nanmax(np.abs(actual - expected))}"


# ---------------------------------------------------------------------------
# resolve_ben_mult_vec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plan_loader,grid_builder", [
    (load_frs_config, _build_frs_grid),
    (load_txtrs_config, _build_trs_grid),
])
def test_resolve_ben_mult_vec_matches_scalar(plan_loader, grid_builder):
    config = plan_loader()
    rows = grid_builder()
    cn, ey, age, yos = _rows_to_arrays(rows)

    # Resolve tiers; ben_mult uses tier_at_dist_age with dist_age=age
    tiers = resolve_tiers_vec(config, cn, ey, age, yos)
    # dist_year = entry_year + (age - entry_age) = entry_year + yos
    dist_year = ey + yos

    expected = np.array([
        get_ben_mult(config, rows[i][0], tiers[i], int(age[i]), int(yos[i]),
                     int(dist_year[i]))
        for i in range(len(rows))
    ], dtype=np.float64)

    actual = resolve_ben_mult_vec(config, cn, tiers, age, yos, dist_year)

    assert np.allclose(actual, expected, equal_nan=True), \
        f"ben_mult mismatch. Max diff: {np.nanmax(np.abs(actual - expected))}"


# ---------------------------------------------------------------------------
# resolve_reduce_factor_vec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("plan_loader,grid_builder", [
    (load_frs_config, _build_frs_grid),
    (load_txtrs_config, _build_trs_grid),
])
def test_resolve_reduce_factor_vec_matches_scalar(plan_loader, grid_builder):
    config = plan_loader()
    rows = grid_builder()
    cn, ey, age, yos = _rows_to_arrays(rows)

    tiers = resolve_tiers_vec(config, cn, ey, age, yos)

    expected = np.array([
        get_reduce_factor(config, rows[i][0], tiers[i], int(age[i]),
                          int(yos[i]), int(ey[i]))
        for i in range(len(rows))
    ], dtype=np.float64)

    actual = resolve_reduce_factor_vec(config, cn, tiers, age, yos, ey)

    # Both should match (including NaN positions)
    nan_match = np.isnan(expected) == np.isnan(actual)
    val_match = np.where(np.isnan(expected), True,
                         np.isclose(actual, expected, equal_nan=True))
    mismatches = np.where(~(nan_match & val_match))[0]
    if len(mismatches) > 0:
        diffs = [
            (rows[i], tiers[i], expected[i], actual[i])
            for i in mismatches[:10]
        ]
        pytest.fail(
            f"{len(mismatches)} / {len(rows)} reduce_factor mismatches. "
            f"First 10: {diffs}"
        )
