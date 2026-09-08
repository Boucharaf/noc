import { useState } from "react";
import { Check } from "lucide-react";

import { Field, Notice } from "../ui/Controls";
import { Modal } from "../ui/Overlay";
import { StateDot } from "../ui/Badge";
import { QueryBoundary } from "../ui/States";
import { errorMessage } from "../../api/client";
import { useIncidentActions, useNodes, useReference } from "../../hooks/queries";

/**
 * Signalement manuel d'une panne.
 *
 * Sert le cas que les six outils de supervision ne couvrent pas : un
 * agent constate sur place une coupure d'alimentation ou une baie
 * inaccessible, alors qu'aucune sonde ne l'a détectée — souvent parce que
 * l'équipement qui aurait dû alerter est justement celui qui est tombé.
 *
 * L'équipement se CHOISIT dans une liste, il ne se tape pas. Le backend
 * (`incident_service.create_manual`) résout le nom par une correspondance
 * EXACTE, insensible à la casse : un champ libre renverrait « aucun
 * équipement ne correspond » à la moindre abréviation. On recherche donc
 * dans l'inventaire — où la recherche est bien partielle — et on envoie
 * le nom exact de la ligne sélectionnée.
 *
 * Effet de bord utile : l'agent voit l'état courant de l'équipement avant
 * de le signaler, et s'aperçoit qu'une alerte existe déjà.
 */
const SEVERITIES = [
  { value: "critical", label: "Critique — service interrompu" },
  { value: "high", label: "Majeur — service fortement dégradé" },
  { value: "medium", label: "Moyen — impact limité" },
  { value: "low", label: "Mineur — à surveiller" },
];

export default function ManualIncidentModal({ open, onClose, defaultNodeCode = "" }) {
  const { createManual } = useIncidentActions();
  const { data: reference } = useReference();

  const [search, setSearch] = useState(defaultNodeCode);
  const [selected, setSelected] = useState(null);
  const [severity, setSeverity] = useState("high");
  const [cause, setCause] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  const nodes = useNodes({ q: search || undefined, page_size: 12, sort: "name" });

  const close = () => {
    setSearch("");
    setSelected(null);
    setSeverity("high");
    setCause("");
    setDescription("");
    setError(null);
    setDone(false);
    onClose();
  };

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    try {
      await createManual.mutateAsync({
        // Le NOM exact de la ligne choisie, jamais la saisie brute.
        node_code: selected.name,
        severity,
        description: description.trim(),
        cause_category: cause || null,
      });
      setDone(true);
      // Laisse le temps de lire la confirmation : refermer instantanément
      // ne dit pas si l'incident a bien été enregistré.
      setTimeout(close, 1300);
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Signaler une panne"
      subtitle="Panne constatée que les outils de supervision n'ont pas détectée"
      width={500}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={close}>
            Annuler
          </button>
          <button
            type="submit"
            form="manual-incident"
            className="btn btn-sm btn-primary"
            disabled={createManual.isPending || done || !selected || !description.trim()}
          >
            {createManual.isPending ? "Enregistrement…" : "Créer l'incident"}
          </button>
        </>
      }
    >
      <form id="manual-incident" onSubmit={submit} className="space-y-2.5">
        {done && <Notice tone="success">Incident créé et diffusé sur le mur d'alertes.</Notice>}
        {error && <Notice tone="error">{error}</Notice>}

        <Field
          label="Équipement concerné"
          required
          hint={
            selected
              ? `Sélectionné : ${selected.name}${selected.locality ? ` — ${selected.locality}` : ""}`
              : "Cherchez par nom ou adresse IP, puis choisissez la ligne exacte."
          }
        >
          <input
            className="input"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setSelected(null);
            }}
            placeholder="RTR-OUA…"
            autoFocus
          />
        </Field>

        <div
          className="panel"
          style={{ maxHeight: 168, overflow: "auto", background: "var(--surface-2)" }}
        >
          <QueryBoundary
            query={nodes}
            compact
            empty={(data) => !data?.items?.length}
            emptyMessage="Aucun équipement ne correspond"
            emptyHint="Un équipement absent de l'inventaire ne peut pas porter d'incident : signalez-le au Chef NOC."
          >
            {(data) => (
              <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                {data.items.map((node) => {
                  const active = selected?.node_id === node.node_id;
                  return (
                    <li key={node.node_id}>
                      <button
                        type="button"
                        className="w-full text-left px-2.5 py-1.5 flex items-center gap-2 hover:bg-[var(--surface-3)]"
                        style={{ background: active ? "var(--accent-soft)" : undefined }}
                        onClick={() => setSelected(node)}
                      >
                        <StateDot state={node.state} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] font-medium truncate">
                            {node.name}
                          </span>
                          <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                            {node.locality || "site inconnu"}
                            {node.ip_address ? ` · ${node.ip_address}` : ""}
                            {node.open_incidents
                              ? ` · ${node.open_incidents} incident(s) déjà ouvert(s)`
                              : ""}
                          </span>
                        </span>
                        {active && <Check size={13} style={{ color: "var(--accent-ink)" }} />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </QueryBoundary>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          <Field label="Gravité" required>
            <select
              className="select"
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              {SEVERITIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Cause présumée" hint="Facultatif — affine les statistiques.">
            <select
              className="select"
              value={cause}
              onChange={(event) => setCause(event.target.value)}
            >
              <option value="">Non déterminée</option>
              {(reference?.causes ?? []).map((item) => (
                <option key={item.category} value={item.category}>
                  {item.label || item.category}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field label="Description" required hint="Ce que vous constatez, et depuis quand.">
          <textarea
            className="textarea"
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Baie injoignable depuis 09h15, disjoncteur déclenché côté onduleur."
          />
        </Field>
      </form>
    </Modal>
  );
}
