"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { SignOffPanel } from "@/components/approvals/SignOffPanel";
import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { IntegrationPanel } from "@/components/studio/IntegrationPanel";
import { useEntity } from "@/context/EntityContext";
import { fetchPeriods } from "@/lib/cost-analysis";
import { periodLabel, useWorkingPeriod } from "@/lib/workspace";

/**
 * Approving a month. The month is the working period shown in the header, so
 * this page, the Control Centre and the results never disagree about which
 * month is meant. Approval is only offered for a month whose register is stored
 * and has been validated; the panel says what is still missing.
 */
export default function MonthApprovalPage() {
  const { entity } = useEntity();
  const { period, setPeriod, loading } = useWorkingPeriod();

  const { data } = useQuery({
    queryKey: ["register-periods", entity?.id],
    queryFn: fetchPeriods,
    enabled: !!entity,
  });
  const periods = data?.periods ?? [];
  const hasRegister = !!period && periods.some((p) => p.period.startsWith(period));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Month approval"
        description="Sign off a month once its register has been validated and its findings dealt with."
      />

      <Menu label="Period" summary={period ? periodLabel(period) : "Latest month"} width="w-56">
        {(close) => (
          <>
            {periods.map((option) => (
              <MenuItem
                key={option.period}
                selected={!!period && option.period.startsWith(period)}
                onClick={() => {
                  setPeriod(option.period.slice(0, 7));
                  close();
                }}
              >
                {option.label}
              </MenuItem>
            ))}
          </>
        )}
      </Menu>

      {!loading && period && !hasRegister ? (
        <AlertBanner variant="warning" title={`No register is stored for ${periodLabel(period)}`}>
          Nothing can be approved for this month until its register is uploaded and validated.{" "}
          <Link href="/control-centre" className="font-medium underline">Check the register from the Control Centre</Link>
        </AlertBanner>
      ) : null}

      {period && hasRegister ? (
        <>
          <SignOffPanel period={`${period}-01`} />
          <IntegrationPanel period={`${period}-01`} />
        </>
      ) : null}
    </div>
  );
}
