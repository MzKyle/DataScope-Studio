import { Command } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";

export function EmptyState({
  action,
  className,
  text,
  title
}: {
  action?: ReactNode;
  className?: string;
  text: string;
  title?: string;
}) {
  return (
    <div
      className={cn(
        "flex min-h-28 items-center gap-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-5 text-slate-500",
        className
      )}
    >
      <Command className="shrink-0 text-blue-700" size={18} />
      <div className="min-w-0">
        {title && <strong className="block text-sm text-slate-900">{title}</strong>}
        <span className="block text-sm">{text}</span>
      </div>
      {action && <div className="ml-auto shrink-0">{action}</div>}
    </div>
  );
}
