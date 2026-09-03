"use client";

import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Headphones,
  LoaderCircle,
  RefreshCcw,
  Save,
  Send,
  X,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { isApiAbortError } from "@/lib/api";
import { OutboundConfirm } from "@/components/outbound-confirm";

import {
  EMPTY_CS_SUMMARY,
  getCSMessage,
  getCSMessages,
  getCSSummary,
  sendCSReply,
  updateCSMessage,
  type CSChannel,
  type CSMessage,
  type CSMessageStatus,
  type CSSummary,
} from "./api";

type StatusFilter = CSMessageStatus | "";

type ChannelListState = {
  items: CSMessage[];
  total: number;
  page: number;
  pageSize: number;
  pages: number;
  loading: boolean;
  error: string;
};

const CHANNELS: Array<{
  channel: CSChannel;
  label: string;
  shortLabel: string;
}> = [
  { channel: "retail", label: "C端 · 零售咨询", shortLabel: "零售咨询" },
  { channel: "wholesale", label: "B端 · 批发询盘", shortLabel: "批发询盘" },
];

const STATUS_OPTIONS: Array<{ value: CSMessageStatus; label: string }> = [
  { value: "new", label: "新消息" },
  { value: "in_progress", label: "处理中" },
  { value: "resolved", label: "已解决" },
  { value: "spam", label: "垃圾消息" },
];

const MESSAGE_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function emptyListState(): ChannelListState {
  return {
    error: "",
    items: [],
    loading: true,
    page: 1,
    pageSize: 20,
    pages: 1,
    total: 0,
  };
}

function isChannel(value: string | null): value is CSChannel {
  return value === "retail" || value === "wholesale";
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求未完成，请稍后再试。";
}

function statusLabel(status: CSMessageStatus) {
  return STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

function messagePreview(value: string) {
  const normalized = value.replace(/\s+/g, " ").trim();
  const characters = Array.from(normalized);
  return characters.length > 40
    ? `${characters.slice(0, 40).join("")}…`
    : normalized;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function safeSourceUrl(value: string | null) {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
}

function channelHref(channel: CSChannel, messageId?: string | null) {
  const params = new URLSearchParams({ channel });
  if (messageId) {
    params.set("message", messageId);
  }
  return `/cs/customer-service?${params.toString()}`;
}

export function CustomerServiceDeck() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawChannel = searchParams.get("channel");
  const activeChannel: CSChannel = isChannel(rawChannel) ? rawChannel : "retail";
  const rawMessageId = searchParams.get("message");
  const selectedMessageId =
    rawMessageId && MESSAGE_ID_PATTERN.test(rawMessageId) ? rawMessageId : null;
  const [lists, setLists] = useState<Record<CSChannel, ChannelListState>>({
    retail: emptyListState(),
    wholesale: emptyListState(),
  });
  const [filters, setFilters] = useState<Record<CSChannel, StatusFilter>>({
    retail: "",
    wholesale: "",
  });
  const [summary, setSummary] = useState<CSSummary>(EMPTY_CS_SUMMARY);
  const [summaryError, setSummaryError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [detail, setDetail] = useState<CSMessage | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [draftStatus, setDraftStatus] = useState<CSMessageStatus>("new");
  const [draftNote, setDraftNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);
  const [replyBody, setReplyBody] = useState("");
  const [sendingReply, setSendingReply] = useState(false);
  // 待确认的回信。对外动作必须先让人看清代价再点。
  const [pendingReply, setPendingReply] = useState(false);
  const [replyError, setReplyError] = useState("");
  const drawerRef = useRef<HTMLElement>(null);

  const activeList = lists[activeChannel];
  const activeFilter = filters[activeChannel];

  const loadList = useCallback(
    async ({
      channel,
      page,
      signal,
      status,
    }: {
      channel: CSChannel;
      page: number;
      signal?: AbortSignal;
      status: StatusFilter;
    }) => {
      setLists((current) => ({
        ...current,
        [channel]: { ...current[channel], error: "", loading: true },
      }));
      try {
        const result = await getCSMessages({
          channel,
          page,
          signal,
          status: status || undefined,
        });
        setLists((current) => ({
          ...current,
          [channel]: {
            error: "",
            items: result.items,
            loading: false,
            page: result.page,
            pageSize: result.page_size,
            pages: Math.max(1, result.pages),
            total: result.total,
          },
        }));
      } catch (error) {
        if (signal?.aborted || isApiAbortError(error)) return;
        setLists((current) => ({
          ...current,
          [channel]: {
            ...current[channel],
            error: errorMessage(error),
            loading: false,
          },
        }));
      }
    },
    [],
  );

  const refreshSummary = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await getCSSummary(signal);
      setSummary(result);
      setSummaryError("");
    } catch (error) {
      if (signal?.aborted || isApiAbortError(error)) return;
      setSummaryError(errorMessage(error));
    }
  }, []);

  useEffect(() => {
    if (!isChannel(rawChannel) || (rawMessageId && !selectedMessageId)) {
      router.replace(channelHref(activeChannel, selectedMessageId), {
        scroll: false,
      });
    }
  }, [activeChannel, rawChannel, rawMessageId, router, selectedMessageId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadList({
      channel: activeChannel,
      page: activeList.page,
      signal: controller.signal,
      status: activeFilter,
    });
    return () => controller.abort();
  }, [activeChannel, activeFilter, activeList.page, loadList]);

  useEffect(() => {
    const controller = new AbortController();
    void refreshSummary(controller.signal);
    return () => controller.abort();
  }, [refreshSummary]);

  useEffect(() => {
    if (!selectedMessageId) {
      setDetail(null);
      setDetailError("");
      setDetailLoading(false);
      return;
    }

    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError("");
    void getCSMessage(selectedMessageId, controller.signal)
      .then((message) => {
        setDetail(message);
        if (message.channel !== activeChannel) {
          router.replace(channelHref(message.channel, message.id), {
            scroll: false,
          });
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted && !isApiAbortError(error)) {
          setDetailError(errorMessage(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [activeChannel, router, selectedMessageId]);

  useEffect(() => {
    if (!detail) return;
    setDraftStatus(detail.status);
    setDraftNote(detail.internal_note ?? "");
    setSaveError("");
    setSaved(false);
    setReplyBody("");
    setReplyError("");
  }, [detail?.id]);

  useEffect(() => {
    if (!selectedMessageId) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawerRef.current?.focus({ preventScroll: true });
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        router.replace(channelHref(activeChannel), { scroll: false });
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [activeChannel, router, selectedMessageId]);

  const channelMeta = useMemo(
    () => CHANNELS.find((entry) => entry.channel === activeChannel) ?? CHANNELS[0],
    [activeChannel],
  );

  function selectChannel(channel: CSChannel) {
    if (channel !== activeChannel) {
      router.replace(channelHref(channel), { scroll: false });
    }
  }

  function openMessage(message: CSMessage) {
    setDetail(message);
    router.replace(channelHref(message.channel, message.id), { scroll: false });
  }

  function closeDrawer() {
    router.replace(channelHref(activeChannel), { scroll: false });
  }

  function handleRowKeyDown(
    event: ReactKeyboardEvent<HTMLTableRowElement>,
    message: CSMessage,
  ) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openMessage(message);
    }
  }

  function changeFilter(value: StatusFilter) {
    setFilters((current) => ({ ...current, [activeChannel]: value }));
    setLists((current) => ({
      ...current,
      [activeChannel]: { ...current[activeChannel], page: 1 },
    }));
  }

  function changePage(page: number) {
    setLists((current) => ({
      ...current,
      [activeChannel]: {
        ...current[activeChannel],
        page: Math.max(1, Math.min(page, current[activeChannel].pages)),
      },
    }));
  }

  async function handleRefresh() {
    setRefreshing(true);
    await Promise.all([
      loadList({
        channel: activeChannel,
        page: activeList.page,
        status: activeFilter,
      }),
      refreshSummary(),
    ]);
    setRefreshing(false);
  }

  async function handleSave() {
    if (!detail || saving) return;
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      const updated = await updateCSMessage(detail.id, {
        internal_note: draftNote.trim() || null,
        status: draftStatus,
      });
      // PATCH intentionally returns the light message shape. Keep the detail
      // thread already loaded in the drawer while applying status/note edits.
      setDetail((current) =>
        current?.id === updated.id
          ? { ...updated, replies: current.replies ?? [] }
          : current,
      );
      setLists((current) => ({
        ...current,
        [updated.channel]: {
          ...current[updated.channel],
          items: current[updated.channel].items.map((item) =>
            item.id === updated.id ? updated : item,
          ),
        },
      }));
      setSaved(true);
      await Promise.all([
        refreshSummary(),
        loadList({
          channel: activeChannel,
          page: activeList.page,
          status: activeFilter,
        }),
      ]);
    } catch (error) {
      setSaveError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  function handleReply() {
    // 只弹确认，不发送。邮件发出即不可撤回，而这个按钮以前是 onClick 直连
    // sendCSReply —— 后端收到就立刻 POST 到 WP relay 真发（"Send exactly once"）。
    // 2026-08-31 体检时收件箱里 4 条有 2 条是 SEO 垃圾推销，误点等于向垃圾
    // 发送方确认 service@ 是活邮箱。
    const body = replyBody.trim();
    if (!detail || sendingReply || !body) return;
    setPendingReply(true);
  }

  async function doSendReply() {
    const body = replyBody.trim();
    if (!detail || sendingReply || !body) return;
    setPendingReply(false);

    const messageId = detail.id;
    const previousStatus = detail.status;
    setSendingReply(true);
    setReplyError("");

    try {
      const reply = await sendCSReply(messageId, body);
      setReplyBody("");
      setDetail((current) => {
        if (!current || current.id !== messageId) return current;
        const replies = current.replies ?? [];
        return {
          ...current,
          replies: replies.some((item) => item.id === reply.id)
            ? replies
            : [...replies, reply],
          status:
            current.status === "new" ? "in_progress" : current.status,
        };
      });
      setLists((current) => ({
        ...current,
        [detail.channel]: {
          ...current[detail.channel],
          items: current[detail.channel].items.map((item) =>
            item.id === messageId && item.status === "new"
              ? { ...item, status: "in_progress" }
              : item,
          ),
        },
      }));
      if (previousStatus === "new") {
        setDraftStatus("in_progress");
      }

      // Reconcile server-owned timestamps/status without holding the composer
      // in a loading state. A refresh failure must not misreport a sent email.
      void getCSMessage(messageId)
        .then((message) => {
          setDetail((current) =>
            current?.id === messageId ? message : current,
          );
        })
        .catch(() => undefined);
      void refreshSummary();
      void loadList({
        channel: activeChannel,
        page: activeList.page,
        status: activeFilter,
      });
    } catch (error) {
      setReplyError(errorMessage(error));
      // The backend persists failed delivery attempts before returning 502.
      // Pull that audit row back so the red failed bubble stays in the thread.
      void getCSMessage(messageId)
        .then((message) => {
          setDetail((current) =>
            current?.id === messageId ? message : current,
          );
        })
        .catch(() => undefined);
    } finally {
      setSendingReply(false);
    }
  }

  const columnCount = activeChannel === "wholesale" ? 6 : 5;
  const detailSourceUrl = safeSourceUrl(detail?.source_url ?? null);

  return (
    <section className="cs-service-deck" aria-label="客服中心收件箱">
      <header className="cs-command-bar">
        <div>
          <span className="cs-command-eyebrow">CUSTOMER SERVICE / INBOX</span>
          <p>零售咨询与批发询盘物理分队，分别处理、分别计数。</p>
        </div>
        <button
          className="secondary-button cs-refresh-button"
          disabled={refreshing}
          onClick={() => void handleRefresh()}
          type="button"
        >
          <RefreshCcw
            aria-hidden="true"
            className={refreshing ? "spin" : undefined}
            size={16}
          />
          {refreshing ? "刷新中" : "刷新"}
        </button>
      </header>

      <div className="cs-team-tabs" role="tablist" aria-label="客服分队">
        {CHANNELS.map((entry) => (
          <button
            aria-controls={`cs-panel-${entry.channel}`}
            aria-selected={activeChannel === entry.channel}
            className={activeChannel === entry.channel ? "active" : undefined}
            id={`cs-tab-${entry.channel}`}
            key={entry.channel}
            onClick={() => selectChannel(entry.channel)}
            role="tab"
            type="button"
          >
            <span>{entry.label}</span>
            <span
              className="cs-new-count"
              data-has-new={summary[entry.channel].new > 0}
              title={`${entry.shortLabel} ${summary[entry.channel].new} 条新消息`}
            >
              new {summary[entry.channel].new}
            </span>
          </button>
        ))}
      </div>

      {summaryError ? (
        <p className="cs-inline-warning" role="status">
          <AlertTriangle aria-hidden="true" size={15} />
          新消息计数暂时无法刷新，列表仍可继续处理。
        </p>
      ) : null}

      <div
        aria-labelledby={`cs-tab-${activeChannel}`}
        className="cs-team-panel"
        id={`cs-panel-${activeChannel}`}
        role="tabpanel"
      >
        <div className="cs-list-toolbar">
          <div>
            <strong>{channelMeta.label}</strong>
            <span>{activeList.total} 条记录</span>
          </div>
          <label>
            <span>状态</span>
            <select
              aria-label={`${channelMeta.shortLabel}状态筛选`}
              onChange={(event) => changeFilter(event.target.value as StatusFilter)}
              value={activeFilter}
            >
              <option value="">全部状态</option>
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {activeList.error ? (
          <div className="cs-error-banner" role="alert">
            <AlertTriangle aria-hidden="true" size={17} />
            <span>{activeList.error}</span>
            <button onClick={() => void handleRefresh()} type="button">
              重试
            </button>
          </div>
        ) : null}

        <div className="cs-table-shell">
          <table className="cs-message-table">
            <thead>
              <tr>
                <th>状态</th>
                <th>姓名</th>
                <th>Email</th>
                {activeChannel === "wholesale" ? <th>公司</th> : null}
                <th>消息摘要</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {activeList.loading && activeList.items.length === 0 ? (
                <tr>
                  <td className="cs-table-state" colSpan={columnCount}>
                    <LoaderCircle aria-hidden="true" className="spin" size={18} />
                    正在加载{channelMeta.shortLabel}…
                  </td>
                </tr>
              ) : null}
              {!activeList.loading &&
              activeList.items.length === 0 &&
              !activeList.error ? (
                <tr>
                  <td className="cs-table-state" colSpan={columnCount}>
                    <Headphones aria-hidden="true" size={18} />
                    当前分队暂无消息
                  </td>
                </tr>
              ) : null}
              {activeList.items.map((message) => (
                <tr
                  aria-label={`打开 ${message.name} 的${channelMeta.shortLabel}`}
                  className={message.status === "new" ? "cs-row-new" : undefined}
                  key={message.id}
                  onClick={() => openMessage(message)}
                  onKeyDown={(event) => handleRowKeyDown(event, message)}
                  tabIndex={0}
                >
                  <td>
                    <span className="cs-status-badge" data-status={message.status}>
                      {statusLabel(message.status)}
                    </span>
                  </td>
                  <td className="cs-name-cell">{message.name}</td>
                  <td>{message.email}</td>
                  {activeChannel === "wholesale" ? (
                    <td>{message.company || "—"}</td>
                  ) : null}
                  <td className="cs-preview-cell">{messagePreview(message.message)}</td>
                  <td>
                    <time dateTime={message.created_at}>
                      {formatTime(message.created_at)}
                    </time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {activeList.loading && activeList.items.length > 0 ? (
            <div className="cs-table-loading" role="status">
              <LoaderCircle aria-hidden="true" className="spin" size={16} />
              正在更新
            </div>
          ) : null}
        </div>

        <footer className="cs-pagination">
          <span>
            第 {activeList.page} / {activeList.pages} 页 · 每页 {activeList.pageSize} 条
          </span>
          <div>
            <button
              aria-label="上一页"
              disabled={activeList.loading || activeList.page <= 1}
              onClick={() => changePage(activeList.page - 1)}
              type="button"
            >
              <ChevronLeft aria-hidden="true" size={16} />
              上一页
            </button>
            <button
              aria-label="下一页"
              disabled={activeList.loading || activeList.page >= activeList.pages}
              onClick={() => changePage(activeList.page + 1)}
              type="button"
            >
              下一页
              <ChevronRight aria-hidden="true" size={16} />
            </button>
          </div>
        </footer>
      </div>

      {selectedMessageId ? (
        <div
          className="cs-drawer-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDrawer();
          }}
        >
          <aside
            aria-labelledby="cs-detail-title"
            aria-modal="true"
            className="cs-detail-drawer"
            ref={drawerRef}
            role="dialog"
            tabIndex={-1}
          >
            <header className="cs-drawer-header">
              <div>
                <span className="cs-command-eyebrow">
                  {activeChannel === "retail" ? "C TEAM" : "B TEAM"} / MESSAGE
                </span>
                <h2 id="cs-detail-title">{detail?.name || "消息详情"}</h2>
              </div>
              <button
                aria-label="关闭消息详情"
                className="cs-drawer-close"
                onClick={closeDrawer}
                type="button"
              >
                <X aria-hidden="true" size={20} />
              </button>
            </header>

            {replyError ? (
              <div className="cs-reply-toast" role="alert">
                <AlertTriangle aria-hidden="true" size={17} />
                <span>{replyError}</span>
                <button
                  aria-label="关闭发送失败提示"
                  onClick={() => setReplyError("")}
                  type="button"
                >
                  <X aria-hidden="true" size={15} />
                </button>
              </div>
            ) : null}

            {detailLoading && !detail ? (
              <div className="cs-drawer-state" role="status">
                <LoaderCircle aria-hidden="true" className="spin" size={20} />
                正在加载消息详情…
              </div>
            ) : null}
            {detailError ? (
              <div className="cs-error-banner" role="alert">
                <AlertTriangle aria-hidden="true" size={17} />
                {detailError}
              </div>
            ) : null}

            {detail ? (
              <div className="cs-drawer-body">
                <div className="cs-detail-topline">
                  <span className="cs-status-badge" data-status={detail.status}>
                    {statusLabel(detail.status)}
                  </span>
                  <time dateTime={detail.created_at}>{formatTime(detail.created_at)}</time>
                </div>

                <section className="cs-detail-section">
                  <h3>客户信息</h3>
                  <dl className="cs-detail-grid">
                    <div>
                      <dt>Email</dt>
                      <dd>
                        <a href={`mailto:${detail.email}`}>{detail.email}</a>
                      </dd>
                    </div>
                    <div>
                      <dt>{detail.channel === "wholesale" ? "公司" : "订单号"}</dt>
                      <dd>
                        {detail.channel === "wholesale"
                          ? detail.company || "—"
                          : detail.order_number || "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>来源页面</dt>
                      <dd>
                        {detailSourceUrl ? (
                          <a href={detailSourceUrl} rel="noreferrer" target="_blank">
                            {detail.source_url}
                            <ExternalLink aria-hidden="true" size={13} />
                          </a>
                        ) : (
                          detail.source_url || "—"
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>访客 IP</dt>
                      <dd>{detail.client_ip || "—"}</dd>
                    </div>
                    <div className="cs-detail-wide">
                      <dt>User Agent</dt>
                      <dd>{detail.user_agent || "—"}</dd>
                    </div>
                  </dl>
                </section>

                <section className="cs-detail-section cs-conversation-section">
                  <h3>会话</h3>
                  <div className="cs-conversation-line" aria-label="客服会话记录">
                    <article className="cs-message-bubble cs-message-bubble-buyer">
                      <header>
                        <strong>{detail.name}</strong>
                        <time dateTime={detail.created_at}>
                          {formatTime(detail.created_at)}
                        </time>
                      </header>
                      <p>{detail.message}</p>
                    </article>

                    {(detail.replies ?? []).map((reply) => (
                      <article
                        className="cs-message-bubble cs-message-bubble-agent"
                        data-delivery={reply.delivery_status}
                        key={reply.id}
                      >
                        <header>
                          <strong>客服回复</strong>
                          <span
                            className="cs-delivery-badge"
                            data-delivery={reply.delivery_status}
                          >
                            {reply.delivery_status === "sent"
                              ? "已发送"
                              : "发送失败"}
                          </span>
                          <time dateTime={reply.created_at}>
                            {formatTime(reply.created_at)}
                          </time>
                        </header>
                        <p>{reply.body}</p>
                        {reply.delivery_status === "failed" &&
                        reply.provider_note ? (
                          <small className="cs-provider-note">
                            {reply.provider_note}
                          </small>
                        ) : null}
                      </article>
                    ))}
                  </div>

                  <form
                    className="cs-reply-composer"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void handleReply();
                    }}
                  >
                    <label htmlFor="cs-reply-body">写回信</label>
                    <textarea
                      disabled={sendingReply}
                      id="cs-reply-body"
                      maxLength={10000}
                      onChange={(event) => {
                        setReplyBody(event.target.value);
                        setReplyError("");
                      }}
                      placeholder="输入将通过 service@barongyekhna.com 发给买家的内容"
                      rows={5}
                      value={replyBody}
                    />
                    <div className="cs-reply-actions">
                      <span>{replyBody.length} / 10000</span>
                      <button
                        className="primary-button cs-send-reply-button"
                        disabled={sendingReply || !replyBody.trim()}
                        type="submit"
                      >
                        {sendingReply ? (
                          <LoaderCircle
                            aria-hidden="true"
                            className="spin"
                            size={16}
                          />
                        ) : (
                          <Send aria-hidden="true" size={16} />
                        )}
                        {sendingReply ? "发送中" : "发送回复"}
                      </button>
                    </div>
                    {pendingReply && detail ? (
                      <OutboundConfirm
                        busy={sendingReply}
                        confirmLabel="确认发送"
                        consequence={
                          "邮件一旦发出**不可撤回**。请确认收件人是真实买家 —— " +
                          "对垃圾推销回信等于向对方确认这个邮箱是活的。"
                        }
                        details={[
                          `收件人：${detail.email ?? "(未知)"}`,
                          `正文 ${replyBody.trim().length} 字`,
                        ]}
                        onCancel={() => setPendingReply(false)}
                        onConfirm={() => {
                          void doSendReply();
                        }}
                        title="确认给买家发送这封回信？"
                      />
                    ) : null}
                    <small className="cs-reply-boundary-note">
                      买家的回信会送达 service@ 邮箱(Titan),暂不回流控制台
                    </small>
                  </form>
                </section>

                <section className="cs-detail-section cs-workbench">
                  <h3>客服处理</h3>
                  <label>
                    <span>状态</span>
                    <select
                      disabled={saving}
                      onChange={(event) => {
                        setDraftStatus(event.target.value as CSMessageStatus);
                        setSaved(false);
                      }}
                      value={draftStatus}
                    >
                      {STATUS_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>内部备注</span>
                    <textarea
                      disabled={saving}
                      maxLength={5000}
                      onChange={(event) => {
                        setDraftNote(event.target.value);
                        setSaved(false);
                      }}
                      placeholder="仅客服团队可见，不会发送给客户"
                      rows={6}
                      value={draftNote}
                    />
                  </label>
                  {saveError ? (
                    <p className="cs-save-error" role="alert">
                      <AlertTriangle aria-hidden="true" size={15} />
                      {saveError}
                    </p>
                  ) : null}
                  {saved ? (
                    <p className="cs-save-success" role="status">
                      状态与内部备注已保存。
                    </p>
                  ) : null}
                  <button
                    className="primary-button cs-save-button"
                    disabled={saving}
                    onClick={() => void handleSave()}
                    type="button"
                  >
                    {saving ? (
                      <LoaderCircle aria-hidden="true" className="spin" size={16} />
                    ) : (
                      <Save aria-hidden="true" size={16} />
                    )}
                    {saving ? "保存中" : "保存处理结果"}
                  </button>
                </section>
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}
    </section>
  );
}
