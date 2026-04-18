#!/usr/bin/env python3
"""
First-cut estimator for TXTRS-AV healthy-retiree mortality when the actual
2021 TRS healthy pensioner table is not available locally.

This is intentionally a txtrs-av-specific prototype. It is not yet a shared
prep method.

Method summary:
  1. Start from shared PubT-2010(B) healthy-retiree rates.
  2. Project those rates to 2021 using the ultimate MP-2021 / UMP-2021 rates
     immediately for all future years ("immediate convergence").
  3. Fit an age-specific multiplicative adjustment in log space so the
     projected 2021 reference curve matches the published 2021 healthy-retiree
     sample checkpoints from the 2022 experience study.
  4. Apply a credibility envelope:
     - full weight at ages 60-95
     - taper toward the published-teacher reference below 60 and above 95
  5. Enforce monotone non-decreasing qx by age and cap at 1.0.
  6. Validate projected rates against published 2021/2051 and 2023/2053
     checkpoints from the experience study and the 2024 AV.

Outputs:
  - prep/txtrs-av/reference_tables/estimated_retiree_mortality_base_2021.csv
  - prep/txtrs-av/reference_tables/estimated_retiree_mortality_validation.csv
  - prep/txtrs-av/reference_tables/estimated_retiree_mortality_validation_summary.csv
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pension_model.core.mortality_builder import _read_base_mort_table, _read_mp_table


PUB_PATH = PROJECT_ROOT / "prep" / "common" / "sources" / "soa_pub2010_amount_mort_rates.xlsx"
MP_PATH = PROJECT_ROOT / "prep" / "common" / "sources" / "soa_mp2021_rates.xlsx"
CHECKPOINTS_PATH = (
    PROJECT_ROOT / "prep" / "txtrs-av" / "reference_tables" / "retiree_mortality_sample_checkpoints.csv"
)
OUT_BASE = (
    PROJECT_ROOT / "prep" / "txtrs-av" / "reference_tables" / "estimated_retiree_mortality_base_2021.csv"
)
OUT_VALIDATION = (
    PROJECT_ROOT / "prep" / "txtrs-av" / "reference_tables" / "estimated_retiree_mortality_validation.csv"
)
OUT_SUMMARY = (
    PROJECT_ROOT
    / "prep"
    / "txtrs-av"
    / "reference_tables"
    / "estimated_retiree_mortality_validation_summary.csv"
)
OUT_PLOT_2021 = (
    PROJECT_ROOT / "prep" / "txtrs-av" / "reference_tables" / "estimated_retiree_mortality_fit_2021.svg"
)
OUT_PLOT_VALIDATION = (
    PROJECT_ROOT / "prep" / "txtrs-av" / "reference_tables" / "estimated_retiree_mortality_validation.svg"
)


@dataclass(frozen=True)
class FitConfig:
    min_age: int = 20
    max_age: int = 120
    base_year: int = 2010
    target_base_year: int = 2021
    full_credibility_min_age: int = 60
    full_credibility_max_age: int = 95
    anchor_floor: float = 1e-10


CFG = FitConfig()


def _load_pub_teacher_retiree() -> pd.DataFrame:
    df = _read_base_mort_table(PUB_PATH, "PubT-2010(B)")
    out = pd.DataFrame(
        {
            "age": df["age"].astype(int),
            "male_qx": df["healthy_retiree_male"].astype(float),
            "female_qx": df["healthy_retiree_female"].astype(float),
        }
    )
    return out[(out["age"] >= CFG.min_age) & (out["age"] <= CFG.max_age)].reset_index(drop=True)


def _load_mp_ultimate() -> pd.DataFrame:
    male = _read_mp_table(MP_PATH, "Male", min_age=CFG.min_age)
    female = _read_mp_table(MP_PATH, "Female", min_age=CFG.min_age)
    male_last = max(int(c) for c in male.columns if c != "age")
    female_last = max(int(c) for c in female.columns if c != "age")
    out = pd.DataFrame(
        {
            "age": male["age"].astype(int),
            "male_improvement": male[str(male_last)].astype(float),
            "female_improvement": female[str(female_last)].astype(float),
        }
    )
    return out[(out["age"] >= CFG.min_age) & (out["age"] <= CFG.max_age)].reset_index(drop=True)


def _project_with_immediate_convergence(base_qx: pd.Series, annual_improvement: pd.Series, years: int) -> pd.Series:
    return base_qx * np.power(1.0 - annual_improvement, years)


def _credibility_weight(age: np.ndarray) -> np.ndarray:
    age = age.astype(float)
    weights = np.ones_like(age, dtype=float)

    young = age < CFG.full_credibility_min_age
    if young.any():
        weights[young] = np.clip(
            (age[young] - CFG.min_age) / (CFG.full_credibility_min_age - CFG.min_age),
            0.0,
            1.0,
        )

    old = age > CFG.full_credibility_max_age
    if old.any():
        weights[old] = np.clip(
            1.0
            - (age[old] - CFG.full_credibility_max_age)
            / (CFG.max_age - CFG.full_credibility_max_age),
            0.0,
            1.0,
        )

    return weights


def _interpolate_log_adjustment(ages: np.ndarray, anchor_ages: np.ndarray, anchor_log_ratio: np.ndarray) -> np.ndarray:
    return np.interp(ages, anchor_ages, anchor_log_ratio, left=anchor_log_ratio[0], right=anchor_log_ratio[-1])


def _monotone_cap(qx: np.ndarray) -> np.ndarray:
    qx = np.maximum.accumulate(qx)
    qx = np.clip(qx, 0.0, 1.0)
    qx[-1] = 1.0
    return qx


def _build_base_2021_estimate() -> pd.DataFrame:
    pub = _load_pub_teacher_retiree()
    mp = _load_mp_ultimate()
    checkpoints = pd.read_csv(CHECKPOINTS_PATH)
    fit_points = checkpoints[
        (checkpoints["member_state"] == "healthy_retiree")
        & (checkpoints["source_id"] == "EXPSTUDY_2022")
        & (checkpoints["rate_year"] == 2021)
        & (checkpoints["age"] < 120)
    ].copy()

    merged = pub.merge(mp, on="age", how="inner")
    years_forward = CFG.target_base_year - CFG.base_year
    merged["ref_2021_male_qx"] = _project_with_immediate_convergence(
        merged["male_qx"], merged["male_improvement"], years_forward
    )
    merged["ref_2021_female_qx"] = _project_with_immediate_convergence(
        merged["female_qx"], merged["female_improvement"], years_forward
    )

    out = merged[["age", "male_improvement", "female_improvement", "ref_2021_male_qx", "ref_2021_female_qx"]].copy()

    for gender in ("male", "female"):
        fit_gender = fit_points[fit_points["gender"] == gender].sort_values("age")
        joined = fit_gender.merge(out, on="age", how="left")
        ref_col = f"ref_2021_{gender}_qx"
        ratios = np.maximum(joined["qx"].to_numpy(dtype=float), CFG.anchor_floor) / np.maximum(
            joined[ref_col].to_numpy(dtype=float), CFG.anchor_floor
        )
        anchor_log_ratio = np.log(ratios)
        ages = out["age"].to_numpy(dtype=float)
        anchor_ages = joined["age"].to_numpy(dtype=float)
        raw_log_adj = _interpolate_log_adjustment(ages, anchor_ages, anchor_log_ratio)
        cred = _credibility_weight(ages)
        adj = np.exp(raw_log_adj * cred)
        est = out[ref_col].to_numpy(dtype=float) * adj
        est = _monotone_cap(est)
        out[f"credibility_weight_{gender}"] = cred
        out[f"estimated_2021_{gender}_qx"] = est

    out.loc[out["age"] == 120, ["estimated_2021_male_qx", "estimated_2021_female_qx"]] = 1.0
    return out


def _project_from_estimated_2021(base_2021: pd.DataFrame, target_year: int) -> pd.DataFrame:
    years_forward = target_year - CFG.target_base_year
    out = base_2021[["age"]].copy()
    out["male_qx"] = _project_with_immediate_convergence(
        base_2021["estimated_2021_male_qx"], base_2021["male_improvement"], years_forward
    )
    out["female_qx"] = _project_with_immediate_convergence(
        base_2021["estimated_2021_female_qx"], base_2021["female_improvement"], years_forward
    )
    out["male_qx"] = _monotone_cap(out["male_qx"].to_numpy(dtype=float))
    out["female_qx"] = _monotone_cap(out["female_qx"].to_numpy(dtype=float))
    return out


def _build_validation(base_2021: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    checkpoints = pd.read_csv(CHECKPOINTS_PATH)
    projection_years = sorted(checkpoints["rate_year"].unique())
    projections = {}
    for year in projection_years:
        if year == 2021:
            proj = base_2021[["age"]].copy()
            proj["male_qx"] = base_2021["estimated_2021_male_qx"]
            proj["female_qx"] = base_2021["estimated_2021_female_qx"]
        else:
            proj = _project_from_estimated_2021(base_2021, year)
        projections[year] = proj

    rows = []
    for _, row in checkpoints.iterrows():
        proj = projections[int(row["rate_year"])]
        value = proj.loc[proj["age"] == int(row["age"]), f"{row['gender']}_qx"].iloc[0]
        expected = float(row["qx"])
        abs_diff = float(value - expected)
        rel_diff = float(abs_diff / expected) if expected else math.nan
        rows.append(
            {
                "source_id": row["source_id"],
                "member_state": row["member_state"],
                "rate_year": int(row["rate_year"]),
                "age": int(row["age"]),
                "gender": row["gender"],
                "expected_qx": expected,
                "estimated_qx": float(value),
                "abs_diff": abs_diff,
                "rel_diff": rel_diff,
                "notes": row["notes"],
            }
        )

    detail = pd.DataFrame(rows).sort_values(["source_id", "rate_year", "gender", "age"]).reset_index(drop=True)
    summary = (
        detail.groupby(["source_id", "rate_year", "gender"], as_index=False)
        .agg(
            max_abs_diff=("abs_diff", lambda s: float(np.max(np.abs(s)))),
            mean_abs_diff=("abs_diff", lambda s: float(np.mean(np.abs(s)))),
            max_rel_diff=("rel_diff", lambda s: float(np.max(np.abs(s)))),
            mean_rel_diff=("rel_diff", lambda s: float(np.mean(np.abs(s)))),
        )
        .sort_values(["source_id", "rate_year", "gender"])
        .reset_index(drop=True)
    )
    return detail, summary


def _svg_line(points: list[tuple[float, float]], color: str, width: float = 2.0, dash: str | None = None) -> str:
    coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline fill="none" stroke="{color}" stroke-width="{width}"{dash_attr} '
        f'points="{coords}" />'
    )


def _svg_circle(x: float, y: float, color: str, radius: float = 3.5) -> str:
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{color}" />'


def _map_age(age: float, x0: float, width: float) -> float:
    return x0 + width * (age - CFG.min_age) / (CFG.max_age - CFG.min_age)


def _map_qx(qx: float, y0: float, height: float, min_log: float, max_log: float) -> float:
    qx = max(float(qx), 1e-6)
    val = math.log10(qx)
    return y0 + height * (max_log - val) / (max_log - min_log)


def _write_svg(path: Path, body: str, width: int = 1200, height: int = 700) -> None:
    text = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white" />'
        f"{body}</svg>"
    )
    path.write_text(text, encoding="utf-8")


def _plot_fit_2021(base_2021: pd.DataFrame) -> None:
    checkpoints = pd.read_csv(CHECKPOINTS_PATH)
    points_2021 = checkpoints[
        (checkpoints["member_state"] == "healthy_retiree") & (checkpoints["rate_year"] == 2021)
    ].copy()

    width = 1200
    height = 700
    panel_w = 480
    panel_h = 500
    x_margin = 80
    top = 80
    min_log = -4.5
    max_log = 0.0

    body = ['<text x="40" y="35" font-size="24" font-family="monospace">TXTRS-AV healthy retiree mortality fit, 2021</text>']
    body.append(
        '<text x="40" y="58" font-size="14" font-family="monospace">Estimated 2021 curve vs projected PubT-2010(B) reference and published 2021 checkpoints. Y-axis is log10(qx).</text>'
    )

    for i, gender in enumerate(("male", "female")):
        x0 = x_margin + i * (panel_w + 80)
        y0 = top
        body.append(f'<rect x="{x0}" y="{y0}" width="{panel_w}" height="{panel_h}" fill="none" stroke="#333" stroke-width="1"/>')
        body.append(
            f'<text x="{x0}" y="{y0 - 15}" font-size="18" font-family="monospace">{gender.title()}</text>'
        )

        for age_tick in range(20, 121, 10):
            x = _map_age(age_tick, x0, panel_w)
            body.append(f'<line x1="{x:.2f}" y1="{y0}" x2="{x:.2f}" y2="{y0 + panel_h}" stroke="#eee" stroke-width="1"/>')
            body.append(
                f'<text x="{x - 10:.2f}" y="{y0 + panel_h + 20}" font-size="12" font-family="monospace">{age_tick}</text>'
            )
        for q_tick in (1e-4, 1e-3, 1e-2, 1e-1, 1.0):
            y = _map_qx(q_tick, y0, panel_h, min_log, max_log)
            body.append(f'<line x1="{x0}" y1="{y:.2f}" x2="{x0 + panel_w}" y2="{y:.2f}" stroke="#eee" stroke-width="1"/>')
            body.append(
                f'<text x="{x0 - 60}" y="{y + 4:.2f}" font-size="12" font-family="monospace">{q_tick:.0e}</text>'
            )

        ref_col = f"ref_2021_{gender}_qx"
        est_col = f"estimated_2021_{gender}_qx"
        ref_pts = [(_map_age(a, x0, panel_w), _map_qx(q, y0, panel_h, min_log, max_log))
                   for a, q in zip(base_2021["age"], base_2021[ref_col])]
        est_pts = [(_map_age(a, x0, panel_w), _map_qx(q, y0, panel_h, min_log, max_log))
                   for a, q in zip(base_2021["age"], base_2021[est_col])]
        body.append(_svg_line(ref_pts, "#999999", width=2.0, dash="6 4"))
        body.append(_svg_line(est_pts, "#005f73", width=2.5))

        gpts = points_2021[points_2021["gender"] == gender]
        for _, row in gpts.iterrows():
            x = _map_age(float(row["age"]), x0, panel_w)
            y = _map_qx(float(row["qx"]), y0, panel_h, min_log, max_log)
            body.append(_svg_circle(x, y, "#bb3e03", radius=4.0))

    legend_x = 80
    legend_y = 630
    body.append(_svg_line([(legend_x, legend_y), (legend_x + 35, legend_y)], "#005f73", width=2.5))
    body.append('<text x="125" y="634" font-size="13" font-family="monospace">estimated 2021 healthy-retiree curve</text>')
    body.append(_svg_line([(legend_x + 340, legend_y), (legend_x + 375, legend_y)], "#999999", width=2.0, dash="6 4"))
    body.append('<text x="385" y="634" font-size="13" font-family="monospace">projected PubT-2010(B) reference</text>')
    body.append(_svg_circle(760, legend_y, "#bb3e03", radius=4.0))
    body.append('<text x="775" y="634" font-size="13" font-family="monospace">published 2021 sample checkpoint</text>')

    _write_svg(OUT_PLOT_2021, "".join(body), width=width, height=height)


def _plot_validation(base_2021: pd.DataFrame) -> None:
    checkpoints = pd.read_csv(CHECKPOINTS_PATH)
    projection_years = [2021, 2023, 2051, 2053]
    projections = {year: (_project_from_estimated_2021(base_2021, year) if year != 2021 else pd.DataFrame({
        "age": base_2021["age"],
        "male_qx": base_2021["estimated_2021_male_qx"],
        "female_qx": base_2021["estimated_2021_female_qx"],
    })) for year in projection_years}

    width = 1200
    height = 900
    panel_w = 480
    panel_h = 320
    lefts = [80, 640]
    tops = [80, 460]
    min_log = -4.5
    max_log = 0.0

    body = ['<text x="40" y="35" font-size="24" font-family="monospace">TXTRS-AV healthy retiree mortality validation</text>']
    body.append(
        '<text x="40" y="58" font-size="14" font-family="monospace">Estimated curves for 2021/2023/2051/2053 vs published checkpoints. Y-axis is log10(qx).</text>'
    )

    colors = {2021: "#005f73", 2023: "#0a9396", 2051: "#ca6702", 2053: "#ee9b00"}

    for idx, gender in enumerate(("male", "female")):
        col = idx
        x0 = lefts[col]
        for row_idx, years_pair in enumerate(((2021, 2023), (2051, 2053))):
            y0 = tops[row_idx]
            body.append(f'<rect x="{x0}" y="{y0}" width="{panel_w}" height="{panel_h}" fill="none" stroke="#333" stroke-width="1"/>')
            body.append(
                f'<text x="{x0}" y="{y0 - 15}" font-size="18" font-family="monospace">{gender.title()} {" / ".join(str(y) for y in years_pair)}</text>'
            )
            for age_tick in range(20, 121, 10):
                x = _map_age(age_tick, x0, panel_w)
                body.append(f'<line x1="{x:.2f}" y1="{y0}" x2="{x:.2f}" y2="{y0 + panel_h}" stroke="#eee" stroke-width="1"/>')
            for q_tick in (1e-4, 1e-3, 1e-2, 1e-1, 1.0):
                y = _map_qx(q_tick, y0, panel_h, min_log, max_log)
                body.append(f'<line x1="{x0}" y1="{y:.2f}" x2="{x0 + panel_w}" y2="{y:.2f}" stroke="#eee" stroke-width="1"/>')

            for year in years_pair:
                proj = projections[year]
                pts = [(_map_age(a, x0, panel_w), _map_qx(q, y0, panel_h, min_log, max_log))
                       for a, q in zip(proj["age"], proj[f"{gender}_qx"])]
                body.append(_svg_line(pts, colors[year], width=2.3))
                gpts = checkpoints[(checkpoints["gender"] == gender) & (checkpoints["rate_year"] == year)]
                for _, pt in gpts.iterrows():
                    body.append(
                        _svg_circle(
                            _map_age(float(pt["age"]), x0, panel_w),
                            _map_qx(float(pt["qx"]), y0, panel_h, min_log, max_log),
                            colors[year],
                            radius=3.8,
                        )
                    )

    legend_x = 80
    legend_y = 860
    offset = 0
    for year in projection_years:
        body.append(_svg_line([(legend_x + offset, legend_y), (legend_x + offset + 30, legend_y)], colors[year], width=2.5))
        body.append(_svg_circle(legend_x + offset + 15, legend_y, colors[year], radius=3.8))
        body.append(
            f'<text x="{legend_x + offset + 40}" y="{legend_y + 4}" font-size="13" font-family="monospace">{year} estimated curve and checkpoints</text>'
        )
        offset += 260

    _write_svg(OUT_PLOT_VALIDATION, "".join(body), width=width, height=height)


def main() -> None:
    OUT_BASE.parent.mkdir(parents=True, exist_ok=True)
    base_2021 = _build_base_2021_estimate()
    detail, summary = _build_validation(base_2021)

    base_2021.to_csv(OUT_BASE, index=False)
    detail.to_csv(OUT_VALIDATION, index=False)
    summary.to_csv(OUT_SUMMARY, index=False)
    _plot_fit_2021(base_2021)
    _plot_validation(base_2021)

    print(f"Wrote {OUT_BASE}")
    print(f"Wrote {OUT_VALIDATION}")
    print(f"Wrote {OUT_SUMMARY}")
    print(f"Wrote {OUT_PLOT_2021}")
    print(f"Wrote {OUT_PLOT_VALIDATION}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
