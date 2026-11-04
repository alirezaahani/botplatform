"""Browser profiles, the bot per profile, and the evidence events. Real Chrome, fake demo."""

import pytest

from botplatform.bots import BOTS, arcaptcha
from botplatform.bots.arcaptcha import ArcaptchaBot, StepTimeouts
from botplatform.bots.selenium_support import CapturedResponse, chrome
from botplatform.contract import Status
from botplatform.profiles import BASELINE, HEADFUL_USER_AGENT, PROFILES, STEALTH_FLAGS, Profile
from botplatform.worker.registry import validate
from tests.conftest import RecordingContext

SIGNAL_KEYS = {
    "webdriver", "user_agent", "platform", "languages", "plugins", "mime_types",
    "hardware_concurrency", "device_memory", "chrome", "window", "screen",
    "notification_permission", "permissions_notifications", "webgl", "automation_properties",
}  # fmt: skip


def test_baseline_adds_nothing():
    assert (BASELINE.args, BASELINE.excluded_switches, BASELINE.init_script) == ((), (), None)


def test_stealth_flags_profile_contents():
    assert STEALTH_FLAGS.args == ("--disable-blink-features=AutomationControlled",)
    assert STEALTH_FLAGS.excluded_switches == ("enable-automation",)
    assert STEALTH_FLAGS.init_script is None
    assert set(PROFILES) >= {"baseline", "stealth-flags"}


def test_init_script_runs_before_page_scripts(fake):
    profile = Profile("t", "t", init_script="window.__early = 42")
    with chrome(headless=True, profile=profile) as driver:
        driver.get(fake.url)
        assert driver.execute_script("return window.__early") == 42


def test_extra_args_apply(fake):
    profile = Profile("t", "t", args=("--user-agent=ProbeAgent/1",))
    with chrome(headless=True, profile=profile) as driver:
        driver.get(fake.url)
        assert driver.execute_script("return navigator.userAgent") == "ProbeAgent/1"


def test_stealth_flags_hide_navigator_webdriver_and_baseline_does_not(fake):
    seen = {}
    for profile in (BASELINE, STEALTH_FLAGS):
        with chrome(headless=True, profile=profile) as driver:
            driver.get(fake.url)
            seen[profile.name] = driver.execute_script("return navigator.webdriver")
    assert seen == {"baseline": True, "stealth-flags": False}


# -- Registration -------------------------------------------------------------------------------


def test_every_profile_has_a_registered_bot_with_a_unique_id():
    validate(BOTS)  # raises on a duplicate id or a missing attribute
    ids = [bot.id for bot in BOTS]
    assert len(ids) == len(set(ids))
    assert "arcaptcha" in ids
    for name in PROFILES:
        if name != "baseline":
            assert f"arcaptcha-{name}" in ids


def test_baseline_bot_keeps_its_identity_and_profile_bots_describe_theirs():
    assert (ArcaptchaBot.id, ArcaptchaBot.name) == ("arcaptcha", "ARCaptcha demo (Selenium)")
    assert ArcaptchaBot.profile is BASELINE
    bot = next(b for b in BOTS if b.id == "arcaptcha-stealth-flags")
    assert "stealth-flags" in bot.name
    assert STEALTH_FLAGS.description in bot.description
    assert bot.modes == ArcaptchaBot.modes
    assert bot().profile is STEALTH_FLAGS  # the worker builds bots with no arguments


# -- Evidence events ----------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES.values(), ids=PROFILES.keys())
def test_run_records_profile_signals_and_create_request(fake, credentials, profile):
    fast = StepTimeouts(3, 2, 3, 1, 3, 1.5)
    ctx = RecordingContext()
    result = ArcaptchaBot(url=fake.url, timeouts=fast, profile=profile).run(ctx)

    assert result.status == Status.SUCCESS
    assert ctx.one("browser_profile") == profile.settings()
    signals = ctx.one("browser_signals")
    assert SIGNAL_KEYS <= signals.keys()
    hides_webdriver = "--disable-blink-features=AutomationControlled" in profile.args
    assert signals["webdriver"] is (not hides_webdriver)
    assert signals["window"]["inner_width"] > 0
    request = ctx.one("create_request")
    assert request["request"] == {"site_key": "fake"}  # what the page sent
    assert request["response"]["captcha_type"] == "accept"
    # Login holds the password, so its request body is never captured.
    assert "tester@example.com" not in repr(ctx.events)


def test_undecodable_request_body_is_noted_not_fatal():
    garbage = CapturedResponse("create", "u", 201, b'{"captcha_type":"accept"}', None, b"\x01\x02")
    record = arcaptcha.Scenario._create_request_record(garbage)
    assert record["request"] is None
    assert record["request_note"].startswith("decode failed")
    assert record["request_raw_length"] == 2
    assert record["response"] == {"captcha_type": "accept"}


def test_missing_request_body_is_noted():
    record = arcaptcha.Scenario._create_request_record(
        CapturedResponse("create", "u", 201, b"{}", None, None, "WebDriverException: gone")
    )
    assert record["request"] is None
    assert "gone" in record["request_note"]


def test_run_survives_a_failed_request_decode(fake, credentials, monkeypatch):
    real = arcaptcha.decode_body

    def decode(data: bytes):
        if b"site_key" in data and b"challenge_id" not in data:
            raise ValueError("cannot decode the request")
        return real(data)

    monkeypatch.setattr(arcaptcha, "decode_body", decode)
    ctx = RecordingContext()
    result = ArcaptchaBot(url=fake.url, timeouts=StepTimeouts(3, 2, 3, 1, 3, 1.5)).run(ctx)

    assert result.status == Status.SUCCESS
    request = ctx.one("create_request")
    assert request["request"] is None
    assert request["request_raw_length"] > 0


# -- Profiles that change what the page sees (measured, not assumed) ---------------------------

SIGNALS_JS = arcaptcha.BROWSER_SIGNALS_JS


def page_signals(profile: Profile, fake, headless: bool = True) -> dict:
    with chrome(headless=headless, profile=profile) as driver:
        driver.get(fake.url)
        return driver.execute_async_script(SIGNALS_JS)


def test_no_cdc_removes_the_properties_that_baseline_shows(fake):
    before = page_signals(BASELINE, fake)["automation_properties"]
    after = page_signals(PROFILES["no-cdc"], fake)["automation_properties"]
    assert [name for name in before if name.startswith("cdc_")], "baseline should show cdc_"
    assert not [name for name in after if "cdc_" in name]


def test_no_cdc_is_gone_before_page_scripts_and_after_navigation(fake):
    script = "return Object.getOwnPropertyNames(window).filter(n => /cdc_/.test(n)).length"
    with chrome(headless=True, profile=PROFILES["no-cdc"]) as driver:
        driver.get(fake.url)
        assert driver.execute_script(script) == 0
        driver.get("data:text/html,<p>other page</p>")
        assert driver.execute_script(script) == 0
        driver.execute_script("location.reload()")
        assert driver.execute_script(script) == 0


@pytest.fixture
def display(monkeypatch):
    """A virtual display for headful Chrome, like the worker's, on its own number."""
    import subprocess
    import time
    from pathlib import Path

    xvfb = subprocess.Popen(["Xvfb", ":98", "-screen", "0", "1280x800x24", "-nolisten", "tcp"])
    for _ in range(50):
        if Path("/tmp/.X11-unix/X98").exists():
            break
        time.sleep(0.1)
    monkeypatch.setenv("DISPLAY", ":98")
    yield
    xvfb.terminate()
    xvfb.wait()


def test_webgl_fix_gives_headful_chrome_a_webgl_context(fake, display):
    before = page_signals(BASELINE, fake, headless=False)["webgl"]
    after = page_signals(PROFILES["webgl-fix"], fake, headless=False)["webgl"]
    assert before is None or not before["vendor"]  # the problem the first audit found
    assert after["vendor"] and after["renderer"]


def test_webgl_fix_leaves_headless_as_it_was(fake):
    before = page_signals(BASELINE, fake)["webgl"]
    after = page_signals(PROFILES["webgl-fix"], fake)["webgl"]
    assert before == after
    assert after["renderer"]


def test_webgl_fix_keeps_the_window_size_settings(fake, display):
    with chrome(headless=False, profile=PROFILES["webgl-fix"]) as driver:
        driver.get(fake.url)
        assert driver.execute_script("return screen.width") == 1280
        assert driver.execute_script("return window.outerWidth") >= 1270


def test_all_signals_is_the_union_of_the_single_factor_profiles():
    combined = PROFILES["all-signals"]
    for name in ("stealth-flags", "no-cdc", "webgl-fix"):
        single = PROFILES[name]
        assert set(single.args) <= set(combined.args)
        assert set(single.excluded_switches) <= set(combined.excluded_switches)
        assert single.init_script is None or single.init_script == combined.init_script


def test_all_signals_headless_hides_webdriver_and_cdc(fake):
    signals = page_signals(PROFILES["all-signals"], fake)
    assert signals["webdriver"] is False
    assert not [name for name in signals["automation_properties"] if "cdc_" in name]


def test_all_signals_headful_also_has_webgl(fake, display):
    signals = page_signals(PROFILES["all-signals"], fake, headless=False)
    assert signals["webdriver"] is False
    assert not [name for name in signals["automation_properties"] if "cdc_" in name]
    assert signals["webgl"]["vendor"] and signals["webgl"]["renderer"]


HUMAN_JS = """return {
  ua: navigator.userAgent, app_version: navigator.appVersion,
  brands: navigator.userAgentData ? navigator.userAgentData.brands.map(b => b.brand) : null,
  screen: [screen.width, screen.height], inner: [innerWidth, innerHeight],
  outer: [outerWidth, outerHeight]
}"""


def page_view(profile: Profile, fake, headless: bool) -> dict:
    with chrome(headless=headless, profile=profile) as driver:
        driver.get(fake.url)
        return driver.execute_script(HUMAN_JS)


def test_all_signals_headless_looks_like_headful_chrome_in_headless(fake):
    base = page_view(BASELINE, fake, headless=True)
    assert "HeadlessChrome" in base["ua"] and base["screen"] == [800, 600]  # the problem
    view = page_view(PROFILES["all-signals-headless"], fake, headless=True)
    assert view["ua"] == HEADFUL_USER_AGENT
    assert "Headless" not in view["app_version"]
    assert view["screen"] == [1280, 800]
    assert view["outer"] == [1280, 800]
    assert view["inner"][0] == 1280
    assert not view["brands"] or all("Headless" not in b for b in view["brands"])
    signals = page_signals(PROFILES["all-signals-headless"], fake)
    assert signals["webdriver"] is False
    assert signals["webgl"]["renderer"]
    assert not [name for name in signals["automation_properties"] if "cdc_" in name]


def test_all_signals_headless_does_not_change_headful(fake, display):
    plain = page_view(PROFILES["all-signals"], fake, headless=False)
    headless_view = page_view(PROFILES["all-signals-headless"], fake, headless=False)
    assert headless_view == plain
    assert headless_view["ua"] == HEADFUL_USER_AGENT  # the constant matches what headful really sends
