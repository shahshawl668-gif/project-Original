"use client";

import dynamic from "next/dynamic";
import { useEffect, useImperativeHandle, useRef, forwardRef } from "react";
import { useTheme } from "@/providers/ThemeProvider";

// Use the locally bundled monaco-editor instead of @monaco-editor/react's
// default CDN loader — keeps the editor working offline / behind strict CSPs.
const Monaco = dynamic(
  async () => {
    const [reactMonaco, monaco] = await Promise.all([
      import("@monaco-editor/react"),
      // Explicit ESM entry — the package's `require` condition points at the
      // AMD `min` build, which webpack cannot bundle.
      import("monaco-editor/esm/vs/editor/editor.api.js"),
    ]);
    reactMonaco.loader.config({ monaco });
    return reactMonaco.default;
  },
  { ssr: false },
);

export type FormulaEditorHandle = {
  insertAtCursor: (text: string) => void;
  focus: () => void;
};

type Props = {
  value: string;
  onChange: (next: string) => void;
  errorLine?: number | null;
  errorMessage?: string | null;
  height?: number;
};

const FormulaEditor = forwardRef<FormulaEditorHandle, Props>(function FormulaEditor(
  { value, onChange, errorLine, errorMessage, height = 220 },
  ref
) {
  const editorRef = useRef<unknown>(null);
  const monacoRef = useRef<unknown>(null);
  const decorationsRef = useRef<string[]>([]);
  const { resolved } = useTheme();

  useImperativeHandle(ref, () => ({
    insertAtCursor: (text: string) => {
      const editor = editorRef.current as
        | {
            getPosition?: () => unknown;
            executeEdits?: (source: string, edits: unknown[]) => void;
            focus?: () => void;
          }
        | null;
      if (!editor || !editor.getPosition) return;
      const position = editor.getPosition() as
        | { lineNumber: number; column: number }
        | null;
      if (!position) return;
      const range = {
        startLineNumber: position.lineNumber,
        startColumn: position.column,
        endLineNumber: position.lineNumber,
        endColumn: position.column,
      };
      editor.executeEdits?.("variable-picker", [
        { range, text, forceMoveMarkers: true },
      ]);
      editor.focus?.();
    },
    focus: () => {
      (editorRef.current as { focus?: () => void } | null)?.focus?.();
    },
  }));

  useEffect(() => {
    const editor = editorRef.current as
      | {
          deltaDecorations?: (old: string[], next: unknown[]) => string[];
          getModel?: () => { getLineMaxColumn?: (n: number) => number } | null;
        }
      | null;
    const monaco = monacoRef.current as
      | { editor?: { setModelMarkers: (model: unknown, owner: string, markers: unknown[]) => void } }
      | null;
    if (!editor || !monaco?.editor) return;
    const model = editor.getModel?.();

    if (errorLine && errorMessage) {
      decorationsRef.current = editor.deltaDecorations?.(decorationsRef.current, [
        {
          range: {
            startLineNumber: errorLine,
            startColumn: 1,
            endLineNumber: errorLine,
            endColumn: model?.getLineMaxColumn?.(errorLine) ?? 1,
          },
          options: {
            isWholeLine: true,
            className: "bg-red-100",
            glyphMarginClassName: "bg-red-500",
          },
        },
      ]) || [];
      if (model) {
        monaco.editor.setModelMarkers(model, "formula", [
          {
            startLineNumber: errorLine,
            startColumn: 1,
            endLineNumber: errorLine,
            endColumn: model.getLineMaxColumn?.(errorLine) ?? 80,
            severity: 8,
            message: errorMessage,
          },
        ]);
      }
    } else {
      decorationsRef.current = editor.deltaDecorations?.(decorationsRef.current, []) || [];
      if (model) monaco.editor.setModelMarkers(model, "formula", []);
    }
  }, [errorLine, errorMessage]);

  return (
    <div className="overflow-hidden rounded-xl border border-ink-200 bg-white shadow-sm dark:border-white/10 dark:bg-ink-950">
      <Monaco
        height={height}
        defaultLanguage="javascript"
        value={value}
        theme={resolved === "dark" ? "vs-dark" : "vs"}
        onChange={(v) => onChange(v ?? "")}
        onMount={(editor, monaco) => {
          editorRef.current = editor;
          monacoRef.current = monaco;
        }}
        options={{
          minimap: { enabled: false },
          lineNumbers: "on",
          fontSize: 14,
          tabSize: 2,
          scrollBeyondLastLine: false,
          wordWrap: "on",
          automaticLayout: true,
          padding: { top: 12, bottom: 12 },
        }}
      />
    </div>
  );
});

export default FormulaEditor;
