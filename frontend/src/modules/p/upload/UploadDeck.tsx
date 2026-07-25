"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Rocket,
  UploadCloud,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  dispatchProducts,
  getBoard,
  getUploadJobs,
  recheckFaq,
  type BoardProduct,
  type BoardResult,
  type FaqRecheckResult,
  type UploadJob,
  type UploadJobsResult,
} from "./api";
import styles from "./UploadDeck.module.css";

const POLL_MS = 12000;

function statusLabel(status: string) {
  switch (status) {
    case "success":
      return "上架成功";
    case "failed":
      return "失败";
    case "dispatched":
      return "n8n 执行中";
    case "queued":
      return "排队中";
    case "pending":
      return "待派单";
    default:
      return status;
  }
}

function formatTime(value: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(
    date.getHours(),
  ).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function UploadDeck() {
  const [board, setBoard] = useState<BoardResult | null>(null);
  const [ledger, setLedger] = useState<UploadJobsResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [faqBusyId, setFaqBusyId] = useState<string | null>(null);
  const [faqResults, setFaqResults] = useState<
    Record<string, FaqRecheckResult>
  >({});
  const [activeTab, setActiveTab] = useState<"pending" | "uploaded" | "ledger">(
    "pending",
  );

  const mounted = useRef(true);
  const timer = useRef<number | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const [boardData, ledgerData] = await Promise.all([
        getBoard(),
        getUploadJobs(80),
      ]);
      if (mounted.current) {
        setBoard(boardData);
        setLedger(ledgerData);
        setError(null);
      }
    } catch (loadError) {
      if (mounted.current) {
        setError(
          loadError instanceof Error ? loadError.message : "驾驶舱数据加载失败。",
        );
      }
    } finally {
      if (mounted.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    timer.current = window.setInterval(() => void load(true), POLL_MS);
    return () => {
      mounted.current = false;
      if (timer.current !== null) {
        window.clearInterval(timer.current);
      }
    };
  }, [load]);

  const handleUpload = useCallback(
    async (productIds: string[], busyKey: string) => {
      setBusyId(busyKey);
      setError(null);
      setNotice(null);
      try {
        const result = await dispatchProducts(productIds);
        const queued = result.queued.length;
        const blocked = result.blocked.length;
        setNotice(
          `已排队 ${queued} 个产品${
            blocked ? `；${blocked} 个未过门禁被拦下` : ""
          } —— 队列严格一个接一个进 n8n，完成会自动流转到「已上传」。`,
        );
        await load(true);
      } catch (uploadError) {
        setError(
          uploadError instanceof Error ? uploadError.message : "上传派单失败。",
        );
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const handleFaqRecheck = useCallback(async (productId: string) => {
    setFaqBusyId(productId);
    try {
      const result = await recheckFaq(productId);
      setFaqResults((prev) => ({ ...prev, [productId]: result }));
    } catch (recheckError) {
      setFaqResults((prev) => ({
        ...prev,
        [productId]: {
          status: "audit_failed",
          ok: false,
          page_url: null,
          schema_faq_count: null,
          visible_faq_present: null,
          missing_from_visible: null,
          message:
            recheckError instanceof Error
              ? recheckError.message
              : "FAQ 复检失败。",
        },
      }));
    } finally {
      setFaqBusyId(null);
    }
  }, []);

  const summary = ledger?.summary;
  const jobs = ledger?.jobs ?? [];
  const pending = board?.pending ?? [];
  const uploaded = board?.uploaded ?? [];
  const readyIds = pending
    .filter((product) => product.gate_ready)
    .map((product) => product.product_id);

  return (
    <div className={styles.deck}>
      <div className={styles.statRow}>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>待上传</span>
          <span className={styles.statValue}>{board ? pending.length : "—"}</span>
        </div>
        <div className={styles.statCard} data-tone="success">
          <span className={styles.statLabel}>已上传</span>
          <span className={styles.statValue}>
            {board ? uploaded.length : "—"}
          </span>
        </div>
        <div className={styles.statCard} data-tone="flight">
          <span className={styles.statLabel}>队列/执行中</span>
          <span className={styles.statValue}>{summary?.in_flight ?? "—"}</span>
        </div>
        <div className={styles.statCard} data-tone="failed">
          <span className={styles.statLabel}>失败</span>
          <span className={styles.statValue}>{summary?.failed ?? "—"}</span>
        </div>
      </div>

      {error ? (
        <div className={styles.state} role="alert">
          <AlertTriangle aria-hidden="true" size={18} />
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? <p className={styles.notice}>{notice}</p> : null}

      {/* ---- 横向分区 tab ---- */}
      <div className={styles.tabs} role="tablist">
        <button
          className={`${styles.tab} ${activeTab === "pending" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("pending")}
          role="tab"
          type="button"
        >
          待上传 <span className={styles.tabCount}>{pending.length}</span>
        </button>
        <button
          className={`${styles.tab} ${activeTab === "uploaded" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("uploaded")}
          role="tab"
          type="button"
        >
          已上传 <span className={styles.tabCount}>{uploaded.length}</span>
        </button>
        <button
          className={`${styles.tab} ${activeTab === "ledger" ? styles.tabOn : ""}`}
          onClick={() => setActiveTab("ledger")}
          role="tab"
          type="button"
        >
          队列与台账 <span className={styles.tabCount}>{jobs.length}</span>
        </button>
      </div>

      {/* ---- 待上传 ---- */}
      {activeTab === "pending" ? (
      <section className={styles.ledger} aria-label="待上传产品">
        <div className={styles.ledgerHead}>
          <span className={styles.ledgerTitle}>
            <UploadCloud aria-hidden="true" size={16} />
            待上传 · K 链路完成的产品（点上传才进队列）
          </span>
          <button
            className="primary-button"
            disabled={busyId !== null || readyIds.length === 0}
            onClick={() => void handleUpload(readyIds, "__batch__")}
            title={
              readyIds.length
                ? `把 ${readyIds.length} 个已过门禁的产品全部排队上传`
                : "没有已过门禁的待上传产品"
            }
            type="button"
          >
            {busyId === "__batch__" ? (
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
            ) : (
              <Rocket aria-hidden="true" size={15} />
            )}
            批量上传（{readyIds.length}）
          </button>
        </div>

        {isLoading && !board ? (
          <div className={styles.state}>
            <LoaderCircle aria-hidden="true" className="spin" size={18} />
            <span>正在加载…</span>
          </div>
        ) : pending.length === 0 ? (
          <div className={styles.emptyHint}>
            <p>
              没有待上传的产品。去 <strong>K系列产品知识库</strong>
              把产品链路走完（文案 / 成品图 / 类目 / 价格 / 品牌审查），
              它们会自动出现在这里。
            </p>
          </div>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>产品</th>
                  <th>价格</th>
                  <th>门禁</th>
                  <th>最近任务</th>
                  <th aria-label="操作" />
                </tr>
              </thead>
              <tbody>
                {pending.map((product: BoardProduct) => (
                  <tr key={product.product_id}>
                    <td className={styles.productCell}>
                      <strong>{product.product_name || "（未命名）"}</strong>
                      <span>{product.sku || product.product_id.slice(0, 8)}</span>
                    </td>
                    <td>{product.price || "—"}</td>
                    <td>
                      {product.gate_ready ? (
                        <span className={styles.statusBadge} data-status="success">
                          就绪
                        </span>
                      ) : (
                        <span
                          className={styles.errorCell}
                          title={product.blockers.join("；")}
                        >
                          {product.blockers.join("；")}
                        </span>
                      )}
                    </td>
                    <td>
                      {product.last_job_status ? (
                        <span
                          className={styles.statusBadge}
                          data-status={product.last_job_status}
                        >
                          {statusLabel(product.last_job_status)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <button
                        className="secondary-button"
                        disabled={busyId !== null || !product.gate_ready}
                        onClick={() =>
                          void handleUpload([product.product_id], product.product_id)
                        }
                        title={
                          product.gate_ready
                            ? "排队上传这个产品"
                            : "先解决门禁问题"
                        }
                        type="button"
                      >
                        {busyId === product.product_id ? (
                          <LoaderCircle
                            aria-hidden="true"
                            className="spin"
                            size={14}
                          />
                        ) : (
                          <UploadCloud aria-hidden="true" size={14} />
                        )}
                        上传
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      ) : null}

      {/* ---- 已上传 ---- */}
      {activeTab === "uploaded" ? (
      <section className={styles.ledger} aria-label="已上传产品">
        <div className={styles.ledgerHead}>
          <span className={styles.ledgerTitle}>
            <CheckCircle2 aria-hidden="true" size={16} />
            已上传 · n8n 回传成功后自动流转到这里
          </span>
        </div>
        {uploaded.length === 0 ? (
          <div className={styles.emptyHint}>
            <p>还没有已上传的产品。</p>
          </div>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>产品</th>
                  <th>价格</th>
                  <th>店铺页</th>
                  <th>FAQ 结构化数据</th>
                  <th>再次上传</th>
                </tr>
              </thead>
              <tbody>
                {uploaded.map((product: BoardProduct) => {
                  const faq = faqResults[product.product_id];
                  return (
                  <tr key={product.product_id}>
                    <td className={styles.productCell}>
                      <strong>{product.product_name || "（未命名）"}</strong>
                      <span>{product.sku || product.product_id.slice(0, 8)}</span>
                    </td>
                    <td>{product.price || "—"}</td>
                    <td>
                      {product.last_external_url ? (
                        <a
                          className={styles.wooLink}
                          href={product.last_external_url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          打开 <ExternalLink aria-hidden="true" size={11} />
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <div className={styles.faqCell}>
                        <button
                          className="secondary-button"
                          disabled={faqBusyId !== null}
                          onClick={() =>
                            void handleFaqRecheck(product.product_id)
                          }
                          title="抓取真实上架页，核对 FAQ 结构化数据与页面可见 FAQ 是否一致"
                          type="button"
                        >
                          {faqBusyId === product.product_id ? (
                            <LoaderCircle
                              aria-hidden="true"
                              className="spin"
                              size={14}
                            />
                          ) : (
                            <RefreshCw aria-hidden="true" size={14} />
                          )}
                          复检
                        </button>
                        {faq ? (
                          <span
                            className={styles.faqResult}
                            data-tone={
                              faq.ok === true
                                ? "ok"
                                : faq.status === "deferred_unpublished"
                                  ? "muted"
                                  : "bad"
                            }
                            title={faq.message}
                          >
                            {faq.ok === true ? (
                              <>
                                <CheckCircle2 aria-hidden="true" size={12} />
                                一致
                                {faq.schema_faq_count != null
                                  ? `（${faq.schema_faq_count}组）`
                                  : ""}
                              </>
                            ) : faq.status === "deferred_unpublished" ? (
                              "页面待发布"
                            ) : (
                              <>
                                <AlertTriangle aria-hidden="true" size={12} />
                                {faq.status === "mismatch"
                                  ? "不一致，请复查"
                                  : faq.message}
                              </>
                            )}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <button
                        className="secondary-button"
                        disabled={busyId !== null || !product.gate_ready}
                        onClick={() =>
                          void handleUpload([product.product_id], product.product_id)
                        }
                        title="内容更新后重新上传（同 SKU 覆盖更新）"
                        type="button"
                      >
                        {busyId === product.product_id ? (
                          <LoaderCircle
                            aria-hidden="true"
                            className="spin"
                            size={14}
                          />
                        ) : (
                          <RefreshCw aria-hidden="true" size={14} />
                        )}
                        更新
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      ) : null}

      {/* ---- 台账 ---- */}
      {activeTab === "ledger" ? (
      <section className={styles.ledger} aria-label="上架台账">
        <div className={styles.ledgerHead}>
          <span className={styles.ledgerTitle}>
            <span className={styles.pulse} aria-hidden="true" />
            队列与台账 · 严格串行：上一单回传后下一单才进 n8n
          </span>
          <button
            className="secondary-button"
            disabled={isLoading}
            onClick={() => void load()}
            type="button"
          >
            {isLoading ? (
              <LoaderCircle aria-hidden="true" className="spin" size={15} />
            ) : (
              <RefreshCw aria-hidden="true" size={15} />
            )}
            刷新
          </button>
        </div>

        {jobs.length === 0 ? (
          <div className={styles.emptyHint}>
            <p>暂无任务记录。</p>
          </div>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>产品</th>
                  <th>状态</th>
                  <th>Woo ID</th>
                  <th>店铺页</th>
                  <th>错误</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job: UploadJob) => (
                  <tr key={job.job_id}>
                    <td className={styles.timeCell}>{formatTime(job.created_at)}</td>
                    <td className={styles.productCell}>
                      <strong>{job.product_name || "（产品已删除）"}</strong>
                      <span>{job.sku || job.product_id.slice(0, 8)}</span>
                    </td>
                    <td>
                      <span className={styles.statusBadge} data-status={job.status}>
                        {statusLabel(job.status)}
                      </span>
                    </td>
                    <td>{job.external_product_id || "—"}</td>
                    <td>
                      {job.external_url ? (
                        <a
                          className={styles.wooLink}
                          href={job.external_url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          打开 <ExternalLink aria-hidden="true" size={11} />
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {job.error ? (
                        <span className={styles.errorCell} title={job.error}>
                          {job.error}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      ) : null}
    </div>
  );
}
