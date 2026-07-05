#!/usr/bin/env python3
"""
Deepgram TTS Proxy for ClawPuter Cardputer
============================================
Accepts OpenAI-compatible TTS requests (POST /v1/audio/speech)
and proxies them to Deepgram TTS API, returning PCM audio.

The Cardputer sends:
    POST /v1/audio/speech
    {"text":"Hello","voice":"nova"}

This script proxies to:
    POST https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=linear16&sample_rate=8000
    {"text":"Hello"}
"""

import os
import io
import json
import struct
import logging
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="[TTS] %(message)s")
log = logging.getLogger("tts-proxy")

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
LISTEN_HOST = os.environ.get("TTS_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("TTS_PORT", "8080"))

# Default Deepgram TTS voice — neutral English, works well for short AI responses
DEFAULT_VOICE = "aura-asteria-en"

# Deepgram TTS endpoint
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"

# Audio format: 8kHz 16-bit signed PCM (matches Cardputer expectations)
SAMPLE_RATE = 8000
ENCODING = "linear16"
CONTAINER = "none"  # raw PCM


class TTSProxyHandler(BaseHTTPRequestHandler):
    """Handle OpenAI-compatible TTS requests and proxy to Deepgram."""

    def do_POST(self):
        log.info(f"Request: {self.path}")

        if self.path != "/v1/audio/speech":
            self.send_error(404, "Not Found")
            return

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            text = data.get("text", "").strip()
            voice = data.get("voice", DEFAULT_VOICE)
        except (json.JSONDecodeError, KeyError) as e:
            log.error(f"Invalid JSON: {e}")
            self.send_error(400, f"Invalid JSON: {e}")
            return

        if not text:
            log.error("Empty text")
            self.send_error(400, "Empty text")
            return

        if not DEEPGRAM_API_KEY:
            log.error("DEEPGRAM_API_KEY not set")
            self.send_error(500, "DEEPGRAM_API_KEY not configured")
            return

        log.info(f"TTS: text='{text[:60]}...' voice='{voice}'")

        # Build Deepgram TTS request
        dg_url = f"{DEEPGRAM_TTS_URL}?model={voice}&encoding={ENCODING}&sample_rate={SAMPLE_RATE}&container={CONTAINER}"
        dg_headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "application/json",
        }
        dg_body = json.dumps({"text": text}).encode("utf-8")

        try:
            req = urllib.request.Request(dg_url, data=dg_body, headers=dg_headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                pcm_data = resp.read()
        except urllib.error.HTTPError as e:
            log.error(f"Deepgram HTTP error: {e.code} {e.reason}")
            if e.code == 401:
                self.send_error(500, "DEEPGRAM_API_KEY is invalid or expired")
            else:
                self.send_error(502, f"Deepgram error: {e.code}")
            return
        except urllib.error.URLError as e:
            log.error(f"Deepgram connection error: {e.reason}")
            self.send_error(502, f"Deepgram connection failed: {e.reason}")
            return

        log.info(f"Deepgram returned {len(pcm_data)} PCM bytes ({len(pcm_data)//2} samples)")

        # Send response as PCM (raw 16-bit signed, 8kHz)
        self.send_response(200)
        self.send_header("Content-Type", "audio/L16")
        self.send_header("Content-Length", str(len(pcm_data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(pcm_data)

    def log_message(self, format, *args):
        log.info(format % args)


def main():
    global DEEPGRAM_API_KEY, LISTEN_HOST, LISTEN_PORT
    
    parser = argparse.ArgumentParser(description="Deepgram TTS Proxy for ClawPuter")
    parser.add_argument("--host", default=LISTEN_HOST, help=f"Listen host (default: {LISTEN_HOST})")
    parser.add_argument("--port", type=int, default=LISTEN_PORT, help=f"Listen port (default: {LISTEN_PORT})")
    parser.add_argument("--deepgram-key", help="Deepgram API key (or DEEPGRAM_API_KEY env)")
    args = parser.parse_args()

    if args.deepgram_key:
        DEEPGRAM_API_KEY = args.deepgram_key
    LISTEN_HOST = args.host
    LISTEN_PORT = args.port

    if not DEEPGRAM_API_KEY:
        log.error("❌ DEEPGRAM_API_KEY not set! Use --deepgram-key or DEEPGRAM_API_KEY env var")
        exit(1)

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), TTSProxyHandler)
    log.info(f"🎤 Deepgram TTS Proxy listening on {LISTEN_HOST}:{LISTEN_PORT}")
    log.info(f"   API key: {DEEPGRAM_API_KEY[:6]}...{DEEPGRAM_API_KEY[-4:]}")
    log.info(f"   Endpoint: POST /v1/audio/speech (OpenAI-compatible)")
    log.info(f"   Backend: api.deepgram.com/v1/speak ({SAMPLE_RATE}Hz PCM)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
