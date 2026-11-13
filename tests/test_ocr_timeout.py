"""A stuck OCR call returns nothing and does not hold the next read."""
import asyncio
import threading
import time

import numpy as np

from desktop_agent.control.pc_control import core


def test_hung_ocr_returns_empty_and_does_not_block_the_next_read(monkeypatch):
    release = threading.Event()
    started = threading.Event()
    calls = []
    com = []
    caller = threading.get_ident()

    async def hang(_png):
        calls.append(threading.get_ident())
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.05)
        return [core.Item("ocr", "should-not-surface", (0, 0, 1, 1), None, "ocr", True)]

    def co_initialize(_reserved, flags):
        com.append((threading.get_ident(), int(flags)))
        return 0

    monkeypatch.setattr(core, "_ocr", hang)
    monkeypatch.setattr(core.ctypes.windll.ole32, "CoInitializeEx", co_initialize)
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    try:
        t0 = time.monotonic()
        assert core.ocr_items(img) == []
        elapsed = time.monotonic() - t0
        assert started.is_set()
        assert 7 <= elapsed < 20
        worker = core.ocr_items._worker
        assert worker.is_alive()
        assert worker.ident != caller
        assert com == [(worker.ident, 0)]
        assert calls == [worker.ident]

        def following_read():
            return "read"

        read_at = time.monotonic()
        assert following_read() == "read"
        assert time.monotonic() - read_at < 1
        assert worker.is_alive()

        skipped = time.monotonic()
        assert core.ocr_items(img) == []
        assert time.monotonic() - skipped < 1
        assert calls == [worker.ident]
        assert worker.is_alive()
    finally:
        release.set()
        worker = getattr(core.ocr_items, "_worker", None)
        if worker is not None:
            worker.join(2)
