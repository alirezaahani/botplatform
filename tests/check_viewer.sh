#!/bin/bash
# Checks that the worker image's start script brings up Xvfb, x11vnc and noVNC.
# Run from the project root: tests/check_viewer.sh   (needs Docker and a .env, like `compose up`)
set -eu
docker compose build worker
# start-worker runs the command in the background, so its stdin is empty: pass the code with -c.
check=$(cat <<'PY'
import os
import socket
import time
import urllib.request

deadline = time.time() + 20
while True:
    try:
        page = urllib.request.urlopen("http://127.0.0.1:6080/vnc.html", timeout=2).read()
        socket.create_connection(("127.0.0.1", 5900), timeout=2).close()
        break
    except OSError:
        if time.time() > deadline:
            raise SystemExit("FAIL: noVNC or x11vnc did not come up")
        time.sleep(0.5)
assert os.path.exists("/tmp/.X11-unix/X99"), "FAIL: no Xvfb display :99"
assert b"noVNC" in page, "FAIL: port 6080 did not serve noVNC"
print("OK: Xvfb :99, x11vnc on 5900 and noVNC on 6080 are up")
PY
)
docker compose run --rm --no-deps -T worker start-worker python -c "$check"
