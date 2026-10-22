"use client";

import { useEffect, useState } from "react";
import { ShieldCheck, ShieldWarning } from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getAudit, type AuditEntry } from "@/lib/api";

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [chainValid, setChainValid] = useState<boolean | null>(null);

  useEffect(() => {
    getAudit().then((r) => {
      setEntries(r.entries);
      setChainValid(r.chain_valid);
    });
  }, []);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5 px-8 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Audit log</h1>
          <p className="text-sm text-muted-foreground">
            Append-only, hash-chained record of every redact/reveal action. Counts and hashes
            only — raw content is never logged.
          </p>
        </div>
        {chainValid !== null && (
          <Badge
            variant="outline"
            className={
              chainValid
                ? "border-[#d6e7d4] bg-[#edf3ec] text-[#346538]"
                : "border-[#f8cfd0] bg-[#fdebec] text-[#9f2f2d]"
            }
          >
            {chainValid ? <ShieldCheck size={13} /> : <ShieldWarning size={13} />}
            {chainValid ? "Chain valid" : "Chain broken"}
          </Badge>
        )}
      </div>

      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">No audit entries yet.</p>
      ) : (
        <div className="rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Time</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Document</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-mono text-xs text-muted-foreground">{e.id}</TableCell>
                  <TableCell className="font-mono text-xs">{e.ts}</TableCell>
                  <TableCell className="text-xs">{e.action}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.doc ?? "—"}</TableCell>
                  <TableCell className="max-w-xs truncate font-mono text-xs text-muted-foreground">
                    {JSON.stringify(e.detail)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
