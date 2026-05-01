"""Render a plan's input_checklist.csv to a human-readable markdown view.

Usage:
    python prep/common/render_input_checklist.py {plan}

Reads:
    prep/{plan}/input_checklist.csv
Writes:
    prep/{plan}/reports/input_checklist.md

The markdown view groups rows by category and surfaces open gaps
(status = missing or partial) at the top. Other sections of the file
(prose preamble, "what this is for") are written from a small template
in this script — edit here, not in the generated file.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


CATEGORY_HEADINGS = {
    "plan_meta": "Plan meta",
    "economic": "Economic assumptions",
    "ranges": "Ranges (modeling grid)",
    "benefit": "Benefit rules",
    "plan_structure": "Plan structure (classes, tiers, multipliers)",
    "funding_policy": "Funding policy",
    "valuation_inputs": "Valuation inputs (per class)",
    "funding_year0": "Funding year-0 seed (init_funding.csv)",
    "calibration": "Calibration (computed)",
    "term_vested": "Term-vested cashflow parameters",
    "demographics": "Demographics",
    "decrements": "Decrements",
    "mortality": "Mortality",
    "funding_data": "Funding data",
    "modeling": "Modeling switches",
}

CATEGORY_ORDER = list(CATEGORY_HEADINGS.keys())

STATUS_ORDER = {"missing": 0, "partial": 1, "have": 2, "N/A": 3, "": 4}


def _format_source(row: dict) -> str:
    """Build a compact source citation cell from row fields."""
    parts = []
    if row.get("source_doc"):
        parts.append(row["source_doc"])
    pages = []
    if row.get("printed_page"):
        pages.append(f"printed p. {row['printed_page']}")
    if row.get("pdf_page"):
        pages.append(f"PDF p. {row['pdf_page']}")
    if pages:
        parts.append(" / ".join(pages))
    if row.get("table_or_section"):
        parts.append(row["table_or_section"])
    return "; ".join(parts) or "—"


def _escape_pipe(s: str) -> str:
    return s.replace("|", "\\|")


def _row_md_cell(s: str) -> str:
    return _escape_pipe((s or "").strip())


def render(plan: str) -> Path:
    csv_path = REPO_ROOT / "prep" / plan / "input_checklist.csv"
    out_path = REPO_ROOT / "prep" / plan / "reports" / "input_checklist.md"

    with csv_path.open() as f:
        rows = list(csv.DictReader(f))

    # status summary
    status_counts = Counter(r["status"] or "" for r in rows)
    total = len(rows)

    # gaps
    gaps = [r for r in rows if r["status"] in ("missing", "partial")]
    gaps.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 99), r["category"], r["item"]))

    # by category
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)

    lines: list[str] = []
    lines.append(f"# {plan.upper()} Input Checklist")
    lines.append("")
    lines.append(
        f"Plan-level view of every input the runtime needs to run `{plan}`, "
        "with status and source for each. Generated from "
        f"`prep/{plan}/input_checklist.csv` by "
        "`prep/common/render_input_checklist.py`. Schema is documented in "
        "`prep/common/reports/input_checklist_README.md`."
    )
    lines.append("")
    lines.append("## Status summary")
    lines.append("")
    lines.append("| status | count |")
    lines.append("| --- | --- |")
    for status in ("have", "partial", "missing", "N/A"):
        lines.append(f"| {status} | {status_counts.get(status, 0)} |")
    lines.append(f"| **total** | **{total}** |")
    lines.append("")

    lines.append("## Open gaps")
    lines.append("")
    if not gaps:
        lines.append("No open gaps — every row is `have` or `N/A`.")
    else:
        lines.append("Rows with status `missing` or `partial`.")
        lines.append("")
        lines.append("| category | item | status | source_type | notes |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in gaps:
            note = (r.get("notes") or "").replace("\n", " ")
            lines.append(
                f"| {_row_md_cell(r['category'])} "
                f"| {_row_md_cell(r['item'])} "
                f"| {_row_md_cell(r['status'])} "
                f"| {_row_md_cell(r['source_type'] or '—')} "
                f"| {_row_md_cell(note)} |"
            )
    lines.append("")

    lines.append("## Full checklist by category")
    lines.append("")
    for cat in CATEGORY_ORDER:
        cat_rows = by_cat.get(cat, [])
        if not cat_rows:
            continue
        lines.append(f"### {CATEGORY_HEADINGS[cat]}")
        lines.append("")
        lines.append("| item | required | status | source_type | source citation | notes |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        cat_rows = sorted(cat_rows, key=lambda r: (STATUS_ORDER.get(r["status"], 99), r["item"]))
        for r in cat_rows:
            note = (r.get("notes") or "").replace("\n", " ")
            lines.append(
                f"| {_row_md_cell(r['item'])} "
                f"| {_row_md_cell(r['required'])} "
                f"| {_row_md_cell(r['status'])} "
                f"| {_row_md_cell(r['source_type'] or '—')} "
                f"| {_row_md_cell(_format_source(r))} "
                f"| {_row_md_cell(note)} |"
            )
        lines.append("")

    # any rows with categories not in the canonical order
    extras = [c for c in by_cat if c not in CATEGORY_HEADINGS]
    for cat in extras:
        lines.append(f"### {cat}")
        lines.append("")
        lines.append("| item | required | status | source_type | source citation | notes |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in sorted(by_cat[cat], key=lambda r: (STATUS_ORDER.get(r["status"], 99), r["item"])):
            note = (r.get("notes") or "").replace("\n", " ")
            lines.append(
                f"| {_row_md_cell(r['item'])} "
                f"| {_row_md_cell(r['required'])} "
                f"| {_row_md_cell(r['status'])} "
                f"| {_row_md_cell(r['source_type'] or '—')} "
                f"| {_row_md_cell(_format_source(r))} "
                f"| {_row_md_cell(note)} |"
            )
        lines.append("")

    lines.append("## What this checklist is for")
    lines.append("")
    lines.append(
        "- A single place to see, per plan, what is sourced, partially "
        "sourced, estimated, computed, or still missing."
    )
    lines.append(
        "- A reusable shape: copy `prep/common/input_checklist_template.csv` "
        "for a new plan, fill in the right-hand columns as documents arrive."
    )
    lines.append(
        "- Complementary to `artifact_provenance.csv`, `source_registry.csv`, "
        "and the artifact coverage matrix. The checklist drills into "
        "individual scalars in `init_funding.csv`, `valuation_inputs`, and "
        "the calibration block — places where one row per file is too "
        "coarse to see the gaps."
    )
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return out_path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: render_input_checklist.py {plan}", file=sys.stderr)
        return 2
    out = render(argv[1])
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
