"""Browser profiles: named sets of Chrome settings, so each can be measured as its own bot.

To add a profile, add one entry to `PROFILES`. `BASELINE` is what the bot did before profiles
existed, and must stay free of extras so old and new runs remain comparable.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    args: tuple[str, ...] = ()  # extra Chrome command line arguments
    excluded_switches: tuple[str, ...] = ()  # Chrome switches Selenium adds that we drop
    # JS run through CDP before any page script, on every new document.
    init_script: str | None = None

    def settings(self) -> dict[str, object]:
        """The profile as plain data, for the run's record."""
        return {
            "name": self.name,
            "description": self.description,
            "args": list(self.args),
            "excluded_switches": list(self.excluded_switches),
            "init_script": self.init_script,
        }


def bot_id(profile_name: str) -> str:
    """The id of the registered bot that runs `profile_name`. The baseline keeps the plain id."""
    return "arcaptcha" if profile_name == "baseline" else f"arcaptcha-{profile_name}"


BASELINE = Profile("baseline", "Plain Chrome for Testing driven by Selenium, no changes.")

STEALTH_FLAGS = Profile(
    "stealth-flags",
    "Hides the automation flags: AutomationControlled blink feature off, enable-automation dropped.",
    args=("--disable-blink-features=AutomationControlled",),
    excluded_switches=("enable-automation",),
)

# chromedriver adds `cdc_adoQpoasnfa76pfcZLmcfl_*` properties to `window` before page scripts run,
# and the site's WindowCDC check lists them. They are plain, configurable properties, so deleting
# them from a script that runs first is enough (measured, see DECISIONS.md Bonus (b)).
NO_CDC = Profile(
    "no-cdc",
    "Deletes chromedriver's cdc_ properties from the page before its scripts run, because the "
    "site's WindowCDC check lists them and the first audit found them in every run.",
    init_script="for (const name of Object.getOwnPropertyNames(window)) {"
    " if (/^\\$?cdc_/.test(name)) delete window[name]; }",
)

# Headful Chrome in the worker's Xvfb has no GPU, and without this flag it gives the page no WebGL
# context at all. With it, it uses the same SwiftShader software renderer that headless Chrome
# already uses. Smallest working set of the flags tried, see DECISIONS.md Bonus (b).
WEBGL_FIX = Profile(
    "webgl-fix",
    "Lets headful Chrome use the SwiftShader software renderer, so the page gets a WebGL context "
    "with a vendor and renderer. The first audit found none in headful runs. No effect on headless.",
    args=("--enable-unsafe-swiftshader",),
)

# Built from the single-factor profiles, so the three stay in sync.
ALL_SIGNALS = Profile(
    "all-signals",
    "Combines stealth-flags, no-cdc and webgl-fix, because in the first live batch each of them "
    "was blocked while fixing only its own signal. Tests whether the site needs all of them fixed.",
    args=STEALTH_FLAGS.args + WEBGL_FIX.args,
    excluded_switches=STEALTH_FLAGS.excluded_switches,
    init_script=NO_CDC.init_script,
)

# The user agent headful Chrome sends in the worker. It must follow the Chrome version pinned in
# the Dockerfile (CHROME_VERSION): Chrome reports only the major version, then `.0.0.0`.
HEADFUL_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/156.0.0.0 Safari/537.36"
)

# On top of all-signals, makes headless Chrome look like the headful one in the worker: the user
# agent without `Headless` (this also fixes `navigator.appVersion`) and a 1280x800 screen and
# window. `--window-size` alone left the screen at 800x600; `--screen-info` fixes that.
ALL_SIGNALS_HEADLESS = Profile(
    "all-signals-headless",
    "Everything in all-signals, plus the user agent and a 1280x800 screen and window that headful "
    "Chrome has, because live headless runs were blocked while headful ones got a puzzle and "
    "headless still sent HeadlessChrome and an 800x600 screen. Meant for headless runs only.",
    args=(
        *ALL_SIGNALS.args,
        f"--user-agent={HEADFUL_USER_AGENT}",
        "--window-size=1280,800",
        "--screen-info={1280x800}",
    ),
    excluded_switches=ALL_SIGNALS.excluded_switches,
    init_script=ALL_SIGNALS.init_script,
)

PROFILES: dict[str, Profile] = {
    p.name: p
    for p in (BASELINE, STEALTH_FLAGS, NO_CDC, WEBGL_FIX, ALL_SIGNALS, ALL_SIGNALS_HEADLESS)
}
