"""The drag probe bot against the fake demo, whose handle drags the piece at a set ratio."""

from dataclasses import replace

import pytest

from botplatform.bots import BOTS
from botplatform.bots.arcaptcha import ArcaptchaBot, ArcaptchaDragProbeBot, Scenario
from botplatform.contract import Status
from botplatform.profiles import ALL_SIGNALS
from tests.conftest import FAST, RecordingContext, assert_no_password
from tests.fake_demo.server import Reply, create_reply

RATIO = 0.5
WRONG = Reply(json={"status": "OK", "success": False})
RIGHT = Reply(json={"status": "OK", "success": True})
IDS = [f"{i:030d}" for i in range(1, 7)]
PROBE = replace(FAST, drag_probe=60, drag_attempts=4, answer_settle=2, puzzle_images=3)


@pytest.fixture
def probe(fake, credentials):
    fake.slider = RATIO
    fake.creates = [create_reply("puzzle", challenge_id=cid) for cid in IDS]
    fake.answers = [WRONG]

    def run(timeouts=PROBE, bot=ArcaptchaDragProbeBot):
        ctx = RecordingContext()
        result = bot(url=fake.url, timeouts=timeouts).run(ctx)
        assert_no_password(type("O", (), {"result": result, "ctx": ctx})())
        return result, ctx

    return run


def test_each_puzzle_gets_one_planned_drag_and_the_methods_alternate(probe):
    result, ctx = probe()

    assert (result.status, result.reason) == (Status.BLOCKED, "drag_probe_done")
    attempts = ctx.of("drag_probe_attempt")
    assert [a["method"] for a in attempts] == ["selenium", "cdp", "selenium", "cdp"]
    assert [a["dx"] for a in attempts] == [40, 80, 120, 150]
    assert [a["n"] for a in attempts] == [1, 2, 3, 4]
    assert [a["challenge_id"] for a in attempts] == IDS[:4]
    assert all(a["error"] is None for a in attempts)
    # A wrong answer brings the next puzzle, which is captured too.
    assert [a["outcome"] for a in attempts] == ["next_puzzle"] * 4
    assert [e["n"] for e in ctx.of("puzzle_captured")] == [1, 2, 3, 4, 5]
    assert ctx.one("drag_probe_finished")["reason"] == "plan_finished"
    assert ctx.of("drag_probe_failed") == []


def test_puzzle_n_is_captured_before_the_drag_of_attempt_n(probe):
    _, ctx = probe()
    kinds = [(kind, data.get("n")) for kind, data in ctx.events]
    for n in (1, 2, 3, 4):
        assert kinds.index(("puzzle_captured", n)) < kinds.index(("drag_probe_attempt", n))
    names = [name for name, _, _ in ctx.artifacts]
    assert "drag-probe-before.png" in names
    assert "drag-probe-after.png" in names


def test_samples_follow_the_handle_and_the_piece_at_the_ratio(probe):
    _, ctx = probe()
    for attempt in ctx.of("drag_probe_attempt"):
        samples = attempt["samples"]
        labels = [s["label"] for s in samples]
        assert labels[0] == "before" and labels[1] == "pressed" and labels[-1] == "released"
        assert labels.count("step") == 8
        assert samples[0]["handle"]["style_left"] == "0px"
        assert samples[0]["piece"]["style_left"] == "0px"
        # Moves are monotonic and end at dx (below the clamp).
        moved = [float(s["handle"]["style_left"].removesuffix("px")) for s in samples]
        assert moved == sorted(moved)
        last = samples[-1]
        assert last["moved"] == attempt["dx"]
        assert last["handle"]["style_left"] == f"{attempt['dx']:g}px"
        assert last["piece"]["style_left"] == f"{attempt['dx'] * RATIO:g}px"
        assert last["handle"]["rect"]["width"] == 64
        assert last["piece"]["rect"] is not None and "computed_transform" in last["piece"]
        assert attempt["after_outcome"]["handle"] is not None


def test_the_answer_equals_the_piece_left_and_pairs_by_challenge_id(probe):
    _, ctx = probe()
    answers = {a["request"]["challenge_id"]: a["request"]["answer"] for a in ctx.of("answer_request")}
    for attempt in ctx.of("drag_probe_attempt"):
        assert answers[attempt["challenge_id"]] == attempt["dx"] * RATIO


def test_the_listener_summary_counts_mouse_events_and_their_trust(probe):
    _, ctx = probe()
    for attempt in ctx.of("drag_probe_attempt"):
        listener = attempt["listener"]
        assert listener["mousedown"]["count"] == 1
        assert listener["mouseup"]["count"] == 1
        assert listener["mousemove"]["count"] >= 8
        assert listener["mousedown"]["trusted"] == [True]
        assert set(listener["mousemove"]["trusted"]) == {True}
        assert len(listener["mousemove"]["trusted"]) <= 5  # bounded
        assert listener["mousedown"]["targets"][0].startswith("div.")
        assert "draggable" in listener["mousedown"]["targets"][0]
        assert "dragstart" not in listener  # the fake handle uses mouse events only


def test_an_attempt_that_raises_is_recorded_and_the_probe_goes_on(probe, monkeypatch):
    real = Scenario._drag
    calls = []

    def flaky(self, method, dx, samples):
        calls.append(method)
        if len(calls) == 1:
            raise RuntimeError("boom\nsecond line")
        return real(self, method, dx, samples)

    monkeypatch.setattr(Scenario, "_drag", flaky)
    result, ctx = probe()

    assert (result.status, result.reason) == (Status.BLOCKED, "drag_probe_done")
    failed = ctx.one("drag_probe_failed")
    assert (failed["n"], failed["method"], failed["type"]) == (1, "selenium", "RuntimeError")
    assert failed["message"] == "boom"
    attempts = ctx.of("drag_probe_attempt")
    assert attempts[0]["error"] == "RuntimeError: boom"
    assert attempts[0]["outcome"] == "no_answer"
    # Nothing was dragged, so the next attempt is on the same puzzle and works.
    assert (attempts[1]["n"], attempts[1]["method"], attempts[1]["error"]) == (1, "cdp", None)
    assert len(attempts) == 4


def test_an_accepted_answer_is_recorded_and_ends_the_probe_without_a_solve(probe, fake):
    fake.answers = [RIGHT]
    result, ctx = probe()

    assert (result.status, result.reason) == (Status.BLOCKED, "drag_probe_done")
    assert len(ctx.of("drag_probe_attempt")) == 1
    assert ctx.one("answer_request")["response"]["success"] is True
    assert ctx.one("drag_probe_finished")["reason"] == "answer_accepted"


def test_the_budget_stops_the_probe(probe):
    _, ctx = probe(replace(PROBE, drag_probe=0))
    assert ctx.of("drag_probe_attempt") == []
    assert ctx.one("drag_probe_finished")["reason"] == "budget_spent"


def test_the_normal_bot_never_drags(probe):
    result, ctx = probe(bot=ArcaptchaBot)
    assert (result.status, result.reason) == (Status.BLOCKED, "challenge_unsolved")
    assert ctx.of("drag_probe_attempt") == []
    assert ctx.of("drag_probe_started") == []


def test_the_probe_bot_is_registered_headful_with_an_honest_description():
    assert ArcaptchaDragProbeBot in BOTS
    assert BOTS[-1] is ArcaptchaDragProbeBot
    assert ArcaptchaDragProbeBot.id == "arcaptcha-drag-probe"
    assert ArcaptchaDragProbeBot.modes == ["headful"]
    assert ArcaptchaDragProbeBot.profile is ALL_SIGNALS
    assert ArcaptchaDragProbeBot.drag_probe is True
    assert "never counts as a solve" in ArcaptchaDragProbeBot.description
