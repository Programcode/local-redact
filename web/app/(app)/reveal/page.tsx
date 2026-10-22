"use client";

import { useState } from "react";
import { Copy, Check, Eye, ArrowCounterClockwise } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { reveal as apiReveal, ApiError } from "@/lib/api";

export default function RevealPage() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ text: string; restored: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleReveal() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await apiReveal(text);
      setResult(resp);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reveal text.");
    } finally {
      setBusy(false);
    }
  }

  function handleCopy() {
    if (!result) return;
    navigator.clipboard.writeText(result.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  function reset() {
    setText("");
    setResult(null);
    setError(null);
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 px-8 py-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Reveal text</h1>
        <p className="text-sm text-muted-foreground">
          Paste an AI reply containing placeholders (e.g. PERSON_00001) to restore the real
          values from the local mapping database.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {!result ? (
        <div className="flex flex-col gap-3">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste the AI's response here…"
            className="min-h-64 text-sm"
            autoFocus
          />
          <div className="flex justify-end">
            <Button onClick={handleReveal} disabled={busy || !text.trim()}>
              <Eye size={15} />
              {busy ? "Revealing…" : "Reveal"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="whitespace-pre-wrap rounded-lg border border-border bg-card px-3 py-2.5 text-sm leading-relaxed">
            {result.text}
          </div>
          <p className="text-xs text-muted-foreground">{result.restored} value(s) restored.</p>
          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button variant="ghost" onClick={reset}>
              <ArrowCounterClockwise size={15} />
              Reveal another
            </Button>
            <Button onClick={handleCopy}>
              {copied ? <Check size={15} /> : <Copy size={15} />}
              {copied ? "Copied" : "Copy revealed text"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
