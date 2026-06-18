"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

export default function HomePage() {
  const router = useRouter();
  const { status, user } = useAuth();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace(
        user?.must_change_password ? "/force-password-reset" : "/dashboard",
      );
      return;
    }

    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [router, status, user?.must_change_password]);

  return null;
}
