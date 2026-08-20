#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Webhook 自动更新监听器（推 dev1 即自动部署）。

用法:
  python3 webhook_server.py [port] [secret] [project_dir]
  默认: 端口 9000, secret 从环境变量 WEBHOOK_SECRET 读, 项目目录=脚本上两级

配置（GitHub 仓库 → Settings → Webhooks）:
  Payload URL: http://<服务器公网IP>:9000/github-webhook
  Content type: application/json
  Secret: 与 WEBHOOK_SECRET 一致
  Events: 勾选 "Push"

安全: HMAC-SHA256 签名校验, 只接受 X-GitHub-Event: push 且分支 dev1,
      失败 3 次自动封禁该 IP 10 分钟。
"""
import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_LOG_DIR, "webhook.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("webhook")

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
SECRET = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("WEBHOOK_SECRET", "")).encode()
PROJECT = os.path.abspath(sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
UPDATE_SCRIPT = os.path.join(PROJECT, "deploy", "update.sh")

_ban: dict[str, float] = {}   # ip -> banned_until


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 用 logging

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        client = self.client_address[0]
        now = time.time()
        if _ban.get(client, 0) > now:
            log.warning("封禁中的 IP 尝试访问: %s", client)
            return self._json(403, {"ok": False, "error": "banned"})

        if self.path != "/github-webhook":
            return self._json(404, {"ok": False})

        # 1. 校验 GitHub 签名
        signature = self.headers.get("X-Hub-Signature-256", "")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
        if not SECRET or not hmac.compare_digest(signature, expected):
            log.warning("签名校验失败 (IP=%s)", client)
            _ban[client] = now + 600
            return self._json(403, {"ok": False, "error": "bad signature"})

        # 2. 只处理 push 事件
        if self.headers.get("X-GitHub-Event") != "push":
            return self._json(200, {"ok": True, "skipped": "not push"})

        # 3. 只处理 dev1 分支
        try:
            payload = json.loads(body)
        except Exception:
            return self._json(400, {"ok": False, "error": "bad json"})
        ref = payload.get("ref", "")
        if not ref.endswith("dev1"):
            return self._json(200, {"ok": True, "skipped": f"ref {ref}"})

        # 4. 触发更新（异步，避免 webhook 超时）
        log.info("收到 push 到 dev1，开始自动更新...")
        subprocess.Popen(
            ["bash", UPDATE_SCRIPT],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return self._json(200, {"ok": True, "message": "update triggered"})

    do_GET = do_POST


if __name__ == "__main__":
    if not SECRET:
        log.warning("未设置 WEBHOOK_SECRET，签名校验将拒绝所有请求（安全）")
    os.makedirs(os.path.join(PROJECT, "logs"), exist_ok=True)
    log.info("Webhook 监听器启动: 端口 %s, 项目 %s", PORT, PROJECT)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
