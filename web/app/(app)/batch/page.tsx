"use client";

import { useState } from "react";
import { FolderOpen } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { runBatch, ApiError, type BatchResp } from "@/lib/api";

const STATUS_VARIANT: Record<string, { bg: string; text: string; border: string }> = {
  redacted: { bg: "#edf3ec", text: "#346538", border: "#d6e7d4" },
  partial: { bg: "#fbf3db", text: "#956400", border: "#f3e2ac" },
  skipped: { bg: "#f2f1ed", text: "#2f3437", border: "#c9c7bf" },
  failed: { bg: "#fdebec", text: "#9f2f2d", border: "#f8cfd0" },
};

export default function BatchPage() {
  const [inputDir, setInputDir] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<BatchResp | null>(null);

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const resp = await runBatch(inputDir, outputDir);
      setReport(resp);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Batch run failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5 px-8 py-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Batch redact a folder</h1>
        <p className="text-sm text-muted-foreground">
          Redacts every supported file under the input folder into a mirrored output folder,
          using your current category/term settings. Nothing unsupported or corrupt is copied
          un-redacted.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <form onSubmit={handleRun} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="input-dir">Input folder (on this machine)</Label>
            <Input
              id="input-dir"
              value={inputDir}
              onChange={(e) => setInputDir(e.target.value)}
              placeholder="/Users/you/Documents/to-redact"
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="output-dir">Output folder</Label>
            <Input
              id="output-dir"
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
              placeholder="/Users/you/Documents/redacted"
              required
            />
          </div>
        </div>
        <div className="flex justify-end">
          <Button type="submit" disabled={busy || !inputDir || !outputDir}>
            <FolderOpen size={15} />
            {busy ? "Running…" : "Run batch"}
          </Button>
        </div>
      </form>

      {report && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(report.summary).map(([status, n]) => {
              const swatch = STATUS_VARIANT[status] ?? STATUS_VARIANT.skipped;
              return (
                <Badge
                  key={status}
                  variant="outline"
                  style={{ backgroundColor: swatch.bg, color: swatch.text, borderColor: swatch.border }}
                >
                  {status}: {n}
                </Badge>
              );
            })}
          </div>
          <div className="rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Counts</TableHead>
                  <TableHead>Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {report.files.map((f) => (
                  <TableRow key={f.source}>
                    <TableCell className="font-mono text-xs">{f.source}</TableCell>
                    <TableCell className="text-xs">{f.status}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {Object.entries(f.counts)
                        .map(([t, n]) => `${t}:${n}`)
                        .join(", ") || "—"}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                      {f.reason ?? f.notes.join("; ") ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  );
}
