"""A uvicorn server for an app, on 127.0.0.1 and a free port, run in a thread inside pytest."""

import socket
import threading

import uvicorn
from fastapi import FastAPI


class LocalServer:
    def __init__(self, app: FastAPI) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.origin = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        config = uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True
        )

    def start(self) -> None:
        self.thread.start()
        while not self.server.started:
            if not self.thread.is_alive():
                raise RuntimeError("the local server did not start")
            threading.Event().wait(0.02)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)
        self.sock.close()
