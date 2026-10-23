"""Настройки. Берутся из переменных окружения или файла .env рядом с проектом."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# id админов через запятую (свой id можно узнать у @userinfobot)
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
# необязательно: канал, куда тоже постить новые задания (бот должен быть админом канала)
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip() or None

# как часто проходить банк целиком, в часах
SCAN_EVERY_HOURS = float(os.environ.get("SCAN_EVERY_HOURS", "6"))
# пауза между запросами к ФИПИ, секунды (не долбим сайт)
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1.5"))
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "50"))
# если за один проход по предмету «новых» больше этого числа — не рассылаем,
# а спрашиваем админа (скорее всего банк переразметили, а не добавили задания)
MAX_NEW_PER_SCAN = int(os.environ.get("MAX_NEW_PER_SCAN", "120"))
# у ФИПИ бывают проблемы с цепочкой сертификатов; по умолчанию проверяем
FIPI_VERIFY_SSL = os.environ.get("FIPI_VERIFY_SSL", "1") != "0"

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "fipi.sqlite3"
CACHE_DIR = DATA_DIR / "cache"

FIPI_BASE = "https://ege.fipi.ru/bank/"

# proj — идентификатор банка предмета в адресе ege.fipi.ru/bank/index.php?proj=...
SUBJECTS = {
    "math": {
        "title": "Профильная математика",
        "proj": "AC437B34557F88EA4115D2F374B0A07B",
        "accent": "#2F55D4",
    },
    "phys": {
        "title": "Физика",
        "proj": "BA1F39653304A5B041B656915DC36B38",
        "accent": "#D2581C",
    },
    "inf": {
        "title": "Информатика",
        "proj": "B9ACA5BBB2E19E434CD6BEC25284C67F",
        "accent": "#12806A",
    },
    "rus": {
        "title": "Русский язык",
        "proj": "AF0ED3F2557F8FFC4C06F80B6803FD26",
        "accent": "#B8324A",
    },
}
