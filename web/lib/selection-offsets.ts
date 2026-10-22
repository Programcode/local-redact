/** Map the browser's current text Selection to character offsets relative to
 * `container`'s flattened text content. Works regardless of how many inline
 * elements (spans/marks) sit inside the container, as long as the container's
 * rendered text reconstructs the original string with no extra characters. */
export function getSelectionOffsets(
  container: HTMLElement
): { start: number; end: number } | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) {
    return null;
  }

  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let charIndex = 0;
  let start = -1;
  let end = -1;
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const len = node.textContent?.length ?? 0;
    if (node === range.startContainer) start = charIndex + range.startOffset;
    if (node === range.endContainer) {
      end = charIndex + range.endOffset;
      break;
    }
    charIndex += len;
  }
  if (start === -1 || end === -1 || end <= start) return null;
  return { start, end };
}
