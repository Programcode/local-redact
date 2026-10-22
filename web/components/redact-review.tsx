"use client";

import { useMemo, useRef, useState } from "react";
import { X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { getSelectionOffsets } from "@/lib/selection-offsets";
import { labelFor, swatchFor } from "@/lib/entity-types";

export interface ReviewSpan {
  id: string;
  start: number;
  end: number;
  entity_type: string;
  accepted: boolean;
}

interface Props {
  text: string;
  spans: ReviewSpan[];
  onChange: (spans: ReviewSpan[]) => void;
}

/** Renders `text` with `spans` as inline highlights. Accepted spans are
 * colored per entity category and clickable to reject; rejected spans show
 * struck-through and clickable to re-accept. Selecting plain text offers
 * "Redact selection" to add a manual span. */
export function RedactReview({ text, spans, onChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pendingSelection, setPendingSelection] = useState<{
    start: number;
    end: number;
  } | null>(null);

  const ordered = useMemo(() => [...spans].sort((a, b) => a.start - b.start), [spans]);

  function toggle(id: string) {
    onChange(spans.map((s) => (s.id === id ? { ...s, accepted: !s.accepted } : s)));
  }

  function handleMouseUp() {
    if (!containerRef.current) return;
    const offsets = getSelectionOffsets(containerRef.current);
    if (!offsets) {
      setPendingSelection(null);
      return;
    }
    const overlaps = spans.some((s) => offsets.start < s.end && offsets.end > s.start);
    if (overlaps) {
      setPendingSelection(null);
      return;
    }
    setPendingSelection(offsets);
  }

  function addManual() {
    if (!pendingSelection) return;
    const id = `manual-${pendingSelection.start}-${pendingSelection.end}-${spans.length}`;
    onChange([
      ...spans,
      { id, start: pendingSelection.start, end: pendingSelection.end, entity_type: "MANUAL", accepted: true },
    ]);
    setPendingSelection(null);
    window.getSelection()?.removeAllRanges();
  }

  const segments: React.ReactNode[] = [];
  let cursor = 0;
  for (const span of ordered) {
    if (span.start > cursor) {
      segments.push(<span key={`plain-${cursor}`}>{text.slice(cursor, span.start)}</span>);
    }
    const swatch = swatchFor(span.entity_type);
    const label = span.entity_type === "MANUAL" ? "Manual selection" : labelFor(span.entity_type);
    segments.push(
      <button
        type="button"
        key={span.id}
        title={`${label} — click to ${span.accepted ? "exclude" : "include"}`}
        onClick={() => toggle(span.id)}
        style={
          span.accepted
            ? { backgroundColor: swatch.bg, color: swatch.text, borderColor: swatch.border }
            : undefined
        }
        className={
          span.accepted
            ? "rounded-[3px] border px-0.5 py-px align-baseline text-inherit"
            : "rounded-[3px] border border-dashed border-muted-foreground/40 px-0.5 py-px align-baseline text-muted-foreground line-through decoration-1"
        }
      >
        {text.slice(span.start, span.end)}
      </button>
    );
    cursor = Math.max(cursor, span.end);
  }
  if (cursor < text.length) {
    segments.push(<span key={`plain-${cursor}`}>{text.slice(cursor)}</span>);
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={containerRef}
        onMouseUp={handleMouseUp}
        className="min-h-40 whitespace-pre-wrap rounded-lg border border-input bg-transparent px-3 py-2.5 text-sm leading-relaxed dark:bg-input/30"
      >
        {segments.length > 0 ? segments : text}
      </div>
      {pendingSelection && (
        <div className="flex items-center gap-2 rounded-md border border-border bg-secondary px-2.5 py-1.5 text-xs">
          <span className="text-muted-foreground">
            {`"${text.slice(pendingSelection.start, pendingSelection.end).slice(0, 40)}${
              pendingSelection.end - pendingSelection.start > 40 ? "…" : ""
            }"`}
          </span>
          <Button type="button" size="xs" onClick={addManual}>
            Redact selection
          </Button>
          <button
            type="button"
            onClick={() => setPendingSelection(null)}
            className="ml-auto text-muted-foreground hover:text-foreground"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
