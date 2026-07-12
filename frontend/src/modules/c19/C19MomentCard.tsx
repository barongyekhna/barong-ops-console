"use client";

import {
  Heart,
  LoaderCircle,
  MessageCircle,
  RefreshCcw,
  Send,
  Trash2,
  Users,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

import {
  createC19MomentComment,
  deleteC19Moment,
  deleteC19MomentComment,
  getC19Moment,
  likeC19Moment,
  listC19MomentComments,
  listC19MomentLikes,
  unlikeC19Moment,
} from "./api";
import {
  C19_MOMENT_COMMENT_MAX_LENGTH,
  c19MomentVisibilityLabel,
  makeC19ClientCommentId,
} from "./C19MomentRuntime";
import { C19MomentImage } from "./C19MomentImage";
import styles from "./C19Moments.module.css";
import type {
  C19Moment,
  C19MomentComment,
  C19MomentLike,
} from "./types";

const INTERACTION_PAGE_LIMIT = 50;

function readableTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function sameUser(left: number | string, right: number | string) {
  return String(left) === String(right);
}

function initials(name: string) {
  const normalized = name.trim();
  return normalized ? normalized.slice(0, 2).toUpperCase() : "成员";
}

function interactionErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录状态已失效，请重新登录。";
    if (error.status === 403 || error.status === 404) return "这条朋友圈已不可用。";
    if (error.status === 409) return error.message || "互动状态发生冲突。";
    if (error.status === 410) return "原互动幂等编号已经失效。";
    if (error.status === 422) return error.message || "评论内容不符合规则。";
    if (error.status === 429) return "操作太频繁，请稍后再试。";
    if (error.status >= 500) return "朋友圈互动服务暂时不可用。";
    return error.message || "朋友圈操作未完成。";
  }
  return error instanceof Error && error.message
    ? error.message
    : "朋友圈操作未完成。";
}

export function C19MomentCard({
  currentUserId,
  moment,
  onChanged,
  onRemoved,
}: {
  currentUserId: number;
  moment: C19Moment;
  onChanged: (moment: C19Moment) => void;
  onRemoved: (momentId: string) => void;
}) {
  const [showComments, setShowComments] = useState(false);
  const [comments, setComments] = useState<C19MomentComment[]>([]);
  const [commentsCursor, setCommentsCursor] = useState<string | null>(null);
  const [commentsLoaded, setCommentsLoaded] = useState(false);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [commentDraft, setCommentDraft] = useState("");
  const [pendingComment, setPendingComment] = useState<{
    clientCommentId: string;
    content: string;
  } | null>(null);
  const pendingCommentRef = useRef(pendingComment);
  const [showLikes, setShowLikes] = useState(false);
  const [likes, setLikes] = useState<C19MomentLike[]>([]);
  const [likesCursor, setLikesCursor] = useState<string | null>(null);
  const [likesLoaded, setLikesLoaded] = useState(false);
  const [likesLoading, setLikesLoading] = useState(false);
  const [likeBusy, setLikeBusy] = useState(false);
  const [commentBusy, setCommentBusy] = useState(false);
  const [deletingCommentId, setDeletingCommentId] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [error, setError] = useState("");
  const activeRef = useRef(true);
  const controllersRef = useRef(new Set<AbortController>());

  pendingCommentRef.current = pendingComment;

  useEffect(
    () => () => {
      activeRef.current = false;
      for (const controller of controllersRef.current) controller.abort();
      controllersRef.current.clear();
    },
    [],
  );

  const controller = useCallback(() => {
    const next = new AbortController();
    controllersRef.current.add(next);
    return next;
  }, []);

  const disposeController = useCallback((value: AbortController) => {
    controllersRef.current.delete(value);
  }, []);

  const removeIfUnavailable = useCallback(
    (requestError: unknown) => {
      if (
        requestError instanceof ApiError &&
        (requestError.status === 403 || requestError.status === 404)
      ) {
        onRemoved(moment.moment_id);
        return true;
      }
      return false;
    },
    [moment.moment_id, onRemoved],
  );

  const handleMomentUnavailable = useCallback(
    () => onRemoved(moment.moment_id),
    [moment.moment_id, onRemoved],
  );

  const refreshCanonical = useCallback(async () => {
    const requestController = controller();
    try {
      const canonical = await getC19Moment(
        moment.moment_id,
        requestController.signal,
      );
      if (activeRef.current && !requestController.signal.aborted) onChanged(canonical);
      return canonical;
    } catch (requestError) {
      if (activeRef.current && !requestController.signal.aborted) {
        if (!removeIfUnavailable(requestError)) throw requestError;
      }
      return null;
    } finally {
      disposeController(requestController);
    }
  }, [controller, disposeController, moment.moment_id, onChanged, removeIfUnavailable]);

  const loadComments = useCallback(
    async (append = false) => {
      if (commentsLoading) return;
      setCommentsLoading(true);
      setError("");
      const requestController = controller();
      const requestedCursor = append ? commentsCursor : null;
      try {
        const page = await listC19MomentComments(
          moment.moment_id,
          { cursor: requestedCursor, limit: INTERACTION_PAGE_LIMIT },
          requestController.signal,
        );
        if (!activeRef.current || requestController.signal.aborted) return;
        setComments((current) => {
          const base = append ? current : [];
          const byId = new Map(base.map((item) => [item.comment_id, item]));
          for (const item of page.comments) byId.set(item.comment_id, item);
          return [...byId.values()];
        });
        setCommentsCursor(page.next_cursor);
        setCommentsLoaded(true);
      } catch (requestError) {
        if (!activeRef.current || requestController.signal.aborted) return;
        if (
          append &&
          requestError instanceof ApiError &&
          (requestError.status === 400 || requestError.status === 422)
        ) {
          setComments([]);
          setCommentsCursor(null);
          setCommentsLoaded(false);
          setShowComments(false);
          setError("评论游标已失效，请重新展开评论。");
        } else if (!removeIfUnavailable(requestError)) {
          setError(interactionErrorMessage(requestError));
        }
      } finally {
        disposeController(requestController);
        if (activeRef.current) setCommentsLoading(false);
      }
    },
    [commentsCursor, commentsLoading, controller, disposeController, moment.moment_id, removeIfUnavailable],
  );

  const loadLikes = useCallback(
    async (append = false) => {
      if (likesLoading) return;
      setLikesLoading(true);
      setError("");
      const requestController = controller();
      const requestedCursor = append ? likesCursor : null;
      try {
        const page = await listC19MomentLikes(
          moment.moment_id,
          { cursor: requestedCursor, limit: INTERACTION_PAGE_LIMIT },
          requestController.signal,
        );
        if (!activeRef.current || requestController.signal.aborted) return;
        setLikes((current) => {
          const base = append ? current : [];
          const byUser = new Map(base.map((item) => [String(item.profile.user_id), item]));
          for (const item of page.likes) {
            byUser.set(String(item.profile.user_id), item);
          }
          return [...byUser.values()];
        });
        setLikesCursor(page.next_cursor);
        setLikesLoaded(true);
      } catch (requestError) {
        if (!activeRef.current || requestController.signal.aborted) return;
        if (
          append &&
          requestError instanceof ApiError &&
          (requestError.status === 400 || requestError.status === 422)
        ) {
          setLikes([]);
          setLikesCursor(null);
          setLikesLoaded(false);
          setShowLikes(false);
          setError("点赞游标已失效，请重新展开点赞成员。");
        } else if (!removeIfUnavailable(requestError)) {
          setError(interactionErrorMessage(requestError));
        }
      } finally {
        disposeController(requestController);
        if (activeRef.current) setLikesLoading(false);
      }
    },
    [controller, disposeController, likesCursor, likesLoading, moment.moment_id, removeIfUnavailable],
  );

  const toggleLike = useCallback(async () => {
    if (likeBusy) return;
    setLikeBusy(true);
    setError("");
    const requestController = controller();
    try {
      if (moment.viewer_has_liked) {
        await unlikeC19Moment(moment.moment_id, requestController.signal);
      } else {
        await likeC19Moment(moment.moment_id, requestController.signal);
      }
      if (!requestController.signal.aborted) {
        await refreshCanonical();
        if (showLikes) await loadLikes(false);
      }
    } catch (requestError) {
      if (activeRef.current && !requestController.signal.aborted) {
        if (!removeIfUnavailable(requestError)) {
          setError(interactionErrorMessage(requestError));
        }
      }
    } finally {
      disposeController(requestController);
      if (activeRef.current) setLikeBusy(false);
    }
  }, [controller, disposeController, likeBusy, loadLikes, moment.moment_id, moment.viewer_has_liked, refreshCanonical, removeIfUnavailable, showLikes]);

  const submitComment = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (commentBusy) return;
      const retry = pendingCommentRef.current;
      const normalized = retry?.content ?? commentDraft.trim();
      if (!normalized) return;
      const pendingValue =
        retry ?? {
          clientCommentId: makeC19ClientCommentId(),
          content: normalized,
        };
      pendingCommentRef.current = pendingValue;
      setPendingComment(pendingValue);
      setCommentBusy(true);
      setError("");
      const requestController = controller();
      try {
        await createC19MomentComment(
          moment.moment_id,
          {
            client_comment_id: pendingValue.clientCommentId,
            content: pendingValue.content,
          },
          requestController.signal,
        );
        if (!activeRef.current || requestController.signal.aborted) return;
        pendingCommentRef.current = null;
        setPendingComment(null);
        setCommentDraft("");
        await Promise.all([loadComments(false), refreshCanonical()]);
      } catch (requestError) {
        if (!activeRef.current || requestController.signal.aborted) return;
        if (!removeIfUnavailable(requestError)) {
          setError(interactionErrorMessage(requestError));
        }
      } finally {
        disposeController(requestController);
        if (activeRef.current) setCommentBusy(false);
      }
    },
    [commentBusy, commentDraft, controller, disposeController, loadComments, moment.moment_id, refreshCanonical, removeIfUnavailable],
  );

  const removeComment = useCallback(
    async (commentId: string) => {
      if (deletingCommentId) return;
      setDeletingCommentId(commentId);
      setError("");
      const requestController = controller();
      try {
        await deleteC19MomentComment(
          moment.moment_id,
          commentId,
          requestController.signal,
        );
        if (!activeRef.current || requestController.signal.aborted) return;
        await Promise.all([loadComments(false), refreshCanonical()]);
      } catch (requestError) {
        if (!activeRef.current || requestController.signal.aborted) return;
        if (!removeIfUnavailable(requestError)) {
          setError(interactionErrorMessage(requestError));
        }
      } finally {
        disposeController(requestController);
        if (activeRef.current) setDeletingCommentId("");
      }
    },
    [controller, deletingCommentId, disposeController, loadComments, moment.moment_id, refreshCanonical, removeIfUnavailable],
  );

  const removeMoment = useCallback(async () => {
    if (deleteBusy || !window.confirm("确定删除这条朋友圈吗？")) return;
    setDeleteBusy(true);
    setError("");
    const requestController = controller();
    try {
      await deleteC19Moment(moment.moment_id, requestController.signal);
      if (activeRef.current && !requestController.signal.aborted) {
        onRemoved(moment.moment_id);
      }
    } catch (requestError) {
      if (activeRef.current && !requestController.signal.aborted) {
        if (!removeIfUnavailable(requestError)) {
          setError(interactionErrorMessage(requestError));
        }
      }
    } finally {
      disposeController(requestController);
      if (activeRef.current) setDeleteBusy(false);
    }
  }, [controller, deleteBusy, disposeController, moment.moment_id, onRemoved, removeIfUnavailable]);

  const ownMoment = sameUser(moment.author.user_id, currentUserId);
  const audienceNames = moment.audience_organizations
    .map((item) => item.org_name)
    .filter(Boolean);

  return (
    <article className={styles.momentCard}>
      <header className={styles.momentHeader}>
        <span aria-hidden="true" className={styles.momentAvatar}>
          {initials(moment.author.display_name)}
        </span>
        <div>
          <strong>{moment.author.display_name}</strong>
          <span>
            {readableTime(moment.created_at)} · {c19MomentVisibilityLabel(moment.visibility)}
            {moment.visibility === "org" && audienceNames.length > 0
              ? `：${audienceNames.join("、")}`
              : ""}
          </span>
        </div>
        {ownMoment ? (
          <button
            aria-label="删除朋友圈"
            className={styles.deleteMomentButton}
            disabled={deleteBusy}
            onClick={() => void removeMoment()}
            type="button"
          >
            {deleteBusy ? <LoaderCircle className={styles.spinner} size={15} /> : <Trash2 size={15} />}
          </button>
        ) : null}
      </header>

      {moment.content ? <p className={styles.momentContent}>{moment.content}</p> : null}
      {moment.assets.length > 0 ? (
        <div className={styles.momentImageGrid} data-count={moment.assets.length}>
          {moment.assets.map((asset) => (
            <C19MomentImage
              asset={asset}
              key={`${moment.moment_id}:${asset.asset_id}:${asset.ordinal}`}
              momentId={moment.moment_id}
              onUnavailable={handleMomentUnavailable}
            />
          ))}
        </div>
      ) : null}

      <div className={styles.momentActions}>
        <button
          aria-pressed={moment.viewer_has_liked}
          className={moment.viewer_has_liked ? styles.likedButton : ""}
          disabled={likeBusy}
          onClick={() => void toggleLike()}
          type="button"
        >
          {likeBusy ? <LoaderCircle className={styles.spinner} size={15} /> : <Heart size={15} />}
          {moment.viewer_has_liked ? "取消点赞" : "点赞"}
        </button>
        <button
          aria-expanded={showLikes}
          onClick={() => {
            const next = !showLikes;
            setShowLikes(next);
            if (next && !likesLoaded) void loadLikes(false);
          }}
          type="button"
        >
          <Users aria-hidden="true" size={15} />{moment.like_count} 人
        </button>
        <button
          aria-expanded={showComments}
          onClick={() => {
            const next = !showComments;
            setShowComments(next);
            if (next && !commentsLoaded) void loadComments(false);
          }}
          type="button"
        >
          <MessageCircle aria-hidden="true" size={15} />{moment.comment_count} 条评论
        </button>
      </div>

      {showLikes ? (
        <section className={styles.likesPanel} aria-label="点赞成员">
          {likesLoading && likes.length === 0 ? <span>正在读取点赞成员…</span> : null}
          {!likesLoading && likesLoaded && likes.length === 0 ? <span>还没有人点赞。</span> : null}
          {likes.length > 0 ? (
            <div className={styles.likeNames}>
              <Heart aria-hidden="true" size={14} />
              {likes.map((like) => like.profile.display_name).join("、")}
            </div>
          ) : null}
          {likesCursor ? (
            <button disabled={likesLoading} onClick={() => void loadLikes(true)} type="button">
              {likesLoading ? "读取中…" : "更多点赞成员"}
            </button>
          ) : null}
        </section>
      ) : null}

      {showComments ? (
        <section className={styles.commentsPanel} aria-label="朋友圈评论">
          {commentsLoading && comments.length === 0 ? <span>正在读取评论…</span> : null}
          {!commentsLoading && commentsLoaded && comments.length === 0 ? <span>还没有评论。</span> : null}
          {comments.map((comment) => (
            <article className={styles.commentRow} key={comment.comment_id}>
              <div>
                <strong>{comment.author.display_name}</strong>
                <p>{comment.content}</p>
                <time dateTime={comment.created_at}>{readableTime(comment.created_at)}</time>
              </div>
              {sameUser(comment.author.user_id, currentUserId) || ownMoment ? (
                <button
                  aria-label={`删除 ${comment.author.display_name} 的评论`}
                  disabled={Boolean(deletingCommentId)}
                  onClick={() => void removeComment(comment.comment_id)}
                  type="button"
                >
                  {deletingCommentId === comment.comment_id ? (
                    <LoaderCircle aria-hidden="true" className={styles.spinner} size={13} />
                  ) : (
                    <Trash2 aria-hidden="true" size={13} />
                  )}
                </button>
              ) : null}
            </article>
          ))}
          {commentsCursor ? (
            <button
              className={styles.moreCommentsButton}
              disabled={commentsLoading}
              onClick={() => void loadComments(true)}
              type="button"
            >
              {commentsLoading ? "读取中…" : "加载更多评论"}
            </button>
          ) : null}
          <form className={styles.commentForm} onSubmit={submitComment}>
            <textarea
              aria-label="评论内容"
              disabled={Boolean(pendingComment)}
              maxLength={C19_MOMENT_COMMENT_MAX_LENGTH}
              onChange={(event) => setCommentDraft(event.target.value)}
              placeholder="写评论…"
              rows={2}
              value={commentDraft}
            />
            <button
              disabled={commentBusy || (!pendingComment && !commentDraft.trim())}
              type="submit"
            >
              {commentBusy ? <LoaderCircle className={styles.spinner} size={14} /> : <Send size={14} />}
              {pendingComment ? "重试" : "评论"}
            </button>
          </form>
          {pendingComment && error ? (
            <button
              className={styles.cancelCommentRetry}
              disabled={commentBusy}
              onClick={() => {
                pendingCommentRef.current = null;
                setPendingComment(null);
                setError("");
              }}
              type="button"
            >
              取消评论重试
            </button>
          ) : null}
        </section>
      ) : null}

      {error ? (
        <div className={styles.runtimeError} role="alert">
          <span>{error}</span>
          <button onClick={() => void refreshCanonical()} type="button">
            <RefreshCcw aria-hidden="true" size={13} />刷新
          </button>
        </div>
      ) : null}
    </article>
  );
}
