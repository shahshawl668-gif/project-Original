"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { activateFormula, deleteFormula, type Formula } from "@/lib/rule-engine";

type Props = {
  formulas: Formula[];
  onChanged: () => void;
  onLoad?: (f: Formula) => void;
};

export function VersionPanel({ formulas, onChanged, onLoad }: Props) {
  const [busyId, setBusyId] = useState<string | null>(null);

  const handleActivate = async (id: string) => {
    setBusyId(id);
    try {
      await activateFormula(id);
      toast.success("Version activated");
      onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this version?")) return;
    setBusyId(id);
    try {
      await deleteFormula(id);
      toast.success("Deleted");
      onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <p className="font-display text-[11px] font-bold uppercase tracking-[0.14em] text-ink-500 dark:text-ink-300">
          History
        </p>
        <CardTitle>Versions</CardTitle>
        <p className="text-xs text-ink-500 dark:text-ink-400">
          Each save produces a new immutable version. Roll back at any time.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        {formulas.length === 0 ? (
          <p className="p-6 text-sm text-ink-500 dark:text-ink-400">
            No versions yet — save your first formula.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Version</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {formulas.map((f) => (
                <TableRow key={f.id}>
                  <TableCell className="font-display font-semibold text-ink-900 dark:text-white">
                    v{f.version}
                  </TableCell>
                  <TableCell className="text-ink-600 dark:text-ink-300">
                    {new Date(f.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    {f.is_active ? (
                      <Badge variant="success">Active</Badge>
                    ) : (
                      <Badge variant="secondary">Inactive</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right space-x-1">
                    {onLoad && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => onLoad(f)}
                        disabled={busyId === f.id}
                      >
                        Load
                      </Button>
                    )}
                    {!f.is_active && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => handleActivate(f.id)}
                        disabled={busyId === f.id}
                      >
                        Activate
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(f.id)}
                      disabled={busyId === f.id}
                      className="text-danger-600 hover:text-danger-700 dark:text-danger-400 dark:hover:text-danger-300"
                    >
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
