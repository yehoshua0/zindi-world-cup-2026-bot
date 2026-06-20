import math
from wc2026bot.evaluation import (
    rmse, macro_f1, normalize_rmse, combined, rank_cohort,
)

def test_rmse_known():
    pred = {"a": 3.0, "b": 1.0}
    actual = {"a": 1.0, "b": 1.0}
    # errors 2,0 -> mean sq = 2 -> sqrt(2)
    assert math.isclose(rmse(pred, actual), math.sqrt(2))

def test_macro_f1_perfect():
    pred = {"a": "group", "b": "champion"}
    actual = {"a": "group", "b": "champion"}
    # only classes present score 1; absent classes contribute 0 over 7
    assert math.isclose(macro_f1(pred, actual), 2 / 7)

def test_macro_f1_all_wrong_one_class():
    pred = {"a": "group", "b": "group"}
    actual = {"a": "qf", "b": "sf"}
    assert macro_f1(pred, actual) == 0.0

def test_normalize_rmse_edges():
    assert normalize_rmse(5, 5, 5) == 1.0           # degenerate
    assert normalize_rmse(2, 2, 4) == 1.0           # best (min)
    assert normalize_rmse(4, 2, 4) == 0.0           # worst (max)
    assert normalize_rmse(3, 2, 4) == 0.5

def test_combined():
    assert math.isclose(combined(1.0, 0.5), 0.8)

def test_rank_cohort_orders_by_combined():
    # user1 best rmse worst f1; user2 worst rmse best f1
    res = rank_cohort({1: (2.0, 0.2), 2: (4.0, 0.9)})
    by_id = {u.user_id: u for u in res}
    # user1 rmse_norm=1.0 -> 0.6 + 0.08 = 0.68
    # user2 rmse_norm=0.0 -> 0.0 + 0.36 = 0.36
    assert by_id[1].rank == 1
    assert by_id[2].rank == 2
