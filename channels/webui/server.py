"""In-process WebUI listener with safe missing-dist fallback."""

import logging
from pathlib import Path
import threading
from config import get_global_config

log = logging.getLogger(__name__)
DIST = Path(__file__).resolve().parents[2] / "webui" / "dist"
_server = None
_stop = threading.Event()


def available():
    return DIST.joinpath("index.html").is_file()


def start():
    _stop.clear()
    if not available():
        log.warning("WebUI disabled: run npm ci && npm run build in webui/ first")
        return

    def supervise():
        global _server
        from channels.webui import state
        import uvicorn
        from channels.webui.api import create_app

        while not _stop.is_set():
            cfg = get_global_config()
            if not cfg.ENABLE_WEBUI:
                state.enabled = False
                _stop.wait(0.5)
                continue
            try:
                host, port = cfg.WEBUI_HOST, cfg.WEBUI_PORT
                app = create_app(DIST)
                server = uvicorn.Server(
                    uvicorn.Config(
                        app, host=host, port=port, log_level="warning", access_log=False, timeout_graceful_shutdown=3
                    )
                )
                _server = server
                thread = threading.Thread(target=server.run, daemon=True, name="webui-api")
                thread.start()
                while thread.is_alive() and not _stop.is_set():
                    state.enabled = server.started
                    cfg = get_global_config()
                    if not cfg.ENABLE_WEBUI or (cfg.WEBUI_HOST, cfg.WEBUI_PORT) != (host, port):
                        break
                    _stop.wait(0.5)
                server.should_exit = True
                thread.join(timeout=5)
                state.enabled = False
            except Exception:
                log.exception("WebUI initialization failed; other channels remain enabled")
            _stop.wait(1)

    threading.Thread(target=supervise, daemon=True, name="webui-supervisor").start()


def stop():
    _stop.set()
    if _server:
        _server.should_exit = True
