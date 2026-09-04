"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { useTheme } from "@/components/theme-provider";
import { getMyProfile, type ProfileMe } from "@/lib/profile-api";

type ProfileContextValue = {
  profile: ProfileMe | null;
  refresh: () => Promise<void>;
  applyProfile: (profile: ProfileMe) => void;
};

const ProfileContext = createContext<ProfileContextValue | null>(null);

export function ProfileProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { setModePref, setSkinPref } = useTheme();
  const [profile, setProfile] = useState<ProfileMe | null>(null);

  const applyProfile = useCallback(
    (next: ProfileMe) => {
      setProfile(next);
      if (next.theme_pref) {
        setModePref(next.theme_pref);
      }
      if (next.skin_pref) {
        setSkinPref(next.skin_pref);
      }
    },
    [setModePref, setSkinPref],
  );

  const refresh = useCallback(async () => {
    try {
      const data = await getMyProfile();
      applyProfile(data);
    } catch {
      /* header simply falls back to the auth username */
    }
  }, [applyProfile]);

  useEffect(() => {
    if (!user) {
      setProfile(null);
      return;
    }
    void refresh();
  }, [user, refresh]);

  return (
    <ProfileContext.Provider value={{ profile, refresh, applyProfile }}>
      {children}
    </ProfileContext.Provider>
  );
}

export function useProfile(): ProfileContextValue {
  const value = useContext(ProfileContext);
  if (value === null) {
    return { profile: null, refresh: async () => undefined, applyProfile: () => undefined };
  }
  return value;
}

/** "nickname（realname）" when a nickname is set, else the real name. */
export function formatDisplayName(
  nickname: string | null | undefined,
  realName: string,
): string {
  const nick = (nickname ?? "").trim();
  return nick ? `${nick}（${realName}）` : realName;
}
