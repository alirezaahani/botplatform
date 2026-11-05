"""Web-side modules must not need Selenium."""


def test_web_side_modules_import_without_selenium():
    """The web image has no Selenium. Importing a `bots` module there would crash the batch CLI."""
    import subprocess
    import sys

    code = (
        "import sys; sys.modules['selenium'] = None\n"
        "import botplatform.batch, botplatform.web.app, botplatform.web.stats, botplatform.stats\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
