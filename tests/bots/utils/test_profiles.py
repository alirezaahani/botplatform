"""Browser profiles: what each one changes in what the page can see. Real Chrome, a local page.

These measure Chrome, not our configuration: a profile counts only if the page sees the change.
"""

from botplatform.bots.utils import page_scripts
from botplatform.bots.utils.browser import chrome
from botplatform.bots.utils.profiles import (
    BASELINE,
    HEADFUL_USER_AGENT,
    PROFILES,
    STEALTH_FLAGS,
    Profile,
)

VIEW_JS = """return {
  ua: navigator.userAgent, app_version: navigator.appVersion,
  brands: navigator.userAgentData ? navigator.userAgentData.brands.map(b => b.brand) : null,
  screen: [screen.width, screen.height], inner: [innerWidth, innerHeight],
  outer: [outerWidth, outerHeight]
}"""
CDC_JS = "return Object.getOwnPropertyNames(window).filter(n => /cdc_/.test(n)).length"


def page_signals(profile: Profile, local_page, headless: bool = True) -> dict:
    with chrome(headless=headless, profile=profile) as driver:
        driver.get(local_page.url)
        return driver.execute_async_script(page_scripts.BROWSER_SIGNALS_JS)


def page_view(profile: Profile, local_page, headless: bool) -> dict:
    with chrome(headless=headless, profile=profile) as driver:
        driver.get(local_page.url)
        return driver.execute_script(VIEW_JS)


def cdc_names(signals: dict) -> list[str]:
    return [name for name in signals["automation_properties"] if "cdc_" in name]


# -- How a profile reaches Chrome ---------------------------------------------------------------


def test_the_init_script_runs_before_the_page_scripts(local_page):
    profile = Profile("t", "t", init_script="window.__early = 42")
    with chrome(headless=True, profile=profile) as driver:
        driver.get(local_page.url)
        assert driver.execute_script("return window.__early") == 42


def test_extra_arguments_reach_chrome(local_page):
    profile = Profile("t", "t", args=("--user-agent=ProbeAgent/1",))
    with chrome(headless=True, profile=profile) as driver:
        driver.get(local_page.url)
        assert driver.execute_script("return navigator.userAgent") == "ProbeAgent/1"


# -- What the page can see ----------------------------------------------------------------------


def test_stealth_flags_hide_navigator_webdriver_and_baseline_does_not(local_page):
    assert page_signals(BASELINE, local_page)["webdriver"] is True
    assert page_signals(STEALTH_FLAGS, local_page)["webdriver"] is False


def test_no_cdc_removes_what_baseline_shows_and_keeps_it_removed(local_page):
    assert cdc_names(page_signals(BASELINE, local_page)), "the baseline should show cdc_ properties"

    with chrome(headless=True, profile=PROFILES["no-cdc"]) as driver:
        driver.get(local_page.url)
        assert driver.execute_script(CDC_JS) == 0
        driver.get("data:text/html,<p>other page</p>")
        assert driver.execute_script(CDC_JS) == 0
        driver.execute_script("location.reload()")
        assert driver.execute_script(CDC_JS) == 0


def test_the_webgl_fix_gives_headful_chrome_a_webgl_context_and_keeps_its_window(
    local_page, display
):
    before = page_signals(BASELINE, local_page, headless=False)["webgl"]
    after = page_signals(PROFILES["webgl-fix"], local_page, headless=False)

    assert before is None or not before["vendor"]  # the problem the first audit found
    assert after["webgl"]["vendor"] and after["webgl"]["renderer"]
    assert after["screen"]["width"] == 1280
    assert after["window"]["outer_width"] >= 1270


def test_the_webgl_fix_leaves_headless_chrome_as_it_was(local_page):
    before = page_signals(BASELINE, local_page)["webgl"]
    after = page_signals(PROFILES["webgl-fix"], local_page)["webgl"]

    assert before == after
    assert after["renderer"]


def test_all_signals_combines_every_single_factor_profile():
    combined = PROFILES["all-signals"]
    for name in ("stealth-flags", "no-cdc", "webgl-fix"):
        single = PROFILES[name]
        assert set(single.args) <= set(combined.args)
        assert set(single.excluded_switches) <= set(combined.excluded_switches)
        assert single.init_script is None or single.init_script == combined.init_script


def test_all_signals_headful_shows_none_of_the_automation_signals(local_page, display):
    signals = page_signals(PROFILES["all-signals"], local_page, headless=False)

    assert signals["webdriver"] is False
    assert not cdc_names(signals)
    assert signals["webgl"]["vendor"] and signals["webgl"]["renderer"]


def test_all_signals_headless_looks_like_headful_chrome(local_page):
    base = page_view(BASELINE, local_page, headless=True)
    assert "HeadlessChrome" in base["ua"] and base["screen"] == [800, 600]  # the problem

    profile = PROFILES["all-signals-headless"]
    view = page_view(profile, local_page, headless=True)
    assert view["ua"] == HEADFUL_USER_AGENT
    assert "Headless" not in view["app_version"]
    assert view["screen"] == view["outer"] == [1280, 800]
    assert view["inner"][0] == 1280
    assert not view["brands"] or all("Headless" not in b for b in view["brands"])

    signals = page_signals(profile, local_page)
    assert signals["webdriver"] is False
    assert signals["webgl"]["renderer"]
    assert not cdc_names(signals)


def test_the_headless_profile_changes_nothing_in_headful_chrome(local_page, display):
    plain = page_view(PROFILES["all-signals"], local_page, headless=False)
    headless_profile = page_view(PROFILES["all-signals-headless"], local_page, headless=False)

    assert headless_profile == plain
    assert plain["ua"] == HEADFUL_USER_AGENT  # the constant matches what headful really sends
