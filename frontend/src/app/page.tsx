"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { requiresPasswordChange } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();
  const { status, user } = useAuth();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace(
        requiresPasswordChange(user) ? "/force-password-reset" : "/dashboard",
      );
      return;
    }

    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [router, status, user]);

  return null;
}
