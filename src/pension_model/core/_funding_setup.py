"""Funding-model context and setup helpers."""

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from pension_model.config_schema import PlanConfig
from pension_model.core.pipeline_current import _get_pmt
from pension_model.core._funding_helpers import (
    _get_init_row,
    _populate_calibrated_nc_rates,
)
from pension_model.core._funding_strategies import (
    ActuarialContributions,
    CorridorSmoothing,
    GainLossSmoothing,
    RateComponent,
    StatutoryContributions,
)


@dataclass
class FundingContext:
    """Resolved configuration for one funding compute run."""

    dr_current: float
    dr_new: float
    dr_old: Optional[float]
    payroll_growth: float
    inflation: float
    amo_pay_growth: float
    amo_period_new: int
    funding_lag: int
    db_ee_cont_rate: float
    model_return: float
    start_year: int
    n_years: int
    ava_strategy: Any
    cont_strategy: Any
    class_names: list
    agg_name: str
    has_drop: bool
    drop_ref_class: Optional[str]
    all_classes: list
    is_multi_class: bool
    has_cb: bool
    has_dc: bool
    funding_policy: str
    return_scen_col: str
    init_funding: pd.DataFrame
    amort_layers: Optional[pd.DataFrame]
    ret_scen: pd.DataFrame = field(default_factory=pd.DataFrame)


def resolve_funding_context(
    constants: PlanConfig,
    funding_inputs: dict,
) -> FundingContext:
    """Build a ``FundingContext`` from plan config and funding inputs."""
    econ = constants.economic
    fund = constants.funding
    ranges = constants.ranges

    amo_method = fund.amo_method
    amo_pay_growth = fund.amo_pay_growth
    if amo_method == "level $":
        amo_pay_growth = 0

    class_names = list(constants.classes)
    agg_name = constants.plan_name
    has_drop = constants.has_drop
    drop_ref_class = constants.drop_reference_class or (class_names[0] if class_names else None)
    all_classes = class_names + (["drop"] if has_drop else [])
    is_multi_class = len(class_names) > 1

    has_cb = "cb" in constants.benefit_types
    has_dc = "payroll_dc_legacy" in funding_inputs["init_funding"].columns

    method = (fund.ava_smoothing or {}).get("method")
    if method == "corridor":
        ava_strategy = CorridorSmoothing()
    elif method == "gain_loss":
        ava_strategy = GainLossSmoothing()
    else:
        raise ValueError(
            f"Unknown funding.ava_smoothing.method: {method!r}. "
            f"Supported: 'corridor', 'gain_loss'."
        )

    stat_rates = constants.statutory_rates
    if stat_rates:
        ee_schedule = stat_rates.get(
            "ee_rate_schedule",
            [{"from_year": 0, "rate": constants.benefit.db_ee_cont_rate}],
        )
        cont_strategy = StatutoryContributions(
            funding_policy=fund.funding_policy,
            ee_schedule=ee_schedule,
            components=resolve_er_rate_components(stat_rates),
        )
    else:
        cont_strategy = ActuarialContributions(
            db_ee_cont_rate=constants.benefit.db_ee_cont_rate,
        )

    return FundingContext(
        dr_current=econ.dr_current,
        dr_new=econ.dr_new,
        dr_old=econ.dr_old,
        payroll_growth=econ.payroll_growth,
        inflation=econ.inflation,
        amo_pay_growth=amo_pay_growth,
        amo_period_new=fund.amo_period_new,
        funding_lag=fund.funding_lag,
        db_ee_cont_rate=constants.benefit.db_ee_cont_rate,
        model_return=econ.model_return,
        start_year=ranges.start_year,
        n_years=ranges.model_period + 1,
        ava_strategy=ava_strategy,
        cont_strategy=cont_strategy,
        class_names=class_names,
        agg_name=agg_name,
        has_drop=has_drop,
        drop_ref_class=drop_ref_class,
        all_classes=all_classes,
        is_multi_class=is_multi_class,
        has_cb=has_cb,
        has_dc=has_dc,
        funding_policy=fund.funding_policy,
        return_scen_col=constants.return_scen_col,
        init_funding=funding_inputs["init_funding"],
        amort_layers=funding_inputs.get("amort_layers"),
        ret_scen=funding_inputs["return_scenarios"].copy(),
    )


def resolve_er_rate_components(stat_rates: dict) -> list:
    """Build statutory employer-rate components from config."""
    components = stat_rates.get("er_rate_components")
    if components is None:
        raise ValueError(
            "funding.statutory_rates.er_rate_components is required when "
            "using the statutory contribution strategy. See "
            "plans/txtrs/config/plan_config.json for an example schema."
        )
    return [RateComponent.from_config(c) for c in components]


def setup_funding_frames(ctx: FundingContext) -> dict:
    """Build initial funding frames for every class plus the aggregate."""
    init = ctx.init_funding
    has_class_col = "class" in init.columns
    cols = [c for c in init.columns if c != "class"]

    keys = list(ctx.all_classes)
    if ctx.agg_name not in keys:
        keys.append(ctx.agg_name)

    funding = {}
    for cn in keys:
        init_row = _get_init_row(init, cn) if has_class_col else init.iloc[0]
        df = pd.DataFrame(0.0, index=range(ctx.n_years), columns=cols)
        df["year"] = range(ctx.start_year, ctx.start_year + ctx.n_years)
        for col in cols:
            if col == "year":
                continue
            val = init_row.get(col, 0)
            df.loc[0, col] = float(val if pd.notna(val) else 0)
        funding[cn] = df
    return funding


def setup_amort_state(ctx: FundingContext, funding: dict, constants: PlanConfig) -> dict:
    """Build the amortization-state structure for the year loop."""
    from pension_model.core.funding_model import build_amort_period_tables

    if ctx.amort_layers is not None:
        amo_tables = {}
        for cn in ctx.all_classes:
            cur_per, fut_per, init_bal, max_col = build_amort_period_tables(
                ctx.amort_layers, cn, ctx.amo_period_new, ctx.funding_lag, ctx.n_years - 1
            )

            cur_debt = np.zeros((ctx.n_years, max_col + 1))
            if len(init_bal) > 0:
                cur_debt[0, :len(init_bal)] = init_bal
            fut_debt = np.zeros((ctx.n_years, max_col + 1))

            cur_pay = np.zeros((ctx.n_years, max_col))
            dr_old = ctx.dr_old if ctx.dr_old is not None else ctx.dr_current
            for j in range(max_col):
                if cur_per[0, j] > 0 and abs(cur_debt[0, j]) > 1e-6:
                    cur_pay[0, j] = _get_pmt(
                        dr_old, ctx.amo_pay_growth, int(cur_per[0, j]), cur_debt[0, j], t=0.5
                    )
            if ctx.funding_lag > 0:
                cur_pay[0, :ctx.funding_lag] = 0

            fut_pay = np.zeros((ctx.n_years, max_col))
            amo_tables[cn] = {
                "cur_per": cur_per,
                "fut_per": fut_per,
                "cur_debt": cur_debt,
                "fut_debt": fut_debt,
                "cur_pay": cur_pay,
                "fut_pay": fut_pay,
                "max_col": max_col,
            }
        return {"mode": "per_class", "amo_tables": amo_tables}

    amo_period_current = constants.amo_period_current or 30
    amo_period_new = ctx.amo_period_new
    n_years = ctx.n_years

    amo_seq_current = list(range(amo_period_current, 0, -1))
    amo_seq_new = list(range(amo_period_new, 0, -1))
    n_amo = max(len(amo_seq_current), len(amo_seq_new), amo_period_new + ctx.funding_lag)

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
            amo_per_new[row, j] = max(amo_period_new - (row - j - 1), 0)

    debt_current = np.zeros((n_years, n_amo + 1))
    pay_current = np.zeros((n_years, n_amo))
    debt_new = np.zeros((n_years, n_amo + 1))
    pay_new = np.zeros((n_years, n_amo))

    first_class = ctx.class_names[0]
    f = funding[first_class]
    debt_current[0, 0] = f.loc[0, "total_ual_ava"]
    if amo_per_current_diag[0, 0] > 0:
        pay_current[0, 0] = _get_pmt(
            ctx.dr_current, ctx.amo_pay_growth, int(amo_per_current_diag[0, 0]), debt_current[0, 0], t=0.5
        )

    return {
        "mode": "local",
        "debt_current": debt_current,
        "pay_current": pay_current,
        "amo_per_current_diag": amo_per_current_diag,
        "debt_new": debt_new,
        "pay_new": pay_new,
        "amo_per_new": amo_per_new,
        "n_amo": n_amo,
    }


def calibrate_funding_frames(
    funding: dict,
    liability_results: dict,
    ctx: FundingContext,
    constants,
) -> None:
    """Calibrate per-class funding frames from liability pipeline output."""
    n_years = ctx.n_years
    for cn in ctx.class_names:
        f = funding[cn]
        liab = liability_results[cn]

        ratio_specs = [
            ("payroll_db_legacy_ratio", "payroll_db_legacy_est"),
            ("payroll_db_new_ratio", "payroll_db_new_est"),
        ]
        if ctx.has_dc:
            ratio_specs += [
                ("payroll_dc_legacy_ratio", "payroll_dc_legacy_est"),
                ("payroll_dc_new_ratio", "payroll_dc_new_est"),
            ]
        if ctx.has_cb:
            ratio_specs.append(("payroll_cb_new_ratio", "payroll_cb_new_est"))

        pay_est = liab["total_payroll_est"].values
        for ratio_col, num_col in ratio_specs:
            if ratio_col not in f.columns:
                f[ratio_col] = 0.0
            num = liab[num_col].values if num_col in liab.columns else np.zeros(n_years)
            ratios = np.divide(num, pay_est, out=np.zeros_like(pay_est), where=pay_est != 0)
            f.loc[1:, ratio_col] = ratios[:-1]

        if "nc_rate_db_legacy" not in f.columns:
            f["nc_rate_db_legacy"] = 0.0
            f["nc_rate_db_new"] = 0.0

        nc_cal = constants.class_data[cn].nc_cal
        _populate_calibrated_nc_rates(f, liab, nc_cal, n_years)

        f.loc[0, "aal_legacy"] = liab["aal_legacy_est"].iloc[0]
        f.loc[0, "total_aal"] = liab["total_aal_est"].iloc[0]
        f.loc[0, "ual_ava_legacy"] = f.loc[0, "aal_legacy"] - f.loc[0, "ava_legacy"]
        f.loc[0, "total_ual_ava"] = f.loc[0, "total_aal"] - f.loc[0, "total_ava"]

        funding[cn] = f


def select_amo_state(amort_state: dict, cn: str) -> dict:
    """Return the cont-strategy-facing amo_state for one class."""
    if amort_state["mode"] == "per_class":
        return amort_state["amo_tables"][cn]
    return {
        "cur_pay": amort_state["pay_current"],
        "fut_pay": amort_state["pay_new"],
    }
