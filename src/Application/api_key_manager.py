"""Secure local Google API key storage, validation, and request failover."""

import asyncio
import base64
import ctypes
import json
import os
import threading
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import aiohttp


MAX_KEYS = 5
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class KeyStoreError(ValueError):
    pass


class NoActiveKeysError(RuntimeError):
    pass


class GoogleAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("تشفير المفاتيح مدعوم على Windows فقط")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "Evro API Keys", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def _unprotect(data: bytes) -> bytes:
    source, source_buffer = _blob(data)
    output = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error", payload)
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return fallback


class APIKeyManager:
    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._lock = threading.RLock()
        self._cursor = 0

    def _load(self) -> list[dict[str, Any]]:
        if not self.store_path.exists():
            return []
        try:
            encrypted = base64.b64decode(self.store_path.read_bytes())
            data = json.loads(_unprotect(encrypted).decode("utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            raise KeyStoreError(f"تعذر قراءة مخزن المفاتيح المشفر: {exc}") from exc

    def _save(self, keys: list[dict[str, Any]]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(keys, ensure_ascii=False).encode("utf-8")
        temporary = self.store_path.with_suffix(".tmp")
        temporary.write_bytes(base64.b64encode(_protect(payload)))
        os.replace(temporary, self.store_path)

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        value = item["key"]
        return {
            "id": item["id"],
            "name": item["name"],
            "key": value,
            "masked_key": f"{value[:6]}...{value[-4:]}" if len(value) > 12 else "********",
            "enabled": item["enabled"],
            "priority": item["priority"],
            "last_status": item.get("last_status", "untested"),
            "last_tested_at": item.get("last_tested_at"),
            "last_error": item.get("last_error"),
        }

    def list_keys(self, reveal: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(self._load(), key=lambda item: item["priority"])
            public = [self._public(item) for item in items]
            if not reveal:
                for item in public:
                    item.pop("key", None)
            return public

    def add_key(self, name: str, key: str, enabled: bool = True) -> dict[str, Any]:
        name, key = name.strip(), key.strip()
        if not name or not key:
            raise KeyStoreError("اسم المفتاح وقيمته مطلوبان")
        with self._lock:
            keys = self._load()
            if len(keys) >= MAX_KEYS:
                raise KeyStoreError("الحد الأقصى هو خمسة مفاتيح")
            if any(item["key"] == key for item in keys):
                raise KeyStoreError("هذا المفتاح مضاف بالفعل")
            item = {
                "id": uuid.uuid4().hex,
                "name": name,
                "key": key,
                "enabled": enabled,
                "priority": len(keys) + 1,
                "last_status": "untested",
                "last_tested_at": None,
                "last_error": None,
            }
            keys.append(item)
            self._save(keys)
            return self._public(item)

    def update_key(
        self, key_id: str, name: Optional[str] = None, key: Optional[str] = None,
        enabled: Optional[bool] = None, priority: Optional[int] = None,
    ) -> dict[str, Any]:
        with self._lock:
            keys = self._load()
            item = next((entry for entry in keys if entry["id"] == key_id), None)
            if not item:
                raise KeyError(key_id)
            if name is not None:
                if not name.strip():
                    raise KeyStoreError("اسم المفتاح مطلوب")
                item["name"] = name.strip()
            if key is not None:
                if not key.strip():
                    raise KeyStoreError("قيمة المفتاح مطلوبة")
                if any(entry["id"] != key_id and entry["key"] == key.strip() for entry in keys):
                    raise KeyStoreError("هذا المفتاح مضاف بالفعل")
                item["key"] = key.strip()
                item.update(last_status="untested", last_tested_at=None, last_error=None)
            if enabled is not None:
                item["enabled"] = enabled
            if priority is not None:
                target = max(1, min(int(priority), len(keys)))
                keys.remove(item)
                keys.insert(target - 1, item)
            for index, entry in enumerate(keys, 1):
                entry["priority"] = index
            self._save(keys)
            return self._public(item)

    def delete_key(self, key_id: str) -> None:
        with self._lock:
            keys = self._load()
            remaining = [item for item in keys if item["id"] != key_id]
            if len(remaining) == len(keys):
                raise KeyError(key_id)
            for index, item in enumerate(remaining, 1):
                item["priority"] = index
            self._save(remaining)

    def _set_test_result(self, key_id: str, valid: bool, error: Optional[str]) -> None:
        with self._lock:
            keys = self._load()
            item = next((entry for entry in keys if entry["id"] == key_id), None)
            if item:
                item["last_status"] = "valid" if valid else "invalid"
                item["last_tested_at"] = _now()
                item["last_error"] = error
                self._save(keys)

    async def test_key(self, key_id: str) -> dict[str, Any]:
        with self._lock:
            item = next((entry for entry in self._load() if entry["id"] == key_id), None)
        if not item:
            raise KeyError(key_id)
        timeout = aiohttp.ClientTimeout(total=12)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(GOOGLE_MODELS_URL, params={"key": item["key"]}) as response:
                    payload = await response.json(content_type=None)
                    if response.status == 200:
                        self._set_test_result(key_id, True, None)
                        return {"valid": True, "status": 200, "message": "المفتاح صالح والاتصال بـ Google ناجح"}
                    message = _error_message(payload, f"Google API أعاد HTTP {response.status}")
                    self._set_test_result(key_id, False, message)
                    return {"valid": False, "status": response.status, "message": message}
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            message = f"تعذر الاتصال بخدمة Google: {exc}"
            self._set_test_result(key_id, False, message)
            return {"valid": False, "status": 0, "message": message}

    async def test_all(self) -> list[dict[str, Any]]:
        ids = [item["id"] for item in self.list_keys(reveal=False)]
        return await asyncio.gather(*(self.test_key(key_id) for key_id in ids))

    def _active_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(
                (item for item in self._load() if item["enabled"]),
                key=lambda item: item["priority"],
            )

    async def request_with_failover(
        self, operation: Callable[[str], Awaitable[Any]], strategy: str = "round_robin"
    ) -> Any:
        keys = self._active_keys()
        if not keys:
            raise NoActiveKeysError("لا توجد مفاتيح Google مفعلة")
        with self._lock:
            start = self._cursor % len(keys) if strategy == "round_robin" else 0
            if strategy == "round_robin":
                self._cursor = (self._cursor + 1) % len(keys)
        ordered = keys[start:] + keys[:start]
        errors = []
        for item in ordered:
            try:
                return await operation(item["key"])
            except GoogleAPIError as exc:
                errors.append(f"{item['name']}: HTTP {exc.status}")
                if exc.status not in RETRYABLE_STATUSES:
                    raise
        raise GoogleAPIError(429, "نفدت المفاتيح المتاحة: " + "، ".join(errors))
