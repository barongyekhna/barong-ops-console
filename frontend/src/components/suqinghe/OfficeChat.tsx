"use client";

// 办公室里的聊天窗:就是 C19 那条你和苏青禾的私聊,两边同一份消息。
// 打开时每 3 秒拉一次;发消息走 C19 原接口,她那边照常 3 秒内收到、按人设回话。

import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";

import partStyles from "./Office.module.css";
import styles from "./OfficeScene.module.css";
import { AVATAR_SRC, listChat, officeErrorMessage, openSuqingheChat, sendChat, type ChatMessage } from "./office-api";

const POLL_MS = 3000;

export function OfficeChat({ onSeen }: { onSeen?: (sequence: number) => void }) {
  const { user } = useAuth();
  const myId = String(user?.id ?? "");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let alive = true;
    openSuqingheChat()
      .then((id) => {
        if (!alive) return;
        if (id) setConversationId(id);
        else setError("通讯录里没找到苏青禾。");
      })
      .catch((err: unknown) => alive && setError(officeErrorMessage(err, "打不开和她的对话")));
    return () => {
      alive = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!conversationId) return;
    try {
      const next = await listChat(conversationId);
      setMessages(next);
      const last = next.at(-1);
      if (last) onSeen?.(last.sequence);
    } catch (err: unknown) {
      setError(officeErrorMessage(err, "聊天记录没拉下来"));
    }
  }, [conversationId, onSeen]);

  useEffect(() => {
    if (!conversationId) return undefined;
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [conversationId, refresh]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages.length]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || !conversationId || sending) return;
    setSending(true);
    setError(null);
    try {
      await sendChat(conversationId, text);
      setDraft("");
      await refresh();
    } catch (err: unknown) {
      setError(officeErrorMessage(err, "没发出去"));
    } finally {
      setSending(false);
    }
  };

  return (
    <section className={partStyles.section}>
      <div className={styles.chatLog} ref={logRef} aria-live="polite">
        {messages.length === 0 ? <p className={partStyles.muted}>还没聊过。跟她说句话，或者丢一个 1688 链接给她。</p> : null}
        {messages.map((message) => {
          const mine = String(message.sender_user_id) === myId;
          return (
            <div className={mine ? styles.chatRowMine : styles.chatRowHers} key={message.record_id}>
              {mine ? null : <img alt="" className={styles.chatAvatar} height={28} src={AVATAR_SRC} width={28} />}
              <div className={mine ? styles.chatBubbleMine : styles.chatBubbleHers}>
                {message.content_type === "text" || message.content_type === "emoji" ? message.content : "（附件，去 C19 看）"}
              </div>
            </div>
          );
        })}
      </div>
      {error ? <p className={partStyles.error}>{error}</p> : null}
      <form
        className={styles.chatComposer}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <textarea
          aria-label="跟苏青禾说"
          disabled={!conversationId}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
          placeholder="跟她说点什么…（Enter 发送，Shift+Enter 换行）"
          rows={2}
          value={draft}
        />
        <button className={partStyles.primary} disabled={!draft.trim() || sending || !conversationId} type="submit">
          {sending ? "发送中…" : "发送"}
        </button>
      </form>
      <p className={partStyles.muted}>和 C19 里的私聊是同一条对话。</p>
    </section>
  );
}
