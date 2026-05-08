#!/usr/bin/env python3
"""Local CTF Range Server for AttackAgent testing with real model calls.

Runs a self-contained CTF platform that implements the CompetitionProvider HTTP
API (`LocalHTTPCompetitionProvider`-compatible) while also serving the vulnerable
challenge endpoints on the same port.

Usage:
  python scripts/local_range.py                  # default port 8484
  python scripts/local_range.py --port 9999      # custom port
  python scripts/local_range.py --port 8484 --no-prompt  # auto-exit

Then run AttackAgent against it:
  python -m attack_agent --provider-url http://127.0.0.1:8484 --model openai

Challenges (4 total, 2 easy + 2 medium):
  web-auth-easy       Login Portal        — session-materialize + http-request
  web-render-easy     Hidden Comments     — browser-inspect (comments extraction)
  web-encoding-medium Base64 Cookie       — http-request + code-sandbox (base64)
  web-chain-medium    Multi-Step API      — http-request chain + structured-parse
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import sys
import time
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


# ── Challenge Definitions ──────────────────────────────────────────────

def _build_challenge_defs(port: int) -> list[dict[str, Any]]:
    base = f"http://127.0.0.1:{port}"
    return [
        {
            "id": "web-auth-easy",
            "name": "Login Portal",
            "category": "web",
            "difficulty": "easy",
            "target": f"{base}/challenge/web-auth-easy",
            "description": (
                "一个简单的Web登录页面，管理员面板隐藏在认证之后。"
                "你可以通过登录表单获取管理员权限。"
            ),
            "flag_pattern": r"flag\{[^}]+\}",
            "metadata": {
                "flag": "flag{login_portal_cracked_001}",
                "hint": "尝试常见的默认凭据组合，例如 admin/admin123",
                "hint_budget": 2,
                "signals": ["login", "auth", "admin", "credential", "session", "password"],
                "login_url": f"{base}/challenge/web-auth-easy/login",
                "credentials": {"username": "admin", "password": "admin123"},
                "privileged_paths": ["admin"],
            },
        },
        {
            "id": "web-render-easy",
            "name": "Hidden Comments",
            "category": "web",
            "difficulty": "easy",
            "target": f"{base}/challenge/web-render-easy",
            "description": (
                "一个看似简单的信息展示页面，表面上只有一段普通的文字。"
                "仔细检查页面的每个角落，有些东西被刻意隐藏了。"
            ),
            "flag_pattern": r"flag\{[^}]+\}",
            "metadata": {
                "flag": "flag{hidden_in_comments_042}",
                "hint": "查看页面源代码或使用浏览器检查功能",
                "hint_budget": 2,
                "signals": ["render", "browser", "comment", "html", "hidden", "source"],
                "requires_browser": True,
            },
        },
        {
            "id": "web-encoding-medium",
            "name": "Base64 Cookie",
            "category": "web",
            "difficulty": "medium",
            "target": f"{base}/challenge/web-encoding-medium",
            "description": (
                "网站设置了一个神秘的 Cookie，其中包含一个 secret 字段。"
                "它的值看起来经过了某种编码。也许你可以使用代码沙盒来解码它，找到隐藏在其中的 flag。"
            ),
            "flag_pattern": r"flag\{[^}]+\}",
            "metadata": {
                "flag": "flag{base64_cookie_472}",
                "hint": "Cookie中的secret值使用了Base64编码，用python的base64.b64decode()可以解码",
                "hint_budget": 2,
                "signals": ["cookie", "base64", "encode", "decode", "secret", "hidden"],
            },
        },
        {
            "id": "web-chain-medium",
            "name": "Multi-Step API",
            "category": "web",
            "difficulty": "medium",
            "target": f"{base}/challenge/web-chain-medium",
            "description": (
                "这个挑战需要多步操作才能获取 flag。"
                "从 /api/step1 获取 token，然后使用该 token 访问 /api/step2 获取 flag。"
                "仔细阅读每个API返回的JSON指示。"
            ),
            "flag_pattern": r"flag\{[^}]+\}",
            "metadata": {
                "flag": "flag{multi_step_api_839}",
                "hint": "按API返回的next字段指示操作",
                "hint_budget": 2,
                "signals": ["api", "token", "chain", "multi-step", "json", "rest"],
                "login_url": f"{base}/challenge/web-chain-medium/api/step1",
                "api_endpoints": ["api/step1", "api/step2"],
                "token_chain": {"extract_field": "token", "inject_as": "query.token"},
            },
        },
    ]


# ── In-Memory State ────────────────────────────────────────────────────

class RangeState:
    """Per-instance session state and challenge tracking."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.challenges: dict[str, dict[str, Any]] = {
            c["id"]: c for c in _build_challenge_defs(port)
        }
        self.instances: dict[str, dict[str, Any]] = {}
        self.hint_budgets: dict[str, int] = {
            cid: int(c["metadata"].get("hint_budget", 2))
            for cid, c in self.challenges.items()
        }
        # Session tokens for login-based challenges
        self.sessions: dict[str, str] = {}  # token → username
        # Per-challenge state (e.g. generated API tokens)
        self.challenge_state: dict[str, dict[str, Any]] = {
            "web-chain-medium": {"api_token": secrets.token_hex(4)},
        }


# ── Helpers ────────────────────────────────────────────────────────────

def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _parse_cookies(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header:
        return {}
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    return {key: morsel.value for key, morsel in cookie.items()}


def _html_response(handler: BaseHTTPRequestHandler, status: int, html: str,
                   extra_headers: dict[str, str] | None = None) -> None:
    data = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    if extra_headers:
        for key, value in extra_headers.items():
            handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(data)


def _redirect(handler: BaseHTTPRequestHandler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.end_headers()


# ── Challenge Page Handlers ────────────────────────────────────────────

class ChallengePages:
    """Serve the vulnerable challenge pages."""

    @staticmethod
    def _resolve(state: RangeState, path: str) -> tuple[str, str, str] | None:
        """Parse /challenge/{challenge_id}/rest into (challenge_id, rest_path, method_info)."""
        if not path.startswith("/challenge/"):
            return None
        rest = path[len("/challenge/"):]
        if "/" in rest:
            challenge_id, subpath = rest.split("/", 1)
        else:
            challenge_id, subpath = rest, ""
        if challenge_id not in state.challenges:
            return None
        return challenge_id, subpath, ""

    @staticmethod
    def handle_get(state: RangeState, path: str, handler: BaseHTTPRequestHandler) -> bool:
        resolved = ChallengePages._resolve(state, path)
        if resolved is None:
            return False
        challenge_id, subpath, _ = resolved
        cookies = _parse_cookies(handler)

        dispatch = {
            "web-auth-easy": ChallengePages._handle_auth_easy,
            "web-render-easy": ChallengePages._handle_render_easy,
            "web-encoding-medium": ChallengePages._handle_encoding_medium,
            "web-chain-medium": ChallengePages._handle_chain_medium,
        }
        page_handler = dispatch.get(challenge_id)
        if page_handler:
            return page_handler(state, subpath, handler, cookies)
        return False

    @staticmethod
    def handle_post(state: RangeState, path: str, handler: BaseHTTPRequestHandler) -> bool:
        resolved = ChallengePages._resolve(state, path)
        if resolved is None:
            return False
        challenge_id, subpath, _ = resolved
        cookies = _parse_cookies(handler)

        dispatch_post = {
            "web-auth-easy": ChallengePages._handle_auth_easy_post,
            "web-chain-medium": ChallengePages._handle_chain_medium_post,
        }
        post_handler = dispatch_post.get(challenge_id)
        if post_handler:
            return post_handler(state, subpath, handler, cookies)
        return False

    # ── web-auth-easy: Login Portal ──

    @staticmethod
    def _handle_auth_easy(state: RangeState, subpath: str,
                          handler: BaseHTTPRequestHandler,
                          cookies: dict[str, str]) -> bool:
        session_token = cookies.get("attackagent_session", "")

        if subpath in ("", "/"):
            _html_response(handler, 200, AUTH_EASY_HOME)
            return True

        if subpath in ("login", "login/"):
            _html_response(handler, 200, AUTH_EASY_LOGIN)
            return True

        if subpath in ("admin", "admin/"):
            if session_token and session_token in state.sessions:
                username = state.sessions[session_token]
                _html_response(handler, 200, AUTH_EASY_ADMIN.format(username=username))
            else:
                _html_response(handler, 403, AUTH_EASY_FORBIDDEN)
            return True

        return False

    @staticmethod
    def _handle_auth_easy_post(state: RangeState, subpath: str,
                               handler: BaseHTTPRequestHandler,
                               cookies: dict[str, str]) -> bool:
        if subpath not in ("login", "login/"):
            return False

        raw_len = int(handler.headers.get("Content-Length", "0"))
        raw = handler.rfile.read(raw_len)

        # Try JSON first, then form-encoded
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}

        username = str(body.get("username", ""))
        password = str(body.get("password", ""))

        if username == "admin" and password == "admin123":
            token = secrets.token_hex(16)
            state.sessions[token] = username
            _html_response(
                handler, 200, AUTH_EASY_LOGIN_OK,
                extra_headers={"Set-Cookie": f"attackagent_session={token}; Path=/challenge/web-auth-easy; HttpOnly"},
            )
        else:
            _html_response(handler, 401, AUTH_EASY_LOGIN_FAIL)
        return True

    # ── web-render-easy: Hidden Comments ──

    @staticmethod
    def _handle_render_easy(state: RangeState, subpath: str,
                            handler: BaseHTTPRequestHandler,
                            cookies: dict[str, str]) -> bool:
        _html_response(handler, 200, RENDER_EASY_PAGE)
        return True

    # ── web-encoding-medium: Base64 Cookie ──

    @staticmethod
    def _handle_encoding_medium(state: RangeState, subpath: str,
                                handler: BaseHTTPRequestHandler,
                                cookies: dict[str, str]) -> bool:
        encoded = base64.b64encode(b"flag{base64_cookie_472}").decode()
        _html_response(
            handler, 200, ENCODING_MEDIUM_PAGE,
            extra_headers={"Set-Cookie": f"secret={encoded}; Path=/challenge/web-encoding-medium; HttpOnly"},
        )
        return True

    # ── web-chain-medium: Multi-Step API ──

    @staticmethod
    def _handle_chain_medium(state: RangeState, subpath: str,
                             handler: BaseHTTPRequestHandler,
                             cookies: dict[str, str]) -> bool:
        base_target = f"http://127.0.0.1:{state.port}/challenge/web-chain-medium"

        if subpath in ("", "/"):
            html = CHAIN_MEDIUM_HOME.format(base_target=base_target)
            _html_response(handler, 200, html)
            return True

        if subpath in ("api/step1", "api/step1/"):
            token = state.challenge_state["web-chain-medium"]["api_token"]
            _json_response(handler, 200, {
                "message": "Step 1 complete. Here is your access token.",
                "token": token,
                "next": f"/api/step2?token={token}",
                "hint": "Make a GET request to the 'next' URL to retrieve the flag.",
            })
            return True

        if subpath.startswith("api/step2"):
            qs = parse_qs(urlparse(handler.path).query)
            req_token = qs.get("token", [""])[0]
            expected_token = state.challenge_state["web-chain-medium"]["api_token"]
            if req_token == expected_token:
                _json_response(handler, 200, {
                    "message": "Authentication successful!",
                    "flag": "flag{multi_step_api_839}",
                })
            else:
                _json_response(handler, 403, {
                    "error": "Invalid or missing token.",
                    "hint": "First call /api/step1 to get a valid token.",
                })
            return True

        return False

    @staticmethod
    def _handle_chain_medium_post(state: RangeState, subpath: str,
                                  handler: BaseHTTPRequestHandler,
                                  cookies: dict[str, str]) -> bool:
        # Treat POST the same as GET for the API endpoints
        return ChallengePages._handle_chain_medium(state, subpath, handler, cookies)


# ── Provider API Handlers ─────────────────────────────────────────────

class ProviderAPI:
    """Implement the CompetitionProvider REST API for LocalHTTPCompetitionProvider."""

    @staticmethod
    def list_challenges(state: RangeState, handler: BaseHTTPRequestHandler) -> None:
        items = list(state.challenges.values())
        _json_response(handler, 200, {"items": items})

    @staticmethod
    def start_challenge(state: RangeState, handler: BaseHTTPRequestHandler) -> None:
        body = _read_json_body(handler)
        challenge_id = body.get("challenge_id", "")
        if challenge_id not in state.challenges:
            _json_response(handler, 404, {"error": "challenge not found"})
            return

        challenge = state.challenges[challenge_id]
        instance_id = f"instance-{challenge_id}-{uuid.uuid4().hex[:8]}"
        instance = {
            "instance_id": instance_id,
            "challenge_id": challenge_id,
            "target": challenge["target"],
            "status": "running",
            "metadata": dict(challenge["metadata"]),
        }
        state.instances[instance_id] = instance
        _json_response(handler, 200, {"instance": instance})

    @staticmethod
    def submit_flag(state: RangeState, handler: BaseHTTPRequestHandler) -> None:
        body = _read_json_body(handler)
        instance_id = body.get("instance_id", "")
        flag = body.get("flag", "")

        instance = state.instances.get(instance_id)
        if instance is None:
            _json_response(handler, 404, {"accepted": False, "message": "instance not found", "status": "rejected"})
            return

        challenge_id = instance["challenge_id"]
        expected = state.challenges[challenge_id]["metadata"]["flag"]
        accepted = flag == expected
        _json_response(handler, 200, {
            "accepted": accepted,
            "message": "accepted" if accepted else "wrong flag",
            "status": "accepted" if accepted else "rejected",
        })

    @staticmethod
    def request_hint(state: RangeState, handler: BaseHTTPRequestHandler) -> None:
        body = _read_json_body(handler)
        challenge_id = body.get("challenge_id", "")
        instance_id = body.get("instance_id", "")

        if not challenge_id and instance_id:
            instance = state.instances.get(instance_id)
            if instance:
                challenge_id = instance["challenge_id"]

        if challenge_id not in state.challenges:
            _json_response(handler, 404, {"hint": "no hint", "remaining": 0})
            return

        remaining = max(0, state.hint_budgets.get(challenge_id, 0) - 1)
        state.hint_budgets[challenge_id] = remaining
        _json_response(handler, 200, {
            "hint": state.challenges[challenge_id]["metadata"].get("hint", "no hint"),
            "remaining": remaining,
        })

    @staticmethod
    def get_status(state: RangeState, instance_id: str, handler: BaseHTTPRequestHandler) -> None:
        instance = state.instances.get(instance_id)
        if instance is None:
            _json_response(handler, 404, {"status": "unknown"})
        else:
            _json_response(handler, 200, {"status": instance["status"]})


# ── HTML Templates ─────────────────────────────────────────────────────

AUTH_EASY_HOME = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Login Portal</title></head>
<body>
<h1>Welcome to Login Portal</h1>
<p>这是一个简单的Web应用，包含登录和管理功能。</p>
<nav>
  <a href="/challenge/web-auth-easy/login">登录</a> |
  <a href="/challenge/web-auth-easy/admin">管理面板</a>
</nav>
</body>
</html>"""

AUTH_EASY_LOGIN = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>登录 - Login Portal</title></head>
<body>
<h1>用户登录</h1>
<form action="/challenge/web-auth-easy/login" method="post">
  <label>用户名: <input type="text" name="username" placeholder="请输入用户名"></label><br>
  <label>密码: <input type="password" name="password" placeholder="请输入密码"></label><br>
  <button type="submit">登录</button>
</form>
<p>没有账号？尝试猜测管理员凭据。</p>
</body>
</html>"""

AUTH_EASY_LOGIN_OK = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>登录成功</title></head>
<body>
<h1>登录成功</h1>
<p>欢迎回来！你现在可以访问<a href="/challenge/web-auth-easy/admin">管理面板</a>。</p>
</body>
</html>"""

AUTH_EASY_LOGIN_FAIL = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>登录失败</title></head>
<body>
<h1>登录失败</h1>
<p>用户名或密码错误。请<a href="/challenge/web-auth-easy/login">重试</a>。</p>
</body>
</html>"""

AUTH_EASY_ADMIN = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>管理面板</title></head>
<body>
<h1>管理员控制台</h1>
<p>欢迎，{username}！</p>
<section>
  <h2>系统信息</h2>
  <ul>
    <li>服务器状态: 运行中</li>
    <li>在线用户: 1</li>
    <li>安全级别: 低</li>
  </ul>
</section>
<section>
  <h2>Flag</h2>
  <p>恭喜！flag 是: <code>flag{{login_portal_cracked_001}}</code></p>
</section>
</body>
</html>"""

AUTH_EASY_FORBIDDEN = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>403 Forbidden</title></head>
<body>
<h1>403 禁止访问</h1>
<p>你需要先<a href="/challenge/web-auth-easy/login">登录</a>才能访问管理面板。</p>
</body>
</html>"""

RENDER_EASY_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>信息安全公告</title></head>
<body>
<header>
  <h1>信息安全公告</h1>
  <p>发布日期：2025-01-15</p>
</header>
<main id="content">
  <article>
    <h2>关于近期安全事件的通报</h2>
    <p>近期发现部分系统存在弱口令漏洞，建议所有用户及时修改默认密码。</p>
    <p>系统管理员将在近期进行全面的安全审计工作。</p>
    <p>如有疑问，请联系IT安全团队。</p>
  </article>
  <aside>
    <h3>相关链接</h3>
    <ul>
      <li><a href="https://owasp.org">OWASP 安全指南</a></li>
      <li><a href="https://cve.mitre.org">CVE 漏洞数据库</a></li>
    </ul>
  </aside>
</main>
<footer>
  <p>&copy; 2025 Security Team</p>
  <!-- DEBUG: internal audit note — flag for testing: flag{hidden_in_comments_042} -->
  <!-- TODO: remove this comment before deploying to production -->
</footer>
</body>
</html>"""

ENCODING_MEDIUM_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Cookie 谜题</title></head>
<body>
<h1>Cookie 谜题</h1>
<p>欢迎来到 Cookie 谜题挑战。</p>
<p>我们为每位访客准备了一个特殊的 Cookie，其中包含一个 <strong>secret</strong> 字段。</p>
<p>secret 的值使用某种编码方式进行了混淆。解码它就能得到你想要的东西。</p>
<p>提示：检查 HTTP 响应头中 Set-Cookie 字段的 secret 值。</p>
</body>
</html>"""

CHAIN_MEDIUM_HOME = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Multi-Step API</title></head>
<body>
<h1>Multi-Step API 挑战</h1>
<p>这个挑战需要你按顺序调用API来获取flag。</p>
<p>可用的API端点：</p>
<ul>
  <li><code>GET {base_target}/api/step1</code> — 获取访问令牌</li>
  <li><code>GET {base_target}/api/step2?token=&lt;your_token&gt;</code> — 使用令牌获取flag</li>
</ul>
<p>注意：token 每次启动实例时都会重新生成。</p>
</body>
</html>"""


# ── Main Request Handler ───────────────────────────────────────────────

class RangeRequestHandler(BaseHTTPRequestHandler):
    """Route between CompetitionProvider API endpoints and challenge pages."""

    state: RangeState  # set by server factory

    # ── Path routing ──

    def _route(self) -> str:
        """Classify request as 'api', 'challenge', or 'not_found'."""
        p = urlparse(self.path).path

        # CompetitionProvider API endpoints (exact match)
        api_exact = {"/challenges", "/start_challenge", "/submit", "/hint"}
        if p in api_exact:
            return "api"

        # Status endpoint (prefix match)
        if p.startswith("/status/"):
            return "api"

        # Challenge pages (prefix match)
        if p.startswith("/challenge/"):
            return "challenge"

        # Root — show index
        if p == "/":
            return "index"

        return "not_found"

    # ── HTTP methods ──

    def do_GET(self) -> None:  # noqa: N802
        route = self._route()
        if route == "api":
            self._handle_api_get()
        elif route == "challenge":
            self._handle_challenge_get()
        elif route == "index":
            self._handle_index()
        else:
            self.send_error(404, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        route = self._route()
        if route == "api":
            self._handle_api_post()
        elif route == "challenge":
            self._handle_challenge_post()
        else:
            self.send_error(404, "Not Found")

    def do_HEAD(self) -> None:  # noqa: N802
        route = self._route()
        if route in ("api", "challenge", "index"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if route == "api" else "text/html")
            self.end_headers()
        else:
            self.send_error(404, "Not Found")

    # ── API handlers ──

    def _handle_api_get(self) -> None:
        p = urlparse(self.path).path
        if p == "/challenges":
            ProviderAPI.list_challenges(self.state, self)
        elif p.startswith("/status/"):
            instance_id = p[len("/status/"):]
            ProviderAPI.get_status(self.state, instance_id, self)
        else:
            self.send_error(405, "Method Not Allowed")

    def _handle_api_post(self) -> None:
        p = urlparse(self.path).path
        if p == "/start_challenge":
            ProviderAPI.start_challenge(self.state, self)
        elif p == "/submit":
            ProviderAPI.submit_flag(self.state, self)
        elif p == "/hint":
            ProviderAPI.request_hint(self.state, self)
        else:
            self.send_error(405, "Method Not Allowed")

    # ── Challenge handlers ──

    def _handle_challenge_get(self) -> None:
        if not ChallengePages.handle_get(self.state, self.path, self):
            self.send_error(404, "Challenge page not found")

    def _handle_challenge_post(self) -> None:
        if not ChallengePages.handle_post(self.state, self.path, self):
            self.send_error(404, "Challenge endpoint not found")

    # ── Index ──

    def _handle_index(self) -> None:
        port = self.state.port
        lines = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>Local CTF Range</title></head><body>",
                  "<h1>Local CTF Range</h1>",
                  "<h2>Challenges</h2><ul>"]
        for cid, c in self.state.challenges.items():
            lines.append(
                f"<li><strong>{c['name']}</strong> ({c['difficulty']}, {c['category']}) "
                f"— <a href='/challenge/{cid}'>进入挑战</a><br>"
                f"<small>{c['description']}</small></li>"
            )
        lines.append("</ul>")
        lines.append(f"<h2>API</h2><p>CompetitionProvider API 运行在 <code>http://127.0.0.1:{port}</code></p>")
        lines.append("<p>使用 <code>python -m attack_agent --provider-url http://127.0.0.1:{port} --model openai</code> 来测试</p>".format(port=port))
        lines.append("</body></html>")
        _html_response(self, 200, "\n".join(lines))

    # ── Silence logs ──

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("RANGE_VERBOSE"):
            super().log_message(fmt, *args)


# ── Server Factory ─────────────────────────────────────────────────────

def make_server(port: int) -> ThreadingHTTPServer:
    """Create a range server with shared state attached to the handler."""
    state = RangeState(port)

    class Handler(RangeRequestHandler):
        pass

    Handler.state = state  # type: ignore[attr-defined]

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # Reduce poll interval for faster shutdown
    server.timeout = 0.5
    return server


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local CTF Range Server for AttackAgent testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/local_range.py\n"
            "  python scripts/local_range.py --port 9999\n"
            "\n"
            "Then run AttackAgent against it:\n"
            "  python -m attack_agent --provider-url http://127.0.0.1:8484 --model openai\n"
            "  python -m attack_agent --provider-url http://127.0.0.1:8484 --model anthropic\n"
        ),
    )
    parser.add_argument("--port", type=int, default=8484, help="Listen port (default: 8484)")
    parser.add_argument("--no-prompt", action="store_true", help="Run once and exit (don't wait for keyboard interrupt)")
    args = parser.parse_args()

    server = make_server(args.port)
    print(f"[range] Local CTF Range running at http://127.0.0.1:{args.port}")
    print(f"[range] Open http://127.0.0.1:{args.port} in browser to see all challenges")
    print(f"[range] Run AttackAgent via: python -m attack_agent --provider-url http://127.0.0.1:{args.port} --model openai")
    print("[range] Press Ctrl+C to stop")

    if args.no_prompt:
        # Run for the configured timeout then exit
        try:
            while True:
                server.handle_request()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            print("\n[range] Shutting down...")
        finally:
            server.server_close()
            print("[range] Server stopped")


if __name__ == "__main__":
    main()
