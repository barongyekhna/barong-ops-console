"use client";

import {
  Ban,
  Building2,
  Camera,
  MessageSquareText,
  UserMinus,
  UserPlus,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { C19Avatar } from "./C19Avatar";
import styles from "./C19Workspace.module.css";
import type { C19Affiliation, C19Profile } from "./types";

function roleLabel(affiliation: C19Affiliation) {
  return affiliation.role === "owner"
    ? "Owner"
    : affiliation.role === "admin"
      ? "管理员"
      : "成员";
}

export function C19ProfileCard({
  busy,
  isBlocked,
  isFriend,
  isPending,
  isSelf,
  onBlock,
  onClose,
  onRemoveFriend,
  onSendFriendRequest,
  onStartChat,
  onUnblock,
  onUpdateAvatar,
  profile,
}: {
  busy: boolean;
  isBlocked: boolean;
  isFriend: boolean;
  isPending: boolean;
  isSelf: boolean;
  onBlock: (profile: C19Profile) => void;
  onClose: () => void;
  onRemoveFriend: (profile: C19Profile) => void;
  onSendFriendRequest: (profile: C19Profile, message: string) => void;
  onStartChat: (profile: C19Profile) => void;
  onUnblock: (profile: C19Profile) => void;
  onUpdateAvatar: (avatarRef: string | null) => Promise<void>;
  profile: C19Profile;
}) {
  const [avatarDraft, setAvatarDraft] = useState(profile.avatar_ref ?? "");
  const [avatarError, setAvatarError] = useState("");
  const [avatarSaved, setAvatarSaved] = useState("");
  const [requestMessage, setRequestMessage] = useState("");
  const [showRequestForm, setShowRequestForm] = useState(false);

  useEffect(() => {
    setAvatarDraft(profile.avatar_ref ?? "");
  }, [profile.avatar_ref]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const saveAvatar = async (value: string) => {
    const normalized = value.trim();
    setAvatarError("");
    setAvatarSaved("");
    if (
      normalized &&
      (!(
        normalized.startsWith("https://") ||
        (normalized.startsWith("/") && !normalized.startsWith("//"))
      ) ||
        normalized.length > 512)
    ) {
      setAvatarError("请输入 https:// 图片地址或以 / 开头的站内资源路径（最多 512 字符）。");
      return;
    }
    try {
      await onUpdateAvatar(normalized || null);
      setAvatarDraft(normalized);
      setAvatarSaved(normalized ? "头像已更新。" : "已恢复默认头像。");
    } catch (error) {
      setAvatarError(
        error instanceof Error && error.message
          ? error.message
          : "头像更新失败，请稍后重试。",
      );
    }
  };

  return (
    <div
      aria-modal="true"
      className={styles.profileMask}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
    >
      <article
        aria-label={`${profile.display_name} 的名片`}
        className={styles.profileCardModal}
      >
        <button
          aria-label="关闭名片"
          className={styles.profileClose}
          onClick={onClose}
          type="button"
        >
          <X aria-hidden="true" size={17} />
        </button>

        <header className={styles.profileCardHead}>
          <C19Avatar
            avatarRef={profile.avatar_ref}
            className={styles.profileCardAvatar}
            name={profile.display_name}
          />
          <div>
            <strong>
              {profile.display_name}
              {isSelf ? <em className={styles.profileSelfTag}>本人</em> : null}
              {isFriend && !isSelf ? (
                <em className={styles.profileFriendTag}>好友</em>
              ) : null}
            </strong>
            <span>{profile.bio || "这个人还没有填写简介。"}</span>
          </div>
        </header>

        <section
          aria-label="组织身份"
          className={styles.profileOrgList}
        >
          {profile.affiliations.length === 0 ? (
            <span className={styles.profileOrgEmpty}>
              基础通讯用户 · 未加入任何组织
            </span>
          ) : (
            profile.affiliations.map((affiliation) => (
              <span
                className={styles.profileOrgRow}
                key={affiliation.affiliation_id}
              >
                <Building2 aria-hidden="true" size={14} />
                {affiliation.org_name}
                <small>{roleLabel(affiliation)}</small>
              </span>
            ))
          )}
        </section>

        {isSelf ? (
          <form
            className={styles.avatarEditor}
            onSubmit={(event) => {
              event.preventDefault();
              void saveAvatar(avatarDraft);
            }}
          >
            <label htmlFor="c19-avatar-ref">
              <span>
                <Camera aria-hidden="true" size={15} />
                更换头像
              </span>
              <input
                autoComplete="url"
                disabled={busy}
                id="c19-avatar-ref"
                maxLength={512}
                onChange={(event) => {
                  setAvatarDraft(event.target.value);
                  setAvatarError("");
                  setAvatarSaved("");
                }}
                placeholder="https://… 或 /站内资源路径"
                type="text"
                value={avatarDraft}
              />
            </label>
            <small>支持 HTTPS 图片地址或站内绝对路径；加载失败时自动显示姓名首字。</small>
            <div className={styles.avatarEditorActions}>
              <button disabled={busy} type="submit">
                {busy ? "保存中…" : "保存头像"}
              </button>
              <button
                disabled={busy || !profile.avatar_ref}
                onClick={() => void saveAvatar("")}
                type="button"
              >
                恢复默认
              </button>
            </div>
            {avatarError ? <p role="alert">{avatarError}</p> : null}
            {avatarSaved ? <p data-tone="success" role="status">{avatarSaved}</p> : null}
          </form>
        ) : null}

        {!isSelf ? (
          <div className={styles.profileActions}>
            <button
              className={styles.profilePrimaryAction}
              disabled={busy || isBlocked}
              onClick={() => onStartChat(profile)}
              type="button"
            >
              <MessageSquareText aria-hidden="true" size={17} />
              发消息
            </button>

            {showRequestForm && !isFriend && !isPending && !isBlocked ? (
              <form
                className={styles.profileRequestForm}
                onSubmit={(event) => {
                  event.preventDefault();
                  onSendFriendRequest(profile, requestMessage.trim());
                }}
              >
                <input
                  aria-label={`给 ${profile.display_name} 的好友申请说明`}
                  maxLength={500}
                  onChange={(event) => setRequestMessage(event.target.value)}
                  placeholder="申请说明（可选）"
                  value={requestMessage}
                />
                <button disabled={busy} type="submit">
                  发送申请
                </button>
              </form>
            ) : null}

            <div className={styles.profileSecondaryActions}>
              {!isFriend && !isBlocked ? (
                <button
                  disabled={busy || isPending}
                  onClick={() => setShowRequestForm((current) => !current)}
                  type="button"
                >
                  <UserPlus aria-hidden="true" size={15} />
                  {isPending ? "申请处理中" : "加好友"}
                </button>
              ) : null}
              {isFriend ? (
                <button
                  className={styles.dangerButton}
                  disabled={busy}
                  onClick={() => onRemoveFriend(profile)}
                  type="button"
                >
                  <UserMinus aria-hidden="true" size={15} />
                  解除好友
                </button>
              ) : null}
              {isBlocked ? (
                <button
                  disabled={busy}
                  onClick={() => onUnblock(profile)}
                  type="button"
                >
                  解除拉黑
                </button>
              ) : (
                <button
                  className={styles.dangerButton}
                  disabled={busy}
                  onClick={() => onBlock(profile)}
                  type="button"
                >
                  <Ban aria-hidden="true" size={15} />
                  拉黑
                </button>
              )}
            </div>
          </div>
        ) : null}
      </article>
    </div>
  );
}
