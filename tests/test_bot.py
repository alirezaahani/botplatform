"""The ARCaptcha bot: real Selenium and real Chrome against the local fake demo site."""

import socket

import pytest
from selenium.webdriver.common.by import By

from botplatform.bots import arcaptcha
from botplatform.bots.arcaptcha import ArcaptchaBot, Scenario
from botplatform.bots.selenium_support import chrome
from botplatform.contract import Status
from tests.conftest import FAST, PASSWORD, USERNAME, RecordingContext
from tests.fake_demo.server import CHALLENGE_ID, Reply, create_reply

BLOCKED_LOGIN = Reply(status=400, json={"msg": "Please solve captcha"})
# Starting Chrome takes a few seconds, so a timeout test allows for it on top of the step time.
CHROME_START = 12


def assert_login_attempted(fake):
    assert len(fake.logins) == 1


# -- Main workflow ------------------------------------------------------------------------------


@pytest.mark.parametrize("captcha_type", ["accept", "cookie"])
def test_accepted_checkbox_then_confirmed_login_succeeds(fake, run_bot, captcha_type):
    fake.creates = [create_reply(captcha_type)]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.SUCCESS, None)
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]
    assert fake.logins == [
        {"username": USERNAME, "password": PASSWORD, "captcha_token": CHALLENGE_ID}
    ]
    assert outcome.ctx.one("login_response")["http_status"] == 200
    assert outcome.ctx.one("toast")["kind"] == "success"


def test_softban_with_confirmed_login_succeeds(fake, run_bot):
    fake.creates = [create_reply("cookie", softban=True, message="You are softbanned")]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.SUCCESS, None)
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]
    # The bot keeps no softban-specific data. Only the create response's type is recorded.
    assert outcome.ctx.one("create_response")["captcha_type"] == "cookie"


def test_softban_with_rejected_login_fails_verification(fake, run_bot):
    fake.creates = [create_reply("cookie", softban=True, message="You are softbanned")]
    fake.login = BLOCKED_LOGIN
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.FAILED, "verification_failed")
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]


# -- Blocking -----------------------------------------------------------------------------------


def test_block_with_id_records_the_id_and_still_logs_in(fake, run_bot):
    fake.creates = [create_reply("block")]
    fake.login = BLOCKED_LOGIN
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.BLOCKED, "captcha_blocked")
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]
    after = outcome.ctx.one("widget_challenge_id_after_click")
    assert after["widget_value"] == {"value": None}
    assert after["hidden_field"] == {"value": None}
    assert_login_attempted(fake)
    login = outcome.ctx.one("login_response")
    assert login["http_status"] == 400
    assert login["body"] == {"msg": "Please solve captcha"}


def test_block_without_id(fake, run_bot):
    fake.creates = [create_reply("block", challenge_id=None)]
    fake.login = BLOCKED_LOGIN
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.BLOCKED, "captcha_blocked")
    assert outcome.ctx.challenge_ids == []
    assert_login_attempted(fake)


def test_successful_login_never_upgrades_a_block(fake, run_bot):
    fake.creates = [create_reply("block")]
    outcome = run_bot()  # the fake's login defaults to 200 with a green toast

    assert (outcome.result.status, outcome.result.reason) == (Status.BLOCKED, "captcha_blocked")
    assert outcome.ctx.one("login_response")["http_status"] == 200


@pytest.mark.parametrize("captcha_type", ["puzzle", "question", "2fa"])
def test_challenges_are_blocked_as_unsolved(fake, run_bot, captcha_type):
    fake.creates = [create_reply(captcha_type)]
    fake.login = BLOCKED_LOGIN
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.BLOCKED, "challenge_unsolved")
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]
    assert_login_attempted(fake)


# -- Missing challenge_id -----------------------------------------------------------------------


def test_accept_without_id_fails(fake, run_bot):
    fake.creates = [create_reply("accept", challenge_id=None)]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (
        Status.FAILED,
        "missing_challenge_id",
    )
    assert outcome.ctx.challenge_ids == []
    assert_login_attempted(fake)


def test_undecodable_body_fails_without_crashing(fake, run_bot):
    fake.creates = [Reply(raw=b"this is not a captcha body at all")]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (
        Status.FAILED,
        "missing_challenge_id",
    )
    assert outcome.ctx.one("create_response")["decode_error"] == "ValueError"


def test_http_500_from_create_fails(fake, run_bot):
    fake.creates = [Reply(status=500, json={"message": "boom"})]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (
        Status.FAILED,
        "missing_challenge_id",
    )
    assert outcome.ctx.one("create_response")["http_status"] == 500


def test_http_422_from_create_fails_and_records_the_alert(fake, run_bot):
    fake.creates = [Reply(status=422, json={"message": "Invalid site key"})]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (
        Status.FAILED,
        "missing_challenge_id",
    )
    assert outcome.ctx.of("alert") == [{"text": "Invalid site key"}]


# -- Verification -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("login", "toast"),
    [
        (Reply(status=401, json={"msg": "Wrong password"}), {}),
        (Reply(status=200, json={"msg": "You are logged in successfully!"}), {"kind": "error"}),
        (Reply(status=200, json={"msg": "You are logged in successfully!"}), {"text": "Other"}),
        (Reply(status=200, json={}), {}),
        (Reply(status=200, json={"msg": "You are logged in successfully!"}), {"none": True}),
    ],
    ids=["401-red", "200-red", "200-different-text", "200-no-msg", "200-no-toast"],
)
def test_login_not_confirmed_by_both_signals_fails(fake, run_bot, login, toast):
    fake.login = login
    fake.toast = {"none": False, "kind": None, "text": None} | toast
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.FAILED, "verification_failed")
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]


def test_missing_toast_is_recorded_as_none(fake, run_bot):
    fake.toast = {"none": True, "kind": None, "text": None}
    outcome = run_bot()

    assert outcome.ctx.one("toast") == {"kind": "none", "text": ""}
    assert "none" in outcome.result.error


# -- Timeouts -----------------------------------------------------------------------------------


def assert_timeout(outcome, step, seconds):
    assert (outcome.result.status, outcome.result.reason) == (Status.TIMEOUT, step)
    assert outcome.seconds < seconds + CHROME_START, f"took {outcome.seconds:.1f}s"


def test_page_load_hang(fake, run_bot):
    fake.page = Reply(action="hang")
    outcome = run_bot()

    assert_timeout(outcome, "load_page", FAST.load_page)
    assert fake.logins == []


def test_checkbox_missing(fake, run_bot):
    fake.checkbox = False
    outcome = run_bot()

    assert_timeout(outcome, "find_checkbox", FAST.find_checkbox)
    assert fake.logins == []


def test_create_hang(fake, run_bot):
    fake.creates = [Reply(action="hang")]
    outcome = run_bot()

    assert_timeout(outcome, "create_response", FAST.create_response)
    assert outcome.ctx.of("checkbox_clicked")
    assert fake.logins == []


def test_create_connection_dropped(fake, run_bot):
    fake.creates = [Reply(action="drop", json={"status": "OK", "captcha_type": "accept"})]
    outcome = run_bot()

    # The failed request produces no response, so the wait ends in a timeout. The
    # `create_requests` event comes after that wait, so it is never reached.
    assert_timeout(outcome, "create_response", FAST.create_response)
    assert outcome.ctx.of("create_requests") == []
    assert outcome.ctx.of("create_response") == []
    assert fake.logins == []


def test_login_response_hang(fake, run_bot):
    fake.login = Reply(action="hang")
    outcome = run_bot()

    assert_timeout(outcome, "login_response", FAST.create_response + FAST.login_response)
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]


def test_blocked_run_whose_login_hangs_stays_blocked(fake, run_bot):
    fake.creates = [create_reply("block")]
    fake.login = Reply(action="hang")
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.BLOCKED, "captcha_blocked")
    assert outcome.ctx.one("login_timeout") == {"step": "login_response"}


# -- Other errors -------------------------------------------------------------------------------


def test_unknown_captcha_type_is_an_error(fake, run_bot):
    fake.creates = [create_reply("hologram")]
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.ERROR, "unknown_captcha_type")
    assert_login_attempted(fake)


def test_connection_refused_is_an_error(run_bot):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port_url = f"http://127.0.0.1:{sock.getsockname()[1]}/"
    outcome = run_bot(url=closed_port_url)

    assert (outcome.result.status, outcome.result.reason) == (Status.ERROR, "unhandled_exception")
    assert "ERR_CONNECTION_REFUSED" in outcome.result.error


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("ARCAPTCHA_USERNAME", raising=False)
    monkeypatch.delenv("ARCAPTCHA_PASSWORD", raising=False)
    result = ArcaptchaBot().run(RecordingContext())

    assert (result.status, result.reason) == (Status.ERROR, "missing_credentials")


# -- History and robustness ---------------------------------------------------------------------


def test_two_create_responses_are_recorded_in_network_order(fake, run_bot):
    first, second = "1" * 30, "2" * 30
    fake.creates = [create_reply("accept", first), create_reply("accept", second)]
    fake.second_create = True
    outcome = run_bot()

    assert outcome.ctx.challenge_ids == [first, second]
    assert fake.logins[0]["captcha_token"] == second
    assert (outcome.result.status, outcome.result.reason) == (Status.SUCCESS, None)


def test_js_alert_is_recorded_and_the_run_continues(fake, run_bot):
    fake.alert_on_click = "Hello from the page"
    outcome = run_bot()

    assert {"text": "Hello from the page"} in outcome.ctx.of("alert")
    assert (outcome.result.status, outcome.result.reason) == (Status.SUCCESS, None)


def test_cors_preflight_is_not_counted(fake, run_bot):
    outcome = run_bot()

    requests = outcome.ctx.one("create_requests")
    assert [r["method"] for r in requests["not_counted"]] == ["OPTIONS"]
    assert requests["post_requests_started"] == 1
    assert requests["responses"] == fake.create_requests == 1
    assert requests["failed"] == 0


# -- Secrets ------------------------------------------------------------------------------------


def test_screenshots_never_show_the_password(fake, credentials):
    seen: list[tuple[str, str]] = []
    with chrome(headless=True) as driver:

        def on_artifact(name: str) -> None:
            field = driver.find_elements(By.ID, "password")
            seen.append((name, field[0].get_attribute("value") if field else "no field"))

        ctx = RecordingContext(on_artifact)
        Scenario(ctx, driver, USERNAME, PASSWORD, fake.url, FAST).run()

    names = [name for name, _ in seen]
    assert "after-login.png" in names
    assert fake.logins[0]["password"] == PASSWORD  # it really was typed before the last shots
    assert all(value == "" for _, value in seen), seen


def test_unhandled_exception_text_hides_the_password(fake, run_bot, monkeypatch):
    def explode(self):
        raise RuntimeError(f"cannot log in with {PASSWORD}")

    monkeypatch.setattr(arcaptcha.Scenario, "_log_in", explode)
    outcome = run_bot()

    assert (outcome.result.status, outcome.result.reason) == (Status.ERROR, "unhandled_exception")
    assert "[password]" in outcome.result.error
    assert PASSWORD not in outcome.result.error
