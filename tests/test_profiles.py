"""Browser profiles: what each one changes in what the page can see. Real Chrome, fake demo.

These measure Chrome, not our configuration: a profile counts only if the page sees the change.
"""

import pytest

from botplatform.bots.utils import page_scripts
from botplatform.bots.utils.browser import chrome
from botplatform.bots.utils.profiles import (
    BASELINE,
    HEADFUL_USER_AGENT,
    PROFILES,
    STEALTH_FLAGS,
    Profile,
)
from botplatform.contract import Status

SIGNAL_KEYS = {
    "webdriver", "user_agent", "platform", "languages", "plugins", "mime_types",
    "hardware_concurrency", "device_memory", "chrome", "window", "screen",
    "notification_permission", "permissions_notifications", "webgl", "automation_properties",
}  # fmt: skip

VIEW_JS = """return {
  ua: navigator.userAgent, app_version: navigator.appVersion,
  brands: navigator.userAgentData ? navigator.userAgentData.brands.map(b => b.brand) : null,
  screen: [screen.width, screen.height], inner: [innerWidth, innerHeight],
  outer: [outerWidth, outerHeight]
}"""
CDC_JS = "return Object.getOwnPropertyNames(window).filter(n => /cdc_/.test(n)).length"


def page_signals(profile: Profile, fake, headless: bool = True) -> dict:
    with chrome(headless=headless, profile=profile) as driver:
        driver.get(fake.url)
        return driver.execute_async_script(page_scripts.BROWSER_SIGNALS_JS)


def page_view(profile: Profile, fake, headless: bool) -> dict:
    with chrome(headless=headless, profile=profile) as driver:
        driver.get(fake.url)
        return driver.execute_script(VIEW_JS)


def cdc_names(signals: dict) -> list[str]:
    return [name for name in signals["automation_properties"] if "cdc_" in name]


# -- How a profile reaches Chrome ---------------------------------------------------------------


def test_the_init_script_runs_before_the_page_scripts(fake):
    profile = Profile("t", "t", init_script="window.__early = 42")
    with chrome(headless=True, profile=profile) as driver:
        driver.get(fake.url)
        assert driver.execute_script("return window.__early") == 42


def test_extra_arguments_reach_chrome(fake):
    profile = Profile("t", "t", args=("--user-agent=ProbeAgent/1",))
    with chrome(headless=True, profile=profile) as driver:
        driver.get(fake.url)
        assert driver.execute_script("return navigator.userAgent") == "ProbeAgent/1"


# -- What the page can see ----------------------------------------------------------------------


def test_stealth_flags_hide_navigator_webdriver_and_baseline_does_not(fake):
    assert page_signals(BASELINE, fake)["webdriver"] is True
    assert page_signals(STEALTH_FLAGS, fake)["webdriver"] is False


def test_no_cdc_removes_what_baseline_shows_and_keeps_it_removed(fake):
    assert cdc_names(page_signals(BASELINE, fake)), "the baseline should show cdc_ properties"

    with chrome(headless=True, profile=PROFILES["no-cdc"]) as driver:
        driver.get(fake.url)
        assert driver.execute_script(CDC_JS) == 0
        driver.get("data:text/html,<p>other page</p>")
        assert driver.execute_script(CDC_JS) == 0
        driver.execute_script("location.reload()")
        assert driver.execute_script(CDC_JS) == 0


def test_the_webgl_fix_gives_headful_chrome_a_webgl_context_and_keeps_its_window(fake, display):
    before = page_signals(BASELINE, fake, headless=False)["webgl"]
    after = page_signals(PROFILES["webgl-fix"], fake, headless=False)

    assert before is None or not before["vendor"]  # the problem the first audit found
    assert after["webgl"]["vendor"] and after["webgl"]["renderer"]
    assert after["screen"]["width"] == 1280
    assert after["window"]["outer_width"] >= 1270


def test_the_webgl_fix_leaves_headless_chrome_as_it_was(fake):
    before = page_signals(BASELINE, fake)["webgl"]
    after = page_signals(PROFILES["webgl-fix"], fake)["webgl"]

    assert before == after
    assert after["renderer"]


def test_all_signals_combines_every_single_factor_profile():
    combined = PROFILES["all-signals"]
    for name in ("stealth-flags", "no-cdc", "webgl-fix"):
        single = PROFILES[name]
        assert set(single.args) <= set(combined.args)
        assert set(single.excluded_switches) <= set(combined.excluded_switches)
        assert single.init_script is None or single.init_script == combined.init_script


def test_all_signals_headful_shows_none_of_the_automation_signals(fake, display):
    signals = page_signals(PROFILES["all-signals"], fake, headless=False)

    assert signals["webdriver"] is False
    assert not cdc_names(signals)
    assert signals["webgl"]["vendor"] and signals["webgl"]["renderer"]


def test_all_signals_headless_looks_like_headful_chrome(fake):
    base = page_view(BASELINE, fake, headless=True)
    assert "HeadlessChrome" in base["ua"] and base["screen"] == [800, 600]  # the problem

    profile = PROFILES["all-signals-headless"]
    view = page_view(profile, fake, headless=True)
    assert view["ua"] == HEADFUL_USER_AGENT
    assert "Headless" not in view["app_version"]
    assert view["screen"] == view["outer"] == [1280, 800]
    assert view["inner"][0] == 1280
    assert not view["brands"] or all("Headless" not in b for b in view["brands"])

    signals = page_signals(profile, fake)
    assert signals["webdriver"] is False
    assert signals["webgl"]["renderer"]
    assert not cdc_names(signals)


def test_the_headless_profile_changes_nothing_in_headful_chrome(fake, display):
    plain = page_view(PROFILES["all-signals"], fake, headless=False)
    headless_profile = page_view(PROFILES["all-signals-headless"], fake, headless=False)

    assert headless_profile == plain
    assert plain["ua"] == HEADFUL_USER_AGENT  # the constant matches what headful really sends


# -- The evidence a run records -----------------------------------------------------------------


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
