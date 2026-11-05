from enum import StrEnum

from botplatform.contract import Bot, BotResult, RunContext, Status


class ExampleMode(StrEnum):
    DIRECT = "direct"


class ExampleBot(Bot[ExampleMode]):
    """The smallest possible bot. It uses no browser, so it declares a `direct` mode."""

    def __init__(self) -> None:
        super().__init__(
            id="example",
            name="Example bot",
            description="Adds one timeline event and succeeds. It checks the platform, not a website.",
            modes=ExampleMode,
        )

    def run(self, ctx: RunContext, mode: ExampleMode) -> BotResult:
        ctx.event("hello", {"mode": mode})
        return BotResult(status=Status.SUCCESS)
