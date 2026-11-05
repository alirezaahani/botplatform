"""The ARCaptcha bot's run: real Selenium and Chrome against the local fake demo site.

Only what needs a real browser is tested here. The decisions made from what the browser saw
(which `create` types block, which login responses are confirmed) are tested without Chrome in
`test_verdicts.py`.
"""

import socket
from contextlib import contextmanager
from dataclasses import replace

import pytest
from selenium.webdriver.common.by import By

from botplatform.bots.arcaptcha import BASELINE_BOT, BASELINE_SPEC, ArcaptchaBot, core
from botplatform.bots.arcaptcha.flow import run_flow
from botplatform.bots.arcaptcha.session import Session
from botplatform.bots.selenium_support import chrome
from botplatform.contract import Status
from tests.conftest import FAST, PASSWORD, USERNAME, RecordingContext
from tests.fake_demo.server import CHALLENGE_ID, Reply, Toast, create_reply

LOGIN_OK = Reply(status=200, json={"msg": "You are logged in successfully!"})
LOGIN_REFUSED = Reply(status=400, json={"msg": "Please solve captcha"})
# A step that is meant to time out only needs a moment, and the test waits for all of it.
QUICK = replace(FAST, load_page=1, find_checkbox=1, create_response=1, login_response=1)
# For tests where waiting out a timeout would be the bug: the run must end long before it.
PATIENT = replace(FAST, create_response=30, login_response=30)
FAR_BEFORE_THE_TIMEOUT = 20  # seconds, including Chrome's start


# -- A login that works -------------------------------------------------------------------------


@pytest.mark.parametrize("captcha_type", ["accept", "cookie"])
def test_an_accepted_checkbox_then_a_confirmed_login_succeeds(fake, run_bot, captcha_type):
    fake.creates = [create_reply(captcha_type)]
    outcome = run_bot()

    assert outcome.verdict == (Status.SUCCESS, None)
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]
    # The login carries the challenge ID the site gave us.
    assert fake.logins == [
        {"username": USERNAME, "password": PASSWORD, "captcha_token": CHALLENGE_ID}
    ]


def test_the_latest_of_two_create_responses_is_the_one_the_login_uses(fake, run_bot):
    first, second = "1" * 30, "2" * 30
    fake.creates = [create_reply("accept", first), create_reply("accept", second)]
    fake.send_second_create()
    outcome = run_bot()

    assert outcome.ctx.challenge_ids == [first, second]
    assert fake.logins[0]["captcha_token"] == second
    assert outcome.verdict == (Status.SUCCESS, None)


@pytest.mark.parametrize(
    ("login", "verdict"),
    [(LOGIN_OK, (Status.SUCCESS, None)), (LOGIN_REFUSED, (Status.FAILED, "verification_failed"))],
    ids=["login-confirmed", "login-refused"],
)
def test_a_softban_is_judged_by_the_login_alone(fake, run_bot, login, verdict):
    fake.creates = [create_reply("cookie", softban=True, message="You are softbanned")]
    fake.login = login

    assert run_bot().verdict == verdict


# -- What the page shows after the login --------------------------------------------------------


@pytest.mark.parametrize(
    ("toast", "seen"),
    [(Toast(kind="error"), "error"), (Toast(show=False), "none")],
    ids=["red-toast-on-a-200", "no-toast"],
)
def test_a_login_the_page_does_not_confirm_fails_verification(fake, run_bot, toast, seen):
    fake.toast = toast
    outcome = run_bot()

    assert outcome.verdict == (Status.FAILED, "verification_failed")
    assert outcome.ctx.one("toast")["kind"] == seen


# -- A block, or a challenge nobody solves ------------------------------------------------------


@pytest.mark.parametrize("login", [LOGIN_REFUSED, LOGIN_OK], ids=["login-refused", "login-ok"])
def test_a_block_still_logs_in_and_a_good_login_never_upgrades_it(fake, run_bot, login):
    fake.creates = [create_reply("block")]
    fake.login = login
    outcome = run_bot()

    assert outcome.verdict == (Status.BLOCKED, "captcha_blocked")
    assert outcome.ctx.challenge_ids == [CHALLENGE_ID]
    assert len(fake.logins) == 1
    # A blocked widget never stores the challenge ID, and the bot records that it saw none.
    assert outcome.ctx.one("widget_challenge_id_after_click")["hidden_field"] == {"value": None}


def test_a_puzzle_no_one_solves_ends_blocked_but_still_tries_the_login(fake, run_bot):
    fake.creates = [create_reply("puzzle")]
    fake.login = LOGIN_REFUSED
    outcome = run_bot()

    assert outcome.verdict == (Status.BLOCKED, "challenge_unsolved")
    assert len(fake.logins) == 1


# -- Replies the bot cannot use -----------------------------------------------------------------


def test_a_create_body_nobody_can_decode_fails_without_crashing(fake, run_bot):
    fake.creates = [Reply(raw=b"this is not a captcha body at all")]
    outcome = run_bot()

    assert outcome.verdict == (Status.FAILED, "missing_challenge_id")
    assert outcome.ctx.one("create_response")["decode_error"] == "ValueError"


def test_an_alert_from_the_page_is_recorded_and_the_run_goes_on(fake, run_bot):
    fake.alert_on_click("Hello from the page")
    outcome = run_bot()

    assert outcome.ctx.of("alert") == [{"text": "Hello from the page"}]
    assert outcome.verdict == (Status.SUCCESS, None)


def test_a_rejected_create_that_alerts_fails_the_run_and_records_the_alert(fake, run_bot):
    fake.creates = [Reply(status=422, json={"message": "Invalid site key"})]
    outcome = run_bot()

    assert outcome.ctx.of("alert") == [{"text": "Invalid site key"}]
    assert outcome.verdict == (Status.FAILED, "missing_challenge_id")


def test_a_cors_preflight_is_not_counted_as_a_create_request(fake, run_bot):
    outcome = run_bot()

    requests = outcome.ctx.one("create_requests")
    assert [r["method"] for r in requests["not_counted"]] == ["OPTIONS"]
    assert requests["post_requests_started"] == requests["responses"] == fake.create_requests == 1
    assert requests["failed"] == 0


# -- Timeouts -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("break_the_site", "step"),
    [
        (lambda fake: fake.hang_page(), "load_page"),
        (lambda fake: fake.remove_checkbox(), "find_checkbox"),
        (lambda fake: setattr(fake, "creates", [Reply(action="hang")]), "create_response"),
        (lambda fake: setattr(fake, "login", Reply(action="hang")), "login_response"),
    ],
    ids=["page", "checkbox", "create", "login"],
)
def test_a_step_that_never_finishes_times_out_with_its_name(fake, run_bot, break_the_site, step):
    break_the_site(fake)
    outcome = run_bot(timeouts=QUICK)

    assert outcome.verdict == (Status.TIMEOUT, step)
    # The login is only tried when the page and the checkbox worked.
    assert bool(fake.logins) == (step == "login_response")


def test_a_blocked_run_whose_login_hangs_stays_blocked(fake, run_bot):
    fake.creates = [create_reply("block")]
    fake.login = Reply(action="hang")
    outcome = run_bot(timeouts=QUICK)

    assert outcome.verdict == (Status.BLOCKED, "captcha_blocked")
    assert outcome.ctx.one("login_timeout") == {"step": "login_response"}


# -- Broken connections end the run at once, not at the timeout ---------------------------------


@pytest.mark.parametrize(
    "break_create",
    [
        lambda fake: setattr(fake, "creates", [Reply(action="drop", json={"status": "OK"})]),
        lambda fake: fake.stop_api(),
    ],
    ids=["reply-cut-off", "origin-refuses"],
)
def test_a_failed_create_request_is_an_error_straight_away(fake, run_bot, break_create):
    break_create(fake)
    outcome = run_bot(timeouts=PATIENT)

    assert outcome.verdict == (Status.ERROR, "create_request_failed")
    requests = outcome.ctx.one("create_requests")
    assert (requests["failed"], requests["responses"]) == (1, 0)
    assert outcome.seconds < FAR_BEFORE_THE_TIMEOUT
    assert len(fake.logins) == 1  # a failure that is already classified still logs in


@pytest.mark.parametrize(
    ("create", "verdict"),
    [
        ("accept", (Status.ERROR, "login_request_failed")),
        ("block", (Status.BLOCKED, "captcha_blocked")),  # the earlier failure stands
    ],
)
def test_a_dropped_login_is_an_error_unless_the_run_already_failed(fake, run_bot, create, verdict):
    fake.creates = [create_reply(create)]
    fake.login = Reply(action="drop", json={"msg": "any"})
    outcome = run_bot(timeouts=PATIENT)

    assert outcome.verdict == verdict
    assert outcome.ctx.of("login_request_failed") == [{}]
    assert outcome.seconds < FAR_BEFORE_THE_TIMEOUT


def test_a_site_that_is_down_is_an_error_with_the_reason(run_bot):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port_url = f"http://127.0.0.1:{sock.getsockname()[1]}/"
    outcome = run_bot(url=closed_port_url)

    assert outcome.verdict == (Status.ERROR, "unhandled_exception")
    assert "ERR_CONNECTION_REFUSED" in outcome.result.error


def test_without_credentials_the_run_is_an_error_before_any_browser_starts(monkeypatch):
    monkeypatch.delenv("ARCAPTCHA_USERNAME", raising=False)
    monkeypatch.delenv("ARCAPTCHA_PASSWORD", raising=False)
    result = BASELINE_BOT.run(RecordingContext())

    assert (result.status, result.reason) == (Status.ERROR, "missing_credentials")


# -- The password never leaks -------------------------------------------------------------------


def test_screenshots_never_show_the_password(fake, credentials):
    seen: list[tuple[str, str]] = []
    with chrome(headless=True) as driver:

        def on_artifact(name: str) -> None:
            field = driver.find_elements(By.ID, "password")
            seen.append((name, field[0].get_attribute("value") if field else "no field"))

        ctx = RecordingContext(on_artifact)
        run_flow(Session(ctx, driver, USERNAME, PASSWORD, fake.url, FAST))

    assert "after-login.png" in [name for name, _ in seen]
    assert fake.logins[0]["password"] == PASSWORD  # it really was typed before the last shots
    assert all(value == "" for _, value in seen), seen


@contextmanager
def no_browser(**_):
    yield None


@pytest.mark.parametrize(
    ("password", "url", "failure", "host"),
    [
        ("s3cret", "http://127.0.0.1:8000/", "could not reach 127.0.0.1 with s3cret", "127.0.0.1"),
        # A password that is also part of the host name: the host stays readable, nothing else.
        (
            "demo",
            "https://demo.arcaptcha.co/",
            "could not load https://demo.arcaptcha.co/ for demo",
            "demo.arcaptcha.co",
        ),
    ],
    ids=["ordinary-password", "password-inside-the-host"],
)
def test_an_unexpected_exception_is_reported_without_the_password(
    monkeypatch, password, url, failure, host
):
    def explode(session, challenge):
        raise RuntimeError(failure)

    monkeypatch.setenv("ARCAPTCHA_USERNAME", "someone")
    monkeypatch.setenv("ARCAPTCHA_PASSWORD", password)
    monkeypatch.setattr(core, "chrome", no_browser)  # the failure is injected, so skip Chrome
    monkeypatch.setattr(core, "run_flow", explode)
    result = ArcaptchaBot(BASELINE_SPEC, url=url).run(RecordingContext())

    assert (result.status, result.reason) == (Status.ERROR, "unhandled_exception")
    assert host in result.error  # the host stays readable
    assert "[password]" in result.error
    assert not any(f"{word} {password}" in result.error for word in ("for", "with"))
