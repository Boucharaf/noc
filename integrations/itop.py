"""
Connecteur iTop 3.2 — REST/JSON sur /webservices/rest.php.

Documentation : https://www.itophub.io/wiki/page?id=latest:advancedtopics:rest_json

CE QUE LE NOC ATTEND D'iTOP, ET CE QU'IL N'EN ATTEND PAS. iTop est une CMDB
et un outil de gestion de tickets : il sait QUI est responsable d'un
équipement, DANS QUELLE organisation il se trouve, et QUEL ticket est ouvert
dessus. Il ne mesure rien — `fetch_history` rend donc toujours une liste
vide, et c'est normal, pas une panne.

CORRÉLATION AVEC LA SUPERVISION. Rien ne relie nativement un ticket iTop à un
événement Zabbix. Deux chemins, dans cet ordre :
  1. si l'agence a ajouté un champ portant l'identifiant de l'événement
     (`ZBX_EVENT_FIELD`), on l'utilise — c'est exact ;
  2. sinon, la corrélation se fait sur le nom du CI concerné, dans
     collector/merge.py. C'est une heuristique, et elle est traitée comme
     telle : jamais présentée comme un lien certain.

CLASSES DES CI ET DES TICKETS. Selon les modules activés, certaines classes
peuvent manquer. Elles sont omises avec un avertissement explicite; les
autres erreurs d'accès restent des erreurs de collecte.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import SourceClient, ToolUnavailable
from .models import Alert, Node, ToolHealth
from .normalize import severity, sql_to_dt

logger = logging.getLogger(__name__)

# Classes de CI remontées à l'inventaire, avec les attributs demandés pour
# chacune. `PhysicalDevice` couvrirait tout d'un coup, mais rend aussi les
# onduleurs et les baies : on cible ce qui porte une adresse et peut être
# supervisé.
#
# LES ATTRIBUTS DIFFÈRENT D'UNE CLASSE À L'AUTRE, et c'est la source d'une
# erreur qu'on ne voit qu'à l'exécution : `location_id` existe sur
# PhysicalDevice (NetworkDevice, Server) mais PAS sur VirtualMachine, qui
# dérive de VirtualDevice. Demander l'attribut à toutes les classes fait
# répondre iTop « invalid attribute code », et la classe entière disparaît de
# l'inventaire — son absence est alors signalée dans la santé de l'intégration.
_CLASS_FIELDS = {
    "NetworkDevice": "id,name,status,org_id_friendlyname,location_id_friendlyname,managementip",
    "Server": "id,name,status,org_id_friendlyname,location_id_friendlyname,managementip",
    "VirtualMachine": "id,name,status,org_id_friendlyname",
}

# Attributs présents sur toute classe dérivée de FunctionalCI. Sert de repli
# quand une instance a été personnalisée et refuse un attribut ci-dessus :
# mieux vaut un inventaire sans localité qu'une classe absente du parc.
_MINIMAL_FIELDS = "id,name,status,org_id_friendlyname"

# Champs d'un ticket. Le socle existe sur toute classe dérivée de Ticket ;
# les champs de prise en charge sont ceux d'Incident / UserRequest (ITIL).
_TICKET_MINIMAL_FIELDS = (
    "id,ref,title,status,start_date,last_update,priority,"
    "org_id_friendlyname,functionalcis_list"
)
_TICKET_FIELDS = (
    _TICKET_MINIMAL_FIELDS
    + ",urgency,impact,caller_id_friendlyname,agent_id_friendlyname,"
    "team_id_friendlyname,assignment_date,resolution_date,close_date"
)
# Code de résolution (UserRequest, et Incident sur la plupart des instances) :
# la cause retenue à la clôture. Demandé à part pour qu'une classe qui ne le
# porte pas garde quand même ses champs de prise en charge.
_TICKET_FULL_FIELDS = _TICKET_FIELDS + ",resolution_code"
_PAGE_SIZE = 500
_MAX_PAGES = 200

# Équipement cité dans le titre d'un ticket créé automatiquement par un outil
# de supervision — « Alerte NetXMS: 'Node down' sur 'MANGA-DREP-CPEK01' ».
# Sur l'iTop de l'agence, ces tickets n'ont AUCUN CI lié : sans ce repli, ils
# resteraient tous « non localisés » alors que l'équipement est nommé.
# Le rattachement reste signalé comme tel (`from_title`), jamais présenté
# comme un lien CI.
_TITLE_CI = re.compile(r"\bsur\s+'([^']+)'\s*$")

# Statuts iTop considérés comme CLOS. Un ticket clos n'entre pas dans
# l'instantané : il appartient à l'historique, qui reste chez iTop.
# « rejected » est un état final des demandes (UserRequest) : sans lui, une
# demande refusée resterait comptée comme ticket ouvert indéfiniment.
CLOSED_STATES = frozenset({"closed", "resolved", "rejected"})

# Changements (ITIL) : la maintenance planifiée. Un changement refusé ou non
# approuvé n'a pas lieu ; un changement clos est terminé.
CHANGE_DROPPED_STATES = frozenset({"rejected", "notapproved"})
_CHANGE_FIELDS = (
    "ref,title,status,finalclass,start_date,end_date,outage,"
    "org_id_friendlyname,agent_id_friendlyname,team_id_friendlyname,functionalcis_list"
)
_CHANGE_MINIMAL_FIELDS = "ref,title,status,start_date,end_date,functionalcis_list"
_WORKORDER_FIELDS = (
    "name,status,ticket_id,ticket_id_friendlyname,team_id_friendlyname,"
    "agent_id_friendlyname,start_date,end_date,description"
)
_WORKORDER_MINIMAL_FIELDS = "name,status,ticket_id,start_date,end_date"
# Fenêtre des changements et ordres de travail CLOS encore montrés.
_RECENT_DAYS = 30

# Statuts de CI qui retirent l'équipement du parc supervisé.
RETIRED_STATES = frozenset({"obsolete", "decommissioned", "stock"})


class ITopClient(SourceClient):
    name = "itop"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 30.0,
                 ticket_classes: tuple[str, ...] = ("Incident", "UserRequest"),
                 zbx_event_field: str = "", timezone_name: str = "Europe/Paris"):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        # L'URL de l'agence porte souvent déjà le script et sa version :
        # « https://helpdesk.example.bf/webservices/rest.php?version=1.0 ».
        # On ne garde que la racine, la version est fixée ci-dessous.
        root = self.base_url.split("/webservices/", 1)[0]
        self.endpoint = f"{root}/webservices/rest.php"
        self.ticket_classes = ticket_classes
        self.zbx_event_field = zbx_event_field.strip()
        try:
            self.tz = ZoneInfo(timezone_name or "UTC")
        except ZoneInfoNotFoundError:
            logger.error("ITOP_TIMEZONE « %s » inconnu : dates iTop lues en UTC", timezone_name)
            self.tz = ZoneInfo("UTC")
        self.collection_warnings: list[str] = []
        # 1.3 : version du protocole REST introduite en iTop 2.5 et toujours
        # servie en 3.2. Elle apporte `core/check_credentials`, utilisé par
        # le contrôle de santé.
        self.protocol_version = "1.3"

    @staticmethod
    def _is_unknown_class(error: ToolUnavailable) -> bool:
        message = str(error).lower()
        return any(
            marker in message
            for marker in ("unknown class", "class not found", "class does not exist")
        )

    async def _call(self, operation: str, payload: dict) -> dict:
        body = await self._request(
            "POST",
            self.endpoint,
            params={"version": self.protocol_version},
            data={
                "auth_user": self.user,
                "auth_pwd": self.password,
                "json_data": json.dumps({"operation": operation, **payload}),
            },
        )
        try:
            result = body.json()
        except ValueError as exc:
            raise ToolUnavailable(
                self.name, "réponse non-JSON (URL de webservices erronée ?)"
            ) from exc
        if not isinstance(result, dict):
            raise ToolUnavailable(
                self.name,
                f"réponse JSON inattendue : objet attendu, {type(result).__name__} reçu",
            )
        # iTop répond TOUJOURS en HTTP 200 : le succès se lit dans `code`.
        # 0 = succès, 1 = authentification refusée, 100+ = erreur d'appel.
        code = result.get("code", -1)
        if type(code) is not int or code != 0:
            raise ToolUnavailable(
                self.name, f"code {code} : {result.get('message', 'sans message')}"
            )
        return result

    def _objects(self, result: dict, operation: str) -> dict:
        objects = result.get("objects")
        if objects is None and result.get("message") == "Found: 0":
            return {}
        if not isinstance(objects, dict) or any(
            not isinstance(obj, dict)
            or (
                obj.get("fields") is not None
                and not isinstance(obj.get("fields"), dict)
            )
            for obj in objects.values()
        ):
            raise ToolUnavailable(
                self.name,
                f"réponse {operation} invalide : objets avec champs structurés attendus",
            )
        return objects

    async def check(self) -> ToolHealth:
        async def probe():
            await self._call(
                "core/check_credentials",
                {"user": self.user, "password": self.password},
            )
            # iTop ne publie pas sa version par l'API REST ; la renseigner à
            # partir d'une constante serait mentir si l'instance était mise à
            # jour sans qu'on le sache.
            return None

        return await self._health(probe)

    async def _get_class(self, cls: str, fields: str) -> dict | None:
        """`core/get` sur une classe, avec repli sur les attributs minimaux.

        Deux échecs sont possibles et se traitent différemment :
          * attribut refusé — l'instance a un modèle différent de celui
            attendu : on réessaie avec le socle commun à toute FunctionalCI ;
          * toute autre erreur reste visible : ignorer une classe en erreur
            ferait passer un inventaire partiel pour complet.
        """
        try:
            return await self._get_all(
                "core/get",
                {"class": cls, "key": f"SELECT {cls}", "output_fields": fields},
            )
        except ToolUnavailable as exc:
            message = str(exc).lower()
            if "invalid attribute" in message and fields != _MINIMAL_FIELDS:
                logger.info(
                    "iTop : classe %s — attribut refusé, repli sur les champs minimaux (%s)",
                    cls,
                    exc,
                )
                return await self._get_class(cls, _MINIMAL_FIELDS)
            if self._is_unknown_class(exc):
                warning = f"classe iTop {cls} non disponible"
                self.collection_warnings.append(warning)
                logger.warning("iTop : %s (%s)", warning, exc)
                return None
            raise

    async def _get_all(self, operation: str, payload: dict) -> dict:
        objects: dict = {}
        offset = 0
        for _ in range(_MAX_PAGES):
            result = await self._call(
                operation,
                {**payload, "limit": f"{offset},{_PAGE_SIZE}"},
            )
            page = self._objects(result, operation)
            objects.update(page)
            message = str(result.get("message", ""))
            total = None
            if message.startswith("Found:"):
                try:
                    total = int(message.partition(":")[2].strip())
                except ValueError:
                    total = None
            if total is not None and len(page) < _PAGE_SIZE:
                if offset + len(page) >= total:
                    return {"objects": objects, "message": f"Found: {len(objects)}"}
                if page:
                    offset += len(page)
                    continue
            if not page and total is not None and offset < total:
                raise ToolUnavailable(
                    self.name,
                    f"pagination iTop incomplète : {offset} objet(s) reçu(s) "
                    f"sur {total} annoncés",
                )
            if len(page) < _PAGE_SIZE and total is None:
                return {"objects": objects, "message": f"Found: {len(objects)}"}
            offset += len(page)
        raise ToolUnavailable(
            self.name,
            f"pagination iTop interrompue après {_MAX_PAGES} pages; "
            "résultat incomplet",
        )

    async def fetch_nodes(self) -> list[Node]:
        nodes: list[Node] = []
        for cls, fields in _CLASS_FIELDS.items():
            result = await self._get_class(cls, fields)
            if result is None:
                continue

            for obj in self._objects(result, "core/get").values():
                fields = obj.get("fields") or {}
                node_id = fields.get("id")
                if node_id is None:
                    raise ToolUnavailable(
                        self.name,
                        f"CI {obj.get('key')} sans identifiant numérique",
                    )
                status = str(fields.get("status", "")).lower()
                nodes.append(
                    Node(
                        tool=self.name,
                        # Les tickets exposent functionalci_id ; il correspond
                        # à l'identifiant numérique, pas à la clé OQL Class::id.
                        ref=str(node_id),
                        name=fields.get("name") or "(sans nom)",
                        hostname=fields.get("name") or "",
                        ip=fields.get("managementip") or None,
                        # iTop est un référentiel : il déclare ce qui DEVRAIT
                        # exister, pas ce qui répond. L'état vient de la
                        # supervision, jamais d'ici.
                        state="unknown",
                        enabled=status not in RETIRED_STATES,
                        organisation=fields.get("org_id_friendlyname") or None,
                        site=fields.get("location_id_friendlyname") or None,
                        node_type=cls,
                    )
                )
        return nodes

    async def _get_tickets(self, cls: str, condition: str) -> dict | None:
        """Tickets d'une classe, champs détaillés puis socle commun.

        Les champs de prise en charge (agent, équipe, dates) existent sur
        Incident et UserRequest du modèle ITIL standard, mais une instance
        personnalisée peut en retirer : iTop refuse alors TOUTE la requête
        (« invalid attribute »). Le socle suffit à compter et rattacher les
        tickets ; la perte de détail est signalée, pas la classe entière.
        """
        for fields in (_TICKET_FULL_FIELDS, _TICKET_FIELDS, _TICKET_MINIMAL_FIELDS):
            if self.zbx_event_field:
                fields = f"{fields},{self.zbx_event_field}"
            try:
                return await self._get_all(
                    "core/get",
                    {
                        "class": cls,
                        "key": f"SELECT {cls} WHERE {condition}",
                        "output_fields": fields,
                    },
                )
            except ToolUnavailable as exc:
                if self._is_unknown_class(exc):
                    warning = f"classe de tickets iTop {cls} non disponible"
                    self.collection_warnings.append(warning)
                    logger.warning("iTop : %s (%s)", warning, exc)
                    return None
                refused = "invalid attribute" in str(exc).lower()
                if refused and fields.startswith(_TICKET_FULL_FIELDS):
                    logger.info("iTop : tickets %s sans code de résolution (%s)", cls, exc)
                    continue
                if refused and fields.startswith(_TICKET_FIELDS):
                    warning = f"tickets {cls} : détails de prise en charge indisponibles"
                    self.collection_warnings.append(warning)
                    logger.info("iTop : %s (%s)", warning, exc)
                    continue
                raise
        return None

    def _ticket(self, cls: str, obj: dict) -> dict:
        """Un ticket iTop, sous forme normalisée (dates en UTC)."""
        f = obj.get("fields") or {}
        since = sql_to_dt(f.get("start_date"), self.tz)
        if since is None:
            raise ToolUnavailable(
                self.name, f"ticket {obj.get('key')} sans date de début valide"
            )
        cis = [
            {
                "ref": str(ci.get("functionalci_id") or "") or None,
                "name": ci.get("functionalci_name") or None,
            }
            for ci in (f.get("functionalcis_list") or [])
            if isinstance(ci, dict)
        ]
        if not cis:
            cited = _TITLE_CI.search(str(f.get("title") or ""))
            if cited:
                cis = [{"ref": None, "name": cited.group(1).strip(), "from_title": True}]
        return {
            "id": str(f.get("id") or obj.get("key")),
            "ref": f.get("ref") or None,
            "class": cls,
            "title": f.get("title") or "(sans objet)",
            "status": str(f.get("status") or "").lower() or None,
            "priority": f.get("priority"),
            "severity": severity("itop", f.get("priority")),
            "urgency": f.get("urgency"),
            "impact": f.get("impact"),
            "organisation": f.get("org_id_friendlyname") or None,
            "caller": f.get("caller_id_friendlyname") or None,
            "agent": f.get("agent_id_friendlyname") or None,
            "team": f.get("team_id_friendlyname") or None,
            "start_date": since,
            "assignment_date": sql_to_dt(f.get("assignment_date"), self.tz),
            "resolution_date": sql_to_dt(f.get("resolution_date"), self.tz),
            "close_date": sql_to_dt(f.get("close_date"), self.tz),
            "last_update": sql_to_dt(f.get("last_update"), self.tz),
            # None : la classe ne porte pas le champ ; "" : cause non saisie.
            # La différence compte pour la part d'incidents sans cause.
            "resolution_code": (
                str(f["resolution_code"] or "") if "resolution_code" in f else None
            ),
            "cis": cis,
            "zbx_event": f.get(self.zbx_event_field) if self.zbx_event_field else None,
        }

    # -- Maintenances et interventions -------------------------------------
    async def _get_optional(self, cls: str, condition: str, fields_options: tuple) -> dict | None:
        """`core/get` sur une classe que l'instance n'a peut-être pas (module
        de gestion des changements non installé) ou dont un champ manque.
        Classe absente : None, signalé ; champ absent : jeu de champs réduit."""
        for fields in fields_options:
            try:
                return await self._get_all(
                    "core/get",
                    {"class": cls, "key": f"SELECT {cls} WHERE {condition}", "output_fields": fields},
                )
            except ToolUnavailable as exc:
                if self._is_unknown_class(exc):
                    self.collection_warnings.append(f"classe iTop {cls} non disponible")
                    return None
                if "invalid attribute" in str(exc).lower() and fields != fields_options[-1]:
                    logger.info("iTop : %s, champs réduits (%s)", cls, exc)
                    continue
                raise
        return None

    def _recent_bound(self) -> str:
        from datetime import timedelta, timezone

        bound = datetime.now(timezone.utc) - timedelta(days=_RECENT_DAYS)
        return f"{bound.astimezone(self.tz):%Y-%m-%d %H:%M:%S}"

    @staticmethod
    def _cis(fields: dict) -> list[dict]:
        cis = [
            {
                "ref": str(ci.get("functionalci_id") or "") or None,
                "name": ci.get("functionalci_name") or None,
            }
            for ci in (fields.get("functionalcis_list") or [])
            if isinstance(ci, dict)
        ]
        if not cis:
            cited = _TITLE_CI.search(str(fields.get("title") or ""))
            if cited:
                cis = [{"ref": None, "name": cited.group(1).strip(), "from_title": True}]
        return cis

    def _iso(self, value) -> str | None:
        parsed = sql_to_dt(value, self.tz)
        return parsed.isoformat() if parsed else None

    async def fetch_maintenance(self) -> list[dict]:
        """Changements iTop : en cours, à venir, et clos depuis moins de
        30 jours. Un changement sans date de début n'est pas planifié : il
        n'est pas une fenêtre de maintenance."""
        bound = self._recent_bound()
        result = await self._get_optional(
            "Change",
            # OQL n'a pas « IS NULL » : c'est la fonction ISNULL().
            f"end_date >= '{bound}' OR (status != 'closed' AND ISNULL(end_date))",
            (_CHANGE_FIELDS, _CHANGE_MINIMAL_FIELDS),
        )
        if result is None:
            return []
        windows = []
        for key, obj in self._objects(result, "core/get").items():
            f = obj.get("fields") or {}
            status = str(f.get("status") or "").lower() or None
            start = self._iso(f.get("start_date"))
            if start is None or status in CHANGE_DROPPED_STATES:
                continue
            outage = str(f.get("outage") or "").lower()
            windows.append({
                "key": f"itop:change:{obj.get('key') or key}",
                "tool": self.name,
                "kind": "change",
                "ref": f.get("ref") or None,
                "title": f.get("title") or "(sans objet)",
                "status": status,
                "change_type": f.get("finalclass") or None,
                "start": start,
                "end": self._iso(f.get("end_date")),
                "outage": True if outage == "yes" else False if outage == "no" else None,
                "organisation": f.get("org_id_friendlyname") or None,
                "agent": f.get("agent_id_friendlyname") or None,
                "team": f.get("team_id_friendlyname") or None,
                "cis": self._cis(f),
            })
        return windows

    async def fetch_work_orders(self) -> list[dict]:
        """Ordres de travail iTop ouverts, et clos depuis moins de 30 jours,
        avec les CI du ticket auquel chacun est rattaché."""
        bound = self._recent_bound()
        result = await self._get_optional(
            "WorkOrder",
            f"status = 'open' OR end_date >= '{bound}'",
            (_WORKORDER_FIELDS, _WORKORDER_MINIMAL_FIELDS),
        )
        if result is None:
            return []
        objects = self._objects(result, "core/get")
        ticket_ids = sorted({
            str((obj.get("fields") or {}).get("ticket_id"))
            for obj in objects.values()
            if str((obj.get("fields") or {}).get("ticket_id") or "0") not in ("", "0")
        })
        tickets: dict[str, dict] = {}
        if ticket_ids:
            found = await self._get_optional(
                "Ticket",
                f"id IN ({','.join(ticket_ids)})",
                ("ref,title,finalclass,functionalcis_list", "ref,title,functionalcis_list"),
            )
            for key, obj in self._objects(found or {}, "core/get").items() if found else ():
                f = obj.get("fields") or {}
                tickets[str(obj.get("key") or key)] = {
                    "id": str(obj.get("key") or key),
                    "ref": f.get("ref") or None,
                    "title": f.get("title") or None,
                    "class": f.get("finalclass") or None,
                    "cis": self._cis(f),
                }
        orders = []
        for key, obj in objects.items():
            f = obj.get("fields") or {}
            ticket = tickets.get(str(f.get("ticket_id") or ""))
            orders.append({
                "key": f"itop:workorder:{obj.get('key') or key}",
                "ref": f.get("name") or None,
                "title": f.get("name") or "(sans objet)",
                "status": str(f.get("status") or "").lower() or None,
                "start": self._iso(f.get("start_date")),
                "end": self._iso(f.get("end_date")),
                "team": f.get("team_id_friendlyname") or None,
                "agent": f.get("agent_id_friendlyname") or None,
                "description": f.get("description") or None,
                "ticket": (
                    {k: v for k, v in ticket.items() if k != "cis"}
                    if ticket
                    else ({"ref": f.get("ticket_id_friendlyname")} if f.get("ticket_id_friendlyname") else None)
                ),
                "cis": ticket["cis"] if ticket else [],
            })
        return orders

    async def fetch_alerts(self) -> list[Alert]:
        """Return open ITSM tickets as records distinct from technical alerts."""
        closed = "','".join(sorted(CLOSED_STATES))
        alerts: list[Alert] = []
        for cls in self.ticket_classes:
            result = await self._get_tickets(cls, f"status NOT IN ('{closed}')")
            if result is None:
                continue
            for obj in self._objects(result, "core/get").values():
                ticket = self._ticket(cls, obj)
                ci = ticket["cis"][0] if ticket["cis"] else {}
                alerts.append(
                    Alert(
                        tool=self.name,
                        ref=ticket["id"],
                        severity=ticket["severity"],
                        message=ticket["title"],
                        since=ticket["start_date"],
                        # L'identifiant du CI concerné sert de rattachement à
                        # l'équipement ; le nom sert au rapprochement quand
                        # aucun identifiant commun n'existe.
                        node_ref=ci.get("ref"),
                        node_name=ci.get("name"),
                        # iTop n'a pas d'acquittement au sens supervision :
                        # un ticket pris en charge a changé de statut.
                        acknowledged=(ticket["status"] or "") not in ("new", "nouveau"),
                        acknowledged_at=ticket["assignment_date"],
                        ticket_ref=ticket["ref"],
                        kind="itsm_ticket",
                        details={
                            key: ticket[key]
                            for key in (
                                "class", "status", "priority", "urgency", "impact",
                                "organisation", "caller", "agent", "team",
                                "assignment_date", "resolution_date", "last_update",
                                "cis", "zbx_event",
                            )
                        },
                    )
                )
        return alerts

    async def fetch_incident_history(self, start: datetime, end: datetime) -> list[dict]:
        """Tickets ouverts sur la période [start, end), clos ou non.

        Sert au calcul des SLA : l'instantané ne contient que les tickets
        OUVERTS, alors qu'un taux de respect porte sur ceux qui ont été
        résolus. Ils restent chez iTop et y sont lus à la demande — la même
        fédération que les courbes, jamais une recopie.
        """
        # Bornes exprimées dans le fuseau d'iTop, comme ses dates en base.
        window = (
            f"start_date >= '{start.astimezone(self.tz):%Y-%m-%d %H:%M:%S}' "
            f"AND start_date < '{end.astimezone(self.tz):%Y-%m-%d %H:%M:%S}'"
        )
        tickets: list[dict] = []
        for cls in self.ticket_classes:
            result = await self._get_tickets(cls, window)
            if result is None:
                continue
            tickets.extend(
                self._ticket(cls, obj) for obj in self._objects(result, "core/get").values()
            )
        return tickets

    async def fetch_sla_targets(self) -> list[dict]:
        """Seuils de service (SLT) déclarés dans iTop.

        Lus pour comparer les délais de résolution réels aux engagements
        contractuels, plutôt que de coder en dur un objectif dans le NOC :
        c'est iTop qui porte le contrat, il doit rester la référence.

        Si la classe n'existe pas ou si l'API échoue, l'erreur remonte au
        consommateur : une liste vide ferait passer un SLA indisponible pour
        une instance sans objectif.
        """
        result = await self._call(
            "core/get",
            {
                "class": "SLT",
                "key": "SELECT SLT",
                "output_fields": "id,name,metric,value,unit,priority,request_type",
            },
        )
        return [
            {"ref": str(obj.get("key")), **(obj.get("fields") or {})}
            for obj in self._objects(result, "core/get").values()
        ]
