"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LockKey, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { getStatus, unlock } from "@/lib/api";

export default function UnlockPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"open" | "create">("open");
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getStatus().then((s) => {
      if (s.unlocked) router.replace("/redact");
    });
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await unlock(passphrase, mode === "create");
      router.replace("/redact");
    } catch (err) {
      setError(
        mode === "open"
          ? "Wrong passphrase, or the database is locked or corrupt."
          : err instanceof Error
            ? err.message
            : "Could not create the database."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4">
      <Card className="w-full max-w-sm border-border">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex size-10 items-center justify-center rounded-full bg-secondary">
            <LockKey size={19} />
          </div>
          <CardTitle className="text-base">local-redact</CardTitle>
          <CardDescription>
            Your encrypted mapping database stays on this machine only.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={mode} onValueChange={(v) => setMode(v as "open" | "create")}>
            <TabsList className="mb-5 w-full">
              <TabsTrigger value="open" className="flex-1">
                Open existing
              </TabsTrigger>
              <TabsTrigger value="create" className="flex-1">
                Create new
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="passphrase">
                {mode === "open" ? "Database passphrase" : "New passphrase"}
              </Label>
              <Input
                id="passphrase"
                type="password"
                autoFocus
                required
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                placeholder="••••••••••••"
              />
            </div>
            {error && (
              <Alert variant="destructive">
                <Warning size={16} />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Button type="submit" disabled={busy || !passphrase} className="w-full">
              {busy ? "Working…" : mode === "open" ? "Unlock" : "Create database"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
