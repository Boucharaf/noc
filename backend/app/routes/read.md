# Mise à jour backend NOC — récapitulatif

## Fichiers COMPLETS à remplacer tels quels
- services/interop_service.py     (ajout NSP dans TOOLS)
- services/kpi_service.py         (NSP inclus dans le calcul core_availability)
- services/report_service.py      (fusion des deux KPI_LABELS dupliqués)
- services/incident_service.py    (ingest_incident retourne le Node ; + list_incidents)
- services/auth_service.py        (+ set_password, set_pin)
- routes/incidents.py             (rôles corrigés, requête dupliquée supprimée, /manual, GET liste)
- routes/report.py                (restreint à directeur/chef_noc, clé API ETL toujours OK)
- routes/__init__.py              (enregistre health_router + users_router)

## Fichiers NOUVEAUX (n'existaient pas avant)
- services/user_service.py
- routes/users.py
- routes/health.py

## Fichiers PARTIELS — À FUSIONNER dans vos fichiers existants (schemas_additions/)
Je n'avais pas le contenu de vos schemas/*.py et core/security.py originaux :
ne les écrasez pas, copiez seulement le contenu de ces 3 fichiers dedans.
- schemas_additions/schemas_incidents_ADDITIONS.py  -> à coller dans app/schemas/incidents.py
- schemas_additions/schemas_auth_ADDITIONS.py       -> à coller dans app/schemas/auth.py
- schemas_additions/core_security_ADDITION.py       -> à coller dans app/core/security.py
  (nécessite une relecture : j'ai supposé une implémentation standard de
  verify_api_key/get_current_user que je n'ai pas vue — adaptez les noms de
  header/constante/fonction de décodage JWT à votre code réel)

## À vérifier avant déploiement
1. Les slugs de rôle utilisés partout ("directeur", "chef_noc", "technicien",
   "agent_terrain") DOIVENT correspondre exactement aux valeurs stockées
   dans dim_user.role. Si votre migration a choisi d'autres noms, changez-les
   uniquement dans user_service.VALID_ROLES et les tuples _ROLES en haut de
   routes/incidents.py, routes/users.py, routes/report.py.
2. incident_service.list_incidents() suppose une relation SQLAlchemy
   `Incident.node` (via node_id) — vérifiez qu'elle existe dans models/incident.py,
   sinon remplacez r.node.code / r.node.name / r.node.locality_id par un join
   explicite comme dans get_open_alerts (alerts_service.py).
3. "manual" comme source_tool : à ajouter à toute contrainte CHECK ou enum
   existant sur fact_incident.source_tool, et à interop_service.TOOLS si vous
   voulez qu'il apparaisse (ou pas) sur la vue Interopérabilité.
4. L'endpoint /api/kpi/operational (métriques CPU/RAM/latence) N'EST PAS
   inclus ici : il faut d'abord me confirmer où sont stockées ces métriques
   (nouvelle table fact_metric ? colonnes sur dim_node ?) avant de l'écrire.