"""What differs between the ARCaptcha bots: identity, modes, browser profiles and the solver."""

from dataclasses import dataclass, field

from botplatform.bots.arcaptcha.challenge import Challenge, GiveUp
from botplatform.bots.arcaptcha.solver import SliderSolver
from botplatform.bots.utils.profiles import ALL_SIGNALS, ALL_SIGNALS_HEADLESS, BASELINE, Profile


def bot_id(profile_name: str) -> str:
    """The id of the registered bot that runs `profile_name`. The baseline keeps the plain id."""
    return "arcaptcha" if profile_name == "baseline" else f"arcaptcha-{profile_name}"


@dataclass(frozen=True)
class BotSpec:
    id: str
    name: str
    description: str
    modes: tuple[str, ...]
    profile: Profile = BASELINE
    # A profile for a mode, where `profile` is not right for every mode. Not listed: `profile`.
    profile_by_mode: dict[str, Profile] = field(default_factory=dict)
    # What the bot does when the widget shows a puzzle. Give up unless the spec says otherwise.
    challenge: Challenge = field(default_factory=GiveUp)


BASELINE_SPEC = BotSpec(
    id="arcaptcha",
    name="ARCaptcha demo (Selenium)",
    description=(
        "Ticks the checkbox on demo.arcaptcha.co, records challenge_id, logs in and checks that "
        "the login really succeeded."
    ),
    modes=("headless", "headful"),
)


def solver_spec(finder: str, mover: str) -> BotSpec:
    """An automatic solver bot, `arcaptcha-solver-<finder>-<mover>`.

    The finder and mover names are keys of `gap_finders.FINDERS` and `drag.MOVERS`.
    """
    return BotSpec(
        id=f"arcaptcha-solver-{finder}-{mover}",
        name=f"ARCaptcha demo (automatic solver: {finder} finder, {mover} movement)",
        description=(
            "An automatic solver. Ticks the checkbox and, when a puzzle appears, finds the gap "
            f"with the '{finder}' finder and drags the handle there with '{mover}' movement "
            "(Selenium ActionChains), up to 3 answers per run, then logs in. A verified login "
            "ends as success with the reason solved. If no gap is found the run ends as "
            "blocked / gap_not_found, and after 3 rejected answers as blocked / solve_failed. "
            "Headful uses the all-signals profile and headless the all-signals-headless one."
        ),
        modes=("headless", "headful"),
        profile=ALL_SIGNALS,
        profile_by_mode={"headful": ALL_SIGNALS, "headless": ALL_SIGNALS_HEADLESS},
        challenge=SliderSolver(finder, mover),
    )


def profile_spec(profile: Profile) -> BotSpec:
    """The baseline scenario with `profile`, as bot `arcaptcha-<name>`.

    One bot per profile makes the run history the evidence: a bot's runs are one profile's runs.
    """
    return BotSpec(
        id=bot_id(profile.name),
        name=f"ARCaptcha demo (Selenium, {profile.name})",
        description=f"{BASELINE_SPEC.description} Browser profile: {profile.description}",
        modes=BASELINE_SPEC.modes,
        profile=profile,
    )
