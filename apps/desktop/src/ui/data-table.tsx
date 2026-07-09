import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { EmptyState } from "./empty-state";

export type DataTableColumn<T> = {
  cell: (row: T) => ReactNode;
  header: string;
  key: string;
};

export function DataTable<T>({
  className,
  columns,
  emptyText,
  getRowKey,
  rows
}: {
  className?: string;
  columns: DataTableColumn<T>[];
  emptyText: string;
  getRowKey: (row: T, index: number) => string;
  rows: T[];
}) {
  if (!rows.length) return <EmptyState text={emptyText} />;

  return (
    <div className={cn("overflow-x-auto rounded-lg border border-slate-200", className)}>
      <table className="min-w-[680px] w-full border-collapse text-left">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th
                className="border-b border-slate-200 px-3 py-2 text-[11px] font-bold uppercase tracking-wide text-slate-500"
                key={column.key}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr className="hover:bg-slate-50" key={getRowKey(row, index)}>
              {columns.map((column) => (
                <td className="border-b border-slate-100 px-3 py-2 text-sm" key={column.key}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
