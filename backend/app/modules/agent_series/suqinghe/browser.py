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
- 10-29 热修 4:1688 的「联系供应商」把旺旺开在新标签页,面板跟着新开的页走;同一批滚轮合成一下再给 Chromium;截图直接出 JPEG。
- 10-29 热修 5:日志量出来 page.screenshot 在 1688 商品页上要 2–18 秒(它要在页面主线程里跑脚本,主线程被视频/追踪脚本占满),
  滚动点击都排在它后面。画面改走 CDP screencast(合成器直接出 JPEG,不占主线程;我们确认一帧它才给下一帧,节奏由我们定),
  url/标题走导航历史不问页面,启动时禁视频自动播放。CDP 拿不到(非 Chromium)时退回截图。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

from sqlalchemy import delete, select, update

from ....db.session import SessionLocal
from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .constants import browser_dump_dir, browser_enabled, browser_hold_minutes, browser_idle_minutes, browser_profile_dir
from .models import SqhBrowser, SqhBrowserInput

logger = logging.getLogger(__name__)
_X = SKIP_ORG_DATA_ISOLATION

VIEWPORT = {"width": 1366, "height": 900}
FRAME_QUALITY = 85  # 10-28 老板扫码扫不上:不缩(视口原尺寸 1366 宽)、JPEG 质量 85,二维码才清楚
FRAME_INTERVAL_S = 0.4  # 10-29 老板说滚动「非常慢」:0.7→0.4,且应用完输入立刻出一帧
SLOW_TICK_S = 1.5  # 一轮(应用输入 + 截帧)超过这么久就记日志,老板再说慢我能看出慢在哪
PUMP_MS = 50  # screencast 推帧要靠 Playwright 事件循环转起来,每轮让它转这么久
AUTOPLAY_ARG = "--autoplay-policy=user-gesture-required"  # 1688 商品页视频自动播,主线程和 CPU 都被它吃掉
SCREENCAST_PARAMS = {"format": "jpeg", "quality": FRAME_QUALITY, "maxWidth": VIEWPORT["width"], "maxHeight": VIEWPORT["height"], "everyNthFrame": 1}
WHEEL_MAX = 6000.0  # 合并后的一下滚轮最多滚这么多像素(约六屏半)
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
LOGGED_IN_REASON = "1688 登录成功,账号记住了。页面留给你用:可以贴地址打开商品页、点「联系供应商」、「存一份页面」;用完点「关掉」"
HOLD_IDLE_REASON = "没人用了,我把页面收了(账号还在)"
_ALLOWED_HOSTS = (".1688.com", ".taobao.com", ".alibaba.com")

# ---- 旺旺(1688 网页 IM),10-29 从三份「存一份页面」里读出来的
IM_PAGE = "https://air.1688.com/app/ocms-fusion-components-1688/def_cbu_web_im/index.html"
IM_CORE_FRAME = "def_cbu_web_im_core"  # 聊天本体在这个 iframe 里
IM_SELECTORS = {"input": "pre.edit[contenteditable]", "send": "button.send-btn"}
IM_MESSAGES_JS = """() => Array.from(document.querySelectorAll('.message-list .message-item')).map(el => ({
  self: el.classList.contains('self'),
  nick: ((el.querySelector('.nick') || {}).innerText || '').trim(),
  time: ((el.querySelector('.time') || {}).innerText || '').trim(),
  text: ((el.querySelector('.content-row') || el).innerText || '').trim()
}))"""
SELLER_ID_JS = """() => {
  const pick = (s) => { const m = String(s || '').match(/"sellerLoginId"\\s*:\\s*"([^"]{1,64})"/); return m ? m[1] : null; };
  try { const hit = pick(JSON.stringify(window.context || {})); if (hit) return hit; } catch (e) {}
  try { return pick(document.documentElement.outerHTML); } catch (e) { return null; }
}"""
IM_BLOCK_MARKERS = ("安全验证", "nc_1_n1z", "punish", "验证码")
IM_QUESTION_MAX = 480  # 输入框上限 500 字


class SellerChatError(RuntimeError):
    """问卖家这一下没做成(旺旺没开出来、字没打进去、发了没出现)。detail 里有截图目录和当时的消息列表。"""

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class SellerChatBlocked(SellerChatError):
    """开旺旺/商品页时 1688 要登录或验证:页面留在 needs_human 等老板,这一次算没问成。"""


def im_url(login_id: str, offer_id: str) -> str:
    """直接开到和这个卖家的会话(不用再点「联系供应商」)。"""
    return IM_PAGE + "?" + urlencode({"touid": f"cnalichn{login_id}", "siteid": "cnalichn", "status": "1", "offerId": str(offer_id)})


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
            dy = max(-WHEEL_MAX, min(WHEEL_MAX, float(payload.get("dy") or 0)))
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


def coalesce_inputs(rows: list[tuple[int, str, dict[str, Any]]]) -> list[tuple[int, str, dict[str, Any]]]:
    """同一批里连着的滚轮合成一下(dy 相加、位置取最后一条的),连着的 move 只留最后一个;点、键、命令原样按序保留。
    10-29 老板滚一屏面板发 8 条/秒,worker 每条一次 Chromium 往返(约 100ms),队列积到 24–32 秒才应用上。"""
    out: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        _id, kind, payload = row
        if out and kind in ("wheel", "move") and out[-1][1] == kind:
            if kind == "move":
                out[-1] = row
                continue
            try:
                dy = float(out[-1][2].get("dy") or 0) + float(payload.get("dy") or 0)
            except (TypeError, ValueError):
                out.append(row)
                continue
            out[-1] = (_id, kind, {**payload, "dy": dy})
            continue
        out.append(row)
    return out


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


# ---------------------------------------------------------------- 一页的 CDP 会话(推帧 + 页信息)


class Screen:
    """当前页的 CDP 会话:Page.startScreencast 推帧——Chromium 合成器直接出 JPEG,不占页面主线程;
    一帧我们取走并 Ack 之后它才给下一帧,所以节奏跟着面板走、没人取就不推。url/标题走 Page.getNavigationHistory,也不问页面。"""

    def __init__(self, cdp: Any) -> None:
        self.cdp = cdp
        self.latest: bytes | None = None
        self._acks: list[Any] = []
        self.casting = False
        cdp.on("Page.screencastFrame", self._on_frame)

    def _on_frame(self, params: dict[str, Any]) -> None:
        try:
            self.latest = base64.b64decode(params.get("data") or "")
        except (TypeError, ValueError):
            self.latest = None
        self._acks.append(params.get("sessionId"))

    def start(self) -> None:
        if not self.casting:
            self.cdp.send("Page.startScreencast", dict(SCREENCAST_PARAMS))
            self.casting = True

    def stop(self) -> None:
        if self.casting:
            self.casting = False
            try:
                self.cdp.send("Page.stopScreencast")
            except Exception:  # noqa: BLE001 —— 页可能已经关了
                pass

    def take(self) -> bytes | None:
        """取走最新一帧,并把收到的帧都确认掉——Chromium 才会继续推。"""
        frame, self.latest = self.latest, None
        acks, self._acks = self._acks, []
        for sid in acks:
            try:
                self.cdp.send("Page.screencastFrameAck", {"sessionId": sid})
            except Exception:  # noqa: BLE001
                pass
        return frame

    def info(self) -> tuple[str, str]:
        history = self.cdp.send("Page.getNavigationHistory")
        entry = history["entries"][history["currentIndex"]]
        return str(entry.get("url") or ""), str(entry.get("title") or "")

    def detach(self) -> None:
        self.stop()
        try:
            self.cdp.detach()
        except Exception:  # noqa: BLE001
            pass


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
        self._last_frame_warn = 0.0
        self._screen: Screen | None = None
        self._screen_page: Any = None
        self._screen_warned = False
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

    def ask_seller(self, *, offer_url: str, login_id: str | None, offer_id: str, text: str, dossier_id: int | None, timeout_s: float = 90.0) -> dict[str, Any]:
        """在旺旺里给卖家发一条(B 期)。没有 login_id 就先开商品页从页面数据里找。成功回 {ok, im_url, login_id, messages, dump}。"""
        return self.submit(self._do_ask_seller, offer_url, login_id, offer_id, text, dossier_id, timeout_s).result(timeout=timeout_s + 60)

    def read_seller_chat(self, *, im_url: str, timeout_s: float = 60.0) -> list[dict[str, Any]]:
        """开到和卖家的会话,把消息列表读回来:[{self, nick, time, text}]。"""
        return self.submit(self._do_read_chat, im_url, timeout_s).result(timeout=timeout_s + 60)

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
            self._hook_context(self._ctx)
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
            "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled", AUTOPLAY_ARG],
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
        self._hook_context(self._ctx)
        return self._ctx

    def _hook_context(self, ctx: Any) -> None:
        ctx.on("page", self._on_new_page)
        for page in self._open_pages(ctx):
            page.on("close", self._on_page_closed)

    @staticmethod
    def _open_pages(ctx: Any) -> list[Any]:
        return [p for p in (getattr(ctx, "pages", []) or []) if not getattr(p, "is_closed", lambda: False)()]

    def _ensure_screen(self) -> Screen | None:
        """给当前页挂(或换到)它的 CDP 会话;拿不到就退回截图路径(只警告一次)。"""
        if self._page is None:
            return None
        if self._screen is not None and self._screen_page is self._page:
            return self._screen
        if self._screen is not None:
            self._screen.detach()
            self._screen = None
        self._screen_page = self._page
        try:
            self._screen = Screen(self._context().new_cdp_session(self._page))
        except Exception as exc:  # noqa: BLE001
            if not self._screen_warned:
                self._screen_warned = True
                logger.warning("browser screencast unavailable, falling back to screenshots: %s", str(exc).splitlines()[0][:200])
            self._screen = None
        return self._screen

    def _on_new_page(self, page: Any) -> None:
        """1688 的「联系供应商」把旺旺开在新标签页(10-29 老板点了六下、开出三页,面板却一直盯着商品页):新开的页面板跟过去。"""
        page.on("close", self._on_page_closed)
        self._page = page
        self._last_frame = 0.0
        self._last_frame_hash = ""
        self._last_activity = time.monotonic()
        logger.info("browser followed a new tab")

    def _on_page_closed(self, page: Any) -> None:
        if page is not self._page or self._ctx is None:
            return
        pages = self._open_pages(self._ctx)
        self._page = pages[-1] if pages else None
        self._last_frame = 0.0
        self._last_frame_hash = ""

    def _get_page(self) -> Any:
        ctx = self._context()
        if self._page is None or getattr(self._page, "is_closed", lambda: False)():
            pages = self._open_pages(ctx)
            self._page = pages[-1] if pages else ctx.new_page()  # 最新开的那页
        self._last_activity = time.monotonic()
        return self._page

    def _teardown(self) -> None:
        for closer in (lambda: self._ctx.close() if self._ctx else None, lambda: self._pw.stop() if self._pw else None):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._page = self._pw = None
        self._screen = self._screen_page = None

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
        screen = self._ensure_screen()
        if screen is not None:
            try:
                return screen.info()  # 不碰页面主线程
            except Exception:  # noqa: BLE001
                pass
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

    # ---- 旺旺(B 期,10-29):问卖家 / 读回复。都在本线程,状态 asking_seller,完了回 idle;要登录/验证就留 needs_human 等老板 ----

    def _guard_blocked(self, page: Any, where: str) -> None:
        url, title = self._page_info()
        try:
            html = page.content()
        except Exception:  # noqa: BLE001
            html = ""
        if "login.1688.com" in url or "login.taobao.com" in url or any(m in (title or "") for m in IM_BLOCK_MARKERS[:1]) or any(m in html[:200_000] for m in IM_BLOCK_MARKERS[1:]):
            self._set("needs_human", reason=f"{where}时 1688 要登录/验证,老板开面板帮我过一下(账号还在)", dossier_id=None, url=url, title=title)
            self._last_recovery = time.monotonic()
            raise SellerChatBlocked(f"needs_human:{where}", detail={"url": url, "title": title})

    def _im_frame(self, page: Any, timeout_s: float) -> Any:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for frame in getattr(page, "frames", []) or []:
                if IM_CORE_FRAME in str(getattr(frame, "url", "") or ""):
                    try:
                        frame.wait_for_selector(IM_SELECTORS["input"], timeout=5000)
                        return frame
                    except Exception:  # noqa: BLE001 —— 还在加载,再等
                        break
            page.wait_for_timeout(500)
        raise SellerChatError("旺旺聊天窗没出来")

    def _shot(self, page: Any, path: str) -> None:
        try:
            page.screenshot(path=path)
        except Exception:  # noqa: BLE001
            pass

    def _do_ask_seller(self, offer_url: str, login_id: str | None, offer_id: str, text: str, dossier_id: int | None, timeout_s: float) -> dict[str, Any]:
        page = self._get_page()
        self._set("asking_seller", reason=f"在旺旺问 {offer_id} 的卖家重量尺寸", dossier_id=dossier_id, url=offer_url)
        folder = os.path.join(browser_dump_dir(), "seller-chat", f"{self._clock().strftime('%Y%m%d-%H%M%S')}-{offer_id}")
        os.makedirs(folder, exist_ok=True)
        out: dict[str, Any] = {"ok": False, "login_id": login_id, "im_url": None, "dump": folder, "messages": []}
        try:
            if not login_id:
                page.goto(offer_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(1500)
                self._guard_blocked(page, "开商品页")
                login_id = page.evaluate(SELLER_ID_JS) or None
                out["login_id"] = str(login_id)[:64] if login_id else None
                if not login_id:
                    raise SellerChatError("商品页里找不到卖家账号,开不了旺旺", detail=out)
            url = im_url(str(login_id), offer_id)
            out["im_url"] = url
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self._guard_blocked(page, "开旺旺")
            frame = self._im_frame(page, min(45.0, timeout_s))
            frame.click(IM_SELECTORS["input"])
            page.keyboard.type(text[:IM_QUESTION_MAX], delay=15)
            page.wait_for_timeout(300)
            typed = str(frame.locator(IM_SELECTORS["input"]).inner_text() or "")
            if text[:20] not in typed:
                self._shot(page, os.path.join(folder, "typing-failed.png"))
                raise SellerChatError("字没打进旺旺输入框", detail=out)
            self._shot(page, os.path.join(folder, "before-send.png"))
            frame.click(IM_SELECTORS["send"])
            msgs: list[dict[str, Any]] = []
            for _ in range(20):
                page.wait_for_timeout(500)
                msgs = list(frame.evaluate(IM_MESSAGES_JS) or [])
                if any(m.get("self") and text[:20] in str(m.get("text") or "") for m in msgs):
                    out["ok"] = True
                    break
            self._shot(page, os.path.join(folder, "after-send.png"))
            out["messages"] = msgs
            out["sent_at"] = self._clock().isoformat()
            if not out["ok"]:
                raise SellerChatError("点了发送,消息列表里没出现这一条", detail=out)
            self._refresh_login()
            return out
        finally:
            if self.status == "asking_seller":
                self._set("idle", dossier_id=None)

    def _do_read_chat(self, url: str, timeout_s: float) -> list[dict[str, Any]]:
        page = self._get_page()
        self._set("asking_seller", reason="在旺旺看卖家回了没", dossier_id=None, url=url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self._guard_blocked(page, "开旺旺")
            frame = self._im_frame(page, min(45.0, timeout_s))
            page.wait_for_timeout(1500)  # 消息列表是后拉的
            self._refresh_login()
            return list(frame.evaluate(IM_MESSAGES_JS) or [])
        finally:
            if self.status == "asking_seller":
                self._set("idle", dossier_id=None)

    def _do_dump(self) -> str:
        """把现在开着的每个标签页都存一份(url/html/各 frame/整页截图),B 期靠它读旺旺 IM 的 DOM。"""
        self._get_page()
        ctx = self._context()
        folder = os.path.join(browser_dump_dir(), self._clock().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(folder, exist_ok=True)
        info: dict[str, Any] = {"current": None, "pages": []}
        for i, page in enumerate(self._open_pages(ctx)):
            if page is self._page:
                info["current"] = i
            entry: dict[str, Any] = {"index": i, "url": "", "title": "", "frames": []}
            try:
                entry["url"], entry["title"] = str(page.url), str(page.title())
                with open(os.path.join(folder, f"page-{i}.html"), "w", encoding="utf-8") as fh:
                    fh.write(page.content())
            except Exception as exc:  # noqa: BLE001 —— 一页存不下来不耽误别的页
                entry["error"] = str(exc)[:300]
            for j, frame in enumerate(getattr(page, "frames", []) or []):
                try:
                    entry["frames"].append({"index": j, "url": frame.url, "name": frame.name})
                    with open(os.path.join(folder, f"page-{i}-frame-{j}.html"), "w", encoding="utf-8") as fh:
                        fh.write(frame.content())
                except Exception:  # noqa: BLE001
                    continue
            try:
                page.screenshot(path=os.path.join(folder, f"page-{i}.png"), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            info["pages"].append(entry)
        with open(os.path.join(folder, "info.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=1)
        logger.info("browser dump saved: %s (%d pages)", folder, len(info["pages"]))
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
        applied: list[str] = []
        if viewer:
            applied = self._apply_inputs(self.store.pop_inputs())
        elif now - self._last_command_scan >= 1.0:
            self._last_command_scan = now
            applied = self._apply_inputs(self.store.pop_inputs(kinds=COMMAND_KINDS))
        applied_s = time.monotonic() - now
        if self.status not in HOLD_STATES:
            return
        frame_s = 0.0
        screen = self._ensure_screen()
        if screen is not None:
            try:
                screen.start() if viewer else screen.stop()
            except Exception as exc:  # noqa: BLE001
                self._warn_frame(exc)
        if viewer and time.monotonic() - self._last_frame >= FRAME_INTERVAL_S:
            self._last_frame = time.monotonic()
            self._push_frame(screen)
            frame_s = time.monotonic() - self._last_frame
        if screen is not None and screen.casting:
            try:
                self._page.wait_for_timeout(PUMP_MS)  # 让 Playwright 的事件循环转一下,推来的帧才会到 Screen 手里
            except Exception:  # noqa: BLE001
                pass
        if applied_s + frame_s > SLOW_TICK_S:
            logger.info("browser tick slow: inputs=%s apply=%.2fs frame=%.2fs", ",".join(applied) or "-", applied_s, frame_s)
        if now - self._last_recovery >= RECOVERY_CHECK_S:
            self._last_recovery = now
            self._check_recovery()
        if self.status == "interactive" and not viewer and now - self._last_activity > browser_idle_minutes() * 60:
            logger.info("interactive browser unused, closing context (profile kept)")
            self._teardown()
            self._set("idle", reason=HOLD_IDLE_REASON, dossier_id=None)
            return
        if self.status == "needs_human" and (self._clock() - self._state_since) > timedelta(minutes=browser_hold_minutes()):
            with self._lock:
                self._recovered = {"outcome": "gave_up", "dossier_id": self.dossier_id, "reason": f"等了 {browser_hold_minutes():g} 分钟没人来过验证"}
            self._set("idle", dossier_id=None)

    def _apply_inputs(self, rows: list[tuple[int, str, dict[str, Any]]]) -> list[str]:
        done: list[str] = []
        for _id, kind, payload in coalesce_inputs(rows):
            done.append(kind)
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
                    self._last_frame = 0.0  # 动了就马上截一帧,老板不用等下一个间隔
            except Exception:  # noqa: BLE001 —— 一下点错了不影响下一下
                logger.exception("browser input %s failed", kind)
        return done

    def _warn_frame(self, exc: BaseException) -> None:
        if time.monotonic() - self._last_frame_warn > 60:  # 一分钟最多记一次
            self._last_frame_warn = time.monotonic()
            logger.warning("browser frame failed: %s", str(exc).splitlines()[0][:200])

    def _push_frame(self, screen: Screen | None = None) -> None:
        if self._page is None:
            return
        if screen is not None:
            raw = screen.take()  # screencast 推来的最新一帧;没新帧就是画面没变
            if not raw:
                return
        else:
            try:
                raw = self._page.screenshot(type="jpeg", quality=FRAME_QUALITY)  # 退路:Chromium 直接出 JPEG(视口就是 1366 宽)
            except Exception as exc:  # noqa: BLE001 —— 截不下来(页面正忙/刚关)就等下一帧
                self._warn_frame(exc)
                return
        digest = hashlib.sha1(raw).hexdigest()
        if digest == self._last_frame_hash:
            return
        self._last_frame_hash = digest
        self.store.push_frame(raw)

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
            # 10-29:登上之后不再自动收回——老板要用这页开商品页、点联系供应商、存页面;状态留在 interactive 直到他点「关掉」或久不用
            # 每 2 秒把现在看着的页(url/title)写回库——跟到旺旺新标签页后面板状态行才会换过来
            if "login.1688.com" not in url and self._refresh_login() and self.reason != LOGGED_IN_REASON:
                self._set("interactive", reason=LOGGED_IN_REASON, dossier_id=None, url=url, title=title)
            else:
                self.store.sync_state(status=self.status, reason=self.reason, url=url, title=title, dossier_id=self.dossier_id, logged_in_at=self.logged_in_at)


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
