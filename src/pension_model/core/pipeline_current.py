"""Current retiree and term-vested liability helpers."""

import numpy as np
import pandas as pd


def _pv_annuity(rate, g, nper, pmt, t=1):
    """R's pv() — present value of growing annuity."""
    r = (1 + rate) / (1 + g) - 1
    if abs(r) < 1e-10:
        return pmt * nper / (1 + g) * (1 + rate) ** (1 - t)
    return pmt / r * (1 - 1 / (1 + r) ** nper) / (1 + g) * (1 + rate) ** (1 - t)


def _get_pmt(r, g, nper, pv_val, t=1):
    """R's get_pmt() — amortization payment with growth."""
    r_adj = (1 + r) / (1 + g) - 1
    pv_adj = pv_val * (1 + r) ** t
    if abs(r_adj) < 1e-10:
        return pv_adj / nper if nper > 0 else 0
    if nper == 0:
        return 0
    return pv_adj * r_adj * (1 + r_adj) ** (nper - 1) / ((1 + r_adj) ** nper - 1)


def _recur_grow(x, g):
    """R's recur_grow: x[i] = x[i-1] * (1 + g[i-1]) — lagged growth."""
    out = x.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] * (1 + g[i - 1])
    return out


def _recur_grow2(x, g):
    """R's recur_grow2: x[i] = x[i-1] * (1 + g[i]) — no lag."""
    out = x.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] * (1 + g[i])
    return out


def _recur_grow3(x, g, nper):
    """R's recur_grow3: grow single value at fixed rate for nper periods."""
    vec = np.zeros(nper)
    vec[0] = x
    for i in range(1, nper):
        vec[i] = vec[i - 1] * (1 + g)
    return vec


def _roll_pv(rate, g, nper, pmt_vec, t=1):
    """R's roll_pv: rolling present value of payment stream."""
    n = len(pmt_vec)
    pv_vec = np.zeros(n)
    for i in range(n):
        if i == 0:
            pv_vec[i] = _pv_annuity(rate, g, nper, pmt_vec[1] if n > 1 else 0, t)
        else:
            pv_vec[i] = pv_vec[i - 1] * (1 + rate) - pmt_vec[i] * (1 + rate) ** (1 - t)
    return pv_vec


def _npv(rate, cashflows):
    """Net present value of a cashflow stream (R's npv function)."""
    pv = 0.0
    for i, cf in enumerate(cashflows):
        pv += cf / (1 + rate) ** (i + 1)
    return pv


def _roll_npv(rate, cashflows):
    """Rolling NPV: NPV at each point looking forward (R's roll_npv)."""
    n = len(cashflows)
    pv_vec = np.zeros(n)
    for i in range(n - 1):
        pv_vec[i] = _npv(rate, cashflows[i + 1 :])
    return pv_vec


def compute_current_retiree_liability(
    ann_factor_retire: pd.DataFrame,
    retiree_distribution: pd.DataFrame,
    retiree_pop: float,
    ben_payment_current: float,
    constants,
) -> pd.DataFrame:
    """
    Project current retiree AAL (R liability model lines 204-234).

    Uses ann_factor_retire_table with mortality and COLA to project
    current retiree population and benefits forward.
    """
    ranges = constants.ranges

    init = retiree_distribution[["age", "n_retire_ratio", "total_ben_ratio"]].copy()
    init["n_retire_current"] = init["n_retire_ratio"] * retiree_pop
    init["total_ben_current"] = init["total_ben_ratio"] * ben_payment_current
    init["avg_ben_current"] = init["total_ben_current"] / init["n_retire_current"]
    init_by_age = init.set_index("age")[["n_retire_current", "avg_ben_current"]]

    ann_factor_retire = ann_factor_retire[
        ann_factor_retire["year"] <= ranges.start_year + ranges.model_period
    ]

    projected_groups = []
    for base_age, group in ann_factor_retire.groupby("base_age"):
        if base_age not in init_by_age.index:
            continue

        g = group.sort_values("year").copy()
        init_row = init_by_age.loc[base_age]
        n = _recur_grow(
            np.full(len(g), float(init_row["n_retire_current"])),
            -g["mort_final"].to_numpy(copy=False),
        )
        avg = _recur_grow2(
            np.full(len(g), float(init_row["avg_ben_current"])),
            g["cola"].to_numpy(copy=False),
        )

        g["n_retire_current"] = n
        g["avg_ben_current"] = avg
        g["total_ben_current"] = n * avg
        g["pvfb_retire_current"] = avg * (g["ann_factor_retire"].to_numpy(copy=False) - 1)
        projected_groups.append(
            g[["year", "n_retire_current", "total_ben_current", "pvfb_retire_current"]]
        )

    projected = pd.concat(projected_groups, ignore_index=True)

    return projected.groupby("year").agg(
        retire_ben_current_est=("total_ben_current", "sum"),
        aal_retire_current_est=pd.NamedAgg(
            "pvfb_retire_current",
            aggfunc=lambda x: (x * projected.loc[x.index, "n_retire_current"]).sum(),
        ),
    ).reset_index()


def compute_current_term_vested_liability(
    cashflow_stream: np.ndarray,
    pvfb_term_current: float,
    constants,
) -> pd.DataFrame:
    """Project current term-vested AAL year-by-year from a pre-built cashflow stream.

    The stream is constructed in upstream data prep (see
    ``prep/{plan}/methods/term_vested_*.md``) and read from
    ``plans/{plan}/data/funding/current_term_vested_cashflow.csv`` at
    plan-load time. The runtime is method-agnostic: it just discounts
    whatever per-year payments it gets at the scenario discount rate.

    Args:
        cashflow_stream: per-year payments at year_offset 1..N (length
            depends on the per-plan method; e.g. 50 for FRS legacy,
            D+L for the deferred-annuity method). Empty array when the
            CSV is missing — supported during calibration where
            pvfb_term_current is 0.
        pvfb_term_current: per-class PVFB at baseline rate (the input
            against which the stream was calibrated). Used here only
            to detect the calibration-time "no stream and no PVFB"
            case.
        constants: PlanConfig.
    """
    ranges = constants.ranges
    valuation_rate = constants.economic.dr_current
    n_years = ranges.model_period + 1
    years = list(range(ranges.start_year, ranges.start_year + n_years))

    if len(cashflow_stream) == 0:
        if pvfb_term_current != 0:
            raise FileNotFoundError(
                "No term-vested cashflow stream available, but "
                f"pvfb_term_current={pvfb_term_current}. Run the plan's "
                "term-vested cashflow build script "
                "(scripts/build/build_*_term_vested_cashflow.py) to "
                "generate the per-plan "
                "data/funding/current_term_vested_cashflow.csv."
            )
        return pd.DataFrame(
            {
                "year": years,
                "retire_ben_term_est": np.zeros(n_years),
                "aal_term_current_est": np.zeros(n_years),
            }
        )

    full_stream = np.concatenate(([0.0], np.asarray(cashflow_stream, dtype=float)))

    retire_ben_term_est = np.zeros(n_years)
    take = min(len(full_stream), n_years)
    retire_ben_term_est[:take] = full_stream[:take]

    aal_full = _roll_npv(valuation_rate, full_stream)
    aal_term_current = np.zeros(n_years)
    take_aal = min(len(aal_full), n_years)
    aal_term_current[:take_aal] = aal_full[:take_aal]

    return pd.DataFrame(
        {
            "year": years,
            "retire_ben_term_est": retire_ben_term_est,
            "aal_term_current_est": aal_term_current,
        }
    )
