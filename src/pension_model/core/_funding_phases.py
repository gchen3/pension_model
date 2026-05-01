"""Year-loop phase helpers for the funding model."""

import numpy as np
import pandas as pd

from pension_model.core._funding_helpers import (
    _aal_rollforward,
    _maybe_accumulate,
    _mva_rollforward,
    _roll_amort_layer,
    _solvency_cont,
)
from pension_model.core._funding_setup import FundingContext


def _phase_payroll(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    f.loc[i, "total_payroll"] = f.loc[i - 1, "total_payroll"] * (1 + ctx.payroll_growth)
    f.loc[i, "payroll_db_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_legacy_ratio"]
    f.loc[i, "payroll_db_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_db_new_ratio"]
    if ctx.has_cb:
        f.loc[i, "payroll_cb_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_cb_new_ratio"]
    if ctx.has_dc:
        f.loc[i, "payroll_dc_legacy"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_legacy_ratio"]
        f.loc[i, "payroll_dc_new"] = f.loc[i, "total_payroll"] * f.loc[i, "payroll_dc_new_ratio"]


def _phase_dc_contributions(f: pd.DataFrame, i: int) -> None:
    f.loc[i, "er_dc_cont_legacy"] = f.loc[i, "er_dc_rate_legacy"] * f.loc[i, "payroll_dc_legacy"]
    f.loc[i, "er_dc_cont_new"] = f.loc[i, "er_dc_rate_new"] * f.loc[i, "payroll_dc_new"]
    f.loc[i, "total_er_dc_cont"] = f.loc[i, "er_dc_cont_legacy"] + f.loc[i, "er_dc_cont_new"]


def _phase_benefits_refunds(f: pd.DataFrame, liab: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    f.loc[i, "ben_payment_legacy"] = (
        liab["retire_ben_db_legacy_est"].iloc[i]
        + liab["retire_ben_current_est"].iloc[i]
        + liab["retire_ben_term_est"].iloc[i]
    )
    f.loc[i, "refund_legacy"] = liab["refund_db_legacy_est"].iloc[i]

    ben_new = liab["retire_ben_db_new_est"].iloc[i]
    refund_new = liab["refund_db_new_est"].iloc[i]
    if ctx.has_cb:
        ben_new = ben_new + liab["retire_ben_cb_new_est"].iloc[i]
        refund_new = refund_new + liab["refund_cb_new_est"].iloc[i]
    f.loc[i, "ben_payment_new"] = ben_new
    f.loc[i, "refund_new"] = refund_new


def _prepare_return_scenarios(ctx: FundingContext, dr_current: float) -> pd.DataFrame:
    rs = ctx.ret_scen
    return_path = ctx.raw_economic.get("asset_return_path")
    return_terminal = ctx.raw_economic.get("asset_return_terminal")

    def _resolve_return(value):
        if value == "model_return":
            return ctx.model_return
        return value

    if ctx.return_scen_col == "asset_shock":
        if return_path is None or return_terminal is None:
            raise ValueError(
                "economic.asset_return_path and economic.asset_return_terminal "
                "are required when return_scen is 'asset_shock'."
            )
        resolved_path = [_resolve_return(value) for value in return_path]
        resolved_terminal = _resolve_return(return_terminal)
        first_year = ctx.start_year + 1
        rs["asset_shock"] = [
            resolved_path[year - first_year]
            if 0 <= year - first_year < len(resolved_path)
            else resolved_terminal
            for year in rs["year"]
        ]
    if ctx.ava_strategy.ret_scen_gates_projection:
        first_proj_year = ctx.start_year + 2
        mask = rs["year"] >= first_proj_year
        rs.loc[mask, "model"] = ctx.model_return
        rs.loc[mask, "assumption"] = dr_current
    else:
        rs["model"] = ctx.model_return
        rs["assumption"] = dr_current
    return rs


def _nc_rate_agg(agg: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    denom = agg.loc[i, "payroll_db_legacy"] + agg.loc[i, "payroll_db_new"]
    if ctx.has_cb:
        denom = denom + agg.loc[i, "payroll_cb_new"]
    agg.loc[i, "nc_rate"] = (agg.loc[i, "nc_legacy"] + agg.loc[i, "nc_new"]) / denom if denom > 0 else 0


def _phase_normal_cost(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    f.loc[i, "nc_legacy"] = f.loc[i, "nc_rate_db_legacy"] * f.loc[i, "payroll_db_legacy"]
    nc_new = f.loc[i, "nc_rate_db_new"] * f.loc[i, "payroll_db_new"]
    denom = f.loc[i, "payroll_db_legacy"] + f.loc[i, "payroll_db_new"]
    if ctx.has_cb:
        nc_new = nc_new + f.loc[i, "nc_rate_cb_new"] * f.loc[i, "payroll_cb_new"]
        denom = denom + f.loc[i, "payroll_cb_new"]
    f.loc[i, "nc_new"] = nc_new
    f.loc[i, "nc_rate"] = (f.loc[i, "nc_legacy"] + nc_new) / denom if denom > 0 else 0


def _phase_drop_projection(funding: dict, agg: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    drop = funding["drop"]
    reg = funding[ctx.drop_ref_class]

    drop.loc[i, "total_payroll"] = drop.loc[i - 1, "total_payroll"] * (1 + ctx.payroll_growth)
    drop.loc[i, "payroll_db_legacy"] = drop.loc[i, "total_payroll"] * (
        reg.loc[i, "payroll_db_legacy_ratio"] + reg.loc[i, "payroll_dc_legacy_ratio"]
    )
    drop.loc[i, "payroll_db_new"] = drop.loc[i, "total_payroll"] * (
        reg.loc[i, "payroll_db_new_ratio"] + reg.loc[i, "payroll_dc_new_ratio"]
    )

    if reg.loc[i - 1, "total_ben_payment"] > 0:
        drop.loc[i, "total_ben_payment"] = (
            drop.loc[i - 1, "total_ben_payment"]
            * reg.loc[i, "total_ben_payment"] / reg.loc[i - 1, "total_ben_payment"]
        )
    if reg.loc[i - 1, "total_refund"] > 0:
        drop.loc[i, "total_refund"] = (
            drop.loc[i - 1, "total_refund"]
            * reg.loc[i, "total_refund"] / reg.loc[i - 1, "total_refund"]
        )

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

    drop.loc[i, "aal_legacy"] = (
        drop.loc[i - 1, "aal_legacy"] * (1 + ctx.dr_current)
        + (drop.loc[i, "nc_legacy"] - drop.loc[i, "ben_payment_legacy"] - drop.loc[i, "refund_legacy"])
        * (1 + ctx.dr_current) ** 0.5
    )
    drop.loc[i, "aal_new"] = (
        drop.loc[i - 1, "aal_new"] * (1 + ctx.dr_new)
        + (drop.loc[i, "nc_new"] - drop.loc[i, "ben_payment_new"] - drop.loc[i, "refund_new"])
        * (1 + ctx.dr_new) ** 0.5
    )
    drop.loc[i, "total_aal"] = drop.loc[i, "aal_legacy"] + drop.loc[i, "aal_new"]
    funding["drop"] = drop

    _maybe_accumulate(ctx, agg, drop, i, ["total_payroll", "payroll_db_legacy", "payroll_db_new"])
    _maybe_accumulate(ctx, agg, drop, i, [
        "ben_payment_legacy", "refund_legacy", "ben_payment_new", "refund_new", "total_ben_payment", "total_refund",
    ])
    _maybe_accumulate(ctx, agg, drop, i, ["nc_legacy", "nc_new"])

    _nc_rate_agg(agg, i, ctx)
    agg.loc[i, "nc_rate_db_legacy"] = agg.loc[i, "nc_legacy"] / agg.loc[i, "payroll_db_legacy"] if agg.loc[i, "payroll_db_legacy"] > 0 else 0
    agg.loc[i, "nc_rate_db_new"] = agg.loc[i, "nc_new"] / agg.loc[i, "payroll_db_new"] if agg.loc[i, "payroll_db_new"] > 0 else 0
    _maybe_accumulate(ctx, agg, drop, i, ["aal_legacy", "aal_new", "total_aal"])


def _finalize_ava_with_drop(funding: dict, agg: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    if ctx.has_drop:
        drop = funding["drop"]
        if agg.loc[i, "aal_legacy"] != 0:
            drop.loc[i, "net_reallocation_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "aal_legacy"] * agg.loc[i, "ava_legacy"] / agg.loc[i, "aal_legacy"]
        drop.loc[i, "ava_legacy"] = drop.loc[i, "unadj_ava_legacy"] - drop.loc[i, "net_reallocation_legacy"]
        if agg.loc[i, "aal_new"] != 0:
            drop.loc[i, "net_reallocation_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "aal_new"] * agg.loc[i, "ava_new"] / agg.loc[i, "aal_new"]
        drop.loc[i, "ava_new"] = drop.loc[i, "unadj_ava_new"] - drop.loc[i, "net_reallocation_new"]
        funding["drop"] = drop

        for cn in ctx.class_names:
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
        for cn in ctx.class_names:
            f = funding[cn]
            f.loc[i, "ava_legacy"] = f.loc[i, "unadj_ava_legacy"]
            f.loc[i, "ava_new"] = f.loc[i, "unadj_ava_new"]
            funding[cn] = f


def _phase_ava_corridor_smoothing(agg: pd.DataFrame, i: int, ava_strategy, dr_current: float, dr_new: float) -> None:
    for leg, dr in (("legacy", dr_current), ("new", dr_new)):
        result = ava_strategy.smooth(
            ava_prev=agg.loc[i - 1, f"ava_{leg}"],
            net_cf=agg.loc[i, f"net_cf_{leg}"],
            mva=agg.loc[i, f"mva_{leg}"],
            dr=dr,
            state={},
        )
        agg.loc[i, f"exp_inv_earnings_ava_{leg}"] = result["exp_inv_earnings_ava"]
        agg.loc[i, f"exp_ava_{leg}"] = result["exp_ava"]
        agg.loc[i, f"ava_{leg}"] = result["ava"]
        agg.loc[i, f"alloc_inv_earnings_ava_{leg}"] = result["alloc_inv_earnings_ava"]
        agg.loc[i, f"ava_base_{leg}"] = result["ava_base"]


def _phase_ava_gainloss_smoothing(f: pd.DataFrame, i: int, ava_strategy, dr_current: float, dr_new: float) -> None:
    for leg, dr in (("legacy", dr_current), ("new", dr_new)):
        result = ava_strategy.smooth(
            ava_prev=f.loc[i - 1, f"ava_{leg}"],
            net_cf=f.loc[i, f"net_cf_{leg}"],
            mva=f.loc[i, f"mva_{leg}"],
            dr=dr,
            state={
                "defer_y1_prev": f.loc[i - 1, f"defer_y1_{leg}"],
                "defer_y2_prev": f.loc[i - 1, f"defer_y2_{leg}"],
                "defer_y3_prev": f.loc[i - 1, f"defer_y3_{leg}"],
                "defer_y4_prev": f.loc[i - 1, f"defer_y4_{leg}"],
            },
        )
        for k, v in result.items():
            if k == "exp_inv_income":
                f.loc[i, f"exp_inv_income_{leg}"] = v
            elif k == "exp_ava":
                f.loc[i, f"exp_ava_{leg}"] = v
            elif k == "ava":
                f.loc[i, f"ava_{leg}"] = v
            else:
                f.loc[i, f"{k}_{leg}"] = v


def _phase_real_cost_metrics(f: pd.DataFrame, i: int, year: int, start_year: int, inflation: float) -> None:
    deflator = (1 + inflation) ** (year - start_year)
    f.loc[i, "total_er_cont_real"] = f.loc[i, "total_er_cont"] / deflator
    f.loc[i, "cum_er_cont_real"] = (
        f.loc[i, "total_er_cont_real"] if i == 1 else f.loc[i - 1, "cum_er_cont_real"] + f.loc[i, "total_er_cont_real"]
    )
    f.loc[i, "total_ual_mva_real"] = f.loc[i, "total_ual_mva"] / deflator
    f.loc[i, "all_in_cost_real"] = f.loc[i, "cum_er_cont_real"] + f.loc[i, "total_ual_mva_real"]


def _phase_amort_rolling(funding: dict, amort_state: dict, i: int, ctx: FundingContext) -> None:
    if amort_state["mode"] == "per_class":
        for cn in ctx.all_classes:
            f = funding[cn]
            amo = amort_state["amo_tables"][cn]
            mc = amo["max_col"]
            _roll_amort_layer(
                debt=amo["cur_debt"], pay=amo["cur_pay"], per=amo["cur_per"],
                i=i, max_col=mc, ual=f.loc[i, "ual_ava_legacy"], dr=ctx.dr_current, amo_pay_growth=ctx.amo_pay_growth,
            )
            _roll_amort_layer(
                debt=amo["fut_debt"], pay=amo["fut_pay"], per=amo["fut_per"],
                i=i, max_col=mc, ual=f.loc[i, "ual_ava_new"], dr=ctx.dr_new, amo_pay_growth=ctx.amo_pay_growth,
            )
        return

    f = funding[ctx.class_names[0]]
    n_amo = amort_state["n_amo"]
    _roll_amort_layer(
        debt=amort_state["debt_current"], pay=amort_state["pay_current"], per=amort_state["amo_per_current_diag"],
        i=i, max_col=n_amo, ual=f.loc[i, "ual_ava_legacy"], dr=ctx.dr_current, amo_pay_growth=ctx.amo_pay_growth,
    )
    _roll_amort_layer(
        debt=amort_state["debt_new"], pay=amort_state["pay_new"], per=amort_state["amo_per_new"],
        i=i, max_col=n_amo, ual=f.loc[i, "ual_ava_new"], dr=ctx.dr_new, amo_pay_growth=ctx.amo_pay_growth,
    )


def _phase_er_cont_totals(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    total = (
        f.loc[i, "er_nc_cont_legacy"] + f.loc[i, "er_nc_cont_new"]
        + f.loc[i, "er_amo_cont_legacy"] + f.loc[i, "er_amo_cont_new"]
        + f.loc[i, "solv_cont"]
    )
    if ctx.has_dc:
        total = total + f.loc[i, "total_er_dc_cont"]
    f.loc[i, "total_er_cont"] = total
    total_payroll = f.loc[i, "total_payroll"]
    f.loc[i, "total_er_cont_rate"] = total / total_payroll if total_payroll > 0 else 0


def _phase_ual_and_funded_ratios(f: pd.DataFrame, i: int) -> None:
    f.loc[i, "total_ava"] = f.loc[i, "ava_legacy"] + f.loc[i, "ava_new"]
    f.loc[i, "ual_ava_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "ava_legacy"]
    f.loc[i, "ual_ava_new"] = f.loc[i, "aal_new"] - f.loc[i, "ava_new"]
    f.loc[i, "total_ual_ava"] = f.loc[i, "ual_ava_legacy"] + f.loc[i, "ual_ava_new"]
    f.loc[i, "ual_mva_legacy"] = f.loc[i, "aal_legacy"] - f.loc[i, "mva_legacy"]
    f.loc[i, "ual_mva_new"] = f.loc[i, "aal_new"] - f.loc[i, "mva_new"]
    f.loc[i, "total_ual_mva"] = f.loc[i, "ual_mva_legacy"] + f.loc[i, "ual_mva_new"]

    total_aal = f.loc[i, "total_aal"]
    f.loc[i, "fr_mva"] = f.loc[i, "total_mva"] / total_aal if total_aal != 0 else 0
    f.loc[i, "fr_ava"] = f.loc[i, "total_ava"] / total_aal if total_aal != 0 else 0


def _phase_contributions(f: pd.DataFrame, i: int, ctx: FundingContext) -> None:
    f.loc[i, "admin_exp_rate"] = f.loc[i - 1, "admin_exp_rate"]
    payroll_new = f.loc[i, "payroll_db_new"]
    if ctx.has_cb:
        payroll_new = payroll_new + f.loc[i, "payroll_cb_new"]

    f.loc[i, "ee_nc_cont_legacy"] = f.loc[i, "ee_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
    f.loc[i, "ee_nc_cont_new"] = f.loc[i, "ee_nc_rate_new"] * payroll_new
    f.loc[i, "admin_exp_legacy"] = f.loc[i, "admin_exp_rate"] * f.loc[i, "payroll_db_legacy"]
    f.loc[i, "admin_exp_new"] = f.loc[i, "admin_exp_rate"] * payroll_new
    f.loc[i, "er_nc_cont_legacy"] = (
        f.loc[i, "er_nc_rate_legacy"] * f.loc[i, "payroll_db_legacy"] + f.loc[i, "admin_exp_legacy"]
    )
    f.loc[i, "er_nc_cont_new"] = (
        f.loc[i, "er_nc_rate_new"] * payroll_new + f.loc[i, "admin_exp_new"]
    )
    f.loc[i, "er_amo_cont_legacy"] = f.loc[i, "amo_rate_legacy"] * f.loc[i, "payroll_db_legacy"]
    f.loc[i, "er_amo_cont_new"] = f.loc[i, "amo_rate_new"] * payroll_new


def _phase_cash_flow_and_solvency(f: pd.DataFrame, i: int, roa: float) -> None:
    cf_legacy = (
        f.loc[i, "ee_nc_cont_legacy"] + f.loc[i, "er_nc_cont_legacy"]
        + f.loc[i, "er_amo_cont_legacy"] - f.loc[i, "ben_payment_legacy"]
        - f.loc[i, "refund_legacy"] - f.loc[i, "admin_exp_legacy"]
    )
    cf_new = (
        f.loc[i, "ee_nc_cont_new"] + f.loc[i, "er_nc_cont_new"]
        + f.loc[i, "er_amo_cont_new"] - f.loc[i, "ben_payment_new"]
        - f.loc[i, "refund_new"] - f.loc[i, "admin_exp_new"]
    )

    f.loc[i, "solv_cont"] = _solvency_cont(mva_prev=f.loc[i - 1, "total_mva"], cf_total=cf_legacy + cf_new, roa=roa)
    if f.loc[i, "total_aal"] > 0:
        f.loc[i, "solv_cont_legacy"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_legacy"] / f.loc[i, "total_aal"]
        f.loc[i, "solv_cont_new"] = f.loc[i, "solv_cont"] * f.loc[i, "aal_new"] / f.loc[i, "total_aal"]

    f.loc[i, "net_cf_legacy"] = cf_legacy + f.loc[i, "solv_cont_legacy"]
    f.loc[i, "net_cf_new"] = cf_new + f.loc[i, "solv_cont_new"]


def _phase_mva(f: pd.DataFrame, i: int, roa: float) -> None:
    f.loc[i, "mva_legacy"] = _mva_rollforward(f.loc[i - 1, "mva_legacy"], f.loc[i, "net_cf_legacy"], roa)
    f.loc[i, "mva_new"] = _mva_rollforward(f.loc[i - 1, "mva_new"], f.loc[i, "net_cf_new"], roa)
    f.loc[i, "total_mva"] = f.loc[i, "mva_legacy"] + f.loc[i, "mva_new"]


def _phase_liability_gl_and_aal(f: pd.DataFrame, liab: pd.DataFrame, i: int, dr_current: float, dr_new: float) -> None:
    f.loc[i, "liability_gain_loss_legacy"] = liab["liability_gain_loss_legacy_est"].iloc[i]
    f.loc[i, "liability_gain_loss_new"] = liab["liability_gain_loss_new_est"].iloc[i]
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
