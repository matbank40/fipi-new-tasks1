"""Минимальный клиент Telegram Bot API на requests (без лишних зависимостей)."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import requests

log = logging.getLogger("tg")


class Blocked(Exception):
    """Пользователь заблокировал бота / чат удалён."""


class TG:
    def __init__(self, token: str, api_base: str = "https://api.telegram.org",
                 proxy: str | None = None) -> None:
        self.base = f"{api_base}/bot{token}/"
        self.s = requests.Session()
        if proxy:
            self.s.proxies = {"http": proxy, "https": proxy}
        self._lock = threading.Lock()
        self._last = 0.0

    def call(self, method: str, data: dict | None = None, files: dict | None = None,
             timeout: int = 60):
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                for k, v in (data or {}).items() if v is not None}
        for attempt in range(5):
            if method != "getUpdates":
                with self._lock:                       # ~20 сообщений/с на всё
                    wait = 0.05 - (time.time() - self._last)
                    if wait > 0:
                        time.sleep(wait)
                    self._last = time.time()
            try:
                r = self.s.post(self.base + method, data=data, files=files, timeout=timeout)
                j = r.json()
            except (requests.RequestException, ValueError) as e:
                log.warning("%s: %s", method, e)
                time.sleep(3 * (attempt + 1))
                continue
            if j.get("ok"):
                return j["result"]
            code, desc = j.get("error_code"), j.get("description", "")
            if code == 429:
                time.sleep(j.get("parameters", {}).get("retry_after", 5) + 1)
                continue
            if code == 403 or "chat not found" in desc:
                raise Blocked(desc)
            raise RuntimeError(f"{method}: {code} {desc}")
        raise RuntimeError(f"{method}: не удалось после повторов")

    # удобные обёртки
    def send(self, chat_id, text, kb=None, **kw):
        return self.call("sendMessage", {
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True, "reply_markup": kb, **kw})

    def edit_kb(self, chat_id, message_id, kb):
        try:
            self.call("editMessageReplyMarkup",
                      {"chat_id": chat_id, "message_id": message_id, "reply_markup": kb})
        except RuntimeError:
            pass

    def answer_cb(self, cb_id, text=None):
        try:
            self.call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})
        except RuntimeError:
            pass

    def photo(self, chat_id, photo, caption, kb=None):
        """photo — Path к файлу или file_id (str). Возвращает file_id для повторной отправки."""
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML", "reply_markup": kb}
        if isinstance(photo, str):
            data["photo"] = photo
            res = self.call("sendPhoto", data)
        else:
            p = Path(photo)  # байты целиком, чтобы повтор запроса не слал пустой файл
            res = self.call("sendPhoto", data, files={"photo": (p.name, p.read_bytes())})
        return res["photo"][-1]["file_id"]

    def document(self, chat_id, doc, caption=None, kb=None, filename=None):
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML", "reply_markup": kb}
        if isinstance(doc, str):
            data["document"] = doc
            res = self.call("sendDocument", data)
        elif isinstance(doc, (bytes, bytearray)):
            res = self.call("sendDocument", data, files={"document": (filename or "file", doc)})
        else:
            p = Path(doc)
            res = self.call("sendDocument", data, files={"document": (filename or p.name, p.read_bytes())})
        return res["document"]["file_id"]
