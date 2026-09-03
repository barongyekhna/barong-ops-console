"""图片磁盘缓存的 key 必须包含 URL —— 2026-08-03 熊猫花洒事故的回归防线。

事故：``get_candidate_image`` 的缓存文件名曾是 ``{candidate_id}_{variant}.img``,
不含图片 URL。而 K 的多图导入(manual_reference.attach_manual_reference_images)
对同一产品的 N 个 URL 传的是同一个 candidate_id —— 于是第 1 张落盘后,第 2~N
张全部命中它,把第一张的字节当成自己的内容返回。

这个 bug 伪装得极好:库里 N 条记录各带各的 source_url,看着完全正常,只有文件
内容悄悄是同一张。PSPE-002 因此让 AI 从没见过配件与其他角度,配件图整张靠编
(编出了真实包装里根本不存在的浴球)。

全部离线:monkeypatch 掉 _download,tmp_path 当缓存目录,不出网、不碰 DB。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

_URL_A = "https://cbu01.alicdn.com/img/ibank/aaaaaaaa-0-cib.jpg"
_URL_B = "https://cbu01.alicdn.com/img/ibank/bbbbbbbb-0-cib.jpg"


@pytest.fixture()
def images_module(monkeypatch, tmp_path):
    from backend.app.modules.f_series.enrichment import images

    monkeypatch.setenv("F_IMAGE_CACHE_DIR", str(tmp_path))
    return images


def _fake_downloader(monkeypatch, images, mapping: dict[str, bytes]):
    """按 URL 返回不同字节;并记录实际回源了哪些 URL。"""
    fetched: list[str] = []

    def fake_download(url: str) -> bytes:
        fetched.append(url)
        for key, payload in mapping.items():
            if url.startswith(key):
                return payload
        raise AssertionError(f"unexpected download: {url}")

    monkeypatch.setattr(images, "_download", fake_download)
    return fetched


def test_same_candidate_different_urls_never_share_cache(
    monkeypatch, images_module
) -> None:
    """同一个 candidate_id + 两个不同 URL = 必须拿到两份不同内容。

    这正是熊猫花洒踩的那条路径:K 多图导入对 6 个 URL 用同一个 candidate_id。
    """
    images = images_module
    png_a = b"\x89PNG\r\n\x1a\n" + b"AAAA" * 32
    png_b = b"\x89PNG\r\n\x1a\n" + b"BBBB" * 32
    _fake_downloader(monkeypatch, images, {_URL_A: png_a, _URL_B: png_b})

    data_a, _ = images.get_candidate_image("k-manual-same-product", _URL_A, "full")
    data_b, _ = images.get_candidate_image("k-manual-same-product", _URL_B, "full")

    assert data_a == png_a
    assert data_b == png_b, "第二个 URL 拿回了第一张图 —— 缓存 key 又漏掉 URL 了"


def test_cache_still_hits_for_the_same_url(monkeypatch, images_module) -> None:
    """缓存本身要继续有效:同一 URL 第二次不再回源(这是这个模块存在的理由)。"""
    images = images_module
    png = b"\x89PNG\r\n\x1a\n" + b"CCCC" * 32
    fetched = _fake_downloader(monkeypatch, images, {_URL_A: png})

    first, _ = images.get_candidate_image("cand-1", _URL_A, "full")
    second, _ = images.get_candidate_image("cand-1", _URL_A, "full")

    assert first == second == png
    assert len(fetched) == 1, "同一 URL 第二次不该再回源"


def test_cache_key_separates_variants(monkeypatch, images_module) -> None:
    """thumb / full 仍然各存各的(缩略图不能污染原图)。"""
    images = images_module
    png = b"\x89PNG\r\n\x1a\n" + b"DDDD" * 32
    # thumb 会先试带缩放后缀的 URL,两者都返回同一份字节即可。
    fetched = _fake_downloader(monkeypatch, images, {_URL_A: png})

    images.get_candidate_image("cand-2", _URL_A, "full")
    images.get_candidate_image("cand-2", _URL_A, "thumb")

    assert len(fetched) == 2
    assert fetched[1] != fetched[0], "thumb 变体应当去取缩放后缀 URL"


def test_url_digest_is_stable_and_distinct() -> None:
    from backend.app.modules.f_series.enrichment import images

    assert images._url_digest(_URL_A) == images._url_digest(_URL_A)
    assert images._url_digest(_URL_A) != images._url_digest(_URL_B)
