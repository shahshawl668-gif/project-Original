import { Fragment, type ReactNode } from "react";

/**
 * Just enough Markdown for the API contract's own description: headings,
 * paragraphs, bullet lists, tables, **bold** and `code`. The text comes from
 * our own OpenAPI document; nothing here renders HTML from it.
 */
export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      blocks.push(level <= 2
        ? <h3 key={i} className="pt-3 text-base font-semibold text-ink-900 dark:text-white">{inline(heading[2])}</h3>
        : <h4 key={i} className="pt-2 text-sm font-semibold text-ink-900 dark:text-white">{inline(heading[2])}</h4>);
      i += 1;
      continue;
    }
    if (line.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i += 1;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={`t${i}`} className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr>{head.map((c, j) => <th key={j} className="border-b border-ink-200 px-2 py-1 text-left font-semibold dark:border-white/10">{inline(c)}</th>)}</tr></thead>
            <tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} className="border-b border-ink-100 px-2 py-1 align-top dark:border-white/5">{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i += 1;
      }
      blocks.push(<ul key={`l${i}`} className="list-disc space-y-0.5 pl-5 text-sm">{items.map((t, k) => <li key={k}>{inline(t)}</li>)}</ul>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4})\s/.test(lines[i]) && !lines[i].trim().startsWith("|") && !/^\s*[-*]\s+/.test(lines[i])) {
      para.push(lines[i].trim());
      i += 1;
    }
    blocks.push(<p key={`p${i}`} className="text-sm leading-relaxed text-ink-700 dark:text-ink-200">{inline(para.join(" "))}</p>);
  }
  return <div className="space-y-2">{blocks}</div>;
}

function inline(text: string): ReactNode {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((p, k) => {
    if (p.startsWith("`") && p.endsWith("`")) return <code key={k} className="rounded bg-ink-100 px-1 font-mono text-[12px] dark:bg-white/10">{p.slice(1, -1)}</code>;
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={k}>{p.slice(2, -2)}</strong>;
    return <Fragment key={k}>{p}</Fragment>;
  });
}
