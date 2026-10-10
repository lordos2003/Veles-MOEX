import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

/**
 * Диалог на Radix Dialog (паттерн shadcn/ui, MIT): фокус-ловушка, Esc,
 * возврат фокуса и aria-атрибуты из коробки; внешний вид — токены MVP-8.3.
 * Используется для ConfirmDialog и мобильного меню.
 */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

export function DialogOverlay(props: ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      {...props}
      className={
        "fixed inset-0 z-50 bg-overlay backdrop-blur-[2px] " +
        "data-[state=open]:animate-[dialog-fade_var(--duration-base)_var(--ease-standard)] " +
        (props.className ?? "")
      }
    />
  );
}

/** Центральное модальное окно. */
export function DialogContent(props: { children: ReactNode }) {
  return (
    <DialogPrimitive.Portal>
      <DialogOverlay />
      <DialogPrimitive.Content
        className={
          "fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 " +
          "rounded-card border border-border bg-surface p-5 shadow-pop " +
          "data-[state=open]:animate-[dialog-pop_var(--duration-base)_var(--ease-out-expo)]"
        }
      >
        {props.children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/** Боковая панель (мобильное меню). */
export function SheetContent(props: { children: ReactNode }) {
  return (
    <DialogPrimitive.Portal>
      <DialogOverlay />
      <DialogPrimitive.Content
        aria-describedby={undefined}
        className={
          "fixed inset-y-0 right-0 z-50 flex w-[min(20rem,calc(100%-2.5rem))] flex-col " +
          "border-l border-border-soft bg-surface p-4 shadow-pop " +
          "data-[state=open]:animate-[sheet-in_var(--duration-base)_var(--ease-out-expo)]"
        }
      >
        {props.children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
