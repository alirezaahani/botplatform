from botplatform.contract import Bot, BotResult, RunContext, Status


class ExampleBot(Bot):
    """The smallest possible bot. It uses no browser, so it declares a `direct` mode."""

    id = "example"
    name = "Example bot"
    description = "Adds one timeline event and succeeds. It checks the platform, not a website."
    modes = ["direct"]

    def run(self, ctx: RunContext) -> BotResult:
        ctx.event("hello", {"mode": ctx.mode})
        return BotResult(status=Status.SUCCESS)
