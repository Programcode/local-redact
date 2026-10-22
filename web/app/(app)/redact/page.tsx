"use client";

import { useState } from "react";
import Link from "next/link";
import { Copy, Check, MagnifyingGlass, ArrowCounterClockwise } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { RedactReview, type ReviewSpan } from "@/components/redact-review";
import { redactPreview, redactConfirm, ApiError } from "@/lib/api";
import { labelFor, swatchFor } from "@/lib/entity-types";

type Stage = "edit" | "review" | "done";

export default function RedactTextPage() {
  const [stage, setStage] = useState<Stage>("edit");
  const [text, setText] = useState("");
  const [spans, setSpans] = useState<ReviewSpan[]>([]);
  const [result, setResult] = useState<{ text: string; byType: Record<string, number> } | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function handleAnalyze() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const detections = await redactPreview(text);
      setSpans(
        detections.map((d, i) => ({
          id: `det-${i}-${d.start}-${d.end}`,
          start: d.start,
          end: d.end,
          entity_type: d.entity_type,
          accepted: true,
        }))
      );
      setStage("review");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not analyze text.");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    setBusy(true);
    setError(null);
    try {
      const accepted = spans.filter((s) => s.accepted);
      const resp = await redactConfirm(
        text,
        accepted.map((s) => ({ start: s.start, end: s.end, entity_type: s.entity_type }))
      );
      setResult({ text: resp.text, byType: resp.by_type });
      setStage("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not redact text.");
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
    setStage("edit");
    setText("");
    setSpans([]);
    setResult(null);
    setError(null);
  }

  const acceptedCount = spans.filter((s) => s.accepted).length;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 px-8 py-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Redact text</h1>
        <p className="text-sm text-muted-foreground">
          Review every detected entity before anything is redacted — nothing is written to the
          mapping database until you confirm.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {stage === "edit" && (
        <div className="flex flex-col gap-3">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste the text you want to redact before sending it to a cloud AI…"
            className="min-h-64 text-sm"
            autoFocus
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Need to redact a file instead?{" "}
              <Link href="/redact/files" className="underline underline-offset-2">
                Go to file redaction
              </Link>
              .
            </span>
            <Button onClick={handleAnalyze} disabled={busy || !text.trim()}>
              <MagnifyingGlass size={15} />
              {busy ? "Analyzing…" : "Analyze"}
            </Button>
          </div>
        </div>
      )}

      {stage === "review" && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span>Click a highlight to exclude it. Select plain text to add a manual one.</span>
          </div>
          <RedactReview text={text} spans={spans} onChange={setSpans} />
          <div className="flex flex-wrap gap-1.5">
            {[...new Set(spans.map((s) => s.entity_type))].map((t) => {
              const swatch = swatchFor(t);
              return (
                <Badge
                  key={t}
                  variant="outline"
                  style={{ backgroundColor: swatch.bg, color: swatch.text, borderColor: swatch.border }}
                >
                  {labelFor(t)}
                </Badge>
              );
            })}
          </div>
          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button variant="ghost" onClick={() => setStage("edit")}>
              Back to edit
            </Button>
            <Button onClick={handleConfirm} disabled={busy}>
              {busy ? "Redacting…" : `Confirm & redact (${acceptedCount})`}
            </Button>
          </div>
        </div>
      )}

      {stage === "done" && result && (
        <div className="flex flex-col gap-4">
          <div className="whitespace-pre-wrap rounded-lg border border-border bg-card px-3 py-2.5 text-sm leading-relaxed">
            {result.text}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(result.byType).map(([t, n]) => {
              const swatch = swatchFor(t);
              return (
                <Badge
                  key={t}
                  variant="outline"
                  style={{ backgroundColor: swatch.bg, color: swatch.text, borderColor: swatch.border }}
                >
                  {labelFor(t)}: {n}
                </Badge>
              );
            })}
          </div>
          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button variant="ghost" onClick={reset}>
              <ArrowCounterClockwise size={15} />
              Redact another
            </Button>
            <Button onClick={handleCopy}>
              {copied ? <Check size={15} /> : <Copy size={15} />}
              {copied ? "Copied" : "Copy redacted text"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
