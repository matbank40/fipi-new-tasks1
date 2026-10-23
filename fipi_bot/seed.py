"""Заранее загрузить в базу уже известные ID, чтобы они не считались новыми.

Банк сейчас на профилактике (22–27.10.2026). Если у тебя есть старый
список ID (например, из парсера профильной математики), загрузи его ДО первого
запуска — тогда задания, добавленные во время профилактики, бот поймает как новые.

    python -m fipi_bot.seed math ids_math.txt

Файл: по одному ID на строку (лишний текст вокруг игнорируется).
"""
import re
import sys

from . import config
from .storage import DB


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in config.SUBJECTS:
        raise SystemExit(f"использование: python -m fipi_bot.seed <{'|'.join(config.SUBJECTS)}> файл.txt")
    subject, path = sys.argv[1], sys.argv[2]
    text = open(path, encoding="utf-8", errors="ignore").read()
    ids = {m.upper() for m in re.findall(r"\b[0-9A-Fa-f]{6}\b", text)}
    db = DB()
    db.add_ids(subject, ids, posted=1)
    print(f"{subject}: загружено {len(ids)} ID, всего в базе {db.count(subject)}")


if __name__ == "__main__":
    main()
