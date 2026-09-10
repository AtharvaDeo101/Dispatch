"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

export function useAuth() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const router = useRouter();

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/me`, {
          credentials: "include",
        });

        if (res.ok) {
          const data = await res.json();
          if ("emailAddress" in data) {
            setIsAuthenticated(true);
            return;
          }
        }
      } catch {
        // network error — treat as unauthenticated
      }

      setIsAuthenticated(false);
      router.replace("/login");
    };

    check();
  }, [router]);

  return isAuthenticated;
}