"""她的登录浏览器(10-28)的纯逻辑:状态机(抓页 → 被拦留页等老板 → 老板过了自己接着做 / 等不到人放弃)、
老板动作的映射与合并、登录判断、新标签页跟随、导航白名单、渲染结果 → Capture 的半段、迁移文件。
unit:浏览器用假的 page/context,库用假的 store,不起 Chromium、不连库。"""

from __future__ import annotations

import io
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from backend.app.modules.agent_series.suqinghe import browser, sourcing_1688

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "sqh1688" / "offer_1057528621016"
GOOD_URL = "https://detail.1688.com/offer/1057528621016.html"


def _shot(fmt: str = "JPEG", color: tuple[int, int, int] = (120, 140, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1366, 900), color).save(buffer, fmt)
    return buffer.getvalue()


class FakeMouse:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def click(self, x: float, y: float) -> None:
        self.log.append(("click", (x, y)))

    def move(self, x: float, y: float, steps: int = 1) -> None:
        self.log.append(("move", (x, y)))

    def down(self) -> None:
        self.log.append(("down", None))

    def up(self) -> None:
        self.log.append(("up", None))

    def wheel(self, dx: float, dy: float) -> None:
        self.log.append(("wheel", dy))


class FakeKeyboard:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def type(self, text: str, delay: int = 0) -> None:
        self.log.append(("type", text))

    def press(self, key: str) -> None:
        self.log.append(("press", key))


class FakePage:
    """可编程的页面:url/title/html 随时能改,模拟 1688 从验证页变回商品页。"""

    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []
        self.mouse = FakeMouse(self.log)
        self.keyboard = FakeKeyboard(self.log)
        self.url = "about:blank"
        self._title = ""
        self._html = "<html></html>"
        self._text = ""
        self.shots = 0
        self.shot_kwargs: dict[str, Any] = {}
        self.frames: list[Any] = []
        self.handlers: dict[str, Any] = {}
        self._closed = False
        self.color = (120, 140, 200)

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    def close(self) -> None:
        self._closed = True
        if "close" in self.handlers:
            self.handlers["close"](self)

    def goto(self, url: str, **kwargs: Any) -> None:
        self.log.append(("goto", url))
        self.url = url

    def title(self) -> str:
        return self._title

    def content(self) -> str:
        return self._html

    def inner_text(self, selector: str) -> str:
        return self._text

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        pass

    def evaluate(self, script: str) -> str:
        return self._text

    def screenshot(self, **kwargs: Any) -> bytes:
        self.shots += 1
        self.shot_kwargs = kwargs
        if kwargs.get("path"):
            Path(kwargs["path"]).write_bytes(_shot("PNG", self.color))
            return b""
        return _shot("JPEG" if kwargs.get("type") == "jpeg" else "PNG", self.color)

    def is_closed(self) -> bool:
        return self._closed


class FakeContext:
    def __init__(self, page: FakePage, cookies: list[dict[str, Any]] | None = None) -> None:
        self.page = page
        self.pages = [page]
        self._cookies = cookies or []
        self.closed = False
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    def open_popup(self, url: str) -> FakePage:
        """像 1688 的「联系供应商」那样在新标签页里开一页。"""
        popup = FakePage()
        popup.url = url
        popup.color = (30, 160, 60)
        self.pages.append(popup)
        self.handlers["page"](popup)
        return popup

    def new_page(self) -> FakePage:
        return self.page

    def cookies(self, url: str) -> list[dict[str, Any]]:
        return self._cookies

    def close(self) -> None:
        self.closed = True

    def set_default_timeout(self, ms: int) -> None:
        pass


class FakeStore:
    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []
        self.frames: list[bytes] = []
        self.inputs: list[tuple[int, str, dict[str, Any]]] = []
        self.viewer = False

    def sync_state(self, **values: Any) -> None:
        self.states.append(values)

    def push_frame(self, jpeg: bytes) -> None:
        self.frames.append(jpeg)

    def viewer_recent(self, seconds: float = 5.0) -> bool:
        return self.viewer

    def pop_inputs(self, *, limit: int = 20, kinds: tuple[str, ...] | None = None) -> list[tuple[int, str, dict[str, Any]]]:
        take = [row for row in self.inputs if kinds is None or row[1] in kinds][:limit]
        self.inputs = [row for row in self.inputs if row not in take]
        return take

    def cleanup_inputs(self, **kwargs: Any) -> int:
        return 0


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _wait(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture
def session():
    page = FakePage()
    ctx = FakeContext(page)
    store = FakeStore()
    clock = Clock()
    detect = {"result": "captcha_page"}
    sess = browser.BrowserSession(store=store, launcher=lambda: ctx, clock=clock, detect_blocked=lambda **kw: detect["result"])
    sess.start()
    try:
        yield sess, page, ctx, store, clock, detect
    finally:
        sess.stop_flag.set()
        sess.join(timeout=3)


# ---------------------------------------------------------------- 纯函数


def test_apply_input_maps_each_kind_and_drops_bad_ones() -> None:
    page = FakePage()
    assert browser.apply_input(page, "click", {"x": 10, "y": 20}) and page.log[-1] == ("click", (10.0, 20.0))
    assert browser.apply_input(page, "down", {"x": 1, "y": 2}) and page.log[-2:] == [("move", (1.0, 2.0)), ("down", None)]
    assert browser.apply_input(page, "move", {"x": 50, "y": 2}) and page.log[-1] == ("move", (50.0, 2.0))
    assert browser.apply_input(page, "up", {"x": 90, "y": 2}) and page.log[-1] == ("up", None)
    assert browser.apply_input(page, "type", {"text": "abc"}) and page.log[-1] == ("type", "abc")
    assert browser.apply_input(page, "key", {"key": "Enter"}) and page.log[-1] == ("press", "Enter")
    assert browser.apply_input(page, "wheel", {"x": 5, "y": 5, "dy": 600}) and page.log[-1] == ("wheel", 600.0)
    assert browser.apply_input(page, "navigate", {"url": GOOD_URL}) and page.log[-1] == ("goto", GOOD_URL)
    n = len(page.log)
    assert not browser.apply_input(page, "click", {"x": 2000, "y": 20})  # 越界
    assert not browser.apply_input(page, "click", {"x": "a", "y": 20})
    assert not browser.apply_input(page, "key", {"key": "F12"})  # 不在白名单
    assert not browser.apply_input(page, "type", {"text": ""})
    assert not browser.apply_input(page, "navigate", {"url": "https://evil.example/x"})
    assert not browser.apply_input(page, "explode", {})
    assert len(page.log) == n


def test_coalesce_inputs_merges_runs_of_wheel_and_move_but_keeps_order() -> None:
    rows = [
        (1, "wheel", {"x": 10, "y": 10, "dy": 30}),
        (2, "wheel", {"x": 20, "y": 20, "dy": 40}),
        (3, "wheel", {"x": 20, "y": 20, "dy": -10}),
        (4, "click", {"x": 5, "y": 5}),
        (5, "move", {"x": 1, "y": 1}),
        (6, "move", {"x": 2, "y": 2}),
        (7, "wheel", {"x": 9, "y": 9, "dy": 5}),
        (8, "wheel", {"x": 9, "y": 9, "dy": "bad"}),
    ]
    out = browser.coalesce_inputs(rows)
    assert [(k, p.get("dy"), p.get("x")) for _, k, p in out] == [("wheel", 60.0, 20), ("click", None, 5), ("move", None, 2), ("wheel", 5, 9), ("wheel", "bad", 9)]
    assert browser.coalesce_inputs([]) == []


def test_login_cookies_and_url_allowlist() -> None:
    assert browser.logged_in([{"name": "cookie2", "value": "x"}, {"name": "cna"}])
    assert not browser.logged_in([{"name": "cna"}, {"name": "isg"}]) and not browser.logged_in([])
    assert browser.allowed_url("https://login.1688.com/member/signin.htm") and browser.allowed_url("https://1688.com/")
    assert not browser.allowed_url("https://detail.1688.com.evil.com/x") and not browser.allowed_url("ftp://1688.com") and not browser.allowed_url("")


def test_capture_from_render_parses_a_good_page_and_flags_a_blocked_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sourcing_1688, "fetch_detail_description", lambda url, **kw: (FIXTURE.with_suffix(".desc.txt").read_text(encoding="utf-8"), None))
    capture = sourcing_1688.capture_from_render(
        offer_id="1057528621016",
        target=GOOD_URL,
        final_url=GOOD_URL,
        title="捏捏乐 - 阿里巴巴",
        html=FIXTURE.with_suffix(".html").read_text(encoding="utf-8"),
        text=FIXTURE.with_suffix(".txt").read_text(encoding="utf-8"),
    )
    assert not capture.blocked and capture.skus and capture.detail_images and capture.detail_error is None
    blocked = sourcing_1688.capture_from_render(offer_id="1", target=GOOD_URL, final_url=GOOD_URL, title="安全验证", html="<html></html>", text="")
    assert blocked.blocked and blocked.block_reason.startswith("title:")


def test_fetch_offer_marks_needs_human_when_the_login_browser_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[str] = []

    class Fake:
        def fetch_offer_html(self, url: str, timeout_s: float):
            return url, "安全验证", "<div id='nc_1_n1z'>滑动验证</div>", ""

        def hold_for_human(self, reason: str, **kw: Any) -> None:
            held.append(reason)

    monkeypatch.setenv("SQH_BROWSER", "1")
    monkeypatch.setattr(browser, "get", lambda: Fake())
    capture = sourcing_1688.fetch_offer(GOOD_URL)
    assert capture.blocked and capture.block_reason == "needs_human:title:安全验证" and held == ["title:安全验证"]
    monkeypatch.setenv("SQH_BROWSER", "0")
    monkeypatch.setattr(sourcing_1688, "_render_page", lambda url, timeout_s: (url, "安全验证", "<html></html>", ""))
    plain = sourcing_1688.fetch_offer(GOOD_URL)
    assert plain.blocked and plain.block_reason == "title:安全验证"  # 开关关着还是老样子


def test_migration_file_chains_from_the_dossier_migration() -> None:
    text = (Path(__file__).resolve().parents[2] / "backend" / "alembic" / "versions" / "20261028_01_suqinghe_browser.py").read_text(encoding="utf-8")
    assert 'revision = "20261028_01_suqinghe_browser"' in text and 'down_revision = "20261023_01_suqinghe_dossiers"' in text
    assert "sqh_browser_inputs" in text and "'needs_human'" in text and "autovacuum_vacuum_threshold" in text


# ---------------------------------------------------------------- 状态机(真线程 + 假浏览器)


def test_fetch_then_hold_then_boss_solves_then_resume(session) -> None:
    sess, page, ctx, store, clock, detect = session
    page._title, page._html, page._text = "安全验证", "<div id='nc_1_n1z'>滑动验证</div>", "滑动验证"
    final_url, title, html, text = sess.fetch_offer_html(GOOD_URL, 5)
    assert final_url == GOOD_URL and title == "安全验证" and "nc_1_n1z" in html
    assert sess.status == "idle" and [s["status"] for s in store.states][-2:] == ["fetching", "idle"]
    # 被拦:页面留着,进 needs_human;记上档案号
    sess.hold_for_human("captcha_page", dossier_id=7)
    assert sess.status == "needs_human" and sess.dossier_id == 7 and store.states[-1]["dossier_id"] == 7
    # 没人看:不截图;老板打开面板:开始出帧;点一下滑块:动作落到页面上
    time.sleep(0.5)
    assert page.shots == 0 and store.frames == []
    store.viewer = True
    assert _wait(lambda: len(store.frames) >= 1)
    assert page.shot_kwargs == {"type": "jpeg", "quality": browser.FRAME_QUALITY} and Image.open(io.BytesIO(store.frames[0])).size == (1366, 900)  # Chromium 直接出 JPEG,原尺寸
    first = page.shots
    store.inputs.append((1, "down", {"x": 100, "y": 500}))
    store.inputs.append((2, "move", {"x": 300, "y": 500}))
    store.inputs.append((3, "up", {"x": 300, "y": 500}))
    assert _wait(lambda: ("up", None) in page.log)
    assert ("down", None) in page.log and ("move", (300.0, 500.0)) in page.log
    # 同一张画面不重复写库
    time.sleep(1.6)
    assert page.shots > first and len(store.frames) == 1
    # 页面恢复成商品页:自愈,状态回 idle,主线程取走一次
    page._title, page._html, page._text = "捏捏乐 - 阿里巴巴", "<html>window.context offerDetail skuMap</html>", "正文"
    detect["result"] = None
    assert _wait(lambda: sess.status == "idle", timeout=4)
    event = sess.take_recovered()
    assert event and event["outcome"] == "recovered" and event["dossier_id"] == 7 and event["title"] == "捏捏乐 - 阿里巴巴" and "offerDetail" in event["html"]
    assert sess.take_recovered() is None  # 只给一次
    assert sess.snapshot()["status"] == "idle" and store.states[-1]["dossier_id"] is None


def test_hold_gives_up_after_the_limit_and_close_counts_as_giving_up(session, monkeypatch: pytest.MonkeyPatch) -> None:
    sess, page, ctx, store, clock, detect = session
    monkeypatch.setenv("SQH_BROWSER_HOLD_MINUTES", "30")
    sess.fetch_offer_html(GOOD_URL, 5)
    sess.hold_for_human("captcha_page", dossier_id=9)
    clock.now += timedelta(minutes=31)
    assert _wait(lambda: sess.status == "idle", timeout=4)
    event = sess.take_recovered()
    assert event and event["outcome"] == "gave_up" and event["dossier_id"] == 9 and "30 分钟" in event["reason"]
    # 再拦一次,老板直接点「关掉」:也算放弃,浏览器关了
    sess.fetch_offer_html(GOOD_URL, 5)
    sess.hold_for_human("captcha_page", dossier_id=10)
    store.inputs.append((5, "close", {}))
    assert _wait(lambda: sess.status == "idle" and ctx.closed, timeout=4)
    event = sess.take_recovered()
    assert event and event["outcome"] == "gave_up" and event["dossier_id"] == 10


def test_login_flow_records_logged_in_when_cookies_arrive(session) -> None:
    sess, page, ctx, store, clock, detect = session
    store.inputs.append((1, "login", {}))
    assert _wait(lambda: sess.status == "interactive", timeout=4)
    assert page.url == browser.LOGIN_URL and sess.logged_in_at is None
    # 老板扫码:页面跳走、登录 cookie 出现
    ctx._cookies = [{"name": "cookie2", "value": "x"}, {"name": "_tb_token_", "value": "y"}]
    page.url = "https://www.1688.com/"
    assert _wait(lambda: sess.reason == browser.LOGGED_IN_REASON, timeout=4)
    assert sess.status == "interactive" and sess.logged_in_at == clock.now and store.states[-1]["logged_in_at"] == clock.now
    # 10-29:登上后页面留给老板用(开商品页、存页面),不自动收;老板点「关掉」才回 idle
    store.viewer = True  # 老板开着面板(点/贴地址只在有人看时才应用)
    store.inputs.append((2, "navigate", {"url": "https://detail.1688.com/offer/1.html"}))
    assert _wait(lambda: page.url == "https://detail.1688.com/offer/1.html", timeout=4)
    assert sess.status == "interactive"
    store.inputs.append((3, "close", {}))
    assert _wait(lambda: sess.status == "idle", timeout=4)
    assert ctx.closed


def test_contact_seller_popup_is_followed_and_dump_covers_every_tab(session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10-29 老板实况:点「联系供应商」,1688 把旺旺开在新标签页,面板却一直盯着商品页,看着像没反应。"""
    sess, page, ctx, store, clock, detect = session
    monkeypatch.setattr(browser, "browser_dump_dir", lambda: str(tmp_path))
    store.viewer = True
    store.inputs.append((1, "login", {}))
    assert _wait(lambda: sess.status == "interactive" and len(store.frames) >= 1, timeout=4)
    page.url = "https://detail.1688.com/offer/643348607768.html"
    before = len(store.frames)
    popup = ctx.open_popup("https://air.1688.com/app/ocms-fusion-components-1688/def_cbu_web_im/index.html?offerId=643348607768")
    # 面板跟到新页:接下来的帧是新页截的(颜色不同),库里的 url 也换成旺旺页
    assert _wait(lambda: popup.shots >= 1 and len(store.frames) > before, timeout=4)
    assert Image.open(io.BytesIO(store.frames[-1])).getpixel((5, 5))[1] > 120  # 新页是绿的
    assert _wait(lambda: (store.states[-1].get("url") or "").startswith("https://air.1688.com/"), timeout=4)
    # 点和滚落到新页上,不落到商品页
    store.inputs.append((2, "wheel", {"x": 100, "y": 100, "dy": 120}))
    store.inputs.append((3, "wheel", {"x": 100, "y": 100, "dy": 80}))
    assert _wait(lambda: ("wheel", 200.0) in popup.log, timeout=4)  # 两条合成一下
    assert not [e for e in page.log if e[0] == "wheel"]
    # 存一份页面:每个标签页都存
    store.inputs.append((4, "dump", {}))
    assert _wait(lambda: (tmp_path / "20261028-100000" / "info.json").exists(), timeout=4)
    folder = tmp_path / "20261028-100000"
    info = json.loads((folder / "info.json").read_text())
    assert info["current"] == 1 and [p["url"] for p in info["pages"]] == [page.url, popup.url]
    assert (folder / "page-0.html").exists() and (folder / "page-1.html").exists() and (folder / "page-1.png").exists()
    # 旺旺页关了:退回商品页,不掉成 idle
    popup.close()
    assert _wait(lambda: sess._page is page, timeout=4)
    time.sleep(0.3)
    assert sess.status == "interactive"
    store.inputs.append((5, "close", {}))
    assert _wait(lambda: sess.status == "idle", timeout=4)


def test_stale_singleton_files_are_cleared_before_launch(tmp_path: Path) -> None:
    # 10-28 实况:上一个容器留下 SingletonLock -> 7a17bfe4ceca-50(旧主机名),新容器主机名不同,Chromium 会拒绝起
    (tmp_path / "SingletonLock").symlink_to("7a17bfe4ceca-50")
    (tmp_path / "SingletonCookie").symlink_to("14917247614385835859")
    (tmp_path / "SingletonSocket").symlink_to("/tmp/org.chromium.Chromium.x/SingletonSocket")
    (tmp_path / "Default").mkdir()
    assert sorted(browser.clear_stale_singleton(str(tmp_path))) == ["SingletonCookie", "SingletonLock", "SingletonSocket"]
    assert not any((tmp_path / n).is_symlink() for n in browser.SINGLETON_FILES) and (tmp_path / "Default").is_dir()
    assert browser.clear_stale_singleton(str(tmp_path)) == []


def test_shutdown_closes_the_context_and_stops_the_thread(session, monkeypatch: pytest.MonkeyPatch) -> None:
    sess, page, ctx, store, clock, detect = session
    store.inputs.append((1, "login", {}))
    assert _wait(lambda: sess.status == "interactive", timeout=4)
    monkeypatch.setattr(browser, "_session", sess)
    assert browser.shutdown(timeout_s=5)
    assert ctx.closed and not sess.is_alive() and store.states[-1]["status"] == "idle"
    assert browser._session is None and not browser.shutdown()


def test_status_helpers_treat_a_disabled_browser_as_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQH_BROWSER", "0")
    assert browser.status()["status"] == "idle" and not browser.holding() and not browser.enabled()
    monkeypatch.setenv("SQH_BROWSER", "1")
    assert browser.enabled()
    monkeypatch.setattr(browser, "_session", None)
    assert browser.status() == {"status": "idle", "reason": None, "dossier_id": None, "logged_in_at": None, "alive": False}
