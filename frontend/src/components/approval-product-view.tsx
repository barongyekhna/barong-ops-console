"use client";

import {
  CheckCircle2,
  Clock3,
  ExternalLink,
  Layers3,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useAuth } from "@/components/auth-provider";
import {
  approveApproval,
  getApprovalDetail,
  listApprovals,
  rejectApproval,
  type ApprovalCategory,
  type ApprovalDetail,
  type ApprovalListItem,
  type ApprovalListResponse,
} from "@/lib/approval";
import {
  ApiRequestAbortedError,
  ApiTimeoutError,
  isApiAbortError,
} from "@/lib/api";

type ApprovalSectionState = {
  data: ApprovalListResponse | null;
  error: string;
  loading: boolean;
};

const EMPTY_SECTION: ApprovalSectionState = {
  data: null,
  error: "",
  loading: true,
};
const PREVIEW_LIMIT = 10;
const FULL_LIST_LIMIT = 10;
const REJECT_REASON_MIN_LENGTH = 15;

function emptyApprovalListResponse(): ApprovalListResponse {
  return {
    count: 0,
    cursor: null,
    degraded: false,
    items: [],
    limit: 0,
    message: "",
    next_cursor: null,
    offset: 0,
    source: "local",
    status: "ok",
  };
}

function errorText(error: unknown, fallback: string) {
  void error;
  return fallback;
}

function approvalListErrorText(error: unknown) {
  if (error instanceof ApiTimeoutError) {
    return "加载失败，请稍后重试。";
  }
  return errorText(error, "加载失败，请稍后重试。");
}

function formatDate(value: string) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return "时间待确认";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestamp));
}

function categoryTitle(category: ApprovalCategory) {
  return category === "control_plane" ? "主控审批" : "功能审批";
}

function categoryDescription(category: ApprovalCategory) {
  return category === "control_plane"
    ? "系统级操作、权限变更、模块接入等需要owner确认的审批。"
    : "业务模块提交后的审批。";
}

function detailHref(approval: ApprovalListItem) {
  return `/approvals/${encodeURIComponent(approval.approval_id)}`;
}

function canDecide(detail: ApprovalDetail | null, action: "approve" | "reject") {
  return (
    detail?.approval.status === "pending" &&
    detail.permission_boundary.allowed_actions.includes(action)
  );
}

function ApprovalListRows({ items }: { items: ApprovalListItem[] }) {
  if (items.length === 0) {
    return (
      <div className="approval-empty">
        <strong>暂无待处理审批</strong>
        <span>有新的业务草稿提交后会出现在这里。</span>
      </div>
    );
  }

  return (
    <ol className="approval-list">
      {items.map((approval) => (
        <li key={approval.approval_id}>
          <a
            className="approval-row"
            href={detailHref(approval)}
            rel="noreferrer"
            target="_blank"
          >
            <span className="approval-row-main">
              <strong>{approval.display.title}</strong>
              <small>{approval.display.summary}</small>
            </span>
            <span className="approval-row-meta">
              <span>{approval.display.module_label}</span>
              <span>{approval.display.risk_label}</span>
              <span>{formatDate(approval.request_time)}</span>
            </span>
            <span className={`approval-status approval-status-${approval.status}`}>
              {approval.display.status_label}
            </span>
            <ExternalLink aria-hidden="true" size={16} />
          </a>
        </li>
      ))}
    </ol>
  );
}

function ApprovalSection({
  category,
  icon,
  isOwner,
  onRefresh,
  state,
}: {
  category: ApprovalCategory;
  icon: "control" | "feature";
  isOwner: boolean;
  onRefresh: () => void;
  state: ApprovalSectionState;
}) {
  const items = state.data?.items ?? [];
  const showMore = isOwner && items.length >= PREVIEW_LIMIT;
  const Icon = icon === "control" ? ShieldCheck : Layers3;
  const hasDegradedEmptyData =
    state.data?.status === "degraded" && items.length === 0;

  return (
    <section
      className={`approval-section approval-section-${category}`}
      aria-label={categoryTitle(category)}
    >
      <div className="approval-section-heading">
        <div className="approval-heading-copy">
          <span className="approval-section-icon">
            <Icon aria-hidden="true" size={18} />
          </span>
          <div>
            <h2>{categoryTitle(category)}</h2>
            <p>{categoryDescription(category)}</p>
          </div>
        </div>
        <div className="approval-section-actions">
          {showMore ? (
            <Link
              className="secondary-button"
              href={`/approvals/more?category=${category}`}
            >
              查看更多
            </Link>
          ) : null}
          <button
            className="icon-button"
            disabled={state.loading}
            onClick={onRefresh}
            title="刷新"
            type="button"
          >
            {state.loading ? (
              <LoaderCircle aria-hidden="true" className="spin" size={18} />
            ) : (
              <RotateCcw aria-hidden="true" size={18} />
            )}
          </button>
        </div>
      </div>

      {state.error ? (
        <div className="approval-empty approval-empty-error" role="alert">
          <strong>
            {state.data === null ? "审批列表暂时不可用" : "审批列表降级显示"}
          </strong>
          <span>{state.error}</span>
          {state.data !== null ? (
            <span>正在显示上一次成功加载的审批列表。</span>
          ) : null}
        </div>
      ) : null}

      {state.loading && state.data === null ? (
        <div className="approval-empty" role="status">
          <LoaderCircle aria-hidden="true" className="spin" size={18} />
          <span>正在加载审批</span>
        </div>
      ) : null}

      {state.data !== null &&
      !hasDegradedEmptyData &&
      (!state.loading || items.length > 0) ? (
        <ApprovalListRows items={items} />
      ) : null}
    </section>
  );
}

export function ApprovalConsoleView() {
  const { isOwner, user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin" || user?.role === "admin";
  const [control, setControl] = useState<ApprovalSectionState>(EMPTY_SECTION);
  const [feature, setFeature] = useState<ApprovalSectionState>(EMPTY_SECTION);
  const controlAbortRef = useRef<AbortController | null>(null);
  const featureAbortRef = useRef<AbortController | null>(null);

  const loadSection = useCallback(
    async (
      category: ApprovalCategory,
      setter: Dispatch<SetStateAction<ApprovalSectionState>>,
      abortRef: { current: AbortController | null },
    ) => {
      const previous = abortRef.current;
      if (previous && !previous.signal.aborted) {
        previous.abort(new ApiRequestAbortedError("审批列表请求已被替换。"));
      }
      const controller = new AbortController();
      abortRef.current = controller;
      setter((current) => ({ ...current, error: "", loading: true }));
      try {
        const data = await listApprovals({
          category,
          limit: PREVIEW_LIMIT,
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setter({
            data,
            error: data.status === "degraded" ? data.message : "",
            loading: false,
          });
        }
      } catch (error) {
        if (isApiAbortError(error) && !(error instanceof ApiTimeoutError)) {
          return;
        }
        setter((current) => ({
          data: current.data,
          error: approvalListErrorText(error),
          loading: false,
        }));
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [],
  );

  const loadControl = useCallback(() => {
    if (!isOwner) {
      setControl({
        data: emptyApprovalListResponse(),
        error: "",
        loading: false,
      });
      return;
    }
    void loadSection("control_plane", setControl, controlAbortRef);
  }, [isOwner, loadSection]);

  const loadFeature = useCallback(() => {
    void loadSection("feature", setFeature, featureAbortRef);
  }, [loadSection]);

  useEffect(() => {
    loadControl();
    loadFeature();

    return () => {
      for (const ref of [controlAbortRef, featureAbortRef]) {
        const controller = ref.current;
        if (controller && !controller.signal.aborted) {
          controller.abort(new ApiRequestAbortedError("审批列表请求已取消。"));
        }
        ref.current = null;
      }
    };
  }, [loadControl, loadFeature]);

  return (
    <section className="approval-console" aria-label="审批列表">
      <div className="approval-page-heading">
        <div>
          <span className="eyebrow">审批中心</span>
          <h2>审批列表</h2>
          <p>
            {isOwner
              ? "按主控审批和功能审批分组处理。"
              : isSuperAdmin
                ? "仅显示当前组织的功能审批。"
                : "仅显示你有权限模块的功能审批。"}
          </p>
        </div>
      </div>

      <div className="approval-board">
        {isOwner ? (
          <ApprovalSection
            category="control_plane"
            icon="control"
            isOwner={isOwner}
            onRefresh={loadControl}
            state={control}
          />
        ) : null}
        <ApprovalSection
          category="feature"
          icon="feature"
          isOwner={isOwner}
          onRefresh={loadFeature}
          state={feature}
        />
      </div>
    </section>
  );
}

export function ApprovalMoreView() {
  const searchParams = useSearchParams();
  const category = searchParams.get("category") === "control_plane"
    ? "control_plane"
    : "feature";
  const [state, setState] = useState<ApprovalSectionState>(EMPTY_SECTION);
  const [offset, setOffset] = useState(0);

  const load = useCallback(async () => {
    setState((current) => ({ ...current, error: "", loading: true }));
    try {
      const data = await listApprovals({
        category,
        limit: FULL_LIST_LIMIT,
        offset,
      });
      setState({
        data,
        error: data.status === "degraded" ? data.message : "",
        loading: false,
      });
    } catch (error) {
      setState((current) => ({
        data: current.data,
        error: approvalListErrorText(error),
        loading: false,
      }));
    }
  }, [category, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="approval-console" aria-label={`${categoryTitle(category)}列表`}>
      <div className="approval-page-heading">
        <div>
          <span className="eyebrow">审批中心</span>
          <h2>{categoryTitle(category)}列表</h2>
          <p>{categoryDescription(category)}</p>
        </div>
        <Link className="secondary-button" href="/approvals">
          返回审批列表
        </Link>
      </div>

      <ApprovalSection
        category={category}
        icon={category === "control_plane" ? "control" : "feature"}
        isOwner={false}
        onRefresh={load}
        state={state}
      />
      <div className="review-pager">
        <button
          className="secondary-button"
          disabled={state.loading || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - FULL_LIST_LIMIT))}
          type="button"
        >
          上一页
        </button>
        <span>{Math.floor(offset / FULL_LIST_LIMIT) + 1}</span>
        <button
          className="secondary-button"
          disabled={
            state.loading ||
            (state.data?.items.length ?? 0) < FULL_LIST_LIMIT
          }
          onClick={() => setOffset(offset + FULL_LIST_LIMIT)}
          type="button"
        >
          下一页
        </button>
      </div>
    </section>
  );
}

export function ApprovalDetailView() {
  const params = useParams<{ approvalId: string }>();
  const approvalId = useMemo(
    () => decodeURIComponent(params.approvalId ?? ""),
    [params.approvalId],
  );
  const [detail, setDetail] = useState<ApprovalDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [submitting, setSubmitting] = useState<"approve" | "reject" | null>(
    null,
  );

  const load = useCallback(async () => {
    if (!approvalId) {
      setError("审批不存在。");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setDetail(await getApprovalDetail(approvalId));
    } catch (requestError) {
      setError(errorText(requestError, "审批详情加载失败。"));
    } finally {
      setLoading(false);
    }
  }, [approvalId]);

  useEffect(() => {
    void load();
  }, [load]);

  const rejectRemaining = Math.max(
    0,
    REJECT_REASON_MIN_LENGTH - rejectReason.trim().length,
  );
  const approveEnabled = canDecide(detail, "approve") && submitting === null;
  const rejectEnabled =
    canDecide(detail, "reject") &&
    rejectRemaining === 0 &&
    submitting === null;

  async function handleApprove() {
    if (!approvalId || !approveEnabled) {
      return;
    }
    setSubmitting("approve");
    setNotice("");
    setError("");
    try {
      setDetail(await approveApproval(approvalId));
      setNotice("审批已同意。");
    } catch (requestError) {
      setError(errorText(requestError, "审批提交失败。"));
    } finally {
      setSubmitting(null);
    }
  }

  async function handleReject() {
    if (!approvalId || !rejectEnabled) {
      return;
    }
    setSubmitting("reject");
    setNotice("");
    setError("");
    try {
      setDetail(await rejectApproval(approvalId, rejectReason.trim()));
      setRejectReason("");
      setNotice("审批已拒绝。");
    } catch (requestError) {
      setError(errorText(requestError, "审批提交失败。"));
    } finally {
      setSubmitting(null);
    }
  }

  if (loading) {
    return (
      <section className="approval-detail-shell" aria-label="审批详情">
        <div className="approval-empty" role="status">
          <LoaderCircle aria-hidden="true" className="spin" size={20} />
          <span>正在加载审批详情</span>
        </div>
      </section>
    );
  }

  if (error && detail === null) {
    return (
      <section className="approval-detail-shell" aria-label="审批详情">
        <div className="approval-empty approval-empty-error" role="alert">
          <strong>审批详情不可用</strong>
          <span>{error}</span>
        </div>
      </section>
    );
  }

  return (
    <section className="approval-detail-shell" aria-label="审批详情">
      <div className="approval-detail-top">
        <span className="eyebrow">{detail?.display.category_label ?? "审批"}</span>
        <h2>{detail?.display.title ?? "审批详情"}</h2>
        <div className="approval-detail-meta">
          <span className={`approval-status approval-status-${detail?.approval.status ?? "pending"}`}>
            {detail?.display.status_label ?? "待审批"}
          </span>
          <span>{detail?.display.risk_label ?? "标准风险"}</span>
          <span>{formatDate(detail?.approval.request_time ?? "")}</span>
        </div>
      </div>

      <div className="approval-detail-summary">
        <Clock3 aria-hidden="true" size={20} />
        <p>{detail?.display.summary ?? "业务模块已完成草稿，即将提交审批"}</p>
      </div>

      {notice ? (
        <p className="approval-notice" role="status">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="approval-notice approval-notice-error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="approval-decision-panel">
        <button
          className="primary-button"
          disabled={!approveEnabled}
          onClick={() => void handleApprove()}
          type="button"
        >
          {submitting === "approve" ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <CheckCircle2 aria-hidden="true" size={17} />
          )}
          同意
        </button>

        <div className="approval-reject-box">
          <label className="field-group">
            <span>拒绝原因</span>
            <span className="textarea-shell">
              <textarea
                disabled={!canDecide(detail, "reject") || submitting !== null}
                onChange={(event) => setRejectReason(event.target.value)}
                value={rejectReason}
              />
            </span>
          </label>
          <div className="approval-reject-footer">
            <span>{rejectRemaining > 0 ? `还需 ${rejectRemaining} 字` : "原因已满足"}</span>
            <button
              className="danger-button"
              disabled={!rejectEnabled}
              onClick={() => void handleReject()}
              type="button"
            >
              {submitting === "reject" ? (
                <LoaderCircle aria-hidden="true" className="spin" size={17} />
              ) : (
                <XCircle aria-hidden="true" size={17} />
              )}
              拒绝
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
