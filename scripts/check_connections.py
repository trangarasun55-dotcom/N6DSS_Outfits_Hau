"""Kiểm tra nhanh các kết nối: API, cơ sở dữ liệu đăng nhập, Gemini và thời tiết.

Chạy khi API đang hoạt động:  python scripts/check_connections.py
Không in API key. Thoát với mã 0 nếu mọi kiểm tra bắt buộc đều đạt.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
for _key, _value in dotenv_values(ROOT / ".env").items():
    if _key in {"GEMINI_API_KEY", "GEMINI_MODEL"} and _value and _value.strip():
        os.environ[_key] = _value.strip()
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
FAILED = False


def report(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
    global FAILED
    mark = "OK  " if ok else ("LỖI" if required else "CẢNH BÁO")
    print(f"[{mark}] {name}" + (f" - {detail}" if detail else ""))
    if required and not ok:
        FAILED = True


def check_api() -> None:
    try:
        data = requests.get(f"{API_URL}/health", timeout=5).json()
        report("API FastAPI", data.get("status") == "ok", f"{API_URL}, model {data.get('model_version')}")
        report(
            "Cấu hình Gemini",
            bool(data.get("gemini_configured")),
            f"model {data.get('gemini_model')}" if data.get("gemini_configured") else "chưa có GEMINI_API_KEY",
            required=False,
        )
    except requests.RequestException as exc:
        report("API FastAPI", False, f"không kết nối được {API_URL} ({type(exc).__name__}); hãy chạy python run_dev.py")


def check_admin_login() -> None:
    email, password = os.environ.get("ADMIN_EMAIL", ""), os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        report("Đăng nhập admin", False, "chưa đặt ADMIN_EMAIL/ADMIN_PASSWORD trong .env", required=False)
        return
    try:
        response = requests.post(f"{API_URL}/auth/login", json={"email": email, "password": password}, timeout=10)
        report("Đăng nhập admin", response.status_code == 200, f"HTTP {response.status_code}")
    except requests.RequestException as exc:
        report("Đăng nhập admin", False, type(exc).__name__)


def check_gemini() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        report("Gemini (gọi thật)", False, "bỏ qua vì chưa có GEMINI_API_KEY", required=False)
        return
    model = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.1-flash-lite"
    try:
        from google import genai
        from google.genai import types

        with genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=15_000)) as client:
            reply = client.models.generate_content(model=model, contents="Trả lời đúng một từ: OK")
        report("Gemini (gọi thật)", bool(reply.text), f"model {model}", required=False)
    except Exception as exc:  # noqa: BLE001 - chẩn đoán: in loại lỗi, không in khóa
        code = getattr(exc, "code", "")
        report("Gemini (gọi thật)", False, f"{type(exc).__name__} {code}; kiểm tra khóa, tên model, hạn mức, mạng", required=False)


def check_weather() -> None:
    try:
        response = requests.get(f"{API_URL}/weather", params={"city": "Hà Nội"}, timeout=20)
        report("Thời tiết Open-Meteo", response.status_code == 200, f"HTTP {response.status_code}", required=False)
    except requests.RequestException as exc:
        report("Thời tiết Open-Meteo", False, type(exc).__name__, required=False)


if __name__ == "__main__":
    check_api()
    if not FAILED:
        check_admin_login()
        check_weather()
    check_gemini()
    sys.exit(1 if FAILED else 0)
