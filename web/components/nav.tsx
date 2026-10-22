"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ShieldCheck,
  Eye,
  FolderOpen,
  Gear,
  ListChecks,
  LockKey,
} from "@phosphor-icons/react";
import { lock as apiLock } from "@/lib/api";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/redact", label: "Redact", icon: ShieldCheck },
  { href: "/reveal", label: "Reveal", icon: Eye },
  { href: "/batch", label: "Batch", icon: FolderOpen },
  { href: "/settings", label: "Settings", icon: Gear },
  { href: "/audit", label: "Audit log", icon: ListChecks },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLock() {
    await apiLock();
    router.replace("/unlock");
  }

  return (
    <nav className="flex w-56 shrink-0 flex-col border-r border-border bg-card px-3 py-6">
      <div className="mb-8 px-2 text-sm font-semibold tracking-tight">local-redact</div>
      <ul className="flex flex-1 flex-col gap-1">
        {LINKS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <li key={href}>
              <Link
                href={href}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                  active
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Icon size={17} weight={active ? "fill" : "regular"} />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
      <button
        onClick={handleLock}
        className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <LockKey size={17} />
        Lock now
      </button>
    </nav>
  );
}
