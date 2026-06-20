import math
from dataclasses import dataclass

from wc2026bot.validation import VALID_STAGES


def rmse(pred: dict[str, float], actual: dict[str, float]) -> float:
    keys = list(actual.keys())
    if not keys:
        return 0.0
    se = sum((pred[k] - actual[k]) ** 2 for k in keys)
    return math.sqrt(se / len(keys))


def macro_f1(pred: dict[str, str], actual: dict[str, str]) -> float:
    keys = list(actual.keys())
    total = 0.0
    for stage in VALID_STAGES:
        tp = sum(1 for k in keys if pred[k] == stage and actual[k] == stage)
        fp = sum(1 for k in keys if pred[k] == stage and actual[k] != stage)
        fn = sum(1 for k in keys if pred[k] != stage and actual[k] == stage)
        denom = 2 * tp + fp + fn
        f1 = (2 * tp / denom) if denom else 0.0
        total += f1
    return total / len(VALID_STAGES)


def normalize_rmse(raw: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 1.0
    return 1.0 - (raw - lo) / (hi - lo)


def combined(rmse_norm: float, f1: float) -> float:
    return 0.6 * rmse_norm + 0.4 * f1


@dataclass(frozen=True)
class UserScore:
    user_id: int
    raw_rmse: float
    f1: float
    rmse_norm: float
    combined: float
    rank: int


def rank_cohort(per_user: dict[int, tuple[float, float]]) -> list[UserScore]:
    if not per_user:
        return []
    rmses = [r for r, _ in per_user.values()]
    lo, hi = min(rmses), max(rmses)
    rows = []
    for uid, (raw, f1) in per_user.items():
        rn = normalize_rmse(raw, lo, hi)
        rows.append((uid, raw, f1, rn, combined(rn, f1)))
    rows.sort(key=lambda x: x[4], reverse=True)
    return [
        UserScore(uid, raw, f1, rn, comb, i)
        for i, (uid, raw, f1, rn, comb) in enumerate(rows, start=1)
    ]
