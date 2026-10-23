"""SQLite: какие задания уже видели, подписчики, служебные значения."""
from __future__ import annotations

import sqlite3
import threading
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    subject    TEXT NOT NULL,
    qid        TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    posted     INTEGER NOT NULL DEFAULT 0,   -- 0 = ждёт решения админа
    PRIMARY KEY (subject, qid)
);
CREATE TABLE IF NOT EXISTS users (
    chat_id  INTEGER PRIMARY KEY,
    subjects TEXT NOT NULL DEFAULT 'math,phys,inf,rus',
    joined   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    def __init__(self) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        self.c.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _x(self, sql: str, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur.fetchall()

    # --- задания ---
    def known_ids(self, subject: str) -> set[str]:
        return {r[0] for r in self._x("SELECT qid FROM tasks WHERE subject=?", (subject,))}

    def count(self, subject: str) -> int:
        return self._x("SELECT COUNT(*) FROM tasks WHERE subject=?", (subject,))[0][0]

    def add_ids(self, subject: str, qids, posted: int) -> None:
        now = int(time.time())
        with self.lock:
            self.c.executemany(
                "INSERT OR IGNORE INTO tasks(subject,qid,first_seen,posted) VALUES(?,?,?,?)",
                [(subject, q, now, posted) for q in qids],
            )
            self.c.commit()

    def mark_posted(self, subject: str, qids) -> None:
        with self.lock:
            self.c.executemany(
                "UPDATE tasks SET posted=1 WHERE subject=? AND qid=?",
                [(subject, q) for q in qids],
            )
            self.c.commit()

    def pending(self, subject: str) -> list[str]:
        return [r[0] for r in self._x(
            "SELECT qid FROM tasks WHERE subject=? AND posted=0 ORDER BY first_seen", (subject,))]

    # --- пользователи ---
    def user_subjects(self, chat_id: int) -> set[str]:
        rows = self._x("SELECT subjects FROM users WHERE chat_id=?", (chat_id,))
        if not rows:
            self._x("INSERT INTO users(chat_id, joined) VALUES(?,?)", (chat_id, int(time.time())))
            return set(config.SUBJECTS)
        return {s for s in rows[0][0].split(",") if s}

    def set_user_subjects(self, chat_id: int, subjects: set[str]) -> None:
        self.user_subjects(chat_id)
        self._x("UPDATE users SET subjects=? WHERE chat_id=?", (",".join(sorted(subjects)), chat_id))

    def subscribers(self, subject: str) -> list[int]:
        return [r[0] for r in self._x("SELECT chat_id, subjects FROM users")
                if subject in r[1].split(",")]

    def remove_user(self, chat_id: int) -> None:
        self._x("DELETE FROM users WHERE chat_id=?", (chat_id,))

    def users_total(self) -> int:
        return self._x("SELECT COUNT(*) FROM users")[0][0]

    # --- meta ---
    def get(self, key: str, default: str = "") -> str:
        rows = self._x("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0][0] if rows else default

    def set(self, key: str, value: str) -> None:
        self._x("INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
