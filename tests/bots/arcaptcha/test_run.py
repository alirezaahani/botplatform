"""The ARCaptcha bot's run: real Selenium and Chrome against the local fake demo site.

Only what needs a real browser is tested here. The decisions made from what the browser saw
(which `create` types block, which login responses are confirmed) are tested without Chrome in
`test_checkbox.py` and `test_login.py`.
"""

import socket
from dataclasses import replace

import pytest
from selenium.common.exceptions import WebDriverException

from botplatform.bots.arcaptcha import BASELINE_BOT
from botplatform.bots.utils.browser import BrowserMode
from botplatform.bots.utils.profiles import BASELINE, STEALTH_FLAGS
from botplatform.contract import Status
from tests.bots.arcaptcha.conftest import FAST, PASSWORD, USERNAME
from tests.bots.arcaptcha.fake_demo.server import CHALLENGE_ID, Reply, Toast, create_reply
from tests.bots.utils.test_page_scripts import SIGNAL_KEYS
from tests.conftest import RecordingContext

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
    # The recorded login holds the decoded request, password included, and the response.
    login = outcome.ctx.one("login_request")
    assert login["request"] == fake.logins[0]
    assert (login["http_status"], login["response"]) == (200, LOGIN_OK.json)


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
    assert outcome.ctx.one("create_response")["decode_error"].startswith(
        "decode failed: ValueError"
    )


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
    assert "login_response" in outcome.ctx.one("login_failed")["error"]


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


def test_a_site_that_is_down_raises_with_the_reason(run_bot):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port_url = f"http://127.0.0.1:{sock.getsockname()[1]}/"
    with pytest.raises(WebDriverException, match="ERR_CONNECTION_REFUSED"):
        run_bot(url=closed_port_url)


def test_without_credentials_the_run_is_an_error_before_any_browser_starts(monkeypatch):
    monkeypatch.delenv("ARCAPTCHA_USERNAME", raising=False)
    monkeypatch.delenv("ARCAPTCHA_PASSWORD", raising=False)
    result = BASELINE_BOT.run(RecordingContext(), BrowserMode.HEADLESS)

    assert (result.status, result.reason) == (Status.ERROR, "missing_credentials")


# -- The evidence a run records ------------------------------------------------------------------


@pytest.mark.parametrize("profile", [BASELINE, STEALTH_FLAGS], ids=lambda p: p.name)
def test_a_run_records_the_profile_the_signals_and_the_create_request(run_bot, fake, profile):
    outcome = run_bot(profile=profile)

    assert outcome.result.status == Status.SUCCESS
    assert outcome.ctx.one("browser_profile") == profile.settings()
    signals = outcome.ctx.one("browser_signals")
    assert SIGNAL_KEYS <= signals.keys()
    assert signals["webdriver"] is (profile is BASELINE)
    request = outcome.ctx.one("create_request")
    assert request["request"] == {"site_key": "fake"}  # what the page sent
    assert request["response"]["captcha_type"] == "accept"
