"""Проход по банку: находит новые задания, рендерит карточки в кэш."""
from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass

from . import config
from .fipi import FipiClient, Task
from .render import Renderer
from .storage import DB

log = logging.getLogger("scan")


@dataclass
class ScanResult:
    subject: str
    total: int
    new: list[str]           # qid новых, уже отрендеренных
    baseline: bool = False   # первый проход — ничего не рассылаем
    held: bool = False       # слишком много новых — ждём решения админа


def card_dir(subject: str, qid: str):
    d = config.CACHE_DIR / subject / qid
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_card(task: Task, renderer: Renderer) -> None:
    d = card_dir(task.subject, task.qid)
    renderer.render(task, d / "card.png", seen=dt.date.today())
    for name, raw in task.files:
        (d / name).write_bytes(raw)
    (d / "meta.json").write_text(json.dumps({
        "qid": task.qid, "subject": task.subject, "kes": task.kes,
        "number": task.number, "answer_type": task.answer_type,
        "files": [n for n, _ in task.files], "preview": task.text_preview,
    }, ensure_ascii=False), encoding="utf-8")


def load_meta(subject: str, qid: str) -> dict | None:
    p = config.CACHE_DIR / subject / qid / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def scan_subject(subject: str, db: DB, client: FipiClient, renderer: Renderer) -> ScanResult:
    proj = config.SUBJECTS[subject]["proj"]
    known = db.known_ids(subject)
    baseline = not known
    found: list[str] = []
    new: list[str] = []

    for qid, qblock, info, page_url in client.list_ids(proj):
        found.append(qid)
        if baseline or qid in known:
            continue
        if len(new) >= config.MAX_NEW_PER_SCAN:
            new.append(qid)          # дальше не рендерим, просто считаем
            continue
        try:
            task = client.build_task(subject, qid, qblock, info, page_url)
            save_card(task, renderer)
            new.append(qid)
        except Exception:
            log.exception("не удалось обработать %s/%s", subject, qid)

    if not found:
        raise RuntimeError("банк вернул 0 заданий — вероятно, поменялась вёрстка ФИПИ")

    if baseline:
        db.add_ids(subject, found, posted=1)
        log.info("%s: первый проход, запомнил %d заданий", subject, len(found))
        return ScanResult(subject, len(found), [], baseline=True)

    held = len(new) > config.MAX_NEW_PER_SCAN
    if held:
        rendered = new[:config.MAX_NEW_PER_SCAN]
        db.add_ids(subject, rendered, posted=0)
        db.add_ids(subject, new[config.MAX_NEW_PER_SCAN:], posted=1)
    else:
        db.add_ids(subject, new, posted=0)
    log.info("%s: всего %d, новых %d%s", subject, len(found), len(new), " (задержано)" if held else "")
    return ScanResult(subject, len(found), new if not held else [], held=held)
