import { ReactNode } from "react";
import { Button } from "./FormControls";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./ui/Dialog";

/** Modal confirmation dialog with an explicit message (U2 START, U5 stop/delete).
 * MVP-8.3: Radix Dialog (фокус-ловушка, Esc, возврат фокуса). */
export function ConfirmDialog(props: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog open={props.open} onOpenChange={(next) => (next ? undefined : props.onCancel())}>
      <DialogContent>
        <DialogTitle className="text-lg font-semibold text-text">{props.title}</DialogTitle>
        <DialogDescription asChild>
          <div className="mt-2 text-sm text-text-secondary">{props.message}</div>
        </DialogDescription>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={props.onCancel}>
            Отмена
          </Button>
          <Button variant={props.danger ? "danger" : "primary"} onClick={props.onConfirm}>
            {props.confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
