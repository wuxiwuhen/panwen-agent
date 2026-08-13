"""Task 8: 执行准确率 + F1 计算(toy gold/pred)。"""
from panwen.eval import runner as R


def test_exec_acc_exact_match():
    assert R.row_sets_equal([{"a": 1}], [{"a": 1}]) is True
    assert R.row_sets_equal([{"a": 1}], [{"a": 2}]) is False


def test_f1_partial_match():
    # gold 3 行, pred 2 行(1 行命中) → P=1/2, R=1/3
    gold = [{"a": 1}, {"a": 2}, {"a": 3}]
    pred = [{"a": 1}, {"a": 9}]
    p, r, f1 = R.pr_f1(gold, pred)
    assert abs(p - 0.5) < 1e-6 and abs(r - 1/3) < 1e-6 and f1 > 0


def test_f1_empty_pred():
    p, r, f1 = R.pr_f1([{"a": 1}], [])
    assert f1 == 0.0
