"use client";

import { useEffect, useState } from "react";
import { Trash, Plus, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  getCategories,
  setCategory,
  listTerms,
  addTerm,
  removeTerm,
  wipe as apiWipe,
  ApiError,
} from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/entity-types";
import { useRouter } from "next/navigation";

export default function SettingsPage() {
  const router = useRouter();
  const [toggles, setToggles] = useState<Record<string, boolean> | null>(null);
  const [defaults, setDefaults] = useState<Record<string, boolean>>({});
  const [terms, setTerms] = useState<string[]>([]);
  const [newTerm, setNewTerm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [wipeConfirm, setWipeConfirm] = useState("");
  const [wipeDialogOpen, setWipeDialogOpen] = useState(false);

  useEffect(() => {
    getCategories().then((r) => {
      setToggles(r.toggles);
      setDefaults(r.defaults);
    });
    listTerms().then((r) => setTerms(r.terms));
  }, []);

  async function handleToggle(category: string, enabled: boolean) {
    setToggles((prev) => (prev ? { ...prev, [category]: enabled } : prev));
    try {
      await setCategory(category, enabled);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update category.");
      getCategories().then((r) => setToggles(r.toggles));
    }
  }

  async function handleAddTerm(e: React.FormEvent) {
    e.preventDefault();
    const term = newTerm.trim();
    if (!term) return;
    try {
      const resp = await addTerm(term);
      setTerms(resp.terms);
      setNewTerm("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add term.");
    }
  }

  async function handleRemoveTerm(term: string) {
    try {
      const resp = await removeTerm(term);
      setTerms(resp.terms);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove term.");
    }
  }

  async function handleWipe() {
    try {
      await apiWipe();
      setWipeDialogOpen(false);
      setWipeConfirm("");
      router.replace("/redact");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not wipe the database.");
    }
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 px-8 py-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Category toggles and custom terms apply to every redaction from now on.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Categories</CardTitle>
          <CardDescription>What gets redacted by default.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3.5">
          {toggles &&
            Object.entries(CATEGORY_LABELS)
              .filter(([key]) => key in toggles)
              .map(([key, label]) => (
                <div key={key} className="flex items-center justify-between">
                  <div>
                    <Label htmlFor={`toggle-${key}`} className="text-sm">
                      {label}
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      Default {defaults[key] ? "on" : "off"}
                    </p>
                  </div>
                  <Switch
                    id={`toggle-${key}`}
                    checked={toggles[key]}
                    onCheckedChange={(v) => handleToggle(key, v)}
                  />
                </div>
              ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Custom terms</CardTitle>
          <CardDescription>
            Always redacted regardless of detection confidence — codenames, colleague names,
            project names.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <form onSubmit={handleAddTerm} className="flex gap-2">
            <Input
              value={newTerm}
              onChange={(e) => setNewTerm(e.target.value)}
              placeholder="e.g. Project Falcon"
            />
            <Button type="submit" disabled={!newTerm.trim()}>
              <Plus size={15} />
              Add
            </Button>
          </form>
          {terms.length === 0 ? (
            <p className="text-sm text-muted-foreground">No custom terms yet.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {terms.map((term) => (
                <li
                  key={term}
                  className="flex items-center justify-between rounded-md border border-border px-2.5 py-1.5 text-sm"
                >
                  {term}
                  <button
                    onClick={() => handleRemoveTerm(term)}
                    className="text-muted-foreground hover:text-destructive"
                    aria-label={`Remove ${term}`}
                  >
                    <Trash size={15} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle className="text-destructive">Danger zone</CardTitle>
          <CardDescription>
            Wipe every mapping, custom term, and setting. The audit log is cleared and restarted
            with a single wipe entry. This cannot be undone.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Dialog open={wipeDialogOpen} onOpenChange={setWipeDialogOpen}>
            <DialogTrigger render={<Button variant="destructive" />}>
              Wipe everything
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Warning size={16} className="text-destructive" />
                  Wipe the mapping database
                </DialogTitle>
                <DialogDescription>
                  This permanently deletes every stored real value, custom term, and setting.
                  Type <span className="font-mono font-medium">WIPE</span> to confirm.
                </DialogDescription>
              </DialogHeader>
              <Input
                value={wipeConfirm}
                onChange={(e) => setWipeConfirm(e.target.value)}
                placeholder="WIPE"
                autoFocus
              />
              <DialogFooter>
                <Button
                  variant="destructive"
                  disabled={wipeConfirm !== "WIPE"}
                  onClick={handleWipe}
                >
                  Wipe permanently
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardContent>
      </Card>
    </div>
  );
}
