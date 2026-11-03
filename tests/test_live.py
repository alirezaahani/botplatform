"""Drift check against the real site. Run: pytest -m live -v -s"""

import os
import re

import pytest

from botplatform.bots.arcaptcha import ArcaptchaBot
from botplatform.contract import Status
from tests.conftest import RecordingContext


@pytest.mark.live
def test_real_demo_site(monkeypatch):
    # The demo accepts demo/demo. Real credentials from the environment win.
    monkeypatch.setenv("ARCAPTCHA_USERNAME", os.environ.get("ARCAPTCHA_USERNAME", "demo"))
    monkeypatch.setenv("ARCAPTCHA_PASSWORD", os.environ.get("ARCAPTCHA_PASSWORD", "demo"))
    ctx = RecordingContext()
    result = ArcaptchaBot().run(ctx)

    login = ctx.of("login_response")
    print(f"\nstatus={result.status} reason={result.reason}")
    print(f"challenge ids={ctx.challenge_ids}")
    print(f"login_response={login}")
    print(f"events={[kind for kind, _ in ctx.events]}")
    if result.error:
        print(result.error)

    accepted = result.status in (Status.SUCCESS, Status.BLOCKED) or (
        result.status == Status.FAILED and result.reason == "verification_failed"
    )
    assert accepted, f"drift: {result.status} / {result.reason} {result.error}"
    assert ctx.of("checkbox_clicked"), "the selectors no longer find the checkbox"
    assert any(c["captcha_type"] for c in ctx.of("create_response")), "no create response decoded"
    assert ctx.challenge_ids
    assert re.fullmatch(r"\d{30}", ctx.challenge_ids[-1])
    assert login, "no login response"
    assert ctx.of("toast"), "no toast event"
