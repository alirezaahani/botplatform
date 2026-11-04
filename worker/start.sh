#!/bin/bash
# Starts the virtual display, the VNC server and noVNC, then the worker (or the command given).
# If any of them dies, this exits non-zero so Docker restarts the container.
set -u
export DISPLAY=:99

# A restarted container keeps /tmp, and a stale lock stops Xvfb from starting.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
xvfb=$!
while [ ! -S /tmp/.X11-unix/X99 ]; do
    kill -0 "$xvfb" 2>/dev/null || { echo "start.sh: Xvfb did not start" >&2; exit 1; }
    sleep 0.1
done
# VNC listens on localhost only. websockify is the only way in, on port 6080 inside the network.
x11vnc -display :99 -localhost -nopw -shared -forever -rfbport 5900 -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 &

if [ $# -eq 0 ]; then
    set -- python -m botplatform.worker.main
fi
"$@" &
main=$!

trap 'kill $(jobs -p) 2>/dev/null; wait; exit 0' TERM INT
wait -n -p done
code=$?
kill $(jobs -p) 2>/dev/null
if [ "$done" = "$main" ]; then
    exit "$code"
fi
echo "start.sh: a background process (pid $done) exited with code $code" >&2
exit 1
