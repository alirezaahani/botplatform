# Bot platform

## Watching a run live

Launch an ARCaptcha run in `headful` mode. While it is queued or running, its page at `http://127.0.0.1:8000/runs/<id>` shows a "Watch live" link that opens the worker's browser in noVNC. You can use the mouse and keyboard.

If anyone opens the live view, the run page warns that the result may be human-assisted.

On a server, the port only listens on the server's `127.0.0.1`. Open a tunnel from your own machine, then use the same address in your browser:

```
ssh -L 8000:127.0.0.1:8000 user@server
```

To check that the worker image brings up the display and viewer, run `tests/check_viewer.sh`.
