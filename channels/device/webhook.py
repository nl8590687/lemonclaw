# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
WebHook
"""
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable

from config import get_global_config


_webhook_callback_function: Callable[[str, list[str] | None, dict[str, object]], str] | None = None
_webhook_auth_token: str|None = None
_webhook_rate_limiter: TokenBucket|None = None


class TokenBucket:
    """
    令牌桶限流器

    以分钟为粒度进行限制
    """

    def __init__(self, max_tokens: int = 10):
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def take(self) -> bool:
        """
        尝试获取一个令牌

        Returns:
            bool: 是否成功获取令牌（True=允许通过）
        """
        with self._lock:
            now = time.time()
            elapsed = now - self.last_refill

            # 每分钟重新填充
            if elapsed >= 60:
                self.tokens = self.max_tokens
                self.last_refill = now

            if self.tokens > 0:
                self.tokens -= 1
                return True
            return False

    def set_max_tokens(self, max_tokens: int):
        """设置最大令牌数"""
        with self._lock:
            self.max_tokens = max_tokens
            # 确保当前令牌不超过最大值
            if self.tokens > max_tokens:
                self.tokens = max_tokens


class WebhookHandler(BaseHTTPRequestHandler):
    """WebHook HTTP 请求处理器"""

    def _send_json_error(self, status_code: int, message: str):
        """发送 JSON 错误响应"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

    def do_POST(self):
        """处理 POST 请求"""
        try:
            # 1. 检查频率限制
            if _webhook_rate_limiter and not _webhook_rate_limiter.take():
                self._send_json_error(429, "Too many requests")
                return

            # 2. 检查身份验证
            if _webhook_auth_token:
                auth_header = self.headers.get('X-Auth-Token')
                if not auth_header or auth_header != _webhook_auth_token:
                    self._send_json_error(401, "Unauthorized")
                    return

            # 3. 读取内容
            content_length = int(self.headers.get('Content-Length', 0))
            # 防止超大请求
            if content_length > 10 * 1024 * 1024:  # 10MB 限制
                self._send_json_error(413, "Payload too large")
                return

            body = self.rfile.read(content_length) if content_length else b''

            # 4. 解析路径获取 hook 名称
            path = self.path.lstrip('/') or 'default'

            # 5. 解析 JSON
            try:
                payload = json.loads(body.decode('utf-8')) if body else {}
            except json.JSONDecodeError:
                payload = {"text": body.decode('utf-8', errors='replace')}

            # 6. 发布事件
            ctx = {
                "path": path,
                "headers": dict(self.headers),
            }
            if _webhook_callback_function:
                _webhook_callback_function(payload.get("text"), payload.get("img_urls"), ctx)

            # 7. 响应
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

        except Exception as e:
            self._send_json_error(500, str(e))

    def do_GET(self):
        """健康检查端点"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "running"}')

    def log_message(self, format, *args):
        """重写日志避免污染控制台"""
        pass


class WebhookServer:
    """
    WebHook HTTP 服务器

    接收 HTTP POST 请求并转换为事件总线消息
    支持身份验证和频率限制
    """

    def __init__(self, write_callback: Callable[[str, list[str] | None, dict[str, object]], str] | None):
        config = get_global_config()
        self.host = config.WEBHOOK_HOST
        self.port = config.WEBHOOK_PORT
        self.write_callback: Callable[[str, list[str] | None, dict[str, object]], str] | None = write_callback
        self.auth_token = config.WEBHOOK_AUTH_TOKEN
        self.rate_limit_per_minute = config.WEBHOOK_RATE_LIMIT_RPM
        self._server: HTTPServer|None = None
        self._thread: threading.Thread|None = None
        self._running = False

    def start(self):
        """启动服务器"""
        if self._running:
            return

        self._running = True

        # 设置全局引用供 handler 使用
        global _webhook_callback_function, _webhook_auth_token, _webhook_rate_limiter
        _webhook_callback_function = self.write_callback
        _webhook_auth_token = self.auth_token
        _webhook_rate_limiter = TokenBucket(self.rate_limit_per_minute)

        # 创建服务器
        self._server = HTTPServer((self.host, self.port), WebhookHandler)

        # 启动线程
        self._thread = threading.Thread(target=self._serve, daemon=True, name="webhook")
        self._thread.start()

    def stop(self):
        """停止服务器"""
        if not self._running:
            return

        self._running = False
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _serve(self):
        """服务器主循环"""
        if self._server:
            self._server.serve_forever()

    @property
    def url(self) -> str:
        """获取服务器 URL"""
        return f"http://{self.host}:{self.port}"
