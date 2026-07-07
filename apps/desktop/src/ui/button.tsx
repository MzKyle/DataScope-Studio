import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "../lib/cn";

const buttonVariants = cva(
  "inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg border text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-4 disabled:pointer-events-none disabled:opacity-60",
  {
    defaultVariants: {
      size: "default",
      variant: "secondary"
    },
    variants: {
      size: {
        default: "h-10 px-4",
        icon: "h-10 w-10 p-0",
        sm: "h-8 px-3 text-xs"
      },
      variant: {
        danger: "border-red-200 bg-white text-red-700 hover:bg-red-50 focus-visible:ring-red-100",
        ghost: "border-transparent bg-transparent text-slate-600 hover:bg-slate-100 focus-visible:ring-blue-100",
        primary: "border-blue-700 bg-blue-700 text-white hover:bg-blue-800 focus-visible:ring-blue-100",
        secondary: "border-slate-200 bg-white text-slate-900 hover:bg-slate-100 focus-visible:ring-blue-100"
      }
    }
  }
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

export function Button({
  asChild,
  className,
  size,
  type = "button",
  variant,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(buttonVariants({ size, variant }), className)}
      type={asChild ? undefined : type}
      {...props}
    />
  );
}
