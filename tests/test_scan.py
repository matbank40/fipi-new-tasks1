"""Проверка логики «новых»: первый проход запоминает, второй находит добавленное.
Сеть подменяется фикстурой.  python -m tests.test_scan
"""
import os
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["REQUEST_DELAY"] = "0"

from fipi_bot import config, fipi  # noqa: E402
from fipi_bot.render import Renderer  # noqa: E402
from fipi_bot.scanner import scan_subject, load_meta  # noqa: E402
from fipi_bot.storage import DB  # noqa: E402

FIX = Path(__file__).parent / "fixture"
page_html = (FIX / "questions_page.html").read_text(encoding="utf-8")
first, second = page_html.split('<div class="qblock" id="qC71D04">')
state = {"html": first + "</body></html>"}   # сначала в «банке» одно задание


class FakeResp:
    def __init__(self, content): self.content, self.status_code = content, 200


def fake_get(self, url, **kw):
    if "index.php" in url:
        return FakeResp("<html>банк</html>".encode())
    if "questions.php" in url:
        page = int(url.split("page=")[1].split("&")[0])
        return FakeResp(state["html"].encode() if page == 0 else b"<html></html>")
    if url.endswith(".png"):
        return FakeResp((FIX / "graph.png").read_bytes())
    raise fipi.FipiUnavailable(url)


fipi.FipiClient._get = fake_get
db, r = DB(), Renderer()
try:
    res = scan_subject("rus", db, fipi.FipiClient(), r)
    assert res.baseline and res.total == 1, res
    state["html"] = page_html                 # «ФИПИ добавил» второе задание
    res = scan_subject("rus", db, fipi.FipiClient(), r)
    assert res.new == ["C71D04"] and not res.baseline, res
    assert db.pending("rus") == ["C71D04"]
    assert (config.CACHE_DIR / "rus" / "C71D04" / "card.png").exists()
    print("ok", load_meta("rus", "C71D04")["kes"])
    # профилактика определяется
    fipi.FipiClient._get = lambda self, url, **kw: FakeResp(
        "Сообщаем, что будут проводиться профилактические работы. Открытые банки будут недоступны".encode())
    try:
        scan_subject("phys", db, fipi.FipiClient(), r)
        raise AssertionError("должно было упасть")
    except fipi.FipiUnavailable as e:
        print("ok профилактика:", e)
finally:
    r.close()
