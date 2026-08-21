"""End-to-end smoke test: launch the real app with `streamlit run` in a
subprocess and confirm it comes up healthy, exercising the actual entrypoint
(imports of every ui.tabs module, st.set_page_config, tab wiring) rather than
just importing the module.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).parent.parent
STARTUP_TIMEOUT_S = 45
POLL_INTERVAL_S = 0.5


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def running_app():
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "streamlit_app.py",
            "--server.headless=true",
            "--server.port",
            str(port),
            "--browser.gatherUsageStats=false",
            "--server.runOnSave=false",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        yield proc, port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def _wait_for_health(
    port: int, proc: subprocess.Popen, timeout_s: float
) -> requests.Response:
    deadline = time.monotonic() + timeout_s
    last_exc = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            pytest.fail(
                f"streamlit process exited early (code {proc.returncode}):\n{output}"
            )
        try:
            return requests.get(f"http://127.0.0.1:{port}/_stcore/health", timeout=2)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            time.sleep(POLL_INTERVAL_S)
    raise AssertionError(
        f"app never became healthy within {timeout_s}s (last error: {last_exc})"
    )


def test_streamlit_app_launches_and_reports_healthy(running_app):
    proc, port = running_app
    response = _wait_for_health(port, proc, STARTUP_TIMEOUT_S)
    assert response.status_code == 200
    assert response.text.strip().lower() == "ok"


def test_streamlit_app_serves_the_main_page(running_app):
    proc, port = running_app
    _wait_for_health(port, proc, STARTUP_TIMEOUT_S)
    response = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
