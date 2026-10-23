"""Точка входа: Telegram-бот + фоновая проверка банка ФИПИ.

Запуск:  python -m fipi_bot.main
"""
from __future__ import annotations

import datetime as dt
import logging
import struct
import threading
import time

from . import config
from .fipi import FipiClient, FipiUnavailable
from .render import Renderer
from .scanner import card_dir, load_meta, scan_subject
from .storage import DB
from .tg import TG, Blocked

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("bot")

db = DB()
tg = TG(config.BOT_TOKEN, config.TG_API_BASE, config.TG_PROXY)
scan_now = threading.Event()
scan_lock = threading.Lock()


def bank_url(subject: str) -> str:
    return f"{config.FIPI_BASE}index.php?proj={config.SUBJECTS[subject]['proj']}"


# ---------- рассылка ----------
def png_size(path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def caption_for(meta: dict) -> str:
    subj = config.SUBJECTS[meta["subject"]]["title"]
    num = f" · задание {meta['number']}" if meta.get("number") else ""
    kes = f"\nКЭС: {meta['kes']}" if meta.get("kes") else ""
    return f"<b>{subj}</b>{num}\nID <code>{meta['qid']}</code>{kes}"


def deliver(subject: str, qids: list[str]) -> int:
    targets = ([config.CHANNEL_ID] if config.CHANNEL_ID else []) + db.subscribers(subject)
    sent = 0
    for qid in qids:
        meta = load_meta(subject, qid)
        if not meta:
            continue
        d = card_dir(subject, qid)
        png = d / "card.png"
        w, h = png_size(png)
        as_doc = (w + h > 9500) or (h / w > 4)     # слишком длинная — шлём файлом без сжатия
        kb = {"inline_keyboard": [[{"text": "Открыть банк ФИПИ", "url": bank_url(subject)}]]}
        cap = caption_for(meta)
        file_id = None
        attach_ids: dict[str, str] = {}
        for chat in targets:
            try:
                src = file_id or png
                if as_doc:
                    file_id = tg.document(chat, src, cap, kb, filename=f"{subject}_{qid}.png")
                else:
                    file_id = tg.photo(chat, src, cap, kb)
                for name in meta.get("files", []):
                    attach_ids[name] = tg.document(chat, attach_ids.get(name) or (d / name),
                                                   filename=name)
            except Blocked:
                if chat != config.CHANNEL_ID:
                    db.remove_user(int(chat))
            except Exception:
                log.exception("отправка %s/%s в %s", subject, qid, chat)
        db.mark_posted(subject, [qid])
        sent += 1
    return sent


def notify_admins(text: str) -> None:
    for a in config.ADMIN_IDS:
        try:
            tg.send(a, text)
        except Exception:
            log.exception("админ %s", a)


# ---------- фоновая проверка ----------
def run_scan() -> str:
    with scan_lock:
        lines = []
        client = FipiClient()
        renderer = Renderer()
        try:
            for subject in config.SUBJECTS:
                title = config.SUBJECTS[subject]["title"]
                try:
                    res = scan_subject(subject, db, client, renderer)
                except FipiUnavailable as e:
                    lines.append(f"{title}: ФИПИ недоступен ({e})")
                    continue
                except Exception as e:
                    log.exception("скан %s", subject)
                    lines.append(f"{title}: ошибка — {e}")
                    continue
                if res.baseline:
                    lines.append(f"{title}: первый проход, запомнил {res.total}")
                elif res.held:
                    pend = len(db.pending(subject))
                    lines.append(f"{title}: подозрительно много новых, жду решения ({pend} готово)")
                    notify_admins(
                        f"<b>{title}</b>: за один проход появилось больше "
                        f"{config.MAX_NEW_PER_SCAN} «новых» заданий. Возможно, банк переразметили.\n"
                        f"/approve_{subject} — разослать, /skip_{subject} — пропустить"
                    )
                else:
                    n = deliver(subject, res.new) if res.new else 0
                    lines.append(f"{title}: всего {res.total}, новых {n}")
                db.set(f"last_scan_{subject}", dt.datetime.now().strftime("%d.%m %H:%M"))
        finally:
            renderer.close()
        db.set("last_scan", dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
        return "\n".join(lines)


def scheduler() -> None:
    period = config.SCAN_EVERY_HOURS * 3600
    while True:
        try:
            report = run_scan()
            log.info("скан завершён:\n%s", report)
        except Exception:
            log.exception("скан упал")
        scan_now.wait(timeout=period)
        scan_now.clear()


# ---------- команды ----------
def subjects_kb(chat_id: int) -> dict:
    mine = db.user_subjects(chat_id)
    rows = [[{
        "text": ("● " if s in mine else "○ ") + v["title"],
        "callback_data": f"t:{s}",
    }] for s, v in config.SUBJECTS.items()]
    return {"inline_keyboard": rows}


START = (
    "Слежу за открытым банком заданий ЕГЭ на сайте ФИПИ и присылаю новые задания "
    "карточками — условие и рисунки один в один, как в банке.\n\n"
    "Отметь предметы (● — включено):"
)


def status_text() -> str:
    lines = [f"Последняя проверка: {db.get('last_scan', 'ещё не было')}"]
    for s, v in config.SUBJECTS.items():
        lines.append(f"{v['title']}: {db.count(s)} в базе, проверено {db.get('last_scan_' + s, '—')}")
    lines.append(f"Подписчиков: {db.users_total()}")
    return "\n".join(lines)


def handle_message(msg: dict) -> None:
    chat = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0].lower() if text else ""
    is_admin = msg.get("from", {}).get("id") in config.ADMIN_IDS

    if cmd in ("/start", "/subjects"):
        tg.send(chat, START, subjects_kb(chat))
    elif cmd == "/status":
        tg.send(chat, status_text())
    elif cmd == "/help":
        tg.send(chat, "/subjects — выбрать предметы\n/status — когда последний раз проверял банк")
    elif is_admin and cmd == "/scan":
        if scan_lock.locked():
            tg.send(chat, "Проверка уже идёт.")
        else:
            tg.send(chat, "Запускаю проверку, это займёт время.")
            scan_now.set()
    elif is_admin and cmd.startswith(("/approve_", "/skip_")):
        action, subject = cmd[1:].split("_", 1)
        if subject not in config.SUBJECTS:
            return
        pend = db.pending(subject)
        if action == "approve":
            n = deliver(subject, pend)
            tg.send(chat, f"Разослал {n}.")
        else:
            db.mark_posted(subject, pend)
            tg.send(chat, f"Пропустил {len(pend)}.")


def handle_callback(cb: dict) -> None:
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    chat = msg.get("chat", {}).get("id")
    if not chat or not data.startswith("t:"):
        return tg.answer_cb(cb["id"])
    s = data[2:]
    mine = db.user_subjects(chat)
    mine ^= {s} if s in config.SUBJECTS else set()
    db.set_user_subjects(chat, mine)
    tg.edit_kb(chat, msg["message_id"], subjects_kb(chat))
    tg.answer_cb(cb["id"], "Сохранено")


def polling() -> None:
    offset = 0
    tg.call("setMyCommands", {"commands": [
        {"command": "subjects", "description": "Выбрать предметы"},
        {"command": "status", "description": "Когда проверял банк"},
    ]})
    while True:
        try:
            updates = tg.call("getUpdates", {"offset": offset, "timeout": 30,
                                             "allowed_updates": ["message", "callback_query"]},
                              timeout=40)
        except Exception:
            log.exception("getUpdates")
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                if "message" in u:
                    handle_message(u["message"])
                elif "callback_query" in u:
                    handle_callback(u["callback_query"])
            except Exception:
                log.exception("обработка апдейта")


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN в .env")
    threading.Thread(target=scheduler, daemon=True, name="scanner").start()
    polling()


if __name__ == "__main__":
    main()
