#!/usr/bin/env python3
"""
DeepSeek API Proxy for ClawPuter Cardputer
===========================================
Прокси для DeepSeek V4 Flash API.
Cardputer стучится на Pi4 (192.168.1.72:8000),
а Pi4 проксирует запросы к api.deepseek.com.

Решает проблему:
- CloudFront может не открываться с Cardputer напрямую
- TLS без сертификата на ESP32-S3 даёт ошибки
- DNS может не резолвиться на Cardputer
"""

import os
import json
import logging
import argparse
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format="[DS-PROXY] %(message)s")
log = logging.getLogger("deepseek-proxy")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LISTEN_HOST = os.environ.get("DS_PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("DS_PROXY_PORT", "8000"))

DEEPSEEK_BASE = "https://api.deepseek.com"


class DeepSeekProxyHandler(BaseHTTPRequestHandler):
    """Проксирует OpenAI-совместимые запросы к DeepSeek API."""

    def do_POST(self):
        log.info(f"➡️ {self.path}")

        if self.path != "/v1/chat/completions":
            self.send_error(404, "DeepSeek proxy: use /v1/chat/completions")
            return

        if not DEEPSEEK_API_KEY:
            log.error("DEEPSEEK_API_KEY not set")
            self.send_error(500, "DEEPSEEK_API_KEY not configured")
            return

        # Читаем тело запроса
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Добавляем API ключ DeepSeek
        ds_url = f"{DEEPSEEK_BASE}{self.path}"
        ds_headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        log.info(f"   → DeepSeek: {len(body)} bytes")

        try:
            req = urllib.request.Request(ds_url, data=body, headers=ds_headers, method="POST")
            resp = urllib.request.urlopen(req, timeout=60)

            # Проксируем ответ обратно
            self.send_response(resp.status)
            content_type = resp.headers.get("Content-Type", "")
            self.send_header("Content-Type", content_type)
            self.send_header("Connection", "close")  # всегда close — Cardputer так ждёт
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            # Стримим ответ (SSE или plain JSON)
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

            log.info("   ✅ Done")

        except urllib.error.HTTPError as e:
            log.error(f"   ❌ DeepSeek HTTP {e.code}: {e.reason}")
            self.send_error(502, f"DeepSeek error: {e.code}")
        except urllib.error.URLError as e:
            log.error(f"   ❌ DeepSeek connection: {e.reason}")
            self.send_error(502, f"DeepSeek connection: {e.reason}")
        except Exception as e:
            log.error(f"   ❌ {e}")
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        log.info(format % args)


def main():
    global DEEPSEEK_API_KEY, LISTEN_HOST, LISTEN_PORT

    parser = argparse.ArgumentParser(description="DeepSeek Proxy for ClawPuter")
    parser.add_argument("--host", default=LISTEN_HOST)
    parser.add_argument("--port", type=int, default=LISTEN_PORT)
    parser.add_argument("--deepseek-key", help="DeepSeek API key")
    args = parser.parse_args()

    if args.deepseek_key:
        DEEPSEEK_API_KEY = args.deepseek_key
    if not DEEPSEEK_API_KEY:
        log.error("❌ DEEPSEEK_API_KEY not set!")
        exit(1)

    LISTEN_HOST = args.host
    LISTEN_PORT = args.port

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), DeepSeekProxyHandler)
    log.info(f"🪄 DeepSeek Proxy: {LISTEN_HOST}:{LISTEN_PORT}")
    log.info(f"   → Backend: {DEEPSEEK_BASE}")
    log.info(f"   → Use in Cardputer .env: DS_PROXY_HOST={LISTEN_HOST}, DS_PROXY_PORT={LISTEN_PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutdown")
        server.server_close()


if __name__ == "__main__":
    main()
