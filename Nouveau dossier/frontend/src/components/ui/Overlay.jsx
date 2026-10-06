import { LogOut, X } from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";

/**
 * Fermeture au clavier (Échap) et blocage du défilement de fond.
 *
 * Le blocage du scroll n'est pas cosmétique : sans lui, la molette au
 * dessus du tiroir fait défiler la liste d'incidents en dessous, et
 * l'opérateur perd la ligne qu'il était en train de traiter.
 */
function useDismiss(open, onClose) {
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose?.();
    };
    document.addEventListener("keydown", onKeyDown);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);
}

export function Modal({ open, onClose, title, subtitle, children, footer, width = 480, centered = false }) {
  useDismiss(open, onClose);
  if (!open) return null;

  return createPortal(
    <div
      className={`fixed inset-0 z-[2000] flex justify-center p-4 overflow-auto ${
        centered ? "items-center" : "items-start sm:p-8"
      }`}
      style={{ background: "rgba(10, 20, 40, .55)" }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
    >
      <div
        className="panel w-full my-auto"
        style={{ maxWidth: width, boxShadow: "0 20px 60px rgba(0,0,0,.5)" }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="panel-head">
          <div className="min-w-0">
            <h2 className="panel-title">{title}</h2>
            {subtitle && (
              <p className="text-[11px] normal-case tracking-normal" style={{ color: "var(--ink-3)" }}>
                {subtitle}
              </p>
            )}
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm ml-auto"
            onClick={onClose}
            aria-label="Fermer"
          >
            <X size={13} />
          </button>
        </header>
        <div className="panel-body">{children}</div>
        {footer && (
          <footer
            className="flex items-center justify-end gap-2 px-2.5 py-2 border-t"
            style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
          >
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmModal({ open, onClose, onConfirm, title, children, pending = false }) {
  // Dialogue de confirmation : 360 px, centré à l'écran, boutons de même
  // largeur. Une confirmation qui occupe 480 px de large donne à une
  // simple question oui/non le poids d'un formulaire.
  return (
    <Modal
      open={open}
      onClose={pending ? undefined : onClose}
      title={title}
      width={360}
      centered
      footer={
        <div className="grid grid-cols-2 gap-2 w-full">
          <button type="button" className="btn" onClick={onClose} disabled={pending}>
            Annuler
          </button>
          <button type="button" className="btn btn-primary" onClick={onConfirm} disabled={pending}>
            {pending ? "…" : "Confirmer"}
          </button>
        </div>
      }
    >
      <div className="confirm-body">
        <div className="confirm-icon" aria-hidden="true">
          <LogOut size={18} />
        </div>
        {children}
      </div>
    </Modal>
  );
}

/**
 * Tiroir latéral — support du détail d'un incident ou d'un équipement.
 *
 * Un tiroir plutôt qu'une page pleine : l'opérateur garde sous les yeux
 * la file d'attente pendant qu'il traite une ligne, et n'a pas à
 * reconstruire son contexte de filtre au retour.
 */
export function Drawer({ open, onClose, title, subtitle, badge, children, footer, width = 560 }) {
  useDismiss(open, onClose);
  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[2000] flex justify-end"
      style={{ background: "rgba(0,0,0,.5)" }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
    >
      <aside
        className="h-full flex flex-col"
        style={{
          width: "100%",
          maxWidth: width,
          background: "var(--surface)",
          borderLeft: "1px solid var(--border-strong)",
          boxShadow: "-16px 0 48px rgba(0,0,0,.4)",
        }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="panel-head shrink-0">
          <div className="min-w-0 flex items-center gap-2">
            <h2 className="panel-title truncate">{title}</h2>
            {badge}
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm ml-auto"
            onClick={onClose}
            aria-label="Fermer"
          >
            <X size={13} />
          </button>
        </header>
        {subtitle && (
          <div
            className="px-2.5 py-1.5 text-[11.5px] border-b shrink-0"
            style={{ color: "var(--ink-2)", borderColor: "var(--border)", background: "var(--surface-2)" }}
          >
            {subtitle}
          </div>
        )}
        <div className="flex-1 overflow-y-auto p-2.5">{children}</div>
        {footer && (
          <footer
            className="flex items-center gap-2 px-2.5 py-2 border-t shrink-0 flex-wrap"
            style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
          >
            {footer}
          </footer>
        )}
      </aside>
    </div>,
    document.body,
  );
}

/** Confirmation d'une action irréversible (suppression, désactivation). */
export function ConfirmDialog({ open, onClose, onConfirm, title, message, confirmLabel = "Confirmer", danger = true, pending = false }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      width={380}
      centered
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={pending}>
            Annuler
          </button>
          <button
            type="button"
            className={`btn btn-sm ${danger ? "btn-danger" : "btn-primary"}`}
            onClick={onConfirm}
            disabled={pending}
          >
            {pending ? "…" : confirmLabel}
          </button>
        </>
      }
    >
      <p className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
        {message}
      </p>
    </Modal>
  );
}
