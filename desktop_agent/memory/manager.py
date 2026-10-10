"""MemoryManager: session tool events over MilesMemory.

None of the four desktop repos is a memory core. ``dsh-computer-use`` keeps an
observation snapshot with a TTL. ``vision-primitives-mcp`` keeps a
``VisionScratchpad`` for one image. This manager does not reimplement either
ranker.

Long-term reads and writes go to ``memory_kb.engine.KnowledgeBase``:

* ``KnowledgeBase.recall`` — cell-mem ``memory_recall``
* ``KnowledgeBase.search_memories`` — agent-memory-os ``search_memories``
* ``KnowledgeBase.save`` and ``KnowledgeBase.create_memory`` — archive path

Session and tool events live in a separate SQLite table in this process.
``memory_search`` returns the two framework payloads side by side. It does not
fuse them into a third score.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desktop_agent.core.logging import get_logger

log = get_logger("memory")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class MemoryManager:
    """Session log plus the MilesMemory long-term store."""

    def __init__(self, session_db: str | Path, memory_kb_db: str | Path, agent_id: str = "desktop-agent") -> None:
        self.session_db = Path(session_db)
        self.memory_kb_db = Path(memory_kb_db)
        self.agent_id = agent_id
        self.session_db.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.session_db, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_session()
        self._kb: Any = None
        self._kb_error: str | None = None

    def close(self) -> None:
        """Close the session database and the long-term store, if open."""
        self._conn.close()
        if self._kb is not None:
            self._kb.close()
            self._kb = None

    def _init_session(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_events (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                params_json TEXT NOT NULL,
                outcome_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS session_events_ts ON session_events(timestamp)"
        )
        self._conn.commit()

    def add_event(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        *,
        kind: str = "note",
        session_id: str = "default",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Append one session or tool event. This does not write long-term memory."""
        event_id = uuid.uuid4().hex
        stamped = timestamp or _now()
        self._conn.execute(
            """
            INSERT INTO session_events
                (id, timestamp, session_id, kind, name, params_json, outcome_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, stamped, session_id, kind, name, _dumps(params or {}), _dumps(outcome or {})),
        )
        self._conn.commit()
        row = {
            "id": event_id,
            "timestamp": stamped,
            "session_id": session_id,
            "kind": kind,
            "name": name,
            "params": params or {},
            "outcome": outcome or {},
        }
        log.info("session event %s %s %s", kind, name, event_id)
        return row

    def get_recent(self, limit: int = 20, session_id: str | None = None) -> dict[str, Any]:
        """Return the newest session events. Order is timestamp descending."""
        sql = "SELECT * FROM session_events"
        params: list[Any] = []
        if session_id is not None:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(int(limit))
        rows = []
        for row in self._conn.execute(sql, params):
            rows.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "session_id": row["session_id"],
                    "kind": row["kind"],
                    "name": row["name"],
                    "params": json.loads(row["params_json"]),
                    "outcome": json.loads(row["outcome_json"]),
                }
            )
        return {"status": "ok" if rows else "empty", "events": rows, "count": len(rows)}

    def search(self, query: str, limit: int = 10, **options: Any) -> dict[str, Any]:
        """Run cell-mem recall and agent-memory-os search. Do not merge ranks.

        ``options`` are forwarded to ``recall`` (for example ``strategy`` and
        ``memory_type``). ``agent_id``, ``session_id``, ``memory_type``,
        ``min_importance``, and ``tags`` are forwarded to ``search_memories``
        when present. Session rows are not part of either rank.
        """
        kb = self._open_kb()
        if kb is None:
            return {
                "status": "memory_kb_unavailable",
                "error": self._kb_error,
                "query": query,
                "cell_mem": None,
                "agent_memory_os": None,
            }
        recall_options = {
            key: options[key]
            for key in ("strategy", "memory_type", "top_k", "min_confidence")
            if key in options
        }
        recall_options.setdefault("top_k", int(limit))
        cell = kb.recall(query, recall_options)
        search_kwargs: dict[str, Any] = {"query": query, "limit": int(limit)}
        for key in ("memory_type", "agent_id", "session_id", "min_importance", "tags"):
            if key in options:
                search_kwargs[key] = options[key]
        amos = kb.search_memories(**search_kwargs)
        return {
            "status": "ok",
            "query": query,
            "cell_mem": cell,
            "agent_memory_os": amos,
        }

    def archive_summary(
        self,
        summary: str,
        *,
        session_id: str = "default",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Write a summary into both long-term stores.

        cell-mem receives a semantic ``save``. agent-memory-os receives
        ``create_memory`` with type ``semantic``. If the MilesMemory index is
        not built, this calls ``build_index`` once so later recall and search
        are allowed to run. The framework rankers are unchanged.
        """
        text = (summary or "").strip()
        if not text:
            return {"status": "error", "error": "summary is empty"}
        kb = self._open_kb()
        if kb is None:
            return {"status": "memory_kb_unavailable", "error": self._kb_error}
        index_result = None
        if not kb.index_ready:
            index_result = kb.build_index()
            if index_result.get("status") != "ok":
                return {
                    "status": "error",
                    "error": "MilesMemory index is not ready",
                    "index": index_result,
                }
        tag_list = list(tags or ["summary", "desktop-agent"])
        cell = kb.save(
            text,
            "semantic",
            {
                "confidence": 0.9,
                "session_id": session_id,
                "tags": tag_list,
                "metadata": {"source": "desktop-agent", "kind": "summary"},
            },
        )
        amos = kb.create_memory(
            content=text,
            memory_type="semantic",
            agent_id=self.agent_id,
            session_id=session_id,
            importance=5.0,
            tags=tag_list,
            metadata={"source": "desktop-agent", "kind": "summary"},
        )
        log.info("archived summary into MilesMemory session=%s", session_id)
        return {"status": "ok", "cell_mem": cell, "agent_memory_os": amos, "index": index_result}

    def _open_kb(self) -> Any:
        if self._kb is not None:
            return self._kb
        if self._kb_error is not None:
            return None
        try:
            from memory_kb.engine import KnowledgeBase
        except ImportError as exc:
            self._kb_error = (
                "memory_kb is not installed. Install MilesMemory "
                "(pip install -e path/to/MilesMemory) to enable long-term recall. "
                f"Import error: {exc}"
            )
            log.warning(self._kb_error)
            return None
        self.memory_kb_db.parent.mkdir(parents=True, exist_ok=True)
        self._kb = KnowledgeBase(self.memory_kb_db)
        return self._kb
