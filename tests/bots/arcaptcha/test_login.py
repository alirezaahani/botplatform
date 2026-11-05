"""When a login counts as verified: the response and the toast must agree. No Chrome."""

import pytest

from botplatform.bots.arcaptcha.login import verify_login
from botplatform.contract import Status

OK = "You are logged in successfully!"


@pytest.mark.parametrize(
    ("http_status", "body", "toast", "confirmed"),
    [
        pytest.param(200, {"msg": OK}, {"kind": "success", "text": OK}, True, id="both-agree"),
        pytest.param(
            200,
            {"msg": OK},
            {"kind": "success", "text": f"  {OK}  Bye"},
            True,
            id="toast-says-more",
        ),
        pytest.param(
            401,
            {"msg": "Wrong password"},
            {"kind": "error", "text": "Wrong password"},
            False,
            id="refused",
        ),
        pytest.param(401, {"msg": OK}, {"kind": "success", "text": OK}, False, id="green-on-a-401"),
        pytest.param(200, {"msg": OK}, {"kind": "error", "text": OK}, False, id="red-on-a-200"),
        pytest.param(
            200, {"msg": OK}, {"kind": "success", "text": "Other"}, False, id="other-text"
        ),
        pytest.param(200, {"msg": OK}, {"kind": "none", "text": ""}, False, id="no-toast"),
        pytest.param(200, {}, {"kind": "success", "text": OK}, False, id="no-message"),
        pytest.param(200, None, {"kind": "success", "text": OK}, False, id="body-not-json"),
    ],
)
def test_a_login_counts_only_when_the_response_and_the_toast_agree(
    http_status, body, toast, confirmed
):
    result = verify_login(http_status, body, toast)

    assert (result is None) is confirmed
    if not confirmed:
        assert result is not None
        assert (result.status, result.reason) == (Status.FAILED, "verification_failed")
