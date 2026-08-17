
import pytest

from saas_words_two.pipeline import RunOptions


def test_production_must_be_500(tmp_path):
    with pytest.raises(ValueError):
        RunOptions("production", 499, tmp_path).validate()
    RunOptions("production", 500, tmp_path).validate()


def test_qa_must_be_at_least_10(tmp_path):
    with pytest.raises(ValueError):
        RunOptions("qa", 9, tmp_path).validate()
    RunOptions("qa", 20, tmp_path).validate()


def test_round_size_override_must_be_at_least_target_count(tmp_path):
    with pytest.raises(ValueError):
        RunOptions("qa", 100, tmp_path, round_size=50).validate()
    RunOptions("qa", 100, tmp_path, round_size=10000).validate()  # no error
