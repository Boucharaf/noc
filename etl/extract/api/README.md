# extract/api/

Un connecteur par outil, source **principale et obligatoire** de l'ETL.
Tous respectent la même interface (voir `common.py`) :

```python
fetch_nodes() -> list[dict]
fetch_incidents(since: datetime) -> list[dict]
fetch_metrics(since: datetime) -> list[dict]
health_check() -> bool
```

`pipelines/collector.py` ne connaît que cette interface : il traite
Zabbix, iTop, NetXMS, Centreon, Nagios et NSP exactement de la même
façon, sans `if outil == "zabbix"` dispersés dans le code.

## État des connecteurs

| Outil | Statut | Notes |
|---|---|---|
| `zabbix_client.py` | ✅ fonctionnel | JSON-RPC, testé contre la doc Zabbix 7.0 |
| `itop_client.py` | ✅ fonctionnel | `INCIDENT_CLASS` à confirmer (`Incident` vs `UserRequest` selon paramétrage) |
| `netxms_client.py` | ✅ fonctionnel | cible la *Legacy Web API* (adaptée à la 5.0 utilisée) |
| `centreon_client.py` | ✅ fonctionnel | API v2 ; clôture des incidents déduite par transition d'état (voir `normalize_incidents.py`) |
| `nagios_client.py` | ⚠️ en attente | Nagios Core n'a pas d'API REST native — voir section ci-dessous |
| `nsp_client.py` | ⚠️ en attente | version NSP et module FM (classic/YANG) à confirmer côté agence |

## Nagios — décision à prendre

Nagios Core seul n'expose pas d'API REST. Trois cas possibles :

1. **MK Livestatus** activé (module chargé) → `nagios_client.py` fonctionne déjà en mode `"livestatus"`.
2. **Nagios XI** (licence commerciale) → mode `"xi"`, déjà implémenté.
3. **Aucun des deux**, seul NDOUtils (export MySQL) est disponible → ce n'est pas une API, la collecte passe intégralement par `extract/db/nagios_db_reader.py`. Le connecteur API reste inactif (`NAGIOS_MODE=unknown`), ce qui ne bloque rien : `fetch_*` renvoient des listes vides et le reste du pipeline continue.

À trancher avec l'agence, puis fixer `NAGIOS_MODE` dans `.env`.

## Nokia NSP — décision à prendre

Deux inconnues :
- Version NSP réellement en service (impacte les chemins RESTCONF/PM exacts).
- Module Fault Management "classic" (REST direct, en dépréciation selon Nokia) vs "yang" (RESTCONF + abonnements notification, recommandé pour les nouvelles intégrations).

`nsp_client.py` implémente déjà la bascule via `NSP_FM_MODE`, mais
`fetch_metrics()` (Performance Management) reste à finaliser : l'endpoint
PM dépend d'un module/licence séparé du Fault Management, non documenté
publiquement de façon stable — à obtenir directement de l'agence ou du
représentant Nokia local.
