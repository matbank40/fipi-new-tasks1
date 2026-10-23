"""HTML-карточка задания -> PNG через headless Chromium."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from . import config
from .fipi import Task

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def heading_for(task: Task) -> str:
    if task.number:
        return f"Задание {task.number}"
    if task.kes:
        # «4.1 Производная функции…» -> «Производная функции…»
        parts = task.kes.split(" ", 1)
        title = parts[1] if len(parts) == 2 and parts[0][:1].isdigit() else task.kes
        return title[:70] + ("…" if len(title) > 70 else "")
    return "Новое задание"


def card_html(task: Task, seen: dt.date | None = None) -> str:
    subj = config.SUBJECTS[task.subject]
    return _env.get_template("card.html").render(
        accent=subj["accent"],
        subject_title=subj["title"],
        heading=heading_for(task),
        qid=task.qid,
        kes=task.kes.split(" ", 1)[0] if task.kes else "",
        seen_date=(seen or dt.date.today()).strftime("%d.%m.%Y"),
        task_html=task.html,
    )


class Renderer:
    def __init__(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=["--no-sandbox"])
        self._page = self._browser.new_page(
            viewport={"width": 1080, "height": 800}, device_scale_factor=2
        )

    def render(self, task: Task, out: Path, seen: dt.date | None = None) -> Path:
        self._page.set_content(card_html(task, seen), wait_until="load")
        # ждём, пока все картинки декодируются, и только потом масштабируем
        self._page.evaluate(
            "Promise.all([...document.images].map(i => i.decode().catch(() => null)))"
        )
        self._page.evaluate("fitImages()")
        self._page.locator("body").screenshot(path=str(out))
        return out

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()
