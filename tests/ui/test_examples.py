from panwen.ui import examples
from panwen.eval.loader import load_dataset


def test_example_questions_are_answerable_and_bounded():
    qs = examples.example_questions()
    assert 0 < len(qs) <= 8
    assert all(isinstance(q, str) and q.strip() for q in qs)


def test_example_questions_match_dataset_answerable_prefix():
    answerable = [it.question for it in load_dataset(examples.DATASET) if it.gold_sql is not None]
    assert examples.example_questions() == answerable[:8]


def test_limit_respected():
    assert len(examples.example_questions(limit=3)) <= 3
