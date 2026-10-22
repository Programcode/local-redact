"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getStatus } from "@/lib/api";
import { Nav } from "@/components/nav";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getStatus()
      .then((s) => {
        if (cancelled) return;
        if (!s.unlocked) {
          router.replace("/unlock");
        } else {
          setChecked(true);
        }
      })
      .catch(() => {
        if (!cancelled) router.replace("/unlock");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (!checked) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        Checking session…
      </div>
    );
  }

  return (
    <div className="flex flex-1">
      <Nav />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
