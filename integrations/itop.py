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

CLASSE DES TICKETS. Selon le paramétrage, l'agence utilise `Incident`,
`UserRequest`, ou les deux. Plutôt que de deviner, le connecteur interroge
les classes listées dans ITOP_TICKET_CLASSES et ignore silencieusement celles
que l'instance ne connaît pas.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

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
# l'inventaire — silencieusement, puisqu'on tolère les classes absentes.
_CLASS_FIELDS = {
    "NetworkDevice": "id,name,status,org_id_friendlyname,location_id_friendlyname,managementip",
    "Server": "id,name,status,org_id_friendlyname,location_id_friendlyname,managementip",
    "VirtualMachine": "id,name,status,org_id_friendlyname",
}

# Attributs présents sur toute classe dérivée de FunctionalCI. Sert de repli
# quand une instance a été personnalisée et refuse un attribut ci-dessus :
# mieux vaut un inventaire sans localité qu'une classe absente du parc.
_MINIMAL_FIELDS = "id,name,status,org_id_friendlyname"

# Statuts iTop considérés comme CLOS. Un ticket clos n'entre pas dans
# l'instantané : il appartient à l'historique, qui reste chez iTop.
CLOSED_STATES = frozenset({"closed", "resolved"})

# Statuts de CI qui retirent l'équipement du parc supervisé.
RETIRED_STATES = frozenset({"obsolete", "decommissioned", "stock"})


class ITopClient(SourceClient):
    name = "itop"

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 verify_ssl: bool = True, timeout_s: float = 30.0,
                 ticket_classes: tuple[str, ...] = ("Incident", "UserRequest"),
                 zbx_event_field: str = ""):
        super().__init__(base_url, user, password, verify_ssl, timeout_s)
        # L'URL de l'agence porte souvent déjà le script et sa version :
        # « https://helpdesk.example.bf/webservices/rest.php?version=1.0 ».
        # On ne garde que la racine, la version est fixée ci-dessous.
        root = self.base_url.split("/webservices/", 1)[0]
        self.endpoint = f"{root}/webservices/rest.php"
        self.ticket_classes = ticket_classes
        self.zbx_event_field = zbx_event_field.strip()
        # 1.3 : version du protocole REST introduite en iTop 2.5 et toujours
        # servie en 3.2. Elle apporte `core/check_credentials`, utilisé par
        # le contrôle de santé.
        self.protocol_version = "1.3"

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
        # iTop répond TOUJOURS en HTTP 200 : le succès se lit dans `code`.
        # 0 = succès, 1 = authentification refusée, 100+ = erreur d'appel.
        code = result.get("code", -1)
        if code != 0:
            raise ToolUnavailable(
                self.name, f"code {code} : {result.get('message', 'sans message')}"
            )
        return result

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
          * classe inconnue — le module correspondant n'est pas installé :
            ce n'est pas une panne, on passe.
        """
        try:
            return await self._call(
                "core/get",
                {"class": cls, "key": f"SELECT {cls}", "output_fields": fields},
            )
        except ToolUnavailable as exc:
            if "invalid attribute" not in str(exc).lower() or fields == _MINIMAL_FIELDS:
                logger.info("iTop : classe %s ignorée (%s)", cls, exc)
                return None
            logger.info(
                "iTop : classe %s — attribut refusé, repli sur les champs "
                "minimaux (%s)",
                cls,
                exc,
            )
            return await self._get_class(cls, _MINIMAL_FIELDS)

    async def fetch_nodes(self) -> list[Node]:
        nodes: list[Node] = []
        for cls, fields in _CLASS_FIELDS.items():
            result = await self._get_class(cls, fields)
            if result is None:
                continue

            for obj in (result.get("objects") or {}).values():
                fields = obj.get("fields") or {}
                status = str(fields.get("status", "")).lower()
                nodes.append(
                    Node(
                        tool=self.name,
                        ref=str(obj.get("key")),
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

    async def fetch_alerts(self) -> list[Alert]:
        """Tickets OUVERTS. Les tickets clos restent chez iTop."""
        closed = "','".join(sorted(CLOSED_STATES))
        alerts: list[Alert] = []
        fields = (
            "id,ref,title,status,start_date,last_update,priority,"
            "org_id_friendlyname,functionalcis_list"
        )
        if self.zbx_event_field:
            fields += f",{self.zbx_event_field}"

        for cls in self.ticket_classes:
            try:
                result = await self._call(
                    "core/get",
                    {
                        "class": cls,
                        "key": f"SELECT {cls} WHERE status NOT IN ('{closed}')",
                        "output_fields": fields,
                    },
                )
            except ToolUnavailable as exc:
                logger.info("iTop : classe de ticket %s ignorée (%s)", cls, exc)
                continue

            for obj in (result.get("objects") or {}).values():
                f = obj.get("fields") or {}
                ci = (f.get("functionalcis_list") or [{}])[0] if f.get("functionalcis_list") else {}
                alerts.append(
                    Alert(
                        tool=self.name,
                        ref=str(obj.get("key")),
                        severity=severity("itop", f.get("priority")),
                        message=f.get("title") or "(sans objet)",
                        since=sql_to_dt(f.get("start_date")) or datetime.now(timezone.utc),
                        # L'identifiant du CI concerné sert de rattachement à
                        # l'équipement ; le nom sert au rapprochement quand
                        # aucun identifiant commun n'existe.
                        node_ref=str(ci.get("functionalci_id") or "") or None,
                        node_name=ci.get("functionalci_name") or None,
                        # iTop n'a pas d'acquittement au sens supervision :
                        # un ticket pris en charge a changé de statut.
                        acknowledged=str(f.get("status", "")).lower()
                        not in ("new", "nouveau"),
                        ticket_ref=f.get("ref") or None,
                    )
                )
        return alerts

    async def fetch_sla_targets(self) -> list[dict]:
        """Seuils de service (SLT) déclarés dans iTop.

        Lus pour comparer les délais de résolution réels aux engagements
        contractuels, plutôt que de coder en dur un objectif dans le NOC :
        c'est iTop qui porte le contrat, il doit rester la référence.

        Optionnel : une instance sans module de gestion de services ne
        connaît pas la classe SLT, et l'absence n'est pas une erreur.
        """
        try:
            result = await self._call(
                "core/get",
                {
                    "class": "SLT",
                    "key": "SELECT SLT",
                    "output_fields": "id,name,metric,value,unit,priority,request_type",
                },
            )
        except ToolUnavailable:
            return []
        return [
            {"ref": str(obj.get("key")), **(obj.get("fields") or {})}
            for obj in (result.get("objects") or {}).values()
        ]
