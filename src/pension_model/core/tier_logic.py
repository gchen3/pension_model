"""
Tier determination and separation type logic.

Replicates R's get_tier() and get_sep_type() from Florida FRS benefit model.R.
These are plan-specific rules that should eventually go through the adapter pattern.
"""

import numpy as np


def get_tier(class_name: str, entry_year, age, yos, new_year: int = 2024) -> str:
    """
    Determine the tier/status for a member.

    Args:
        class_name: Membership class (e.g., "regular", "special", "admin").
        entry_year: Year the member entered the plan.
        age: Current age (or term_age/dist_age depending on context).
        yos: Years of service.
        new_year: Year when tier 3 begins (default 2024).

    Returns:
        Tier string like "tier_1_norm", "tier_2_vested", "tier_3_non_vested", etc.
    """
    is_special = class_name in ("special", "admin")

    if entry_year < 2011:
        # Tier 1
        if is_special:
            if yos >= 25 or (age >= 55 and yos >= 6) or (age >= 52 and yos >= 25):
                return "tier_1_norm"
        else:
            if yos >= 30 or (age >= 62 and yos >= 6):
                return "tier_1_norm"
        if is_special:
            if yos >= 6 and age >= 53:
                return "tier_1_early"
        else:
            if yos >= 6 and age >= 58:
                return "tier_1_early"
        if yos >= 6:
            return "tier_1_vested"
        return "tier_1_non_vested"

    elif entry_year < new_year:
        # Tier 2
        if is_special:
            if yos >= 30 or (age >= 60 and yos >= 8):
                return "tier_2_norm"
        else:
            if yos >= 33 or (age >= 65 and yos >= 8):
                return "tier_2_norm"
        if is_special:
            if yos >= 8 and age >= 56:
                return "tier_2_early"
        else:
            if yos >= 8 and age >= 61:
                return "tier_2_early"
        if yos >= 8:
            return "tier_2_vested"
        return "tier_2_non_vested"

    else:
        # Tier 3
        if is_special:
            if yos >= 30 or (age >= 60 and yos >= 8):
                return "tier_3_norm"
        else:
            if yos >= 33 or (age >= 65 and yos >= 8):
                return "tier_3_norm"
        if is_special:
            if yos >= 8 and age >= 56:
                return "tier_3_early"
        else:
            if yos >= 8 and age >= 61:
                return "tier_3_early"
        if yos >= 8:
            return "tier_3_vested"
        return "tier_3_non_vested"


def get_tier_vectorized(class_name: str, entry_year: np.ndarray,
                        age: np.ndarray, yos: np.ndarray,
                        new_year: int = 2024) -> np.ndarray:
    """Vectorized version of get_tier for DataFrame operations."""
    n = len(entry_year)
    result = np.empty(n, dtype=object)
    for i in range(n):
        result[i] = get_tier(class_name, entry_year[i], age[i], yos[i], new_year)
    return result


def get_ben_mult(class_name: str, tier: str, dist_age: int, yos: int, dist_year: int = 0) -> float:
    """
    Benefit multiplier by class, tier, age, and YOS.

    Replicates R's ben_mult logic (benefit model lines 722-797).
    FRS-specific: Regular/Admin have graded multipliers; others are flat.
    """
    if "tier_1" in tier:
        min_yos_vesting = 6
        if class_name == "regular":
            if (dist_age >= 65 and yos >= min_yos_vesting) or yos >= 33:
                return 0.0168
            if (dist_age >= 64 and yos >= min_yos_vesting) or yos >= 32:
                return 0.0165
            if (dist_age >= 63 and yos >= min_yos_vesting) or yos >= 31:
                return 0.0163
            if (dist_age >= 62 and yos >= min_yos_vesting) or yos >= 30:
                return 0.0160
            if "early" in tier:
                return 0.0160
            return float("nan")
        elif class_name == "admin":
            if (dist_age >= 58 and yos >= min_yos_vesting) or yos >= 28:
                return 0.0168
            if (dist_age >= 57 and yos >= min_yos_vesting) or yos >= 27:
                return 0.0165
            if (dist_age >= 56 and yos >= min_yos_vesting) or yos >= 26:
                return 0.0163
            if (dist_age >= 55 and yos >= min_yos_vesting) or yos >= 25:
                return 0.0160
            if "early" in tier:
                return 0.0160
            return float("nan")
        elif class_name == "special":
            return 0.02 if dist_year <= 1974 else 0.03
        elif class_name in ("eco", "eso"):
            return 0.03
        elif class_name == "judges":
            return 0.0333
        elif class_name == "senior_management":
            return 0.02

    elif "tier_2" in tier:
        min_yos_vesting = 8
        if class_name == "regular":
            if (dist_age >= 68 and yos >= min_yos_vesting) or yos >= 36:
                return 0.0168
            if (dist_age >= 67 and yos >= min_yos_vesting) or yos >= 35:
                return 0.0165
            if (dist_age >= 66 and yos >= min_yos_vesting) or yos >= 34:
                return 0.0163
            if (dist_age >= 65 and yos >= min_yos_vesting) or yos >= 33:
                return 0.0160
            if "early" in tier:
                return 0.0160
            return float("nan")
        elif class_name == "admin":
            if (dist_age >= 63 and yos >= min_yos_vesting) or yos >= 33:
                return 0.0168
            if (dist_age >= 62 and yos >= min_yos_vesting) or yos >= 32:
                return 0.0165
            if (dist_age >= 61 and yos >= min_yos_vesting) or yos >= 31:
                return 0.0163
            if (dist_age >= 60 and yos >= min_yos_vesting) or yos >= 30:
                return 0.0160
            if "early" in tier:
                return 0.0160
            return float("nan")
        elif class_name == "special":
            return 0.02 if dist_year <= 1974 else 0.03
        elif class_name in ("eco", "eso"):
            return 0.03
        elif class_name == "judges":
            return 0.0333
        elif class_name == "senior_management":
            return 0.02

    elif "tier_3" in tier:
        min_yos_vesting = 8
        if class_name == "regular":
            # R tier_3 regular: same as tier_2 (HAS yos-only conditions)
            if (dist_age >= 68 and yos >= min_yos_vesting) or yos >= 36:
                return 0.0168
            if (dist_age >= 67 and yos >= min_yos_vesting) or yos >= 35:
                return 0.0165
            if (dist_age >= 66 and yos >= min_yos_vesting) or yos >= 34:
                return 0.0163
            if (dist_age >= 65 and yos >= min_yos_vesting) or yos >= 33:
                return 0.0160
            if "early" in tier:
                return 0.0160
            return float("nan")
        elif class_name == "admin":
            # R tier_3 admin: age-only conditions, NO yos-only fallback
            # (R benefit model lines 783-789)
            if dist_age >= 63 and yos >= min_yos_vesting:
                return 0.0168
            if dist_age >= 62 and yos >= min_yos_vesting:
                return 0.0165
            if dist_age >= 61 and yos >= min_yos_vesting:
                return 0.0163
            if dist_age >= 60 and yos >= min_yos_vesting:
                return 0.0160
            if "early" in tier:
                return 0.0160
            return float("nan")
        elif class_name == "special":
            return 0.02 if dist_year <= 1974 else 0.03
        elif class_name in ("eco", "eso"):
            return 0.03
        elif class_name == "judges":
            return 0.0333
        elif class_name == "senior_management":
            return 0.02

    return float("nan")


def get_reduce_factor(class_name: str, tier: str, dist_age: int) -> float:
    """
    Early retirement reduction factor.

    Replicates R's reduce_factor logic (benefit model lines 800-815).
    Normal retirement: factor = 1.0 (no reduction).
    Early retirement: 5% per year before normal retirement age.

    Note: R only uses "special" (not admin) for the special-risk NRA.
    Admin gets the non-special NRA despite having special eligibility rules.
    """
    if "norm" in tier:
        return 1.0
    if "early" not in tier:
        return float("nan")

    # R checks class_name == "special" only (admin excluded)
    is_special = class_name == "special"
    if "tier_1" in tier:
        nra = 55 if is_special else 62
    else:  # tier_2 or tier_3
        nra = 60 if is_special else 65

    return 1 - 0.05 * (nra - dist_age)


def get_sep_type(tier: str) -> str:
    """
    Determine separation type from tier string.

    Returns: "retire", "vested", or "non_vested"
    """
    if any(x in tier for x in ("early", "norm", "reduced")):
        return "retire"
    if "non_vested" in tier:
        return "non_vested"
    if "vested" in tier:
        return "vested"
    return "non_vested"
