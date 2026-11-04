"""The assisted bot: a person (played by a thread) solves the fake page's puzzle."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace

import pytest

from botplatform.bots import BOTS, arcaptcha
from botplatform.bots.arcaptcha import ArcaptchaAssistedBot, ArcaptchaBot, StepTimeouts
from botplatform.bots.selenium_support import chrome
from botplatform.contract import Status
from botplatform.profiles import ALL_SIGNALS
from tests.conftest import FAST, RecordingContext, assert_no_password
from tests.fake_demo.server import CHALLENGE_ID, Reply, create_reply

SECOND_ID = "999999999999999999999999999999"
ACCEPTED = Reply(json={"status": "OK", "accepted": True})
REJECTED = Reply(json={"status": "OK", "accepted": False})
# Short waits keep the suite quick. The settle time is longer than a rejected answer's new puzzle.
ASSISTED = replace(FAST, person_wait=15, answer_settle=1.0)


class Person:
    """Clicks the fake page's "solve" button for each new puzzle, like someone using the viewer."""

    def __init__(self, solves: int) -> None:
        self.solves = solves
        self.drivers: list = []
        self.clicked: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._act, daemon=True)

    def _act(self) -> None:
        while not self._stop.is_set() and len(self.clicked) < self.solves:
            time.sleep(0.2)
            try:
                cid = self.drivers[0].execute_script(
                    "const b = document.getElementById('solve'); return b ? b.dataset.cid : null"
                )
                if cid and cid not in self.clicked:
                    self.drivers[0].execute_script("document.getElementById('solve').click()")
                    self.clicked.append(cid)
            except Exception:  # noqa: BLE001 - the page may be loading or Chrome already closed
                pass

    def watch(self, driver) -> None:
        self.drivers.append(driver)
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()


@pytest.fixture
def person(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[int], Person]]:
    people: list[Person] = []
    real_chrome = chrome

    def make(solves: int) -> Person:
        someone = Person(solves)
        people.append(someone)

        @contextmanager
        def watched(**kwargs):
            with real_chrome(**kwargs) as driver:
                someone.watch(driver)
                yield driver

        monkeypatch.setattr(arcaptcha, "chrome", watched)
        return someone

    yield make
    for someone in people:
        someone.stop()


@pytest.fixture
def assisted(fake, credentials):
    def run(timeouts: StepTimeouts = ASSISTED, bot=ArcaptchaAssistedBot):
        ctx = RecordingContext()
        result = bot(url=fake.url, timeouts=timeouts).run(ctx)
        assert_no_password(type("O", (), {"result": result, "ctx": ctx})())
        return result, ctx

    return run


def test_a_solved_puzzle_then_a_verified_login_is_human_solved(fake, assisted, person):
    fake.creates = [create_reply("puzzle")]
    someone = person(1)
    result, ctx = assisted()

    assert (result.status, result.reason) == (Status.SUCCESS, "human_solved")
    assert someone.clicked == [CHALLENGE_ID]
    assert ctx.one("waiting_for_person") == {"seconds": 15, "challenge_id": CHALLENGE_ID}
    answer = ctx.one("answer_request")
    assert answer["request"] == {"challenge_id": CHALLENGE_ID, "answer": 42}
    assert answer["response"] == {"status": "OK", "accepted": True}
    assert len(fake.logins) == 1
    assert ctx.one("toast")["kind"] == "success"


def test_a_rejected_answer_brings_a_new_puzzle_and_both_are_recorded(fake, assisted, person):
    fake.creates = [create_reply("puzzle"), create_reply("puzzle", challenge_id=SECOND_ID)]
    fake.answers = [REJECTED, ACCEPTED]
    person(2)
    result, ctx = assisted()

    assert (result.status, result.reason) == (Status.SUCCESS, "human_solved")
    assert ctx.challenge_ids == [CHALLENGE_ID, SECOND_ID]
    answers = ctx.of("answer_request")
    assert [a["request"]["challenge_id"] for a in answers] == [CHALLENGE_ID, SECOND_ID]
    assert [a["response"]["accepted"] for a in answers] == [False, True]
    assert len(ctx.of("create_response")) == 2


def test_nobody_answering_times_out_without_a_login(fake, assisted, person):
    fake.creates = [create_reply("puzzle")]
    started = time.monotonic()
    result, ctx = assisted(replace(ASSISTED, person_wait=2))

    assert (result.status, result.reason) == (Status.TIMEOUT, "human_wait_expired")
    assert time.monotonic() - started >= 2
    assert ctx.one("waiting_for_person")["seconds"] == 2
    assert ctx.of("answer_request") == []
    assert fake.logins == []  # like any step timeout, no login is tried


def test_an_undecodable_answer_is_noted_and_the_run_goes_on(fake, assisted, person):
    fake.creates = [create_reply("puzzle")]
    fake.answers = [Reply(raw=b"\x01\x02\x03")]
    person(1)
    result, ctx = assisted()

    answer = ctx.one("answer_request")
    assert answer["response"] is None
    assert answer["response_note"].startswith("decode failed")
    assert (result.status, result.reason) == (Status.SUCCESS, "human_solved")


def test_a_login_that_fails_after_a_solved_puzzle_is_a_verification_failure(fake, assisted, person):
    fake.creates = [create_reply("puzzle")]
    fake.login = Reply(status=400, json={"msg": "Please solve captcha"})
    person(1)
    result, ctx = assisted()

    assert (result.status, result.reason) == (Status.FAILED, "verification_failed")
    assert len(ctx.of("answer_request")) == 1


@pytest.mark.parametrize(
    ("captcha_type", "reason"),
    [
        ("block", "captcha_blocked"),
        ("question", "challenge_unsolved"),
        ("2fa", "challenge_unsolved"),
    ],
)
def test_other_answers_are_handled_like_the_normal_bot(fake, assisted, captcha_type, reason):
    fake.creates = [create_reply(captcha_type)]
    fake.login = Reply(status=400, json={"msg": "Please solve captcha"})
    result, ctx = assisted()

    assert (result.status, result.reason) == (Status.BLOCKED, reason)
    assert ctx.of("waiting_for_person") == []
    assert len(fake.logins) == 1


def test_an_accepted_checkbox_is_a_plain_success(fake, assisted):
    result, _ = assisted()
    assert (result.status, result.reason) == (Status.SUCCESS, None)


def test_the_normal_bot_does_not_wait_on_a_puzzle(fake, assisted):
    fake.creates = [create_reply("puzzle")]
    fake.login = Reply(status=400, json={"msg": "Please solve captcha"})
    result, ctx = assisted(bot=ArcaptchaBot)

    assert (result.status, result.reason) == (Status.BLOCKED, "challenge_unsolved")
    assert ctx.of("waiting_for_person") == []


def test_the_assisted_bot_is_registered_headful_only_with_the_long_wait():
    assert ArcaptchaAssistedBot in BOTS
    assert ArcaptchaAssistedBot.id == "arcaptcha-assisted"
    assert ArcaptchaAssistedBot.modes == ["headful"]
    assert ArcaptchaAssistedBot.profile is ALL_SIGNALS
    timeouts = ArcaptchaAssistedBot().timeouts
    assert (timeouts.person_wait, timeouts.answer_settle) == (130, 3)
    assert "person" in ArcaptchaAssistedBot.description
