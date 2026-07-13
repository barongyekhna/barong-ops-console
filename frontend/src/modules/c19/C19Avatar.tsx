"use client";

import { useEffect, useState } from "react";

function initials(name: string) {
  const normalized = name.trim();
  return normalized ? normalized.slice(0, 2).toUpperCase() : "成员";
}

export function C19Avatar({
  avatarRef,
  className,
  name,
}: {
  avatarRef: string | null | undefined;
  className: string;
  name: string;
}) {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [avatarRef]);

  return (
    <span aria-hidden="true" className={className}>
      {avatarRef && !imageFailed ? (
        <img
          alt=""
          decoding="async"
          loading="lazy"
          onError={() => setImageFailed(true)}
          referrerPolicy="no-referrer"
          src={avatarRef}
        />
      ) : (
        initials(name)
      )}
    </span>
  );
}
