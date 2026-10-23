"""Офлайн-проверка: разбор макета страницы ФИПИ и рендер карточек.
Запуск из корня проекта:  python -m tests.test_offline
"""
import datetime as dt
from pathlib import Path

from bs4 import BeautifulSoup

from fipi_bot.fipi import parse_blocks, clean_task_html, parse_info, Task
from fipi_bot.render import Renderer

FIX = Path(__file__).parent / "fixture"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
PAGE_URL = "https://ege.fipi.ru/bank/questions.php?proj=X&page=0"


def fake_fetch(url: str):
    return (FIX / "graph.png").read_bytes() if url.endswith("graph.png") else None


soup = BeautifulSoup((FIX / "questions_page.html").read_bytes(), "lxml")
blocks = parse_blocks(soup)
assert [b[0] for b in blocks] == ["5B2E9A", "C71D04"], blocks

subjects = {"5B2E9A": "math", "C71D04": "rus"}
r = Renderer()
try:
    for qid, qb, info in blocks:
        html, files, preview = clean_task_html(qb, PAGE_URL, fake_fetch)
        assert "<input" not in html and "Ответ:" not in html, "поля ответа должны быть вырезаны"
        meta = parse_info(info)
        t = Task(subject=subjects[qid], qid=qid, html=html, kes=meta.get("kes", ""),
                 number=meta.get("number", ""), text_preview=preview)
        if qid == "5B2E9A":
            assert "data:image/png;base64," in html, "картинка должна встроиться"
        p = r.render(t, OUT / f"{t.subject}_{qid}.png", seen=dt.date(2026, 10, 28))
        print("ok", p, meta)
finally:
    r.close()
