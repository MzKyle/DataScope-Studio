import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ComponentPropsWithoutRef, ElementRef } from "react";
import { forwardRef } from "react";
import { X } from "lucide-react";

import { cn } from "../lib/cn";
import { Button } from "./button";

export const Dialog = DialogPrimitive.Root;
export const DialogClose = DialogPrimitive.Close;
export const DialogDescription = DialogPrimitive.Description;
export const DialogTitle = DialogPrimitive.Title;
export const DialogTrigger = DialogPrimitive.Trigger;

export const DialogContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(function DialogContent({ children, className, ...props }, ref) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/35" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 grid max-h-[calc(100vh-48px)] w-[min(620px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 gap-4 overflow-auto rounded-lg border border-slate-200 bg-white p-5 shadow-xl focus:outline-none",
          className
        )}
        ref={ref}
        {...props}
      >
        {children}
        <DialogPrimitive.Close asChild>
          <Button aria-label="Close" className="absolute right-3 top-3" size="icon" variant="ghost">
            <X size={16} />
          </Button>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});
