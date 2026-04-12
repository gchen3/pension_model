"""
Funding model core: the two compute functions.

This module holds the two long-running funding compute functions —
``_compute_funding_corridor`` (5-year corridor smoothing, multi-class
plan-aggregate) and ``_compute_funding_gainloss`` (4-year gain/loss
deferral, single-class) — moved out of ``funding_model.py`` so the
public module is a thin entry point.

Both functions receive their AVA smoothing strategy and contribution
strategy by direct instantiation; ``run_funding_model`` (in
``funding_model.py``) selects which core function to call based on the
``funding.ava_smoothing.method`` config field, not on class count.

The two function bodies remain separate by design: a single merged
year loop would have to handle ~12 schema and control-flow differences
between the corridor and gain/loss paths via column-presence detection
and multiple config flags, and a single misplaced operation would
silently break R-baseline reproduction. The strategy abstractions and
helpers in ``_funding_helpers.py`` and ``_funding_strategies.py``
already give a future plan everything it needs to add a third path
without changing either of these functions.

Bit-identity constraints (preserved from the original implementations):
  * Mid-year exponent ``(1 + dr) ** 0.5`` is computed inside helpers
    from a scalar ``dr``, never from a precomputed ``sqrt_factor``.
  * Aggregate accumulation order matches the original single-cell
    write order; do not convert to bulk ``f.loc[i, cols] = values``.
  * The corridor function uses ``agg`` as the local variable name for
    the plan-aggregate frame; the original code called it ``frs``.
"""

import numpy as np
import pandas as pd

from pension_model.core.pipeline import _get_pmt
from pension_model.core._funding_helpers import (
    _aal_rollforward,
    _accumulate_to_aggregate,
    _get_init_row,
    _mva_rollforward,
    _populate_calibrated_nc_rates,
    _roll_amort_layer,
    _solvency_cont,
)
from pension_model.core._funding_strategies import (
    ActuarialContributions,
    CorridorSmoothing,
    GainLossSmoothing,
    RateComponent,
    StatutoryContributions,
)


def _resolve_er_rate_components(funding_raw: dict) -> list:
    """Build the list of statutory employer rate components from config.

    Reads ``funding.statutory_rates.er_rate_components`` (a list of
    component dicts) and returns the corresponding list of
    ``RateComponent`` objects. Each dict is passed to
    ``RateComponent.from_config``.

    A plan that uses the statutory contribution strategy must declare
    its components explicitly — there are no hardcoded defaults.
    """
    stat_rates = funding_raw.get("statutory_rates", {})
    components = stat_rates.get("er_rate_components")
    if components is None:
        raise ValueError(
            "funding.statutory_rates.er_rate_components is required when "
            "using the statutory contribution strategy. See "
            "plans/txtrs/config/plan_config.json for an example schema."
        )
    return [RateComponent.from_config(c) for c in components]


def _compute_funding_corridor(
    liability_results: dict,
    funding_inputs: dict,
    constants,
) -> dict:
    """Corridor-smoothing funding model (multi-class, plan-aggregate AVA).

    Args:
        liability_results: Dict mapping class_name -> liability pipeline output DataFrame.
        funding_inputs: Output of load_funding_inputs().
        constants: Plan configuration.

    Returns:
        Dict mapping class_name -> funding DataFrame, plus the
        ``constants.plan_name`` aggregate frame and an optional
        ``"drop"`` frame for plans with ``has_drop=true``.
    """
    # Local import to avoid a circular import via funding_model.py.
    from pension_model.core.funding_model import build_amort_period_tables

    econ = constants.economic
    fund_params = constants.funding
    r = constants.ranges
    init_funding = funding_inputs["init_funding"]
    amort_layers = funding_inputs["amort_layers"]
    return_scenarios = funding_inputs["return_scenarios"]

    dr_current = econ.dr_current
    dr_new = econ.dr_new
    dr_old = econ.dr_old
    payroll_growth = econ.payroll_growth
    amo_pay_growth = fund_params.amo_pay_growth
    amo_period_new = fund_params.amo_period_new
    funding_lag = fund_params.funding_lag
    db_ee_cont_rate = constants.benefit.db_ee_cont_rate
    inflation = econ.inflation

    # AVA smoothing strategy: corridor at the plan-aggregate level.
    ava_strategy = CorridorSmoothing()

    # Contribution strategy: calibrated NC rates + amort-table-driven amort.
    cont_strategy = ActuarialContributions(db_ee_cont_rate=db_ee_cont_rate)

    model_period = r.model_period
    start_year = r.start_year
    n_years = model_period + 1

    class_names = list(constants.classes)
    agg_name = constants.plan_name
    has_drop = constants.raw.get("funding", {}).get("has_drop", False)
    drop_ref_class = constants.raw.get("funding", {}).get("drop_reference_class", class_names[0])
    all_classes = class_names + (["drop"] if has_drop else [])

    # Return scenario setup — select which column of return_scenarios to use.
    # "assumption" (default) → assets earn dr_current each year.
    # "model" → assets earn model_return each year.
    # Other columns (e.g. "recession") use their pre-loaded values.
    return_scen_col = constants.raw.get("economic", {}).get("return_scen", "assumption")
    ret_scen = return_scenarios.copy()
    # Year 1 (start_year+1) keeps its CSV values (actual realized return).
    # Years after that use model_return / dr_current as the projected path.
    first_proj_year = r.start_year + 2  # year after the first projection year
    ret_scen.loc[ret_scen["year"] >= first_proj_year, "model"] = econ.model_return
    ret_scen.loc[ret_scen["year"] >= first_proj_year, "assumption"] = dr_current

    if fund_params.amo_method == "level $":
        amo_pay_growth = 0

    # Initialize funding tables
    funding = {}
    for cn in all_classes + [agg_name]:
        init_row = _get_init_row(init_funding, cn)
        cols = [c for c in init_funding.columns if c != "class"]
        df = pd.DataFrame(0.0, index=range(n_years), columns=cols)
        df["year"] = range(start_year, start_year + n_years)
        for col in cols:
            if col != "year":
                val = init_row.get(col, 0)
                df.loc[0, col] = float(val if pd.notna(val) else 0)
        funding[cn] = df

    # Calibration
    for cn in class_names:
        f = funding[cn]
        liab = liability_results[cn]

        for ratio_col, num_col, denom_col in [
            ("payroll_db_legacy_ratio", "payroll_db_legacy_est", "total_payroll_est"),
            ("payroll_db_new_ratio", "payroll_db_new_est", "total_payroll_est"),
            ("payroll_dc_legacy_ratio", "payroll_dc_legacy_est", "total_payroll_est"),
            ("payroll_dc_new_ratio", "payroll_dc_new_est", "total_payroll_est"),
        ]:
            if ratio_col not in f.columns:
                f[ratio_col] = 0.0
            denom = liab[denom_col].values
            ratios = np.divide(liab[num_col].values, denom,
                               out=np.zeros_like(denom), where=denom != 0)
            f.loc[1:, ratio_col] = ratios[:-1]

        if "nc_rate_db_legacy" not in f.columns:
            f["nc_rate_db_legacy"] = 0.0
            f["nc_rate_db_new"] = 0.0

        # NC rate calibration: R multiplies liability NC rates by nc_cal
        # nc_cal = val_norm_cost / model_norm_cost (additional adjustment beyond cal_factor=0.9)
        nc_cal = constants.class_data[cn].nc_cal
        _populate_calibrated_nc_rates(f, liab, nc_cal, n_years)

        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
        f.loc[0, "total_aal"] = liab["total_aal_est"].iloc[0]
        f.loc[0, "ual_ava_legacy"] = f.loc[0, "aal_legacy"] - f.loc[0, "ava_legacy"]
        f.loc[0, "total_ual_ava"] = f.loc[0, "total_aal"] - f.loc[0, "total_ava"]

        funding[cn] = f

    # Amortization tables
    amo_tables = {}
    for cn in all_classes:
        cur_per, fut_per, init_bal, max_col = build_amort_period_tables(
            amort_layers, cn, amo_period_new, funding_lag, model_period)

        cur_debt = np.zeros((n_years, max_col + 1))
        if len(init_bal) > 0:
            cur_debt[0, :len(init_bal)] = init_bal
        fut_debt = np.zeros((n_years, max_col + 1))

        cur_pay = np.zeros((n_years, max_col))
        for j in range(max_col):
            if cur_per[0, j] > 0 and abs(cur_debt[0, j]) > 1e-6:
                cur_pay[0, j] = _get_pmt(dr_old, amo_pay_growth, int(cur_per[0, j]),
                                         cur_debt[0, j], t=0.5)
        if funding_lag > 0:
            cur_pay[0, :funding_lag] = 0

        fut_pay = np.zeros((n_years, max_col))

        amo_tables[cn] = {
            "cur_per": cur_per, "fut_per": fut_per,
            "cur_debt": cur_debt, "fut_debt": fut_debt,
            "cur_pay": cur_pay, "fut_pay": fut_pay,
            "max_col": max_col,
        }

    # ========== Main year loop ==========
    for i in range(1, n_years):
        agg = funding[agg_name]

        # --- Membership classes ---
        for cn in class_names:
            f = funding[cn]
            liab = liability_results[cn]

            f.loc[i, "total_payroll"] = f.loc[i - 1, "total_payroll"] * (1 + payroll_growth)
            f.loc[i, "payroll_db_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_legacy_ratio"]
            f.loc[i, "payroll_db_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_new_ratio"]
            f.loc[i, "payroll_dc_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_legacy_ratio"]
            f.loc[i, "payroll_dc_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_new_ratio"]

            _accumulate_to_aggregate(agg, f, i, [
                "total_payroll", "payroll_db_legacy", "payroll_db_new",
                "payroll_dc_legacy", "payroll_dc_new",
            ])

            f.loc[i, "ben_payment_legacy"] = (liab["retire_ben_db_legacy_est"].iloc[i]
                + liab["retire_ben_current_est"].iloc[i] + liab["retire_ben_term_est"].iloc[i])
            f.loc[i, "refund_legacy"] = liab["refund_db_legacy_est"].iloc[i]
            f.loc[i, "ben_payment_new"] = liab["retire_ben_db_new_est"].iloc[i]
            f.loc[i, "refund_new"] = liab["refund_db_new_est"].iloc[i]
            f.loc[i, "total_ben_payment"] = f.loc[i, "ben_payment_legacy"] + f.loc[i, "ben_payment_new"]
            f.loc[i, "total_refund"] = f.loc[i, "refund_legacy"] + f.loc[i, "refund_new"]

            _accumulate_to_aggregate(agg, f, i, [
                "ben_payment_legacy", "refund_legacy",
                "ben_payment_new", "refund_new",
                "total_ben_payment", "total_refund",
            ])

            f.loc[i, "nc_legacy"] = f.loc[i, "nc_rate_db_legacy"] * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "nc_new"] = f.loc[i, "nc_rate_db_new"] * f.loc[i, "payroll_db_new"]
            pdb = f.loc[i, "payroll_db_legacy"] + f.loc[i, "payroll_db_new"]
            f.loc[i, "total_nc_rate"] = (f.loc[i, "nc_legacy"] + f.loc[i, "nc_new"]) / pdb if pdb > 0 else 0
            _accumulate_to_aggregate(agg, f, i, ["nc_legacy", "nc_new"])

            # Under baseline (experience = assumptions), gain/loss = 0
            f.loc[i, "liability_gain_loss_legacy"] = liab["liability_gain_loss_legacy_est"].iloc[i] if "liability_gain_loss_legacy_est" in liab.columns else 0
            f.loc[i, "liability_gain_loss_new"] = liab["liability_gain_loss_new_est"].iloc[i] if "liability_gain_loss_new_est" in liab.columns else 0

            f.loc[i, "aal_legacy"] = _aal_rollforward(
                aal_prev=f.loc[i - 1, "aal_legacy"],
                nc=f.loc[i, "nc_legacy"],
                ben=f.loc[i, "ben_payment_legacy"],
                refund=f.loc[i, "refund_legacy"],
                liab_gl=f.loc[i, "liability_gain_loss_legacy"],
                dr=dr_current,
            )
            f.loc[i, "aal_new"] = _aal_rollforward(
                aal_prev=f.loc[i - 1, "aal_new"],
                nc=f.loc[i, "nc_new"],
                ben=f.loc[i, "ben_payment_new"],
                refund=f.loc[i, "refund_new"],
                liab_gl=f.loc[i, "liability_gain_loss_new"],
                dr=dr_new,
            )
            f.loc[i, "total_aal"] = f.loc[i, "aal_legacy"] + f.loc[i, "aal_new"]

            _accumulate_to_aggregate(agg, f, i, [
                "aal_legacy", "aal_new", "total_aal",
            ])

            funding[cn] = f

        agg_pdb = agg.loc[i, "payroll_db_legacy"] + agg.loc[i, "payroll_db_new"]
        agg.loc[i, "total_nc_rate"] = (agg.loc[i, "nc_legacy"] + agg.loc[i, "nc_new"]) / agg_pdb if agg_pdb > 0 else 0

        # --- DROP (only for plans with has_drop=true) ---
        if has_drop:
            drop = funding["drop"]
            reg = funding[drop_ref_class]
            drop.loc[i, "total_payroll"] = drop.loc[i - 1, "total_payroll"] * (1 + payroll_growth)
            drop.loc[i, "payroll_db_legacy"] = drop.loc[i, "total_payroll"] * (reg.loc[i, "payroll_db_legacy_ratio"] + reg.loc[i, "payroll_dc_legacy_ratio"])
            drop.loc[i, "payroll_db_new"] = drop.loc[i, "total_payroll"] * (reg.loc[i, "payroll_db_new_ratio"] + reg.loc[i, "payroll_dc_new_ratio"])

            if reg.loc[i - 1, "total_ben_payment"] > 0:
                drop.loc[i, "total_ben_payment"] = drop.loc[i - 1, "total_ben_payment"] * reg.loc[i, "total_ben_payment"] / reg.loc[i - 1, "total_ben_payment"]
            if reg.loc[i - 1, "total_refund"] > 0:
                drop.loc[i, "total_refund"] = drop.loc[i - 1, "total_refund"] * reg.loc[i, "total_refund"] / reg.loc[i - 1, "total_refund"]

            if reg.loc[i, "total_ben_payment"] > 0:
                drop.loc[i, "ben_payment_legacy"] = drop.loc[i, "total_ben_payment"] * reg.loc[i, "ben_payment_legacy"] / reg.loc[i, "total_ben_payment"]
                drop.loc[i, "ben_payment_new"] = drop.loc[i, "total_ben_payment"] * reg.loc[i, "ben_payment_new"] / reg.loc[i, "total_ben_payment"]
            if reg.loc[i, "total_refund"] > 0:
                drop.loc[i, "refund_legacy"] = drop.loc[i, "total_refund"] * reg.loc[i, "refund_legacy"] / reg.loc[i, "total_refund"]
                drop.loc[i, "refund_new"] = drop.loc[i, "total_refund"] * reg.loc[i, "refund_new"] / reg.loc[i, "total_refund"]

            drop.loc[i, "nc_rate_db_legacy"] = agg.loc[i, "nc_legacy"] / agg.loc[i, "payroll_db_legacy"] if agg.loc[i, "payroll_db_legacy"] > 0 else 0
            drop.loc[i, "nc_rate_db_new"] = agg.loc[i, "nc_new"] / agg.loc[i, "payroll_db_new"] if agg.loc[i, "payroll_db_new"] > 0 else 0
            drop.loc[i, "nc_legacy"] = drop.loc[i, "nc_rate_db_legacy"] * drop.loc[i, "payroll_db_legacy"]
            drop.loc[i, "nc_new"] = drop.loc[i, "nc_rate_db_new"] * drop.loc[i, "payroll_db_new"]

            drop.loc[i, "aal_legacy"] = (drop.loc[i - 1, "aal_legacy"] * (1 + dr_current)
                + (drop.loc[i, "nc_legacy"] - drop.loc[i, "ben_payment_legacy"] - drop.loc[i, "refund_legacy"]) * (1 + dr_current) ** 0.5)
            drop.loc[i, "aal_new"] = (drop.loc[i - 1, "aal_new"] * (1 + dr_new)
                + (drop.loc[i, "nc_new"] - drop.loc[i, "ben_payment_new"] - drop.loc[i, "refund_new"]) * (1 + dr_new) ** 0.5)
            drop.loc[i, "total_aal"] = drop.loc[i, "aal_legacy"] + drop.loc[i, "aal_new"]
            funding["drop"] = drop

            _accumulate_to_aggregate(agg, drop, i, [
                "total_payroll", "payroll_db_legacy", "payroll_db_new",
            ])
            _accumulate_to_aggregate(agg, drop, i, [
                "ben_payment_legacy", "refund_legacy",
                "ben_payment_new", "refund_new",
                "total_ben_payment", "total_refund",
            ])
            _accumulate_to_aggregate(agg, drop, i, ["nc_legacy", "nc_new"])
            agg_pdb2 = agg.loc[i, "payroll_db_legacy"] + agg.loc[i, "payroll_db_new"]
            agg.loc[i, "total_nc_rate"] = (agg.loc[i, "nc_legacy"] + agg.loc[i, "nc_new"]) / agg_pdb2 if agg_pdb2 > 0 else 0
            agg.loc[i, "nc_rate_db_legacy"] = agg.loc[i, "nc_legacy"] / agg.loc[i, "payroll_db_legacy"] if agg.loc[i, "payroll_db_legacy"] > 0 else 0
            agg.loc[i, "nc_rate_db_new"] = agg.loc[i, "nc_new"] / agg.loc[i, "payroll_db_new"] if agg.loc[i, "payroll_db_new"] > 0 else 0
            _accumulate_to_aggregate(agg, drop, i, [
                "aal_legacy", "aal_new", "total_aal",
            ])

        # --- Contributions, MVA, AVA ---
        for cn in all_classes:
            f = funding[cn]
            amo = amo_tables[cn]

            cont_strategy.compute_rates(f, i, start_year + i, amo)

            if cn == "drop":
                f.loc[i, "er_dc_rate_legacy"] = 0
                f.loc[i, "er_dc_rate_new"] = 0
            else:
                dc_rate = constants.class_data[cn].er_dc_cont_rate
                f.loc[i, "er_dc_rate_legacy"] = dc_rate
                f.loc[i, "er_dc_rate_new"] = dc_rate

            f.loc[i, "admin_exp_rate"] = f.loc[i - 1, "admin_exp_rate"]
            f.loc[i, "ee_nc_cont_legacy"] = db_ee_cont_rate * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "ee_nc_cont_new"] = db_ee_cont_rate * f.loc[i, "payroll_db_new"]
            _accumulate_to_aggregate(agg, f, i, [
                "ee_nc_cont_legacy", "ee_nc_cont_new",
            ])

            f.loc[i, "admin_exp_legacy"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "admin_exp_new"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_new"]
            _accumulate_to_aggregate(agg, f, i, [
                "admin_exp_legacy", "admin_exp_new",
            ])

            f.loc[i, "er_nc_cont_legacy"] = f.loc[i, "er_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"] + f.loc[i, "admin_exp_legacy"]
            f.loc[i, "er_nc_cont_new"] = f.loc[i, "er_nc_rate_new"] * f.loc[i, "payroll_db_new"] + f.loc[i, "admin_exp_new"]
            f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
            f.loc[i, "er_amo_cont_new"] = f.loc[i, "amo_rate_new"] * f.loc[i, "payroll_db_new"]
            f.loc[i, "total_er_db_cont"] = (f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
                                             + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"])
            _accumulate_to_aggregate(agg, f, i, [
                "er_nc_cont_legacy", "er_nc_cont_new",
                "er_amo_cont_legacy", "er_amo_cont_new",
                "total_er_db_cont",
            ])

            f.loc[i, "er_dc_cont_legacy"] = f.loc[i, "er_dc_rate_legacy"] * f.loc[i, "payroll_dc_legacy"]
            f.loc[i, "er_dc_cont_new"] = f.loc[i, "er_dc_rate_new"] * f.loc[i, "payroll_dc_new"]
            f.loc[i, "total_er_dc_cont"] = f.loc[i, "er_dc_cont_legacy"] + f.loc[i, "er_dc_cont_new"]
            _accumulate_to_aggregate(agg, f, i, [
                "er_dc_cont_legacy", "er_dc_cont_new", "total_er_dc_cont",
            ])

            year = start_year + i
            roa_row = ret_scen[ret_scen["year"] == year]
            roa = roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current
            f.loc[i, "roa"] = roa
            agg.loc[i, "roa"] = roa

            cf_leg = (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
                      + f.loc[i, "er_amo_cont_legacy"] - f.loc[i, "ben_payment_legacy"]
                      - f.loc[i, "refund_legacy"] - f.loc[i, "admin_exp_legacy"])
            cf_new = (f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
                      + f.loc[i, "er_amo_cont_new"] - f.loc[i, "ben_payment_new"]
                      - f.loc[i, "refund_new"] - f.loc[i, "admin_exp_new"])

            f.loc[i, "total_solv_cont"] = _solvency_cont(
                mva_prev=f.loc[i - 1, "total_mva"],
                cf_total=cf_leg + cf_new,
                roa=roa,
            )
            if f.loc[i, "total_aal"] > 0:
                f.loc[i, "solv_cont_legacy"] = f.loc[i, "total_solv_cont"] * f.loc[i, "aal_legacy"] / f.loc[i, "total_aal"]
                f.loc[i, "solv_cont_new"] = f.loc[i, "total_solv_cont"] * f.loc[i, "aal_new"] / f.loc[i, "total_aal"]

            f.loc[i, "net_cf_legacy"] = cf_leg + f.loc[i, "solv_cont_legacy"]
            f.loc[i, "net_cf_new"] = cf_new + f.loc[i, "solv_cont_new"]
            _accumulate_to_aggregate(agg, f, i, ["net_cf_legacy", "net_cf_new"])

            f.loc[i, "mva_legacy"] = _mva_rollforward(
                f.loc[i - 1, "mva_legacy"], f.loc[i, "net_cf_legacy"], roa)
            f.loc[i, "mva_new"] = _mva_rollforward(
                f.loc[i - 1, "mva_new"], f.loc[i, "net_cf_new"], roa)
            f.loc[i, "total_mva"] = f.loc[i, "mva_legacy"] + f.loc[i, "mva_new"]
            _accumulate_to_aggregate(agg, f, i, [
                "mva_legacy", "mva_new", "total_mva",
            ])

            f.loc[i, "ava_base_legacy"] = f.loc[i - 1, "ava_legacy"] + f.loc[i, "net_cf_legacy"] / 2
            f.loc[i, "ava_base_new"] = f.loc[i - 1, "ava_new"] + f.loc[i, "net_cf_new"] / 2

            funding[cn] = f

        # --- AVA smoothing at plan aggregate level ---
        ava_leg = ava_strategy.smooth(
            ava_prev=agg.loc[i - 1, "ava_legacy"],
            net_cf=agg.loc[i, "net_cf_legacy"],
            mva=agg.loc[i, "mva_legacy"],
            dr=dr_current,
            state={},
        )
        agg.loc[i, "exp_inv_earnings_ava_legacy"] = ava_leg["exp_inv_earnings_ava"]
        agg.loc[i, "exp_ava_legacy"] = ava_leg["exp_ava"]
        agg.loc[i, "ava_legacy"] = ava_leg["ava"]
        agg.loc[i, "alloc_inv_earnings_ava_legacy"] = ava_leg["alloc_inv_earnings_ava"]
        agg.loc[i, "ava_base_legacy"] = ava_leg["ava_base"]

        ava_new = ava_strategy.smooth(
            ava_prev=agg.loc[i - 1, "ava_new"],
            net_cf=agg.loc[i, "net_cf_new"],
            mva=agg.loc[i, "mva_new"],
            dr=dr_new,
            state={},
        )
        agg.loc[i, "exp_inv_earnings_ava_new"] = ava_new["exp_inv_earnings_ava"]
        agg.loc[i, "exp_ava_new"] = ava_new["exp_ava"]
        agg.loc[i, "ava_new"] = ava_new["ava"]
        agg.loc[i, "alloc_inv_earnings_ava_new"] = ava_new["alloc_inv_earnings_ava"]
        agg.loc[i, "ava_base_new"] = ava_new["ava_base"]

        # --- Allocate AVA earnings to classes (no-op for class-level smoothing) ---
        ava_strategy.allocate_to_classes(agg, funding, all_classes, i)

        # --- DROP reallocation (only for plans with has_drop=true) ---
        if has_drop:
            drop = funding["drop"]
            if agg.loc[i, "aal_legacy"] != 0:
                drop.loc[i, "net_reallocation_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "aal_legacy"] * agg.loc[i, "ava_legacy"] / agg.loc[i, "aal_legacy"]
            drop.loc[i, "ava_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "net_reallocation_legacy"]
            if agg.loc[i, "aal_new"] != 0:
                drop.loc[i, "net_reallocation_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "aal_new"] * agg.loc[i, "ava_new"] / agg.loc[i, "aal_new"]
            drop.loc[i, "ava_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "net_reallocation_new"]
            funding["drop"] = drop

            for cn in class_names:
                f = funding[cn]
                agg_ex_drop_leg = agg.loc[i, "aal_legacy"] - drop.loc[i, "aal_legacy"]
                prop_leg = f.loc[i, "aal_legacy"] / agg_ex_drop_leg if agg_ex_drop_leg != 0 else 0
                f.loc[i, "net_reallocation_legacy"] = prop_leg * drop.loc[i, "net_reallocation_legacy"]
                f.loc[i, "ava_legacy"] = f.loc[i, "unadj_ava_legacy"] + f.loc[i, "net_reallocation_legacy"]

                agg_ex_drop_new = agg.loc[i, "aal_new"] - drop.loc[i, "aal_new"]
                prop_new = f.loc[i, "aal_new"] / agg_ex_drop_new if agg_ex_drop_new != 0 else 0
                f.loc[i, "net_reallocation_new"] = prop_new * drop.loc[i, "net_reallocation_new"]
                f.loc[i, "ava_new"] = f.loc[i, "unadj_ava_new"] + f.loc[i, "net_reallocation_new"]
                funding[cn] = f
        else:
            # No DROP: unadjusted AVA is final AVA
            for cn in class_names:
                f = funding[cn]
                f.loc[i, "ava_legacy"] = f.loc[i, "unadj_ava_legacy"]
                f.loc[i, "ava_new"] = f.loc[i, "unadj_ava_new"]
                funding[cn] = f

        # --- UAL, funded ratios ---
        for cn in all_classes:
            f = funding[cn]
            f.loc[i, "total_ava"] = f.loc[i, "ava_legacy"] + f.loc[i, "ava_new"]
            _accumulate_to_aggregate(agg, f, i, ["total_ava"])

            f.loc[i, "ual_ava_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "ava_legacy"]
            f.loc[i, "ual_ava_new"] = f.loc[i, "aal_new"] - f.loc[i, "ava_new"]
            f.loc[i, "total_ual_ava"] = f.loc[i, "ual_ava_legacy"] + f.loc[i, "ual_ava_new"]
            _accumulate_to_aggregate(agg, f, i, [
                "ual_ava_legacy", "ual_ava_new", "total_ual_ava",
            ])

            f.loc[i, "ual_mva_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "mva_legacy"]
            f.loc[i, "ual_mva_new"] = f.loc[i, "aal_new"] - f.loc[i, "mva_new"]
            f.loc[i, "total_ual_mva"] = f.loc[i, "ual_mva_legacy"] + f.loc[i, "ual_mva_new"]
            _accumulate_to_aggregate(agg, f, i, [
                "ual_mva_legacy", "ual_mva_new", "total_ual_mva",
            ])

            f.loc[i, "fr_mva"] = f.loc[i, "total_mva"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0
            f.loc[i, "fr_ava"] = f.loc[i, "total_ava"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0

            f.loc[i, "total_er_cont"] = f.loc[i, "total_er_db_cont"] + f.loc[i, "total_er_dc_cont"] + f.loc[i, "total_solv_cont"]
            _accumulate_to_aggregate(agg, f, i, ["total_er_cont"])
            f.loc[i, "total_er_cont_rate"] = f.loc[i, "total_er_cont"] / f.loc[i, "total_payroll"] if f.loc[i, "total_payroll"] > 0 else 0
            funding[cn] = f

        agg.loc[i, "fr_mva"] = agg.loc[i, "total_mva"] / agg.loc[i, "total_aal"] if agg.loc[i, "total_aal"] != 0 else 0
        agg.loc[i, "fr_ava"] = agg.loc[i, "total_ava"] / agg.loc[i, "total_aal"] if agg.loc[i, "total_aal"] != 0 else 0
        agg.loc[i, "total_er_cont_rate"] = agg.loc[i, "total_er_cont"] / agg.loc[i, "total_payroll"] if agg.loc[i, "total_payroll"] > 0 else 0

        # --- Amortization layers ---
        for cn in all_classes:
            f = funding[cn]
            amo = amo_tables[cn]
            mc = amo["max_col"]

            _roll_amort_layer(
                debt=amo["cur_debt"], pay=amo["cur_pay"], per=amo["cur_per"],
                i=i, max_col=mc, ual=f.loc[i, "ual_ava_legacy"],
                dr=dr_current, amo_pay_growth=amo_pay_growth,
            )
            _roll_amort_layer(
                debt=amo["fut_debt"], pay=amo["fut_pay"], per=amo["fut_per"],
                i=i, max_col=mc, ual=f.loc[i, "ual_ava_new"],
                dr=dr_new, amo_pay_growth=amo_pay_growth,
            )

        funding[agg_name] = agg

    return funding


def _compute_funding_gainloss(
    liability_result: pd.DataFrame,
    funding_inputs: dict,
    constants,
) -> pd.DataFrame:
    """Gain/loss deferral funding model (statutory-rate, single-class).

    Args:
        liability_result: Output of run_plan_pipeline for the single class.
        funding_inputs: Output of load_funding_inputs().
        constants: PlanConfig.

    Returns:
        DataFrame with funding projection columns. The caller is
        responsible for wrapping this into the standard
        ``{class_name: df, plan_name: agg_df}`` dict.
    """
    econ = constants.economic
    fund = constants.funding
    r_cfg = constants.ranges

    dr_current = econ.dr_current
    dr_new = econ.dr_new
    payroll_growth = econ.payroll_growth
    inflation = econ.inflation

    amo_pay_growth = fund.amo_pay_growth
    amo_period_new = fund.amo_period_new
    funding_policy = fund.funding_policy

    amo_method = fund.amo_method if hasattr(fund, "amo_method") else "level_pct"
    if amo_method == "level $":
        amo_pay_growth = 0

    model_period = r_cfg.model_period
    start_year = r_cfg.start_year
    n_years = model_period + 1

    # Return scenario column selection
    return_scen_col = constants.raw.get("economic", {}).get("return_scen", "assumption")

    # --- Load initial row ---
    init = funding_inputs["init_funding"].iloc[0]
    ret_scen = funding_inputs["return_scenarios"].copy()

    # Set "model" and "assumption" columns in return_scenarios
    ret_scen["model"] = econ.model_return
    ret_scen["assumption"] = dr_current

    # --- Funding config parameters ---
    raw = constants.raw if hasattr(constants, "raw") else {}
    funding_raw = raw.get("funding", {})

    amo_period_current = funding_raw.get("amo_period_current", 30)

    # Statutory rate components: either a config-driven list of
    # RateComponent entries (new schema), or synthesized from the old
    # flat fields (legacy schema; TRS uses this until Step 1.4b).
    stat_rates = funding_raw.get("statutory_rates", {})
    ee_schedule = stat_rates.get("ee_rate_schedule",
                                 [{"from_year": 0, "rate": constants.benefit.db_ee_cont_rate}])
    er_rate_components = _resolve_er_rate_components(funding_raw)

    # nc_cal: authoritative source is calibration.json (class_data), with
    # funding_raw as legacy fallback
    nc_cal = 1.0
    if hasattr(constants, "class_data") and "all" in constants.class_data:
        cd = constants.class_data["all"]
        if hasattr(cd, "nc_cal") and cd.nc_cal != 1.0:
            nc_cal = cd.nc_cal
    if nc_cal == 1.0:
        nc_cal = funding_raw.get("nc_cal", 1.0)

    # --- Initialize DataFrame from initial funding row ---
    # Column names are expected to follow the standardized convention
    # (lowercase, total_ prefix for aggregates). See plans/*/data/funding/.
    cols = list(init.index)
    f = pd.DataFrame(0.0, index=range(n_years), columns=cols)
    f["year"] = range(start_year, start_year + n_years)
    for col in cols:
        if col != "year":
            val = init.get(col, 0)
            f.loc[0, col] = float(val if pd.notna(val) else 0)

    liab = liability_result

    # --- Calibration: payroll ratios and NC rates from liability pipeline ---
    # R uses lag(ratio) — ratio from previous year applied to next year's payroll
    pay_est = liab["total_payroll_est"].values
    for ratio_col, num_col in [
        ("payroll_db_legacy_ratio", "payroll_db_legacy_est"),
        ("payroll_db_new_ratio", "payroll_db_new_est"),
    ]:
        if ratio_col not in f.columns:
            f[ratio_col] = 0.0
        num = liab[num_col].values if num_col in liab.columns else np.zeros(n_years)
        ratios = np.divide(num, pay_est, out=np.zeros_like(pay_est), where=pay_est != 0)
        # lag by 1
        f.loc[1:, ratio_col] = ratios[:-1]

    # CB payroll ratio
    if "payroll_cb_new_ratio" not in f.columns:
        f["payroll_cb_new_ratio"] = 0.0
    if "payroll_cb_new_est" in liab.columns:
        cb_ratios = np.divide(liab["payroll_cb_new_est"].values, pay_est,
                              out=np.zeros_like(pay_est), where=pay_est != 0)
        f.loc[1:, "payroll_cb_new_ratio"] = cb_ratios[:-1]

    # NC rate calibration (with nc_cal and lag)
    _populate_calibrated_nc_rates(f, liab, nc_cal, n_years)

    # AAL initialization
    if "aal_legacy_est" in liab.columns:
        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
    elif "aal_legacy_est" in liab.columns:
        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
    f.loc[0, "total_aal"] = f.loc[0, "aal_legacy"] + f.loc[0, "aal_new"]
    f.loc[0, "ual_ava_legacy"] = f.loc[0, "aal_legacy"] - f.loc[0, "ava_legacy"]
    f.loc[0, "total_ual_ava"] = f.loc[0, "total_aal"] - f.loc[0, "total_ava"]

    # --- Amortization period tables ---
    amo_seq_current = list(range(amo_period_current, 0, -1))
    amo_seq_new = list(range(amo_period_new, 0, -1))
    n_amo = max(len(amo_seq_current), len(amo_seq_new))

    # Current-hire period table: row 0 = existing countdown, rows 1+ = new layers
    amo_per_current = np.zeros((n_years, n_amo))
    amo_per_current[0, :len(amo_seq_current)] = amo_seq_current
    for row in range(1, n_years):
        amo_per_current[row, :len(amo_seq_new)] = amo_seq_new
    # Shift onto diagonals
    for j in range(1, n_amo):
        for row in range(n_years):
            if row - j >= 0:
                amo_per_current[row, j] = amo_per_current[row - j, j] if row == j else amo_per_current[row, j]
    # Rebuild with proper diagonal shift (match R's lag logic)
    amo_per_current_diag = np.zeros((n_years, n_amo))
    amo_per_current_diag[0, :len(amo_seq_current)] = amo_seq_current
    for row in range(1, n_years):
        amo_per_current_diag[row, 0] = amo_seq_new[0] if len(amo_seq_new) > 0 else 0
    for j in range(1, n_amo):
        for row in range(j, n_years):
            prev = amo_per_current_diag[row - 1, j - 1]
            amo_per_current_diag[row, j] = max(prev - 1, 0) if prev > 0 else 0

    amo_per_new = np.zeros((n_years, n_amo))
    for j in range(n_amo):
        for row in range(j + 1, n_years):
            idx = row - j - 1
            amo_per_new[row, j] = max(amo_seq_new[0] - idx, 0) if idx < amo_seq_new[0] else 0
    # Simpler: diagonal from row j+1, col j, counting down
    amo_per_new = np.zeros((n_years, n_amo))
    for j in range(n_amo):
        for row in range(j + 1, n_years):
            amo_per_new[row, j] = max(amo_period_new - (row - j - 1), 0)

    # Debt and payment tables
    debt_current = np.zeros((n_years, n_amo + 1))
    pay_current = np.zeros((n_years, n_amo))
    debt_new = np.zeros((n_years, n_amo + 1))
    pay_new = np.zeros((n_years, n_amo))

    # Initialize first debt layer and payment
    debt_current[0, 0] = f.loc[0, "total_ual_ava"]
    if amo_per_current_diag[0, 0] > 0:
        pay_current[0, 0] = _get_pmt(
            dr_current, amo_pay_growth, int(amo_per_current_diag[0, 0]),
            debt_current[0, 0], t=0.5)

    # AVA smoothing strategy: 4-year gain/loss deferral cascade, per class.
    ava_strategy = GainLossSmoothing()

    # Contribution strategy: statutory rate cascade with optional residual
    # amortization rate (when funding_policy == "statutory").
    cont_strategy = StatutoryContributions(
        funding_policy=funding_policy,
        ee_schedule=ee_schedule,
        components=er_rate_components,
    )

    # --- Main year loop ---
    for i in range(1, n_years):
        year = start_year + i

        # Payroll projection
        f.loc[i, "total_payroll"] = f.loc[i - 1, "total_payroll"] * (1 + payroll_growth)
        f.loc[i, "payroll_db_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_legacy_ratio"]
        f.loc[i, "payroll_db_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_new_ratio"]
        f.loc[i, "payroll_cb_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_cb_new_ratio"]

        # Benefit payments from liability pipeline
        f.loc[i, "ben_payment_legacy"] = (
            liab["retire_ben_db_legacy_est"].iloc[i]
            + liab["retire_ben_current_est"].iloc[i]
            + liab["retire_ben_term_est"].iloc[i])
        f.loc[i, "refund_legacy"] = liab["refund_db_legacy_est"].iloc[i]
        f.loc[i, "ben_payment_new"] = (
            liab.get("retire_ben_db_new_est", pd.Series(np.zeros(n_years))).iloc[i]
            + liab.get("retire_ben_cb_new_est", pd.Series(np.zeros(n_years))).iloc[i])
        f.loc[i, "refund_new"] = (
            liab.get("refund_db_new_est", pd.Series(np.zeros(n_years))).iloc[i]
            + liab.get("refund_cb_new_est", pd.Series(np.zeros(n_years))).iloc[i])

        # Normal cost
        f.loc[i, "nc_legacy"] = f.loc[i, "nc_rate_db_legacy"] * f.loc[i, "payroll_db_legacy"]
        payroll_new_total = f.loc[i, "payroll_db_new"] + f.loc[i, "payroll_cb_new"]
        f.loc[i, "nc_new"] = (f.loc[i, "nc_rate_db_new"] * f.loc[i, "payroll_db_new"]
                               + f.loc[i, "nc_rate_cb_new"] * f.loc[i, "payroll_cb_new"])
        f.loc[i, "nc_rate"] = ((f.loc[i, "nc_legacy"] + f.loc[i, "nc_new"])
                                / f.loc[i, "total_payroll"]) if f.loc[i, "total_payroll"] > 0 else 0

        # Liability gain/loss
        f.loc[i, "liability_gain_loss_legacy"] = (
            liab["liability_gain_loss_legacy_est"].iloc[i]
            if "liability_gain_loss_legacy_est" in liab.columns else 0)
        f.loc[i, "liability_gain_loss_new"] = (
            liab["liability_gain_loss_new_est"].iloc[i]
            if "liability_gain_loss_new_est" in liab.columns else 0)
        f.loc[i, "liability_gain_loss"] = f.loc[i, "liability_gain_loss_legacy"] + f.loc[i, "liability_gain_loss_new"]

        # AAL roll-forward
        f.loc[i, "aal_legacy"] = _aal_rollforward(
            aal_prev=f.loc[i - 1, "aal_legacy"],
            nc=f.loc[i, "nc_legacy"],
            ben=f.loc[i, "ben_payment_legacy"],
            refund=f.loc[i, "refund_legacy"],
            liab_gl=f.loc[i, "liability_gain_loss_legacy"],
            dr=dr_current,
        )
        f.loc[i, "aal_new"] = _aal_rollforward(
            aal_prev=f.loc[i - 1, "aal_new"],
            nc=f.loc[i, "nc_new"],
            ben=f.loc[i, "ben_payment_new"],
            refund=f.loc[i, "refund_new"],
            liab_gl=f.loc[i, "liability_gain_loss_new"],
            dr=dr_new,
        )
        f.loc[i, "total_aal"] = f.loc[i, "aal_legacy"] + f.loc[i, "aal_new"]

        # NC, EE, ER NC, statutory cascade, and amort rates
        cont_strategy.compute_rates(
            f, i, year,
            amo_state={"cur_pay": pay_current, "fut_pay": pay_new},
        )

        # Admin expense rate
        f.loc[i, "admin_exp_rate"] = f.loc[i - 1, "admin_exp_rate"]

        # Employee contribution amounts
        f.loc[i, "ee_nc_cont_legacy"] = f.loc[i, "ee_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
        f.loc[i, "ee_nc_cont_new"] = f.loc[i, "ee_nc_rate_new"] * payroll_new_total

        # Admin expenses
        f.loc[i, "admin_exp_legacy"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_legacy"]
        f.loc[i, "admin_exp_new"] = f.loc[i, "admin_exp_rate"] * payroll_new_total

        # Employer contribution amounts
        f.loc[i, "er_nc_cont_legacy"] = (f.loc[i, "er_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
                                          + f.loc[i, "admin_exp_legacy"])
        f.loc[i, "er_nc_cont_new"] = (f.loc[i, "er_nc_rate_new"] * payroll_new_total
                                       + f.loc[i, "admin_exp_new"])

        # Employer amortization amounts
        if funding_policy == "statutory":
            f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
        else:
            f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "total_payroll"]
        f.loc[i, "er_amo_cont_new"] = f.loc[i, "amo_rate_new"] * payroll_new_total

        # Return on assets
        roa_row = ret_scen[ret_scen["year"] == year]
        roa = roa_row[return_scen_col].iloc[0] if len(roa_row) > 0 else dr_current
        f.loc[i, "roa"] = roa

        # Cash flows and solvency contribution
        cf_legacy = (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
                     + f.loc[i, "er_amo_cont_legacy"] - f.loc[i, "ben_payment_legacy"]
                     - f.loc[i, "refund_legacy"] - f.loc[i, "admin_exp_legacy"])
        cf_new = (f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
                  + f.loc[i, "er_amo_cont_new"] - f.loc[i, "ben_payment_new"]
                  - f.loc[i, "refund_new"] - f.loc[i, "admin_exp_new"])
        cf_total = cf_legacy + cf_new

        f.loc[i, "solv_cont"] = _solvency_cont(
            mva_prev=f.loc[i - 1, "total_mva"],
            cf_total=cf_total,
            roa=roa,
        )
        if f.loc[i, "total_aal"] > 0:
            f.loc[i, "solv_cont_legacy"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_legacy"] / f.loc[i, "total_aal"]
            f.loc[i, "solv_cont_new"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_new"] / f.loc[i, "total_aal"]

        f.loc[i, "net_cf_legacy"] = cf_legacy + f.loc[i, "solv_cont_legacy"]
        f.loc[i, "net_cf_new"] = cf_new + f.loc[i, "solv_cont_new"]

        # MVA projection
        f.loc[i, "mva_legacy"] = _mva_rollforward(
            f.loc[i - 1, "mva_legacy"], f.loc[i, "net_cf_legacy"], roa)
        f.loc[i, "mva_new"] = _mva_rollforward(
            f.loc[i - 1, "mva_new"], f.loc[i, "net_cf_new"], roa)
        f.loc[i, "total_mva"] = f.loc[i, "mva_legacy"] + f.loc[i, "mva_new"]

        # AVA gain/loss deferral smoothing — legacy
        ava_leg = ava_strategy.smooth(
            ava_prev=f.loc[i - 1, "ava_legacy"],
            net_cf=f.loc[i, "net_cf_legacy"],
            mva=f.loc[i, "mva_legacy"],
            dr=dr_current,
            state={
                "defer_y1_prev": f.loc[i - 1, "defer_y1_legacy"],
                "defer_y2_prev": f.loc[i - 1, "defer_y2_legacy"],
                "defer_y3_prev": f.loc[i - 1, "defer_y3_legacy"],
                "defer_y4_prev": f.loc[i - 1, "defer_y4_legacy"],
            },
        )
        for k, v in ava_leg.items():
            if k == "exp_inv_income":
                f.loc[i, "exp_inv_income_legacy"] = v
            elif k == "exp_ava":
                f.loc[i, "exp_ava_legacy"] = v
            elif k == "ava":
                f.loc[i, "ava_legacy"] = v
            else:
                f.loc[i, f"{k}_legacy"] = v

        # AVA gain/loss deferral smoothing — new
        ava_new = ava_strategy.smooth(
            ava_prev=f.loc[i - 1, "ava_new"],
            net_cf=f.loc[i, "net_cf_new"],
            mva=f.loc[i, "mva_new"],
            dr=dr_new,
            state={
                "defer_y1_prev": f.loc[i - 1, "defer_y1_new"],
                "defer_y2_prev": f.loc[i - 1, "defer_y2_new"],
                "defer_y3_prev": f.loc[i - 1, "defer_y3_new"],
                "defer_y4_prev": f.loc[i - 1, "defer_y4_new"],
            },
        )
        for k, v in ava_new.items():
            if k == "exp_inv_income":
                f.loc[i, "exp_inv_income_new"] = v
            elif k == "exp_ava":
                f.loc[i, "exp_ava_new"] = v
            elif k == "ava":
                f.loc[i, "ava_new"] = v
            else:
                f.loc[i, f"{k}_new"] = v

        f.loc[i, "total_ava"] = f.loc[i, "ava_legacy"] + f.loc[i, "ava_new"]

        # UAL and funded ratios
        f.loc[i, "ual_ava_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "ava_legacy"]
        f.loc[i, "ual_ava_new"] = f.loc[i, "aal_new"] - f.loc[i, "ava_new"]
        f.loc[i, "total_ual_ava"] = f.loc[i, "ual_ava_legacy"] + f.loc[i, "ual_ava_new"]

        f.loc[i, "ual_mva_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "mva_legacy"]
        f.loc[i, "ual_mva_new"] = f.loc[i, "aal_new"] - f.loc[i, "mva_new"]
        f.loc[i, "total_ual_mva"] = f.loc[i, "ual_mva_legacy"] + f.loc[i, "ual_mva_new"]

        f.loc[i, "fr_ava"] = f.loc[i, "total_ava"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0
        f.loc[i, "fr_mva"] = f.loc[i, "total_mva"] / f.loc[i, "total_aal"] if f.loc[i, "total_aal"] != 0 else 0

        # Contribution totals
        f.loc[i, "total_er_cont"] = (f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
                                      + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"]
                                      + f.loc[i, "solv_cont"])
        f.loc[i, "total_er_cont_rate"] = f.loc[i, "total_er_cont"] / f.loc[i, "total_payroll"] if f.loc[i, "total_payroll"] > 0 else 0
        f.loc[i, "tot_cont_rate"] = (
            (f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
             + f.loc[i, "er_amo_cont_legacy"]
             + f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
             + f.loc[i, "er_amo_cont_new"] + f.loc[i, "solv_cont"])
            / f.loc[i, "total_payroll"]) if f.loc[i, "total_payroll"] > 0 else 0

        # Real cost metrics
        f.loc[i, "total_er_cont_real"] = f.loc[i, "total_er_cont"] / (1 + inflation) ** (year - start_year)
        if i == 1:
            f.loc[i, "cum_er_cont_real"] = f.loc[i, "total_er_cont_real"]
        else:
            f.loc[i, "cum_er_cont_real"] = f.loc[i - 1, "cum_er_cont_real"] + f.loc[i, "total_er_cont_real"]
        f.loc[i, "total_ual_mva_real"] = f.loc[i, "total_ual_mva"] / (1 + inflation) ** (year - start_year)
        f.loc[i, "all_in_cost_real"] = f.loc[i, "cum_er_cont_real"] + f.loc[i, "total_ual_mva_real"]

        # Amortization layer updates — current hires (legacy)
        _roll_amort_layer(
            debt=debt_current, pay=pay_current, per=amo_per_current_diag,
            i=i, max_col=n_amo, ual=f.loc[i, "ual_ava_legacy"],
            dr=dr_current, amo_pay_growth=amo_pay_growth,
        )

        # Amortization layer updates — new hires
        _roll_amort_layer(
            debt=debt_new, pay=pay_new, per=amo_per_new,
            i=i, max_col=n_amo, ual=f.loc[i, "ual_ava_new"],
            dr=dr_new, amo_pay_growth=amo_pay_growth,
        )

    return f
