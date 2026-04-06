"""
Truth tables: plan-level aggregates for visual R-vs-Python comparison.

A truth table is a single-sheet DataFrame summarizing one pension plan's key
outputs year-by-year at the plan-wide level. It does NOT diagnose why things
differ; it tells you quickly WHETHER anything differs materially from the R
baseline.

Two views of the same data live side by side in an Excel workbook:
- `frs_R`, `txtrs_R`: frozen values extracted from the R model's baseline
  CSVs, written once by scripts/build_r_truth_tables.py and never re-generated
- `frs_Py`, `txtrs_Py`: overwritten by each Python pipeline run (via the CLI),
  so flipping between tabs gives a direct visual diff

Columns (column-naming conventions):
  year                   — plan fiscal year
  n_active_boy           — active headcount at beginning of year
  n_retired_boy          — retired headcount at beginning of year (NA if not available)
  n_inactive_boy         — terminated-vested headcount at beginning of year (NA if not available)
  payroll_fy             — total DB+DC+CB payroll during fiscal year
  benefits_fy            — total benefit payments (DB + CB) during fiscal year
  aal_boy                — actuarial accrued liability (DB + CB, excludes DC) at BOY
  er_cont_fy             — employer contributions (DB + DC) during fiscal year
  ee_cont_fy             — employee contributions during fiscal year
  mva_boy                — market value of assets at BOY
  invest_income_fy       — investment income during fiscal year (AVA basis, R's exp_inv_earnings)
  ava_boy                — actuarial value of assets at BOY
  fr_mva_boy             — funded ratio = MVA / AAL at BOY
  fr_ava_boy             — funded ratio = AVA / AAL at BOY

Missing values are reported as pandas NA and will round-trip as empty cells in
both CSV and Excel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd


# Canonical column order for every truth table (R and Python, FRS and TRS).
TRUTH_TABLE_COLUMNS = [
    "plan",
    "year",
    "n_active_boy",
    "n_retired_boy",
    "n_inactive_boy",
    "payroll_fy",
    "benefits_fy",
    "aal_boy",
    "er_cont_fy",
    "ee_cont_fy",
    "mva_boy",
    "invest_income_fy",
    "ava_boy",
    "fr_mva_boy",
    "fr_ava_boy",
]


# ---------------------------------------------------------------------------
# R-side builders — read from R output CSVs, produce a truth table
# ---------------------------------------------------------------------------

def build_r_truth_table_frs(baseline_dir: Path) -> pd.DataFrame:
    """Build the frozen FRS R truth table from the R model's output CSVs.

    Sources:
      - `frs_funding.csv`: plan-wide aggregate of 7 classes + DROP (payroll,
        AAL, MVA, AVA, contributions, benefits, investment income, funded ratios)
      - `{class}_liability.csv` × 7: per-class total_n_active, summed for
        plan-wide n_active

    Not reported (NA) because R does not emit them:
      - n_retired_boy, n_inactive_boy
    """
    f = pd.read_csv(baseline_dir / "frs_funding.csv")

    # Sum active headcount across all 7 FRS classes (per-year)
    frs_classes = ["regular", "special", "admin", "eco", "eso",
                   "judges", "senior_management"]
    n_active = None
    for cn in frs_classes:
        liab = pd.read_csv(baseline_dir / f"{cn}_liability.csv")
        col = liab["total_n_active"].values
        n_active = col if n_active is None else n_active + col

    df = pd.DataFrame({
        "plan": "frs",
        "year": f["year"].astype(int).values,
        "n_active_boy": n_active,
        "n_retired_boy": pd.NA,
        "n_inactive_boy": pd.NA,
        "payroll_fy": f["total_payroll"].values,
        "benefits_fy": f["total_ben_payment"].values,
        "aal_boy": f["total_aal"].values,
        "er_cont_fy": f["total_er_cont"].values,
        "ee_cont_fy": f["total_ee_nc_cont"].values,
        "mva_boy": f["total_mva"].values,
        "invest_income_fy": (f["exp_inv_earnings_ava_legacy"].values
                             + f["exp_inv_earnings_ava_new"].values),
        "ava_boy": f["total_ava"].values,
        "fr_mva_boy": f["fr_mva"].values,
        "fr_ava_boy": f["fr_ava"].values,
    })
    return df[TRUTH_TABLE_COLUMNS]


def build_r_truth_table_txtrs(trs_r_dir: Path) -> pd.DataFrame:
    """Build the frozen TRS R truth table from the R model's output CSVs.

    Sources:
      - `baseline_fresh.csv`: liability output (n.active)
      - `funding_fresh.csv`: funding output (payroll, AAL, MVA, AVA,
        contributions, benefits, investment income, funded ratios)

    Not reported (NA) because R does not emit them:
      - n_retired_boy, n_inactive_boy
    """
    liab = pd.read_csv(trs_r_dir / "baseline_fresh.csv")
    f = pd.read_csv(trs_r_dir / "funding_fresh.csv")

    df = pd.DataFrame({
        "plan": "txtrs",
        "year": f["fy"].astype(int).values,
        "n_active_boy": liab["n.active"].values,
        "n_retired_boy": pd.NA,
        "n_inactive_boy": pd.NA,
        "payroll_fy": f["payroll"].values,
        "benefits_fy": (f["ben_payment_legacy"].values
                        + f["ben_payment_new"].values),
        "aal_boy": f["AAL"].values,
        "er_cont_fy": f["er_cont"].values,
        "ee_cont_fy": (f["ee_nc_cont_legacy"].values
                       + f["ee_nc_cont_new"].values),
        "mva_boy": f["MVA"].values,
        "invest_income_fy": (f["exp_inv_income_legacy"].values
                             + f["exp_inv_income_new"].values),
        "ava_boy": f["AVA"].values,
        "fr_mva_boy": f["FR_MVA"].values,
        "fr_ava_boy": f["FR_AVA"].values,
    })
    return df[TRUTH_TABLE_COLUMNS]


# ---------------------------------------------------------------------------
# Python-side builder — take live pipeline output, produce a truth table
# ---------------------------------------------------------------------------

def build_python_truth_table(
    plan_name: str,
    liability: Dict[str, pd.DataFrame],
    funding,
    constants,
) -> pd.DataFrame:
    """Build a Python-side truth table from live pipeline output.

    Args:
        plan_name: "frs" or "txtrs".
        liability: dict of class_name -> liability DataFrame (per-class).
        funding: the funding object — for FRS this is a dict with a "frs"
            key aggregated across all classes; for TRS it's a single
            DataFrame for the "all" class.
        constants: PlanConfig for the plan.

    Metrics the Python pipeline does not (yet) compute are returned as NA.
    """
    fmt = constants.raw.get("truth_table_format", plan_name)
    if fmt == "frs":
        return _build_python_truth_table_frs(liability, funding, constants)
    elif fmt == "txtrs":
        return _build_python_truth_table_txtrs(liability, funding, constants)
    else:
        raise ValueError(f"unknown truth_table_format: {fmt!r}")


def _build_python_truth_table_frs(liability, funding, constants) -> pd.DataFrame:
    """FRS: funding is a dict containing 'frs' aggregate."""
    f = funding["frs"]

    # Sum total_n_active across all classes
    classes = list(constants.classes)
    n_active = None
    for cn in classes:
        col = liability[cn]["total_n_active"].values
        n_active = col if n_active is None else n_active + col

    df = pd.DataFrame({
        "plan": "frs",
        "year": f["year"].astype(int).values,
        "n_active_boy": n_active,
        "n_retired_boy": pd.NA,
        "n_inactive_boy": pd.NA,
        "payroll_fy": f["total_payroll"].values,
        "benefits_fy": f["total_ben_payment"].values,
        "aal_boy": f["total_aal"].values,
        "er_cont_fy": f["total_er_cont"].values,
        "ee_cont_fy": f["total_ee_nc_cont"].values,
        "mva_boy": f["total_mva"].values,
        "invest_income_fy": (f["exp_inv_earnings_ava_legacy"].values
                             + f["exp_inv_earnings_ava_new"].values),
        "ava_boy": f["total_ava"].values,
        "fr_mva_boy": f["fr_mva"].values,
        "fr_ava_boy": f["fr_ava"].values,
    })
    return df[TRUTH_TABLE_COLUMNS]


def _build_python_truth_table_txtrs(liability, funding, _constants) -> pd.DataFrame:
    """TRS: funding is a single DataFrame; liability['all'] is the per-class frame."""
    # TRS funding columns use uppercase AAL/MVA/AVA naming
    f = funding
    liab = liability["all"]

    # Find the right column names in a case-insensitive way
    def col(df, *options, default=None):
        for o in options:
            if o in df.columns:
                return df[o].values
        return default

    # Prefer "year" over "fy": the Python TRS funding_df populates "year" in
    # all rows but only writes "fy" to row 0 (an initial-row artifact). R's
    # funding_fresh.csv uses "fy" exclusively, so the R builder takes that path.
    year = col(f, "year", "fy")
    aal = col(f, "AAL", "total_aal")
    mva = col(f, "MVA", "total_mva")
    ava = col(f, "AVA", "total_ava")
    payroll = col(f, "payroll", "total_payroll")
    fr_mva = col(f, "FR_MVA", "fr_mva")
    fr_ava = col(f, "FR_AVA", "fr_ava")
    er_cont = col(f, "er_cont", "total_er_cont")

    # Benefits and ee contributions may be split by legacy/new
    ben_leg = col(f, "ben_payment_legacy")
    ben_new = col(f, "ben_payment_new")
    benefits = (ben_leg + ben_new) if ben_leg is not None and ben_new is not None \
               else col(f, "total_ben_payment")

    ee_leg = col(f, "ee_nc_cont_legacy")
    ee_new = col(f, "ee_nc_cont_new")
    ee_cont = (ee_leg + ee_new) if ee_leg is not None and ee_new is not None \
              else col(f, "total_ee_nc_cont")

    inv_leg = col(f, "exp_inv_income_legacy", "exp_inv_earnings_ava_legacy")
    inv_new = col(f, "exp_inv_income_new", "exp_inv_earnings_ava_new")
    invest_income = None
    if inv_leg is not None and inv_new is not None:
        invest_income = inv_leg + inv_new

    n_active = col(liab, "total_n_active")

    n_rows = len(year) if year is not None else len(liab)
    na_col = [pd.NA] * n_rows

    df = pd.DataFrame({
        "plan": "txtrs",
        "year": pd.Series(year).astype(int).values if year is not None else na_col,
        "n_active_boy": n_active if n_active is not None else na_col,
        "n_retired_boy": na_col,
        "n_inactive_boy": na_col,
        "payroll_fy": payroll if payroll is not None else na_col,
        "benefits_fy": benefits if benefits is not None else na_col,
        "aal_boy": aal if aal is not None else na_col,
        "er_cont_fy": er_cont if er_cont is not None else na_col,
        "ee_cont_fy": ee_cont if ee_cont is not None else na_col,
        "mva_boy": mva if mva is not None else na_col,
        "invest_income_fy": invest_income if invest_income is not None else na_col,
        "ava_boy": ava if ava is not None else na_col,
        "fr_mva_boy": fr_mva if fr_mva is not None else na_col,
        "fr_ava_boy": fr_ava if fr_ava is not None else na_col,
    })
    return df[TRUTH_TABLE_COLUMNS]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def format_truth_table_for_log(df: pd.DataFrame, max_rows: int = 31) -> str:
    """Render a truth table as a human-readable text block for stdout/logs.

    Dollar values are shown in millions with comma separators; counts are
    shown as integers; funded ratios as percentages. NA shows as a dash.
    """
    df = df.head(max_rows).copy()

    def _fmt_dollars(v):
        if pd.isna(v):
            return "    —"
        return f"{v / 1e6:>10,.0f}"

    def _fmt_count(v):
        if pd.isna(v):
            return "       —"
        return f"{v:>8,.0f}"

    def _fmt_pct(v):
        if pd.isna(v):
            return "    —"
        return f"{v * 100:>6.2f}%"

    header = (
        f"  {'year':>4s} {'active':>8s} {'retired':>8s} {'inact':>8s} "
        f"{'payroll':>10s} {'benefits':>10s} {'aal':>10s} "
        f"{'er_cont':>10s} {'ee_cont':>10s} {'mva':>10s} "
        f"{'inv_inc':>10s} {'ava':>10s} {'fr_mva':>7s} {'fr_ava':>7s}"
    )
    sep = "  " + "-" * (len(header) - 2)
    lines = [header, sep]

    for _, row in df.iterrows():
        line = (
            f"  {int(row['year']):>4d} "
            f"{_fmt_count(row['n_active_boy'])} "
            f"{_fmt_count(row['n_retired_boy'])} "
            f"{_fmt_count(row['n_inactive_boy'])} "
            f"{_fmt_dollars(row['payroll_fy'])} "
            f"{_fmt_dollars(row['benefits_fy'])} "
            f"{_fmt_dollars(row['aal_boy'])} "
            f"{_fmt_dollars(row['er_cont_fy'])} "
            f"{_fmt_dollars(row['ee_cont_fy'])} "
            f"{_fmt_dollars(row['mva_boy'])} "
            f"{_fmt_dollars(row['invest_income_fy'])} "
            f"{_fmt_dollars(row['ava_boy'])} "
            f"{_fmt_pct(row['fr_mva_boy'])} "
            f"{_fmt_pct(row['fr_ava_boy'])}"
        )
        lines.append(line)

    lines.append("")
    lines.append("  (dollar amounts in millions; funded ratios as percentages)")
    return "\n".join(lines)


def upsert_sheet_to_excel(df: pd.DataFrame, xlsx_path: Path, sheet_name: str) -> None:
    """Write `df` to `sheet_name` in `xlsx_path`, creating the file if needed
    and preserving any other sheets that already exist.

    This is the function the CLI uses to write a Python sheet without
    clobbering the frozen R sheets in the same workbook.
    """
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)

    if xlsx_path.exists():
        with pd.ExcelWriter(
            xlsx_path, engine="openpyxl",
            mode="a", if_sheet_exists="replace",
        ) as w:
            df.to_excel(w, sheet_name=sheet_name, index=False)
    else:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
            df.to_excel(w, sheet_name=sheet_name, index=False)


# ---------------------------------------------------------------------------
# Diff sheet — live formulas that recompute when the Py sheet is overwritten
# ---------------------------------------------------------------------------

# Metrics in the diff sheet. plan/year are label columns, not metrics.
_DIFF_METRICS = [
    ("n_active_boy", "active"),
    ("n_retired_boy", "retired"),
    ("n_inactive_boy", "inactive"),
    ("payroll_fy", "payroll"),
    ("benefits_fy", "benefits"),
    ("aal_boy", "aal"),
    ("er_cont_fy", "er_cont"),
    ("ee_cont_fy", "ee_cont"),
    ("mva_boy", "mva"),
    ("invest_income_fy", "inv_income"),
    ("ava_boy", "ava"),
    ("fr_mva_boy", "fr_mva"),
    ("fr_ava_boy", "fr_ava"),
]


def write_diff_sheet_with_formulas(
    xlsx_path: Path,
    diff_sheet_name: str,
    r_sheet_name: str,
    py_sheet_name: str,
    n_rows: int,
) -> None:
    """Write a diff sheet whose cells are live formulas referencing the R
    and Py sheets, so every time the Py sheet is overwritten by a pipeline
    run the diffs update automatically in Excel.

    Layout (per year row, 41 columns total):
      A: plan          (=r_sheet!A2)   — pulled from R sheet by formula
      B: year          (=r_sheet!B2)
      C: active_R      (=r_sheet!C2)
      D: active_Py     (=py_sheet!C2)
      E: active_diff   (=IFERROR(D2-C2, ""))
      F: retired_R     ...
      ...

    Diff is an ABSOLUTE difference (Py - R), not a percentage.
    """
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Font, PatternFill, Alignment, NamedStyle
    from openpyxl.formatting.rule import CellIsRule

    wb = load_workbook(xlsx_path)

    # Drop existing diff sheet if present — we rewrite from scratch
    if diff_sheet_name in wb.sheetnames:
        del wb[diff_sheet_name]
    ws = wb.create_sheet(diff_sheet_name)

    # --- Header row 1 (group labels spanning 3 cols) + row 2 (R/Py/diff) ---
    # Row 1: "plan" | "year" | metric label across 3 cells | ...
    # Row 2: blank  | blank  | R | Py | diff | R | Py | diff | ...
    ws.cell(row=1, column=1, value="").font = Font(bold=True)
    ws.cell(row=1, column=2, value="").font = Font(bold=True)
    ws.cell(row=2, column=1, value="plan").font = Font(bold=True)
    ws.cell(row=2, column=2, value="year").font = Font(bold=True)

    for i, (_src_col, label) in enumerate(_DIFF_METRICS):
        c_r = 3 + i * 3        # R column
        c_py = c_r + 1         # Py column
        c_diff = c_r + 2       # diff column
        # Merge three cells in header row 1 for the metric label
        ws.cell(row=1, column=c_r, value=label).font = Font(bold=True)
        ws.cell(row=1, column=c_r).alignment = Alignment(horizontal="center")
        ws.merge_cells(
            start_row=1, start_column=c_r, end_row=1, end_column=c_diff
        )
        # Row 2 sub-labels
        ws.cell(row=2, column=c_r, value="R").font = Font(bold=True, italic=True)
        ws.cell(row=2, column=c_py, value="Py").font = Font(bold=True, italic=True)
        ws.cell(row=2, column=c_diff, value="diff").font = Font(bold=True, italic=True)

    # --- Data rows: formulas referencing r_sheet_name and py_sheet_name ---
    # Source sheets have header in row 1 and data starting at row 2.
    # Column mapping in the source sheets (same for R and Py):
    #   A=plan, B=year, C=n_active_boy, D=n_retired_boy, E=n_inactive_boy,
    #   F=payroll_fy, G=benefits_fy, H=aal_boy, I=er_cont_fy, J=ee_cont_fy,
    #   K=mva_boy, L=invest_income_fy, M=ava_boy, N=fr_mva_boy, O=fr_ava_boy
    #
    # Source col C is metric index 0, D is metric index 1, etc.
    for row_idx in range(n_rows):
        src_row = row_idx + 2       # source data starts at row 2
        dst_row = row_idx + 3       # diff data starts at row 3 (after 2 header rows)

        # plan and year — pull from R sheet by formula
        ws.cell(row=dst_row, column=1,
                value=f"='{r_sheet_name}'!A{src_row}")
        ws.cell(row=dst_row, column=2,
                value=f"='{r_sheet_name}'!B{src_row}")

        for i, _ in enumerate(_DIFF_METRICS):
            src_col_letter = get_column_letter(3 + i)   # C, D, E, ...
            c_r = 3 + i * 3
            c_py = c_r + 1
            c_diff = c_r + 2

            ws.cell(row=dst_row, column=c_r,
                    value=f"='{r_sheet_name}'!{src_col_letter}{src_row}")
            ws.cell(row=dst_row, column=c_py,
                    value=f"='{py_sheet_name}'!{src_col_letter}{src_row}")
            # IFERROR wraps NA handling (blank cell in either side -> blank diff)
            ws.cell(
                row=dst_row, column=c_diff,
                value=(
                    f'=IFERROR('
                    f"'{py_sheet_name}'!{src_col_letter}{src_row}"
                    f"-'{r_sheet_name}'!{src_col_letter}{src_row}"
                    f',"")'
                ),
            )

    # --- Number formatting ---
    # Counts (active/retired/inactive, metric idx 0-2): integer with commas
    # Dollars (payroll through ava, metric idx 3-10): integer with commas (raw $)
    # Funded ratios (fr_mva, fr_ava, metric idx 11-12): percentage w/ 4 decimals
    count_metrics = {0, 1, 2}
    ratio_metrics = {11, 12}
    count_fmt = "#,##0;(#,##0)"
    dollar_fmt = '"$"#,##0;("$"#,##0)'
    ratio_fmt = "0.0000%;(0.0000%)"
    diff_count_fmt = "#,##0;(#,##0)"
    diff_dollar_fmt = '"$"#,##0;("$"#,##0)'
    diff_ratio_fmt = "0.000000;(0.000000)"  # absolute ratio diff, 6 decimals

    for i in range(len(_DIFF_METRICS)):
        c_r = 3 + i * 3
        c_py = c_r + 1
        c_diff = c_r + 2
        if i in count_metrics:
            val_fmt, dif_fmt = count_fmt, diff_count_fmt
        elif i in ratio_metrics:
            val_fmt, dif_fmt = ratio_fmt, diff_ratio_fmt
        else:
            val_fmt, dif_fmt = dollar_fmt, diff_dollar_fmt
        for r_row in range(3, 3 + n_rows):
            ws.cell(row=r_row, column=c_r).number_format = val_fmt
            ws.cell(row=r_row, column=c_py).number_format = val_fmt
            ws.cell(row=r_row, column=c_diff).number_format = dif_fmt

    # --- Column widths ---
    # plan, year: narrow. Metric value cols: wide enough for $ figures. diff
    # cols: same width as value cols so differences are easy to eyeball.
    ws.column_dimensions["A"].width = 7
    ws.column_dimensions["B"].width = 6
    for i in range(len(_DIFF_METRICS)):
        base = 3 + i * 3
        for offset in range(3):
            col_letter = get_column_letter(base + offset)
            # Wider for dollar columns, narrower for counts/ratios
            if i in count_metrics:
                ws.column_dimensions[col_letter].width = 12
            elif i in ratio_metrics:
                ws.column_dimensions[col_letter].width = 13
            else:
                ws.column_dimensions[col_letter].width = 17

    # Freeze top 2 header rows and first 2 label columns
    ws.freeze_panes = "C3"

    # --- Conditional formatting: highlight diff cells that are materially
    # nonzero. Since the user wants raw diffs (not percents) we can't use a
    # single threshold across metrics — dollars and ratios are different
    # scales. Apply per-column thresholds.
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

    for i in range(len(_DIFF_METRICS)):
        c_diff = 3 + i * 3 + 2
        col_letter = get_column_letter(c_diff)
        diff_range = f"{col_letter}3:{col_letter}{2 + n_rows}"
        if i in count_metrics:
            # Counts: red if abs diff > 100, yellow if > 1
            red_thresh, yel_thresh = 100, 1
        elif i in ratio_metrics:
            # Ratios: red if abs diff > 0.001 (0.1 pt), yellow if > 0.00001
            red_thresh, yel_thresh = 0.001, 0.00001
        else:
            # Dollars: red if abs diff > $1M, yellow if > $1
            red_thresh, yel_thresh = 1_000_000, 1
        ws.conditional_formatting.add(
            diff_range,
            CellIsRule(operator="greaterThan", formula=[str(red_thresh)], fill=red_fill),
        )
        ws.conditional_formatting.add(
            diff_range,
            CellIsRule(operator="lessThan", formula=[str(-red_thresh)], fill=red_fill),
        )
        ws.conditional_formatting.add(
            diff_range,
            CellIsRule(operator="greaterThan", formula=[str(yel_thresh)], fill=yellow_fill),
        )
        ws.conditional_formatting.add(
            diff_range,
            CellIsRule(operator="lessThan", formula=[str(-yel_thresh)], fill=yellow_fill),
        )

    wb.save(xlsx_path)
