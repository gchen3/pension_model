"""
Bit-identity snapshot tests for the funding model.

Locks the current ``run_funding_model()`` output for both plans into
parquet snapshots under ``tests/fixtures/funding_snapshots/<plan>/``.
Compares with ``pandas.testing.assert_frame_equal(check_exact=True)`` —
no tolerance, dtype-strict, order-strict.

This is the strictest gate during the Phase 2 funding-model unification
refactor: the existing ``test_funding_baseline.py`` uses a 100 ppm
tolerance, which would let sub-ppm drift slip through unnoticed. These
snapshot tests will fail on any change of even one ULP.

Snapshot capture
----------------
To (re)generate the snapshots, set ``FUNDING_SNAPSHOT_UPDATE=1``::

    FUNDING_SNAPSHOT_UPDATE=1 pytest tests/test_pension_model/test_funding_snapshots.py

The first capture happens at Phase 2 Step 0 on the dev machine; after
that, regeneration should be a deliberate, reviewed action (typically
because the model intentionally changed and the diff has been audited).
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

# pyarrow powers parquet I/O for these snapshots; declared in pyproject.toml
# under [project.optional-dependencies].dev. Skip cleanly with a clear message
# rather than dying inside pandas with a cryptic ImportError.
pytest.importorskip("pyarrow", reason="pyarrow is required for the funding-model snapshot tests")

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

SNAPSHOT_DIR = Path(__file__).parent.parent / "fixtures" / "funding_snapshots"
UPDATE_ENV = "FUNDING_SNAPSHOT_UPDATE"


def _running_in_update_mode() -> bool:
    return os.environ.get(UPDATE_ENV, "").strip() not in ("", "0", "false", "False")


def _run_funding(plan_name: str) -> dict:
    """Run the full pipeline and return the funding dict for ``plan_name``."""
    from pension_model.core.pipeline import run_plan_pipeline
    from pension_model.core.funding_model import load_funding_inputs, run_funding_model
    from pension_model.plan_config import load_frs_config, load_txtrs_config

    if plan_name == "frs":
        constants = load_frs_config()
    elif plan_name == "txtrs":
        constants = load_txtrs_config()
    else:
        raise ValueError(f"Unknown plan: {plan_name}")

    liability = run_plan_pipeline(constants)
    funding_inputs = load_funding_inputs(constants.resolve_data_dir() / "funding")
    return run_funding_model(liability, funding_inputs, constants)


def _plan_dir(plan_name: str) -> Path:
    return SNAPSHOT_DIR / plan_name


def _meta_path(plan_name: str) -> Path:
    return _plan_dir(plan_name) / "__keys__.json"


def _parquet_path(plan_name: str, key: str) -> Path:
    # Sanitize key for filesystem (class names are simple identifiers, but be safe)
    safe = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in key)
    return _plan_dir(plan_name) / f"{safe}.parquet"


def _write_snapshot(plan_name: str, funding: dict) -> None:
    plan_dir = _plan_dir(plan_name)
    plan_dir.mkdir(parents=True, exist_ok=True)
    keys = sorted(funding.keys())
    # Dedupe by id() — TRS aliases plan_name to the single class df
    seen_ids: dict[int, str] = {}
    written = []
    for key in keys:
        df = funding[key]
        obj_id = id(df)
        if obj_id in seen_ids:
            continue
        seen_ids[obj_id] = key
        path = _parquet_path(plan_name, key)
        df.to_parquet(path, engine="pyarrow", index=True)
        written.append(path.name)

    meta = {
        "keys": keys,
        "aliases": {
            key: seen_ids[id(funding[key])]
            for key in keys
            if seen_ids[id(funding[key])] != key
        },
    }
    _meta_path(plan_name).write_text(json.dumps(meta, indent=2, sort_keys=True))
    print(
        f"\n[FUNDING_SNAPSHOT_UPDATE] Wrote {plan_name} snapshots: "
        f"{len(written)} parquet file(s) -> {plan_dir}"
    )


def _load_snapshot(plan_name: str) -> tuple[dict, dict]:
    """Return ``(meta_dict, {key: DataFrame})`` for the saved snapshot."""
    meta_path = _meta_path(plan_name)
    if not meta_path.exists():
        pytest.fail(
            f"No snapshot for plan '{plan_name}' at {meta_path}. "
            f"Capture with: {UPDATE_ENV}=1 pytest "
            f"tests/test_pension_model/test_funding_snapshots.py"
        )
    meta = json.loads(meta_path.read_text())
    aliases: dict[str, str] = meta.get("aliases", {})
    frames: dict[str, pd.DataFrame] = {}
    for key in meta["keys"]:
        canonical = aliases.get(key, key)
        if canonical in frames:
            frames[key] = frames[canonical]
            continue
        path = _parquet_path(plan_name, canonical)
        if not path.exists():
            pytest.fail(f"Missing snapshot file: {path}")
        frames[key] = pd.read_parquet(path, engine="pyarrow")
    return meta, frames


# ---------------------------------------------------------------------------
# Capture step (only runs when FUNDING_SNAPSHOT_UPDATE=1)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def frs_funding():
    return _run_funding("frs")


@pytest.fixture(scope="module")
def txtrs_funding():
    return _run_funding("txtrs")


@pytest.mark.skipif(
    not _running_in_update_mode(),
    reason=f"Snapshot regeneration disabled (set {UPDATE_ENV}=1 to enable)",
)
def test_capture_frs_snapshot(frs_funding):
    _write_snapshot("frs", frs_funding)


@pytest.mark.skipif(
    not _running_in_update_mode(),
    reason=f"Snapshot regeneration disabled (set {UPDATE_ENV}=1 to enable)",
)
def test_capture_txtrs_snapshot(txtrs_funding):
    _write_snapshot("txtrs", txtrs_funding)


# ---------------------------------------------------------------------------
# Verification step (always runs)
# ---------------------------------------------------------------------------


def _assert_funding_matches_snapshot(plan_name: str, funding: dict) -> None:
    meta, expected = _load_snapshot(plan_name)

    # 1. Key set must match exactly (catches added / removed dict entries)
    actual_keys = sorted(funding.keys())
    assert actual_keys == meta["keys"], (
        f"{plan_name}: dict key set drifted.\n"
        f"  expected: {meta['keys']}\n"
        f"  actual:   {actual_keys}"
    )

    # 2. Each DataFrame must be bit-identical (no tolerance, dtype-strict)
    for key in actual_keys:
        actual_df = funding[key]
        expected_df = expected[key]
        try:
            assert_frame_equal(
                actual_df,
                expected_df,
                check_exact=True,
                check_dtype=True,
                check_like=False,
                check_names=True,
            )
        except AssertionError as exc:
            raise AssertionError(
                f"{plan_name}[{key!r}] funding snapshot mismatch:\n{exc}"
            ) from None


@pytest.mark.skipif(
    _running_in_update_mode(),
    reason="Snapshot update mode — skipping verification",
)
def test_frs_funding_matches_snapshot(frs_funding):
    _assert_funding_matches_snapshot("frs", frs_funding)


@pytest.mark.skipif(
    _running_in_update_mode(),
    reason="Snapshot update mode — skipping verification",
)
def test_txtrs_funding_matches_snapshot(txtrs_funding):
    _assert_funding_matches_snapshot("txtrs", txtrs_funding)
