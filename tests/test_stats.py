import pytest

from botplatform.stats import wilson_interval


def test_no_trials_has_no_interval():
    assert wilson_interval(0, 0) is None


def test_zero_of_n_starts_at_zero_and_is_not_zero_width():
    low, high = wilson_interval(0, 10)
    assert low == 0.0
    assert high == pytest.approx(0.2775, abs=1e-4)  # known value for 0/10 at 95%


def test_n_of_n_ends_at_one_and_is_not_zero_width():
    low, high = wilson_interval(10, 10)
    assert high == 1.0
    assert low == pytest.approx(0.7225, abs=1e-4)


def test_middle_value():
    low, high = wilson_interval(5, 10)
    assert (low, high) == pytest.approx((0.2366, 0.7634), abs=1e-4)


def test_more_trials_narrow_the_interval():
    small = wilson_interval(5, 10)
    large = wilson_interval(50, 100)
    assert large[1] - large[0] < small[1] - small[0]


def test_impossible_counts_are_rejected():
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
    with pytest.raises(ValueError):
        wilson_interval(-1, 10)
