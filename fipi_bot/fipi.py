"""Скачивание и разбор открытого банка ФИПИ.

Задание в банке — это блок <div class="qblock" id="q<ID>"> с текстом условия
и соседний блок <div id="i<ID>"> с информацией (КЭС, тип ответа).
Картинки ФИПИ вставляет как <img> или скриптом ShowPictureQ('docs/...').
Всё это превращаем в чистый HTML без полей ответа, картинки — в data: URI,
чтобы рендер не зависел от сайта.
"""
from __future__ import annotations

import base64
import mimetypes
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from . import config

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
IMG_EXT = {".png", ".gif", ".jpg", ".jpeg", ".bmp", ".svg", ".webp"}
SHOW_PIC_RE = re.compile(r"ShowPicture\w*\(\s*['\"]([^'\"]+)['\"]")
QID_RE = re.compile(r"^q([0-9A-Fa-f]{4,})$")


class FipiUnavailable(Exception):
    """Сайт лежит / профилактика / вернул не то."""


@dataclass
class Task:
    subject: str
    qid: str
    html: str                      # очищенное условие, картинки внутри как data:
    kes: str = ""                  # раздел кодификатора
    answer_type: str = ""
    number: str = ""               # номер в КИМ, если удалось определить
    files: list[tuple[str, bytes]] = field(default_factory=list)  # приложенные файлы
    text_preview: str = ""


class FipiClient:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"})
        self.s.verify = config.FIPI_VERIFY_SSL
        self._opened: set[str] = set()

    # ---------- сеть ----------
    def _get(self, url: str, **kw) -> requests.Response:
        last = None
        for attempt in range(4):
            try:
                r = self.s.get(url, timeout=40, **kw)
                if r.status_code == 200:
                    time.sleep(config.REQUEST_DELAY)
                    return r
                last = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last = str(e)
            time.sleep(5 * (attempt + 1))
        raise FipiUnavailable(f"{url}: {last}")

    @staticmethod
    def _soup(r: requests.Response) -> BeautifulSoup:
        # страницы ФИПИ в windows-1251, bs4 сам смотрит meta charset
        return BeautifulSoup(r.content, "lxml")

    def open_bank(self, proj: str) -> BeautifulSoup:
        """Открывает главную банка (нужно для сессионной куки)."""
        r = self._get(urljoin(config.FIPI_BASE, f"index.php?proj={proj}"))
        soup = self._soup(r)
        text = soup.get_text(" ", strip=True).lower()
        if "профилактическ" in text and "недоступн" in text:
            raise FipiUnavailable("ФИПИ на профилактике")
        self._opened.add(proj)
        return soup

    def questions_page(self, proj: str, page: int) -> tuple[BeautifulSoup, str]:
        if proj not in self._opened:
            self.open_bank(proj)
        url = urljoin(
            config.FIPI_BASE,
            f"questions.php?proj={proj}&page={page}&pagesize={config.PAGE_SIZE}",
        )
        return self._soup(self._get(url)), url

    def fetch_bytes(self, url: str) -> bytes | None:
        try:
            return self._get(url).content
        except FipiUnavailable:
            return None

    # ---------- обход ----------
    def list_ids(self, proj: str, max_pages: int = 2000):
        """Генератор (qid, qblock, info_block, page_url) по всему банку."""
        seen: set[str] = set()
        for page in range(max_pages):
            soup, url = self.questions_page(proj, page)
            blocks = parse_blocks(soup)
            fresh = [b for b in blocks if b[0] not in seen]
            if not fresh:
                break
            for qid, qb, info in fresh:
                seen.add(qid)
                yield qid, qb, info, url
            if len(blocks) < config.PAGE_SIZE:
                break

    def build_task(self, subject: str, qid: str, qblock: Tag, info: Tag | None,
                   page_url: str) -> Task:
        html, files, preview = clean_task_html(qblock, page_url, self.fetch_bytes)
        meta = parse_info(info)
        return Task(
            subject=subject,
            qid=qid,
            html=html,
            kes=meta.get("kes", ""),
            answer_type=meta.get("answer_type", ""),
            number=meta.get("number", ""),
            files=files,
            text_preview=preview,
        )


# ---------- разбор HTML ----------
def parse_blocks(soup: BeautifulSoup) -> list[tuple[str, Tag, Tag | None]]:
    out = []
    for qb in soup.select("div.qblock"):
        m = QID_RE.match(qb.get("id", ""))
        qid = m.group(1) if m else None
        if not qid:
            inp = qb.find("input", attrs={"name": "guid"})
            qid = inp.get("value") if inp else None
        if not qid:
            continue
        info = soup.find(id=f"i{qid}")
        out.append((qid.upper(), qb, info))
    return out


def parse_info(info: Tag | None) -> dict:
    res: dict[str, str] = {}
    if info is None:
        return res
    text = info.get_text("\n", strip=True)
    m = re.search(r"КЭС[:\s]*\n?(.+)", text)
    if m:
        res["kes"] = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"Тип ответа[:\s]*\n?(.+)", text)
    if m:
        res["answer_type"] = m.group(1).strip()
    m = re.search(r"(?:Номер задания|Задание\s*№|Линия)\s*[:№]?\s*(\d{1,2})", text)
    if m:
        res["number"] = m.group(1)
    return res


def _data_uri(raw: bytes, url: str) -> str:
    mime = mimetypes.guess_type(urlparse(url).path)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def clean_task_html(qblock: Tag, page_url: str, fetch) -> tuple[str, list, str]:
    soup = BeautifulSoup(str(qblock), "lxml")
    root = soup.select_one("div.qblock")
    content = root.select_one("td.cell_0") or root

    # скрипты ShowPictureQ(...) -> обычные <img>
    for sc in content.find_all("script"):
        m = SHOW_PIC_RE.search(sc.string or sc.get_text() or "")
        if m:
            sc.replace_with(soup.new_tag("img", src=m.group(1)))
        else:
            sc.decompose()

    # убираем поля ответа, кнопки, служебное
    for el in content.select(
        "input, select, textarea, button, form, style, noscript, "
        ".id-text, .answer-button, .hint, [class*=answer]"
    ):
        el.decompose()
    for el in content.find_all(attrs={"onclick": True}):
        del el["onclick"]

    # картинки -> data:, файлы -> вложения
    for img in content.find_all("img"):
        src = img.get("src")
        if not src:
            img.decompose()
            continue
        full = urljoin(page_url, src)
        raw = fetch(full)
        if raw:
            img["src"] = _data_uri(raw, full)
        else:
            img.replace_with(soup.new_string("[рисунок не загрузился]"))
        for attr in ("style", "onload", "onerror"):
            img.attrs.pop(attr, None)

    files = []
    for a in content.find_all("a", href=True):
        full = urljoin(page_url, a["href"])
        ext = "." + full.rsplit(".", 1)[-1].lower() if "." in full.rsplit("/", 1)[-1] else ""
        if "docs/" in full and ext and ext not in IMG_EXT:
            raw = fetch(full)
            if raw:
                name = full.rsplit("/", 1)[-1]
                files.append((name, raw))
                a.replace_with(soup.new_string(f"[файл: {name}]"))

    # инлайн-стили ФИПИ (Times 10pt и т.п.) мешают единому виду
    for el in content.find_all(True):
        el.attrs.pop("style", None) if el.name != "img" else None
        el.attrs.pop("class", None) if el.name not in ("table", "td", "th") else None
        for a in ("face", "size", "color", "bgcolor"):
            el.attrs.pop(a, None)
    for f in content.find_all("font"):
        f.unwrap()

    preview = re.sub(r"\s+", " ", content.get_text(" ", strip=True))[:300]
    inner = "".join(str(c) for c in content.contents)
    return inner.strip(), files, preview
