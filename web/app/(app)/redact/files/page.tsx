"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import {
  UploadSimple,
  DownloadSimple,
  ArrowCounterClockwise,
  Copy,
  Check,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RedactReview, type ReviewSpan } from "@/components/redact-review";
import {
  uploadFile,
  redactPreview,
  redactConfirm,
  downloadUrl,
  ApiError,
  type UploadFileResp,
} from "@/lib/api";
import { labelFor, swatchFor } from "@/lib/entity-types";

type Stage = "pick" | "review" | "done-text" | "done-file";

const STATUS_LABEL: Record<string, string> = {
  redacted: "Redacted",
  partial: "Redacted (partial — see notes)",
  skipped: "Skipped (unsupported format)",
  failed: "Failed",
};

export default function RedactFilesPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [stage, setStage] = useState<Stage>("pick");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // text-like path (.txt/.md/.csv) reuses the same review flow as /redact
  const [text, setText] = useState("");
  const [spans, setSpans] = useState<ReviewSpan[]>([]);
  const [redactedText, setRedactedText] = useState("");
  const [byType, setByType] = useState<Record<string, number>>({});

  // structural-format path (.docx/.pptx/.pdf/.xlsx/.eml/.msg)
  const [fileReport, setFileReport] = useState<UploadFileResp | null>(null);

  function reset() {
    setStage("pick");
    setText("");
    setSpans([]);
    setFileReport(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const resp = await uploadFile(file);
      if (resp.mode === "text") {
        setText(resp.text);
        const detections = await redactPreview(resp.text);
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
      } else {
        setFileReport(resp);
        setStage("done-file");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not process file.");
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
      setRedactedText(resp.text);
      setByType(resp.by_type);
      setStage("done-text");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not redact text.");
    } finally {
      setBusy(false);
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(redactedText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  const acceptedCount = spans.filter((s) => s.accepted).length;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 px-8 py-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Redact a file</h1>
        <p className="text-sm text-muted-foreground">
          Plain text/markdown/CSV files go through the same highlighted review as{" "}
          <Link href="/redact" className="underline underline-offset-2">
            pasted text
          </Link>
          . Structural formats (.docx, .pptx, .pdf, .xlsx, .eml, .msg) are redacted
          automatically using your current settings below — there is no live preview for those,
          only the resulting entity-count report before you download.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {stage === "pick" && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-input px-6 py-14 text-center"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const file = e.dataTransfer.files?.[0];
            if (file) handleFile(file);
          }}
        >
          <UploadSimple size={22} className="text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Drag a file here, or{" "}
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="text-foreground underline underline-offset-2"
            >
              choose one
            </button>
          </p>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            accept=".txt,.md,.csv,.docx,.pptx,.pdf,.xlsx,.eml,.msg"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
            }}
          />
          {busy && <p className="text-xs text-muted-foreground">Processing…</p>}
        </div>
      )}

      {stage === "review" && (
        <div className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">
            Click a highlight to exclude it. Select plain text to add a manual one.
          </p>
          <RedactReview text={text} spans={spans} onChange={setSpans} />
          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button variant="ghost" onClick={reset}>
              Cancel
            </Button>
            <Button onClick={handleConfirm} disabled={busy}>
              {busy ? "Redacting…" : `Confirm & redact (${acceptedCount})`}
            </Button>
          </div>
        </div>
      )}

      {stage === "done-text" && (
        <div className="flex flex-col gap-4">
          <div className="whitespace-pre-wrap rounded-lg border border-border bg-card px-3 py-2.5 text-sm leading-relaxed">
            {redactedText}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(byType).map(([t, n]) => {
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

      {stage === "done-file" && fileReport && (
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-sm font-medium">{fileReport.filename}</p>
            <p className="text-sm text-muted-foreground">
              {STATUS_LABEL[fileReport.status] ?? fileReport.status}
              {fileReport.reason ? ` — ${fileReport.reason}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(fileReport.counts).map(([t, n]) => {
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
          {fileReport.notes.length > 0 && (
            <ul className="list-inside list-disc text-xs text-muted-foreground">
              {fileReport.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button variant="ghost" onClick={reset}>
              <ArrowCounterClockwise size={15} />
              Redact another
            </Button>
            {fileReport.download_token && (
              <Button render={<a href={downloadUrl(fileReport.download_token)} download={fileReport.filename} />}>
                <DownloadSimple size={15} />
                Download redacted file
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
