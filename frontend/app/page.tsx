"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/AuthProvider";

export default function Home() {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    router.replace(user ? "/library" : "/login");
  }, [ready, user, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="skeleton h-6 w-40" />
    </div>
  );
}
