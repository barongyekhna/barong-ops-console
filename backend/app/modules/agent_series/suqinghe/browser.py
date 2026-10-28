"""她的登录浏览器(10-28):worker 里常驻一个带 profile 的 Chromium。

为什么要它:1688 对匿名无头浏览器拦得勤(滑块/验证码/跳登录)。老板拍板用他的 1688 账号——他在办公室「浏览器」面板里
扫一次码,cookie 落在 profile 里跨重启;以后她抓页面都是登录态。真被拦住时页面不关,进 needs_human:面板里推实时画面,
老板点一下滑块/扫个码,页面恢复她就自己接着做。

设计:
- 后端容器和 worker 只共享数据库,所以画面(JPEG)和老板的点击都走库:sqh_browser(单行)+ sqh_browser_inputs。
  只在有人看(viewer_seen_at 5 秒内)时截图、写帧;老板没开面板就什么都不写。
- 同步 Playwright 只能在一个线程里用:BrowserSession 线程独占它,别的线程 submit() 任务拿 Future 等结果。
- 状态:idle / fetching / needs_human(等老板过验证) / interactive(老板在登录) / asking_seller(B 期,问卖家)。
- 不改 compose:profile 放在 worker 已挂的 agent-memory 卷;按需启动,闲置 N 分钟关(profile 留着)。
- 全部受 SQH_BROWSER 开关管;关着时 sourcing_1688 还是每次新开匿名浏览器的老路。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from sqlalchemy import delete, select, update

from ....db.session import SessionLocal
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .constants import browser_dump_dir, browser_enabled, browser_hold_minutes, browser_idle_minutes, browser_profile_dir
from .models import SqhBrowser, SqhBrowserInput

logger = logging.getLogger(__name__)
_X = SKIP_ORG_DATA_ISOLATION

VIEWPORT = {"width": 1366, "height": 900}
FRAME_WIDTH = 1366  # 10-28 老板扫码扫不上:不再缩到 1024,原尺寸 + 质量 85,二维码才清楚
FRAME_QUALITY = 85
FRAME_INTERVAL_S = 0.7
INPUT_POLL_S = 0.1
RECOVERY_CHECK_S = 2.0
VIEWER_FRESH_S = 5.0
LOGIN_URL = "https://login.1688.com/member/signin.htm"
STATES = ("idle", "fetching", "needs_human", "interactive", "asking_seller")
HOLD_STATES = ("needs_human", "interactive", "asking_seller")
INPUT_KINDS = ("click", "down", "move", "up", "type", "key", "wheel", "navigate", "dump", "login", "close")
COMMAND_KINDS = ("login", "close", "dump")  # 没人看也每秒扫一次
KEYS_ALLOWED = ("Enter", "Backspace", "Tab", "Escape", "Delete", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space", "Home", "End")
LOGIN_COOKIES = ("cookie2", "_tb_token_", "sgcookie", "unb")
_ALLOWED_HOSTS = (".1688.com", ".taobao.com", ".alibaba.com")


def enabled() -> bool:
    return browser_enabled()


def allowed_url(url: str) -> bool:
    """老板让她导航只许去阿里系的页面。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return bool(host) and urlparse(url).scheme in ("http", "https") and any(host == h[1:] or host.endswith(h) for h in _ALLOWED_HOSTS)


# ---------------------------------------------------------------- 库(后端和 worker 之间唯一的通道)


class DbStore:
    """sqh_browser / sqh_browser_inputs 的读写,每次一个短事务(worker 的池只有 3+3)。"""

    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._sessions = session_factory

    def sync_state(self, *, status: str, reason: str | None, url: str | None, title: str | None, dossier_id: int | None, logged_in_at: datetime | None = None) -> None:
        values: dict[str, Any] = {"status": status[:16], "reason": (reason or "")[:2000] or None, "url": (url or "")[:1000] or None, "title": (title or "")[:300] or None, "dossier_id": dossier_id}
        if logged_in_at is not None:
            values["logged_in_at"] = logged_in_at
        with self._sessions() as db:
            row = db.get(SqhBrowser, 1, execution_options=_X)
            if row is None:
                db.add(SqhBrowser(id=1, **values))
            else:
                db.execute(update(SqhBrowser).where(SqhBrowser.id == 1).values(**values), execution_options=_X)
            db.commit()

    def push_frame(self, jpeg: bytes) -> None:
        with self._sessions() as db:
            db.execute(update(SqhBrowser).where(SqhBrowser.id == 1).values(frame=jpeg, frame_at=datetime.now(UTC)), execution_options=_X)
            db.commit()

    def viewer_recent(self, seconds: float = VIEWER_FRESH_S) -> bool:
        with self._sessions() as db:
            seen = db.scalar(select(SqhBrowser.viewer_seen_at).where(SqhBrowser.id == 1), execution_options=_X)
        return bool(seen and (datetime.now(UTC) - seen).total_seconds() <= seconds)

    def pop_inputs(self, *, limit: int = 20, kinds: tuple[str, ...] | None = None) -> list[tuple[int, str, dict[str, Any]]]:
        with self._sessions() as db:
            stmt = select(SqhBrowserInput).where(SqhBrowserInput.applied_at.is_(None)).order_by(SqhBrowserInput.id).limit(limit)
            if kinds:
                stmt = stmt.where(SqhBrowserInput.kind.in_(kinds))
            rows = db.scalars(stmt, execution_options=_X).all()
            out = [(int(r.id), str(r.kind), dict(r.payload or {})) for r in rows]
            if out:
                db.execute(update(SqhBrowserInput).where(SqhBrowserInput.id.in_([i for i, _, _ in out])).values(applied_at=datetime.now(UTC)), execution_options=_X)
                db.commit()
        return out

    def cleanup_inputs(self, *, older_than_hours: float = 1.0) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
        with self._sessions() as db:
            result = db.execute(delete(SqhBrowserInput).where(SqhBrowserInput.applied_at.is_not(None), SqhBrowserInput.applied_at < cutoff), execution_options=_X)
            db.commit()
        return int(result.rowcount or 0)


# ---------------------------------------------------------------- 纯函数(有测试)


def apply_input(page: Any, kind: str, payload: dict[str, Any]) -> bool:
    """把老板的一下动作映射到 Playwright 的 page 上。坐标按 1366x900 视口;越界、不认识的一律丢掉。返回有没有做。"""

    def xy() -> tuple[float, float] | None:
        try:
            x, y = float(payload.get("x")), float(payload.get("y"))
        except (TypeError, ValueError):
            return None
        if not (0 <= x <= VIEWPORT["width"] and 0 <= y <= VIEWPORT["height"]):
            return None
        return x, y

    if kind == "click":
        if (p := xy()) is None:
            return False
        page.mouse.click(p[0], p[1])
        return True
    if kind == "down":
        if (p := xy()) is None:
            return False
        page.mouse.move(p[0], p[1])
        page.mouse.down()
        return True
    if kind == "move":
        if (p := xy()) is None:
            return False
        page.mouse.move(p[0], p[1], steps=3)
        return True
    if kind == "up":
        if (p := xy()) is None:
            return False
        page.mouse.move(p[0], p[1])
        page.mouse.up()
        return True
    if kind == "type":
        text = str(payload.get("text") or "")[:200]
        if not text:
            return False
        page.keyboard.type(text, delay=30)
        return True
    if kind == "key":
        key = str(payload.get("key") or "")
        if key not in KEYS_ALLOWED:
            return False
        page.keyboard.press(key)
        return True
    if kind == "wheel":
        if (p := xy()) is None:
            return False
        try:
            dy = max(-3000.0, min(3000.0, float(payload.get("dy") or 0)))
        except (TypeError, ValueError):
            return False
        page.mouse.move(p[0], p[1])
        page.mouse.wheel(0, dy)
        return True
    if kind == "navigate":
        url = str(payload.get("url") or "")
        if not allowed_url(url):
            return False
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return True
    return False


def logged_in(cookies: list[dict[str, Any]]) -> bool:
    """1688 的登录 cookie 齐不齐(cookie2/_tb_token_ 这几个是登录态才有的)。"""
    names = {str(c.get("name")) for c in cookies if isinstance(c, dict)}
    return any(n in names for n in LOGIN_COOKIES)


SINGLETON_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def clear_stale_singleton(profile: str) -> list[str]:
    """worker 容器重建后主机名变了,Chromium 看到上一个容器留下的 SingletonLock(hostname-pid)会当成「别的机器在用这份 profile」拒绝启动。
    这份 profile 只有本线程一个用户,启动前把三个 Singleton* 符号链接清掉。返回清掉的文件名。"""
    removed: list[str] = []
    for name in SINGLETON_FILES:
        path = os.path.join(profile, name)
        if os.path.islink(path) or os.path.exists(path):
            try:
                os.unlink(path)
                removed.append(name)
            except OSError:
                logger.warning("could not remove %s", path)
    if removed:
        logger.info("cleared stale chromium singleton files: %s", removed)
    return removed


def frame_bytes(screenshot_png_or_jpeg: bytes, *, width: int = FRAME_WIDTH, quality: int = FRAME_QUALITY) -> bytes:
    """截图转成 JPEG 给面板看。原尺寸(1366 宽)、质量 85、只压一次(截图用无损 PNG):
    老板要拿手机对着屏幕扫二维码,10-28 第一次用时缩到 1024 又压到 60,码糊得扫不上。≈150–250KB,只在有人看且画面变了才写。"""
    from PIL import Image

    img = Image.open(io.BytesIO(screenshot_png_or_jpeg)).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- 浏览器线程


class BrowserSession(threading.Thread):
    """独占 Playwright 的线程。别的线程只能 submit()。"""

    def __init__(
        self,
        *,
        store: Any | None = None,
        launcher: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        detect_blocked: Callable[..., str | None] | None = None,
    ) -> None:
        super().__init__(name="sqh-browser", daemon=True)
        self.store = store or DbStore()
        self._launcher = launcher  # 测试注入:返回一个「context」(有 new_page/cookies/close)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._detect = detect_blocked
        self._jobs: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], Future]] = queue.Queue()
        self._lock = threading.Lock()
        self._pw: Any = None
        self._ctx: Any = None
        self._page: Any = None
        self.status = "idle"
        self.reason: str | None = None
        self.dossier_id: int | None = None
        self.logged_in_at: datetime | None = None
        self._state_since = self._clock()
        self._last_activity = time.monotonic()
        self._last_frame = 0.0
        self._last_frame_hash = ""
        self._last_recovery = 0.0
        self._last_command_scan = 0.0
        self._last_cleanup = time.monotonic()
        self._recovered: dict[str, Any] | None = None
        self.stop_flag = threading.Event()

    # ---- 其它线程调用 ----

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        fut: Future = Future()
        self._jobs.put((fn, args, fut))
        return fut

    def fetch_offer_html(self, url: str, timeout_s: float) -> tuple[str, str, str, str]:
        """像 webpage.render_raw 一样读一页,但用常驻登录页。(最终地址, 标题, html, 文本)。"""
        return self.submit(self._do_fetch, url, timeout_s).result(timeout=timeout_s + 80)

    def hold_for_human(self, reason: str, *, dossier_id: int | None = None) -> None:
        self.submit(self._do_hold, reason, dossier_id).result(timeout=10)

    def note_dossier(self, dossier_id: int | None) -> None:
        self.submit(self._do_note_dossier, dossier_id).result(timeout=10)

    def open_login(self) -> None:
        self.submit(self._do_login).result(timeout=60)

    def close(self) -> None:
        self.submit(self._do_close).result(timeout=30)

    def take_recovered(self) -> dict[str, Any] | None:
        """自愈(或放弃)之后主线程取一次:{"outcome": "recovered"|"gave_up", "dossier_id", "final_url", "title", "html", "text", "reason"}。"""
        with self._lock:
            out, self._recovered = self._recovered, None
        return out

    def snapshot(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "dossier_id": self.dossier_id, "logged_in_at": self.logged_in_at, "alive": self.is_alive()}

    # ---- 线程主循环 ----

    def run(self) -> None:
        self._set("idle", dossier_id=None)  # 线程一起来就把库里的行归位:上个容器被杀时留下的 interactive/needs_human 不作数
        while not self.stop_flag.is_set():
            try:
                fn, args, fut = self._jobs.get(timeout=INPUT_POLL_S)
            except queue.Empty:
                self._tick_idle()
                continue
            try:
                fut.set_result(fn(*args))
            except BaseException as exc:  # noqa: BLE001 —— 结果交给等的人,线程自己不死
                fut.set_exception(exc)
        self._teardown()

    # ---- 浏览器 ----

    def _context(self) -> Any:
        if self._ctx is not None:
            return self._ctx
        if self._launcher is not None:
            self._ctx = self._launcher()
            return self._ctx
        from playwright.sync_api import sync_playwright

        from ..common.webpage import DESKTOP_UA

        profile = browser_profile_dir()
        os.makedirs(profile, exist_ok=True)
        clear_stale_singleton(profile)
        self._pw = sync_playwright().start()
        kwargs: dict[str, Any] = {
            "user_data_dir": profile,
            "headless": True,
            "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            "locale": "zh-CN",
            "viewport": VIEWPORT,
            "user_agent": DESKTOP_UA,
        }
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(channel="chromium", **kwargs)  # 新 headless,比 headless-shell 更像真浏览器
        except Exception:  # noqa: BLE001 —— 没装完整 chromium 就用默认的
            logger.info("chromium channel unavailable, falling back to default headless")
            self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
        self._ctx.set_default_timeout(30_000)
        return self._ctx

    def _get_page(self) -> Any:
        ctx = self._context()
        if self._page is None or getattr(self._page, "is_closed", lambda: False)():
            pages = list(getattr(ctx, "pages", []) or [])
            self._page = pages[0] if pages else ctx.new_page()
        self._last_activity = time.monotonic()
        return self._page

    def _teardown(self) -> None:
        for closer in (lambda: self._ctx.close() if self._ctx else None, lambda: self._pw.stop() if self._pw else None):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._page = self._pw = None

    def _set(self, status: str, *, reason: str | None = None, dossier_id: int | None = ..., url: str | None = None, title: str | None = None) -> None:  # type: ignore[assignment]
        self.status = status
        self.reason = reason
        if dossier_id is not ...:
            self.dossier_id = dossier_id
        self._state_since = self._clock()
        try:
            self.store.sync_state(status=status, reason=reason, url=url, title=title, dossier_id=self.dossier_id, logged_in_at=self.logged_in_at)
        except Exception:  # noqa: BLE001 —— 库写不进不挡浏览器
            logger.exception("browser state sync failed")

    def _page_info(self) -> tuple[str, str]:
        try:
            return str(self._page.url), str(self._page.title())
        except Exception:  # noqa: BLE001
            return "", ""

    def _refresh_login(self) -> bool:
        try:
            ok = logged_in(self._context().cookies("https://www.1688.com/"))
        except Exception:  # noqa: BLE001
            return False
        if ok and self.logged_in_at is None:
            self.logged_in_at = self._clock()
        if not ok:
            self.logged_in_at = None
        return ok

    # ---- 任务(都在本线程) ----

    def _do_fetch(self, url: str, timeout_s: float) -> tuple[str, str, str, str]:
        page = self._get_page()
        self._set("fetching", dossier_id=None, url=url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            page.wait_for_timeout(2500)
            for _ in range(10):
                try:
                    page.mouse.wheel(0, 1200)
                    page.wait_for_timeout(500)
                except Exception:  # noqa: BLE001
                    break
            html, text = "", ""
            for _ in range(3):
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                    html = page.content()
                    text = page.inner_text("body")
                    break
                except Exception:  # noqa: BLE001
                    page.wait_for_timeout(1000)
            if html and not text:
                try:
                    text = page.evaluate("() => (document.body ? document.body.innerText : '')") or ""
                except Exception:  # noqa: BLE001
                    text = ""
            final_url, title = self._page_info()
            self._refresh_login()
            return final_url, title, html, text
        finally:
            if self.status == "fetching":
                self._set("idle", dossier_id=None)

    def _do_hold(self, reason: str, dossier_id: int | None) -> None:
        url, title = self._page_info()
        self._set("needs_human", reason=reason, dossier_id=dossier_id, url=url, title=title)
        self._last_recovery = time.monotonic()

    def _do_note_dossier(self, dossier_id: int | None) -> None:
        self.dossier_id = dossier_id
        url, title = self._page_info()
        self.store.sync_state(status=self.status, reason=self.reason, url=url, title=title, dossier_id=dossier_id, logged_in_at=self.logged_in_at)

    def _do_login(self) -> None:
        if self.status == "needs_human":
            return  # 正等老板过验证,登录页会把它冲掉;老板在面板里自己点
        page = self._get_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
        url, title = self._page_info()
        self._set("interactive", reason="老板在登录 1688", dossier_id=None, url=url, title=title)

    def _do_close(self) -> None:
        if self.status == "needs_human" and self.dossier_id is not None:
            with self._lock:
                self._recovered = {"outcome": "gave_up", "dossier_id": self.dossier_id, "reason": "老板关掉了浏览器"}
        self._teardown()
        self._set("idle", dossier_id=None)

    def _do_dump(self) -> str:
        """把当前页面存一份(url/html/各 frame/截图),B 期靠它读旺旺 IM 的 DOM。"""
        page = self._get_page()
        folder = os.path.join(browser_dump_dir(), self._clock().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(folder, exist_ok=True)
        info: dict[str, Any] = {"url": page.url, "title": page.title(), "pages": [], "frames": []}
        try:
            info["pages"] = [p.url for p in self._context().pages]
        except Exception:  # noqa: BLE001
            pass
        with open(os.path.join(folder, "page.html"), "w", encoding="utf-8") as fh:
            fh.write(page.content())
        for i, frame in enumerate(getattr(page, "frames", []) or []):
            try:
                info["frames"].append({"index": i, "url": frame.url, "name": frame.name})
                with open(os.path.join(folder, f"frame-{i}.html"), "w", encoding="utf-8") as fh:
                    fh.write(frame.content())
            except Exception:  # noqa: BLE001
                continue
        try:
            page.screenshot(path=os.path.join(folder, "page.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
        with open(os.path.join(folder, "info.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=1)
        return folder

    # ---- 空闲循环:帧 / 输入 / 自愈 / 闲置关闭 ----

    def _tick_idle(self) -> None:
        now = time.monotonic()
        try:
            if self.status in HOLD_STATES:
                self._tick_hold(now)
            else:
                if now - self._last_command_scan >= 1.0:
                    self._last_command_scan = now
                    self._apply_inputs(self.store.pop_inputs(kinds=COMMAND_KINDS))
                if self._ctx is not None and self.status == "idle" and now - self._last_activity > browser_idle_minutes() * 60:
                    logger.info("browser idle, closing context (profile kept)")
                    self._teardown()
            if now - self._last_cleanup > 3600:
                self._last_cleanup = now
                self.store.cleanup_inputs()
        except Exception:  # noqa: BLE001 —— 空闲循环里的任何错都不许把线程带死
            logger.exception("browser idle tick failed")

    def _tick_hold(self, now: float) -> None:
        if self._page is None:
            self._set("idle", dossier_id=None)
            return
        viewer = self.store.viewer_recent()
        if viewer:
            self._apply_inputs(self.store.pop_inputs())
        elif now - self._last_command_scan >= 1.0:
            self._last_command_scan = now
            self._apply_inputs(self.store.pop_inputs(kinds=COMMAND_KINDS))
        if self.status not in HOLD_STATES:
            return
        if viewer and now - self._last_frame >= FRAME_INTERVAL_S:
            self._last_frame = now
            self._push_frame()
        if now - self._last_recovery >= RECOVERY_CHECK_S:
            self._last_recovery = now
            self._check_recovery()
        if self.status == "needs_human" and (self._clock() - self._state_since) > timedelta(minutes=browser_hold_minutes()):
            with self._lock:
                self._recovered = {"outcome": "gave_up", "dossier_id": self.dossier_id, "reason": f"等了 {browser_hold_minutes():g} 分钟没人来过验证"}
            self._set("idle", dossier_id=None)

    def _apply_inputs(self, rows: list[tuple[int, str, dict[str, Any]]]) -> None:
        for _id, kind, payload in rows:
            try:
                if kind == "login":
                    self._do_login()
                elif kind == "close":
                    self._do_close()
                elif kind == "dump":
                    self._do_dump()
                elif self._page is not None:
                    apply_input(self._page, kind, payload)
                    self._last_activity = time.monotonic()
            except Exception:  # noqa: BLE001 —— 一下点错了不影响下一下
                logger.exception("browser input %s failed", kind)

    def _push_frame(self) -> None:
        try:
            raw = self._page.screenshot(type="png")  # 无损截,只在 frame_bytes 压一次
        except Exception:  # noqa: BLE001
            return
        digest = hashlib.sha1(raw).hexdigest()
        if digest == self._last_frame_hash:
            return
        self._last_frame_hash = digest
        self.store.push_frame(frame_bytes(raw))

    def _check_recovery(self) -> None:
        url, title = self._page_info()
        if self.status == "needs_human":
            detect = self._detect
            if detect is None:
                from .sourcing_1688 import detect_blocked as detect
            try:
                html = self._page.content()
            except Exception:  # noqa: BLE001
                return
            if detect(final_url=url, title=title, html=html) is not None:
                self.store.sync_state(status=self.status, reason=self.reason, url=url, title=title, dossier_id=self.dossier_id, logged_in_at=self.logged_in_at)
                return
            try:
                text = self._page.inner_text("body")
            except Exception:  # noqa: BLE001
                text = ""
            self._refresh_login()
            with self._lock:
                self._recovered = {"outcome": "recovered", "dossier_id": self.dossier_id, "final_url": url, "title": title, "html": html, "text": text}
            self._set("idle", dossier_id=None)
        elif self.status == "interactive":
            if "login.1688.com" not in url and self._refresh_login():
                self._set("idle", reason="1688 登录成功,账号记住了,下次抓页面直接用", dossier_id=None, url=url, title=title)


# ---------------------------------------------------------------- 进程内单例


_session: BrowserSession | None = None
_session_lock = threading.Lock()


def get() -> BrowserSession:
    """worker 进程里的那一个;线程挂了就重建。"""
    global _session
    with _session_lock:
        if _session is None or not _session.is_alive():
            _session = BrowserSession()
            _session.start()
        return _session


def status() -> dict[str, Any]:
    """主线程判「别碰 1688」用;没开开关、线程没起都算 idle。"""
    if not enabled() or _session is None or not _session.is_alive():
        return {"status": "idle", "reason": None, "dossier_id": None, "logged_in_at": None, "alive": False}
    return _session.snapshot()


def holding() -> bool:
    return status()["status"] in HOLD_STATES


def shutdown(timeout_s: float = 20.0) -> bool:
    """worker 下线时把 Chromium 关干净(cookie 落盘、SingletonLock 自己撤掉),线程收工。没线程就什么都不做。"""
    global _session
    with _session_lock:
        sess, _session = _session, None
    if sess is None or not sess.is_alive():
        return False
    try:
        sess.close()
    except Exception:  # noqa: BLE001 —— 关不掉也要停线程
        logger.exception("browser close on shutdown failed")
    sess.stop_flag.set()
    sess.join(timeout=timeout_s)
    return True
