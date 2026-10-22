"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getStatus } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    getStatus()
      .then((s) => router.replace(s.unlocked ? "/redact" : "/unlock"))
      .catch(() => router.replace("/unlock"));
  }, [router]);

  return null;
}
