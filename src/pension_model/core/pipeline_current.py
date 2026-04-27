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


def compute_current_term_vested_liability(class_name: str, constants) -> pd.DataFrame:
    """
    Compute current term vested AAL (R liability model lines 238-248 / 286-310).

    Method is config-driven via ``funding.term_vested_method``:
      - "growing_annuity": amortizes pvfb_term_current as a growing payment stream
      - "bell_curve": uses normal distribution weighting of payments
    """
    ranges = constants.ranges
    class_data = constants.class_data[class_name]

    pvfb_term_current = class_data.pvfb_term_current
    # The synthetic payment stream is sized at the rate the input PVFB
    # was published at (baseline dr_current); the resulting stream is
    # then PV'd at the scenario dr_current. See docs/discount_rate_scenarios.md.
    cashflow_rate = constants.economic.baseline_dr_current
    valuation_rate = constants.economic.dr_current
    payroll_growth = constants.economic.payroll_growth
    amo_period = constants.funding.amo_period_term
    years = list(range(ranges.start_year, ranges.start_year + ranges.model_period + 1))

    if constants.term_vested_method == "bell_curve":
        mid = amo_period / 2
        spread = amo_period / 5
        amo_seq = np.arange(1, amo_period + 1)
        amo_weights = (1 / (spread * np.sqrt(2 * np.pi))) * np.exp(
            -0.5 * ((amo_seq - mid) / spread) ** 2
        )
        ann_ratio = amo_weights / amo_weights[0]

        first_payment = pvfb_term_current / _npv(cashflow_rate, ann_ratio)
        term_payments = first_payment * ann_ratio
        full_stream = np.concatenate(([0.0], term_payments))
        full_aal = _roll_npv(valuation_rate, full_stream)

        retire_ben_term_est = np.zeros(len(years))
        aal_term_current = np.zeros(len(years))
        for i in range(len(years)):
            if i < len(full_stream):
                retire_ben_term_est[i] = full_stream[i]
            if i < len(full_aal):
                aal_term_current[i] = full_aal[i]
    else:
        retire_ben_term = _get_pmt(cashflow_rate, payroll_growth, amo_period, pvfb_term_current, t=1)
        amo_years = list(range(ranges.start_year + 1, ranges.start_year + 1 + amo_period))
        retire_ben_term_est = np.zeros(len(years))
        term_payments = _recur_grow3(retire_ben_term, payroll_growth, amo_period)
        for i, year in enumerate(years):
            if year in amo_years:
                idx = year - (ranges.start_year + 1)
                if idx < len(term_payments):
                    retire_ben_term_est[i] = term_payments[idx]

        aal_term_current = _roll_pv(
            valuation_rate,
            payroll_growth,
            amo_period,
            retire_ben_term_est,
            t=1,
        )

    return pd.DataFrame(
        {
            "year": years,
            "retire_ben_term_est": retire_ben_term_est,
            "aal_term_current_est": aal_term_current,
        }
    )
