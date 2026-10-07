import { ReactNode } from "react";
import { Button } from "./FormControls";

/** Modal confirmation dialog with an explicit message (U2 START, U5 stop/delete). */
export function ConfirmDialog(props: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!props.open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-lg border border-zinc-700 bg-zinc-900 p-5 shadow-xl">
        <h3 className="text-lg font-semibold text-zinc-100">{props.title}</h3>
        <div className="mt-2 text-sm text-zinc-300">{props.message}</div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={props.onCancel}>
            Отмена
          </Button>
          <Button variant={props.danger ? "danger" : "primary"} onClick={props.onConfirm}>
            {props.confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
