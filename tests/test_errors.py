import pytest

from botplatform.bots.arcaptcha.errors import describe


def test_describe_joins_type_and_message():
    assert describe(RuntimeError("it broke")) == "RuntimeError: it broke"


def test_describe_keeps_only_the_first_line():
    assert describe(ValueError("first\nsecond\nthird")) == "ValueError: first"


@pytest.mark.parametrize("message", ["", "\n", "\nsecond line"])
def test_describe_gives_just_the_type_when_the_first_line_is_empty(message):
    assert describe(ValueError(message)) == "ValueError"


def test_describe_gives_just_the_type_for_no_message():
    assert describe(TimeoutError()) == "TimeoutError"


def test_describe_truncates_to_the_default_limit_of_200():
    assert describe(ValueError("x" * 500)) == "ValueError: " + "x" * 200


def test_describe_truncates_to_a_given_limit():
    assert describe(ValueError("abcdef"), limit=3) == "ValueError: abc"
