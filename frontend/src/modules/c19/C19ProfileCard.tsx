"use client";

import {
  Ban,
  Building2,
  MessageSquareText,
  UserMinus,
  UserPlus,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import styles from "./C19Workspace.module.css";
import type { C19Affiliation, C19Profile } from "./types";

function initials(name: string) {
  const normalized = name.trim();
  return normalized ? normalized.slice(0, 2).toUpperCase() : "成员";
}

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
  profile: C19Profile;
}) {
  const [requestMessage, setRequestMessage] = useState("");
  const [showRequestForm, setShowRequestForm] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

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
          <span aria-hidden="true" className={styles.profileCardAvatar}>
            {initials(profile.display_name)}
          </span>
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
