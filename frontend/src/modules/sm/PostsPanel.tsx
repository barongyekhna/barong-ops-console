"use client";

import { useCallback, useEffect, useState } from "react";

import { OverlayModal } from "@/components/overlay-modal";

import styles from "./SmWorkspace.module.css";
import {
  type MediaRef,
  type PostDetail,
  type PostSummary,
  PILLAR_LABEL,
  PLATFORM_LABEL,
  getPost,
  getPosts,
  markPosted,
  mediaUrl,
  pickImage,
  rejectImage,
} from "./api";

function MediaCard({
  media,
  detail,
  onReject,
  busy,
}: {
  media: MediaRef;
  detail: PostDetail;
  onReject: (assetId: string, reason: string) => void;
  busy: boolean;
}) {
  const [reason, setReason] = useState(detail.reject_reasons[0]?.code ?? "taste");
  const src = mediaUrl(media.thumbnail_url);
  const assetId = media.layout_asset_id ?? media.asset_id;
  return (
    <div className={styles.mediaCard}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img alt={media.overlay_text ?? ""} src={src} />
      ) : (
        <div className={styles.thumbEmpty} style={{ width: 116, height: 116 }}>无图</div>
      )}
      <span className={styles.muted}>#{media.slot} · {media.kind}{media.overlay_text ? ` · “${media.overlay_text}”` : ""}</span>
      <select className={styles.select} onChange={(e) => setReason(e.target.value)} value={reason}>
        {detail.reject_reasons.map((r) => (
          <option key={r.code} value={r.code}>{r.label}</option>
        ))}
      </select>
      <button className={styles.btnDanger} disabled={busy || !assetId} onClick={() => assetId && onReject(assetId, reason)} type="button">驳回这张</button>
    </div>
  );
}

export function PostsPanel({ initialPostId, onChanged, refreshTick }: { initialPostId: string | null; onChanged: () => void; refreshTick: number }) {
  const [posts, setPosts] = useState<PostSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<PostDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [permalink, setPermalink] = useState("");
  const [filter, setFilter] = useState<"all" | "pending" | "approved" | "rejected">("all");

  useEffect(() => {
    let cancelled = false;
    getPosts(filter === "all" ? {} : { review_status: filter })
      .then((data) => {
        if (!cancelled) {
          setPosts(data.posts);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [filter, refreshTick]);

  const openPost = useCallback(async (id: string) => {
    try {
      setDetail(await getPost(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (initialPostId) void openPost(initialPostId);
  }, [initialPostId, openPost]);

  const close = useCallback(() => setDetail(null), []);

  const run = async (action: () => Promise<PostDetail>) => {
    setBusy(true);
    try {
      setDetail(await action());
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.panel}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>帖子</h2>
        <div className={styles.actions}>
          {(["all", "pending", "approved", "rejected"] as const).map((f) => (
            <button className={styles.btnGhost} key={f} onClick={() => setFilter(f)} style={filter === f ? { textDecoration: "underline" } : undefined} type="button">
              {f === "all" ? "全部" : f === "pending" ? "待审" : f === "approved" ? "已批" : "已驳回"}
            </button>
          ))}
          <a className={styles.btn} href="/content-desk">在内容台审</a>
        </div>
      </div>
      {error ? <div className={styles.error}>{error}</div> : null}
      {posts && posts.length === 0 ? <p className={styles.muted}>还没有帖子。在日历里点一格「写这一格」。</p> : null}
      <div className={styles.list}>
        {(posts ?? []).map((post) => {
          const src = mediaUrl(post.media[0]?.thumbnail_url);
          return (
            <button className={styles.rowBtn} key={post.id} onClick={() => openPost(post.id)} type="button">
              {src ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img alt="" className={styles.thumb} src={src} style={{ width: 48, height: 48 }} />
              ) : (
                <span className={styles.thumbEmpty} style={{ width: 48, height: 48 }}>—</span>
              )}
              <span className={styles.slotBody}>
                <span className={styles.slotTitle}>{post.title || post.first_line || "（无标题）"}</span>
                <span className={styles.slotMeta}>
                  <span>{PLATFORM_LABEL[post.platform]}</span>
                  <span className={styles.pillar} data-pillar={post.pillar}>{PILLAR_LABEL[post.pillar]}</span>
                  <span>{post.post_kind_label}</span>
                </span>
              </span>
              <span className={styles.slotMeta}>
                <span className={styles.status} data-status={post.generation_status === "failed" ? "failed" : post.review_status}>
                  {post.generation_status === "failed" ? "写手拒写" : post.review_status}
                </span>
                <span className={styles.status} data-status={post.audit_clean ? "approved" : "pending"}>
                  {post.audit_clean === null ? "未审" : post.audit_clean ? "审计干净" : `审计 ${post.audit_unresolved}`}
                </span>
                {post.publish_status === "posted" ? <span className={styles.status} data-status="posted">已发</span> : null}
              </span>
            </button>
          );
        })}
      </div>

      {detail ? (
        <OverlayModal label="帖子" onClose={close} placement="drawer" width="min(680px, 100%)">
          <div className={styles.drawer}>
            <h3 className={styles.drawerTitle}>{detail.title || "（无标题）"}</h3>
            <dl className={styles.kv}>
              <dt>平台 / 支柱</dt>
              <dd>{PLATFORM_LABEL[detail.platform]} · {PILLAR_LABEL[detail.pillar]} · {detail.post_kind_label}</dd>
              <dt>状态</dt>
              <dd>审核 {detail.review_status} · 生成 {detail.generation_status} · 发布 {detail.publish_status}</dd>
              <dt>关键词</dt>
              <dd>{detail.keyword_primary}{detail.keywords_secondary.length ? ` · ${detail.keywords_secondary.join(", ")}` : ""}</dd>
              {detail.board ? (<><dt>看板</dt><dd>{detail.board}</dd></>) : null}
              <dt>链接</dt>
              <dd className={styles.mono}>{detail.link_url ?? "—"}</dd>
              <dt>标签</dt>
              <dd>{detail.hashtags.length ? detail.hashtags.map((h) => `#${h}`).join(" ") : "（无）"}</dd>
              <dt>facts_used</dt>
              <dd className={styles.mono}>{detail.facts_used.length ? detail.facts_used.join("\n") : "（空）"}</dd>
              <dt>skill</dt>
              <dd>{detail.skill_version} · {detail.provider}</dd>
            </dl>
            {detail.first_line ? <div className={styles.caption}><b>首行：</b>{detail.first_line}</div> : null}
            {detail.caption ? <div className={styles.caption}>{detail.caption}</div> : null}
            {detail.alt_text ? <div className={styles.muted}>ALT：{detail.alt_text}</div> : null}
            {detail.cta ? <div className={styles.muted}>行动：{detail.cta}</div> : null}
            {detail.brand_audit ? (
              <div className={styles.caption}>
                <b>审计：</b>{(detail.brand_audit as { clean?: boolean }).clean ? "干净" : `未解决 ${(detail.brand_audit as { unresolved_count?: number }).unresolved_count ?? "?"} 处`}
                {Array.isArray((detail.brand_audit as { brand_violations?: unknown[] }).brand_violations) && (detail.brand_audit as { brand_violations: { surface: string; term: string; evidence?: string }[] }).brand_violations.length ? (
                  <ul>
                    {(detail.brand_audit as { brand_violations: { surface: string; term: string; evidence?: string }[] }).brand_violations.map((v, i) => (
                      <li key={i}>[{v.surface}] {v.term} {v.evidence ? `— ${v.evidence}` : ""}</li>
                    ))}
                  </ul>
                ) : null}
                <div className={styles.muted}>逐条放行、解读、重写在内容台做。</div>
              </div>
            ) : null}
            <div>
              <div className={styles.laneHead}>图片</div>
              <div className={styles.mediaRow}>
                {detail.media.map((ref, i) => (
                  <MediaCard
                    busy={busy}
                    detail={detail}
                    key={`${ref.asset_id}-${i}`}
                    media={ref}
                    onReject={(assetId, reason) => run(() => rejectImage(detail.id, { asset_id: assetId, reason_code: reason }))}
                  />
                ))}
              </div>
            </div>
            {detail.candidates.length ? (
              <div>
                <div className={styles.laneHead}>候选替代图（点一张直接换第 1 位）</div>
                <div className={styles.mediaRow}>
                  {detail.candidates.map((c) => (
                    <button className={styles.mediaCard} disabled={busy} key={c.asset_id} onClick={() => run(() => pickImage(detail.id, { asset_id: c.asset_id, slot_index: 1 }))} type="button">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img alt={c.asset_role} src={mediaUrl(c.thumbnail_url) ?? ""} />
                      <span className={styles.muted}>{c.asset_role}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div className={styles.actions}>
              <a className={styles.btn} href="/content-desk">去内容台审这条</a>
              {detail.review_status === "approved" && detail.publish_status !== "posted" ? (
                <>
                  <input className={styles.input} onChange={(e) => setPermalink(e.target.value)} placeholder="手发后把帖子链接贴回来" style={{ maxWidth: 320 }} value={permalink} />
                  <button className={styles.btnPrimary} disabled={busy || permalink.trim().length < 8} onClick={() => run(() => markPosted(detail.id, { permalink: permalink.trim() }))} type="button">标记已手动发布</button>
                </>
              ) : null}
              {detail.permalink ? <a className={styles.btn} href={detail.permalink} rel="noreferrer" target="_blank">看已发帖</a> : null}
            </div>
          </div>
        </OverlayModal>
      ) : null}
    </section>
  );
}
