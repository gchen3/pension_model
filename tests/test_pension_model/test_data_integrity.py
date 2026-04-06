"""Data integrity tests for stage 3 files.

Verifies that classes sharing the same underlying decrement source have
byte-identical data files. This catches accidental drift if someone
edits one copy and forgets to update the others.
"""
import hashlib
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent.parent.parent / "plans"

# Groups of classes that should have identical decrement files.
# Each tuple is (plan, [class_names]) where every class_name in the list
# should have the same {cn}_termination_rates.csv and {cn}_retirement_rates.csv.
SHARED_DECREMENT_GROUPS = [
    ("frs", ["regular", "eso"]),
]


def _file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("plan,group", SHARED_DECREMENT_GROUPS)
def test_shared_decrement_files_identical(plan, group):
    """Classes that share decrement sources must have byte-identical data files."""
    decr_dir = DATA_DIR / plan / "data" / "decrements"
    for suffix in ["termination_rates.csv", "retirement_rates.csv"]:
        hashes = {}
        for cn in group:
            path = decr_dir / f"{cn}_{suffix}"
            assert path.exists(), f"Missing: {path}"
            hashes[cn] = _file_hash(path)
        first_cn = group[0]
        for cn in group[1:]:
            assert hashes[cn] == hashes[first_cn], (
                f"{plan}: {cn}_{suffix} differs from {first_cn}_{suffix}. "
                f"These classes share the same decrement source and their "
                f"data files must be kept in sync."
            )
