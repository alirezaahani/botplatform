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


BASELINE = Profile("baseline", "Plain Chrome for Testing driven by Selenium, no changes.")

STEALTH_FLAGS = Profile(
    "stealth-flags",
    "Hides the automation flags: AutomationControlled blink feature off, enable-automation dropped.",
    args=("--disable-blink-features=AutomationControlled",),
    excluded_switches=("enable-automation",),
)

PROFILES: dict[str, Profile] = {p.name: p for p in (BASELINE, STEALTH_FLAGS)}
