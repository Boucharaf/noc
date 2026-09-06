import React, { useState } from "react";
import { useCreateManualIncident } from "../hooks/useRealtime";
import { STATUS } from "../theme/colors";

const ManualIncidentForm = ({ onClose }) => {
  const [form, setForm] = useState({ nodeCode: "", severity: "medium", description: "" });
  const create = useCreateManualIncident();

  const submit = (e) => {
    e.preventDefault();
    if (!form.nodeCode.trim() || !form.description.trim()) return;
    create.mutate(form, { onSuccess: onClose });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-xl border p-4"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border-strong)", boxShadow: "var(--shadow-elevate)" }}
      >
        <h3 className="mb-3 text-sm font-semibold">Signaler un incident</h3>
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium" style={{ color: "var(--color-text-secondary)" }}>Code du nœud</label>
          <input
            value={form.nodeCode}
            onChange={(e) => setForm((f) => ({ ...f, nodeCode: e.target.value }))}
            placeholder="ex. OUAG-DCI_OUAGA_5-CPEK01"
            className="w-full rounded-md border p-2 text-sm font-mono outline-none"
            style={{ borderColor: "var(--color-border)", background: "var(--color-page)", color: "var(--color-text-primary)" }}
          />
        </div>
        <div className="mb-3">
          <label className="mb-1 block text-xs font-medium" style={{ color: "var(--color-text-secondary)" }}>Sévérité</label>
          <select
            value={form.severity}
            onChange={(e) => setForm((f) => ({ ...f, severity: e.target.value }))}
            className="w-full rounded-md border p-2 text-sm outline-none"
            style={{ borderColor: "var(--color-border)", background: "var(--color-page)", color: "var(--color-text-primary)" }}
          >
            <option value="critical">Critique</option>
            <option value="high">Haute</option>
            <option value="medium">Moyenne</option>
            <option value="low">Basse</option>
          </select>
        </div>
        <div className="mb-4">
          <label className="mb-1 block text-xs font-medium" style={{ color: "var(--color-text-secondary)" }}>Description</label>
          <textarea
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            rows={3}
            placeholder="Problème constaté sur site…"
            className="w-full rounded-md border p-2 text-sm outline-none"
            style={{ borderColor: "var(--color-border)", background: "var(--color-page)", color: "var(--color-text-primary)" }}
          />
        </div>
        {create.isError && (
          <p className="mb-3 text-xs" style={{ color: STATUS.critical }}>
            {create.error?.message ?? "Échec de l'envoi."}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm font-medium" style={{ color: "var(--color-text-secondary)" }}>
            Annuler
          </button>
          <button type="submit" disabled={create.isPending} className="rounded-md px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50" style={{ background: "var(--color-accent)" }}>
            {create.isPending ? "Envoi…" : "Signaler"}
          </button>
        </div>
      </form>
    </div>
  );
};

export default ManualIncidentForm;
