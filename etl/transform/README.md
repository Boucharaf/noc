# transform/

Toute la logique métier qui ne dépend d'aucun outil en particulier :
normalisation, réconciliation, classification.

| Fichier | Rôle |
|---|---|
| `normalize_nodes.py` | homogénéise les nœuds bruts (un format par outil) vers un schéma commun |
| `normalize_incidents.py` | idem pour les incidents, calcule MTTA/MTTR, applique `causes.py` |
| `normalize_metrics.py` | idem pour les métriques temporelles (filtre les valeurs invalides) |
| `causes.py` | classification de la cause d'un incident par règles regex (auditable, pas de boîte noire) |
| `identity_resolution.py` | fusionne les nœuds désignant le même équipement physique vu par plusieurs outils (IP puis nom, jamais de fusion ambiguë) |
| `dedup.py` | anti-jointure API vs BDD restaurée — l'API prime toujours |

Ordre d'exécution dans `pipelines/collector.py` pour un outil donné :

```
extract (api) ──┐
                 ├─> dedup.py ──> normalize_*.py ──> identity_resolution.py (nœuds uniquement) ──> load/
extract (db)  ──┘
```

Aucun de ces modules ne fait d'I/O réseau ou base de données : ce sont
des fonctions pures sur des listes de dicts, donc facilement testables
(voir `tests/`).
