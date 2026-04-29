"use client";

import { apiFetch } from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  CalendarDays,
  Users,
  FileText,
  ChevronRight,
  Download,
  Search,
} from "lucide-react";

// TYPES
type Register = {
  id: string;
  period_month: string;
  filename: string | null;
  employee_count: number | null;
  created_at: string;
};

type RegisterRow = {
  employee_id: string;
  employee_name: string | null;
  paid_days: number | null;
  lop_days: number | null;
  components: Record<string, number>;
  arrears: Record<string, number>;
  increment_arrear_total: number;
};

type RegisterDetail = Register & { rows: RegisterRow[] };

export default function RegisterHistoryContent() {
  const searchParams = useSearchParams();
  const initialId = searchParams.get("id");

  const [registers, setRegisters] = useState<Register[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(initialId);
  const [detail, setDetail] = useState<RegisterDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const res = await apiFetch("/api/payroll/registers");

    if (!res.ok) {
      setError("Failed to load registers");
      setLoading(false);
      return;
    }

    const data: Register[] = await res.json();
    setRegisters(data);
    setError(null);
    setLoading(false);

    if (initialId && data.some((r) => r.id === initialId)) {
      void openRegister(initialId);
    }
  }, [initialId]);

  const openRegister = async (id: string) => {
    setActiveId(id);
    setDetailLoading(true);
    setSearch("");

    const res = await apiFetch(`/api/payroll/registers/${id}`);

    if (!res.ok) {
      setError("Failed to load register detail");
      setDetailLoading(false);
      return;
    }

    setDetail(await res.json());
    setDetailLoading(false);
  };

  useEffect(() => {
    void load();
  }, [load]);

  const fmtMonth = (iso: string) =>
    new Date(iso + (iso.length === 7 ? "-01" : "")).toLocaleDateString(
      "en-IN",
      { month: "long", year: "numeric" }
    );

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });

  const compKeys = detail?.rows.length
    ? Object.keys(detail.rows[0].components || {})
    : [];

  const hasArrears =
    detail?.rows.some((r) => r.increment_arrear_total > 0) ?? false;

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold">Register History</h1>

      {loading && <p>Loading...</p>}
      {error && <p className="text-red-500">{error}</p>}

      {registers.map((reg) => (
        <button key={reg.id} onClick={() => openRegister(reg.id)}>
          {fmtMonth(reg.period_month)}
        </button>
      ))}

      {detail && (
        <div className="mt-4">
          <h2>{fmtMonth(detail.period_month)}</h2>

          <table>
            <thead>
              <tr>
                <th>Employee</th>
                <th>Paid</th>
                {compKeys.map((k) => (
                  <th key={k}>{k}</th>
                ))}
                {hasArrears && <th>Arrear</th>}
              </tr>
            </thead>

            <tbody>
              {detail.rows.map((row) => (
                <tr key={row.employee_id}>
                  <td>{row.employee_id}</td>
                  <td>{row.paid_days}</td>

                  {compKeys.map((k) => (
                    <td key={k}>{row.components[k]}</td>
                  ))}

                  {hasArrears && (
                    <td>{row.increment_arrear_total}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
