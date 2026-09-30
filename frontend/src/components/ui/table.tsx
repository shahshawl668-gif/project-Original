import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Table primitives. Headers are sticky inside their scroll container, numbers
 * are tabular and right-aligned (`numeric`), and the first column can be
 * pinned (`pin`) so a wide table scrolls sideways without losing whose row it
 * is. For paged, sortable, selectable tables use `DataTable`.
 */
export const Table = ({
  className,
  containerClassName,
  scrollLabel,
  ...props
}: React.HTMLAttributes<HTMLTableElement> & {
  containerClassName?: string;
  /** Names a height-limited table's scroll box and lets the keyboard reach it. */
  scrollLabel?: string;
}) => (
  <div
    className={cn("scrollbar-thin w-full overflow-auto", scrollLabel && "focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600", containerClassName)}
    {...(scrollLabel ? { tabIndex: 0, role: "region", "aria-label": scrollLabel } : {})}
  >
    <table className={cn("w-full border-separate border-spacing-0 text-[13px] text-ink-700", className)} {...props} />
  </div>
);

export const TableHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <thead className={cn("[&_th]:sticky [&_th]:top-0 [&_th]:z-10", className)} {...props} />
);

export const TableBody = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) => <tbody className={cn(className)} {...props} />;

export const TableRow = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) => (
  <tr className={cn("group/row transition-colors duration-fast hover:bg-ink-50/70", className)} {...props} />
);

export const TableHead = ({
  className,
  numeric,
  pin,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean; pin?: boolean }) => (
  <th
    scope="col"
    className={cn(
      "h-9 whitespace-nowrap border-b border-ink-200 bg-ink-50 px-3 text-left align-middle text-xs font-medium text-ink-500",
      numeric && "text-right",
      pin && "left-0 z-20 [position:sticky]",
      className,
    )}
    {...props}
  />
);

export const TableCell = ({
  className,
  numeric,
  pin,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean; pin?: boolean }) => (
  <td
    className={cn(
      "border-b border-ink-100 px-3 py-2 align-middle",
      numeric && "num whitespace-nowrap text-right",
      pin && "sticky left-0 z-[1] bg-white group-hover/row:bg-ink-50",
      className,
    )}
    {...props}
  />
);
