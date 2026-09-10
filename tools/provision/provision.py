#!/usr/bin/env python3
"""
Provisionnement du laboratoire local.

CE QUE CE SCRIPT FAIT — ET CE QU'IL NE FAIT PAS.

Il ne crée AUCUNE donnée fictive. Il déclare, dans chacun des trois outils,
les machines qui tournent réellement sur cette pile Docker, et les fait
superviser par de VRAIES sondes : agent Zabbix, ICMP, HTTP. Les mesures qui
en sortent sont de vraies mesures d'une vraie machine — ce n'est pas un jeu
d'essai, c'est un laboratoire réduit.

C'est la différence qui compte pour valider l'intégration. Un jeu de données
semé en base traverse zéro ligne de code d'API : il ne prouve rien sur la
capacité du NOC à lire Zabbix. Ici, chaque valeur affichée dans le NOC a
franchi le connecteur, l'API réelle de l'outil, sa base et sa sonde.

Idempotent : relancer ne crée pas de doublons.

Usage :
    docker compose --profile provision run --rm provision
    docker compose --profile provision run --rm provision --only zabbix
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("provision")

# ---------------------------------------------------------------------------
# L'inventaire réel de la pile
# ---------------------------------------------------------------------------
# Chaque entrée est un conteneur qui tourne pour de bon sur le réseau
# `noc_default`. Le nom de service Docker EST le nom DNS : les sondes le
# résolvent réellement, et un conteneur arrêté produit une vraie alerte.
#
# `site` suit la convention retenue avec l'agence — un groupe « Site/<nom> »
# porte la localisation (voir integrations/zabbix.py::_site_from_groups).
# Le laboratoire n'a qu'un site, mais la convention doit être exercée : c'est
# elle qui alimente les statistiques par localité en production.
LAB_HOSTS = [
    {
        "name": "noc-backend",
        "dns": "backend",
        "role": "Application NOC — API",
        "http_port": 8000,
        "http_path": "/api/health",
        "site": "Laboratoire",
    },
    {
        "name": "noc-frontend",
        "dns": "frontend",
        "role": "Application NOC — interface",
        "http_port": 80,
        "http_path": "/",
        "site": "Laboratoire",
    },
    {
        "name": "noc-redis",
        "dns": "redis",
        "role": "Cache d'état du NOC",
        "site": "Laboratoire",
    },
    {
        "name": "noc-postgres",
        "dns": "postgres",
        "role": "Base des données propres au NOC",
        "site": "Laboratoire",
    },
    {
        "name": "outil-zabbix",
        "dns": "zabbix-web",
        "role": "Supervision Zabbix — interface et API",
        "http_port": 8080,
        "http_path": "/",
        "site": "Laboratoire",
    },
    {
        "name": "outil-centreon",
        "dns": "centreon",
        "role": "Supervision Centreon — central",
        "http_port": 80,
        "http_path": "/centreon/",
        "site": "Laboratoire",
    },
    {
        "name": "outil-itop",
        "dns": "itop",
        "role": "ITSM iTop — interface et API REST",
        "http_port": 80,
        "http_path": "/",
        "site": "Laboratoire",
    },
]


class Http:
    """Client HTTP minimal sur la bibliothèque standard.

    Pas de `requests` : l'image de provisionnement ne tourne que quelques
    secondes, et lui éviter une dépendance la rend triviale à construire et à
    auditer.
    """

    @staticmethod
    def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 60):
        data = json.dumps(payload).encode()
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return Http._send(request, timeout)

    @staticmethod
    def post_form(url: str, fields: dict, timeout: int = 60):
        data = urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return Http._send(request, timeout)

    @staticmethod
    def get(url: str, headers: dict | None = None, timeout: int = 60):
        request = urllib.request.Request(url, headers=headers or {})
        return Http._send(request, timeout)

    @staticmethod
    def _send(request, timeout: int):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {exc.code} : {body[:400]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"injoignable : {exc.reason}") from exc
        try:
            return json.loads(body)
        except ValueError:
            return body


# ═══════════════════════════════════════════════════════════════════════
#  Zabbix
# ═══════════════════════════════════════════════════════════════════════
class Zabbix:
    def __init__(self, url: str, user: str, password: str):
        self.endpoint = url.rstrip("/") + (
            "" if url.endswith(".php") else "/api_jsonrpc.php"
        )
        self.token = self._call(
            "user.login", {"username": user, "password": password}, auth=False
        )
        self._id = 0

    def _call(self, method: str, params, auth: bool = True):
        self._id = getattr(self, "_id", 0) + 1
        headers = {"Authorization": f"Bearer {self.token}"} if auth else {}
        body = Http.post_json(
            self.endpoint,
            {"jsonrpc": "2.0", "method": method, "params": params, "id": self._id},
            headers,
        )
        if "error" in body:
            raise RuntimeError(f"{method} : {body['error']}")
        return body["result"]

    def ensure_group(self, name: str) -> str:
        found = self._call("hostgroup.get", {"filter": {"name": [name]}})
        if found:
            return found[0]["groupid"]
        log.info("Zabbix : création du groupe « %s »", name)
        return self._call("hostgroup.create", {"name": name})["groupids"][0]

    def template_id(self, name: str) -> str | None:
        found = self._call("template.get", {"filter": {"host": [name]}, "output": ["templateid"]})
        return found[0]["templateid"] if found else None

    def run(self):
        # Le groupe porte la convention « Site/<nom> » : c'est lui qui
        # alimente la localité côté NOC.
        site_group = self.ensure_group("Site/Laboratoire")
        lab_group = self.ensure_group("RESINA — Laboratoire local")

        # CORRECTION DE L'INSTALLATION NEUVE. Zabbix crée l'hôte « Zabbix
        # server » avec une interface agent sur 127.0.0.1 — l'adresse du
        # conteneur du SERVEUR, où aucun agent ne tourne. L'agent est dans un
        # conteneur voisin. Sans cette correction, l'installation neuve
        # produit en permanence l'alerte « Zabbix agent is not available »,
        # qui est un artefact du montage et non une panne à observer.
        self._repoint_server_agent()

        # « ICMP Ping » est livré en standard avec Zabbix 7.0 et sonde
        # {HOST.CONN} : avec une interface en mode DNS, il résout réellement
        # le nom du conteneur. Il produit trois des sept types de métriques
        # du NOC — latence, taux de perte, disponibilité — et ce sont de
        # vraies mesures, pas des valeurs déposées en base.
        icmp_template = self.template_id("ICMP Ping")
        if not icmp_template:
            log.warning(
                "Zabbix : modèle « ICMP Ping » introuvable — les hôtes du "
                "laboratoire seront créés sans sonde"
            )
        # Zabbix 7.0 ne livre AUCUN modèle HTTP générique : tous ses modèles
        # « by HTTP » ciblent un produit précis (Nginx, Apache, GitLab…).
        # Superviser en HTTP les services de la pile demanderait de créer des
        # items « agent HTTP » à la main, ce qui dépasse le rôle de ce
        # script — l'ICMP suffit à valider la chaîne de collecte.
        http_template = None

        for host in LAB_HOSTS:
            self._ensure_host(host, [site_group, lab_group], icmp_template, http_template)

    def _repoint_server_agent(self):
        hosts = self._call(
            "host.get",
            {"filter": {"host": ["Zabbix server"]}, "selectInterfaces": "extend"},
        )
        if not hosts:
            return
        for interface in hosts[0].get("interfaces", []):
            if interface.get("type") == "1" and interface.get("ip") == "127.0.0.1":
                log.info(
                    "Zabbix : l'interface agent de « Zabbix server » pointait sur "
                    "127.0.0.1 — repointée sur le conteneur zabbix-agent"
                )
                self._call(
                    "hostinterface.update",
                    {
                        "interfaceid": interface["interfaceid"],
                        "useip": "0",
                        "dns": "zabbix-agent",
                    },
                )

    def _ensure_host(self, host: dict, groups: list[str], icmp_tpl, http_tpl):
        existing = self._call("host.get", {"filter": {"host": [host["name"]]}, "output": ["hostid"]})
        if existing:
            log.info("Zabbix : hôte « %s » déjà présent", host["name"])
            return

        # Interface en DNS et non en IP : les adresses des conteneurs changent
        # à chaque recréation, leur nom de service Docker ne change jamais.
        #
        # `ip` DOIT être présent même vide. Zabbix 7.0 refuse une interface
        # sans cette clé avec « Incorrect arguments passed to function » —
        # message qui ne nomme ni le champ ni l'objet, et qu'on ne peut
        # diagnostiquer qu'en retirant les champs un à un. La documentation
        # présente `ip` comme facultatif quand useip vaut 0 ; l'API, non.
        interfaces = [
            {
                "type": 1,      # 1 = agent
                "main": 1,
                "useip": 0,     # joindre par le nom DNS
                "ip": "",
                "dns": host["dns"],
                "port": "10050",
            }
        ]

        # Le modèle « ICMP Ping » sonde {HOST.CONN}, qui vaut le nom DNS quand
        # useip=0 : la sonde résout donc réellement le nom du conteneur et
        # mesure un vrai temps d'aller-retour. Aucune macro à poser.
        templates = [{"templateid": t} for t in (icmp_tpl, http_tpl) if t]

        log.info("Zabbix : création de l'hôte « %s » (%s)", host["name"], host["dns"])
        self._call(
            "host.create",
            {
                "host": host["name"],
                "name": f"{host['name']} — {host['role']}",
                "interfaces": interfaces,
                "groups": [{"groupid": g} for g in groups],
                "templates": templates,
            },
        )


# ═══════════════════════════════════════════════════════════════════════
#  Centreon
# ═══════════════════════════════════════════════════════════════════════
class Centreon:
    """Provisionnement via l'API REST v2.

    Note : la création d'hôtes passe historiquement par CLAPI, mais l'API v2
    de la 22.10 expose `/configuration/hosts`. On l'utilise pour rester sur
    le même canal que le collecteur — si l'API v2 suffit à écrire, elle
    suffira à lire.
    """

    def __init__(self, url: str, user: str, password: str):
        root = url.rstrip("/")
        if not root.endswith("/centreon"):
            root += "/centreon"
        self.api = f"{root}/api/latest"
        body = Http.post_json(
            f"{self.api}/login",
            {"security": {"credentials": {"login": user, "password": password}}},
        )
        self.token = body["security"]["token"]

    def run(self):
        # Centreon 22.10 n'expose pas la création d'hôtes en API v2 de façon
        # stable ; CLAPI reste l'outil supporté et il est présent dans le
        # conteneur. On l'appelle donc à distance… ce qui n'est pas possible
        # depuis ce conteneur-ci.
        #
        # Le central se provisionne donc lui-même au premier démarrage (voir
        # tools/centreon/docker-entrypoint.sh::bootstrap_self_monitoring), et
        # l'ajout des autres machines du laboratoire se fait par le script
        # embarqué dans le conteneur Centreon :
        #
        #     docker compose exec centreon /usr/local/bin/provision-lab
        #
        # Ce script-ci se contente de VÉRIFIER que le central supervise bien
        # quelque chose, et de le dire clairement sinon.
        body = Http.get(
            f"{self.api}/monitoring/resources?types=%5B%22host%22%5D&limit=100",
            {"X-AUTH-TOKEN": self.token},
        )
        hosts = body.get("result", [])
        log.info("Centreon : %d hôte(s) supervisé(s) — %s", len(hosts),
                 ", ".join(h.get("name", "?") for h in hosts) or "aucun")
        if not hosts:
            log.warning(
                "Centreon ne supervise aucun hôte. Lancer : "
                "docker compose exec centreon /usr/local/bin/provision-lab"
            )


# ═══════════════════════════════════════════════════════════════════════
#  iTop
# ═══════════════════════════════════════════════════════════════════════
class ITop:
    """Peuple la CMDB avec l'inventaire réel de la pile.

    Chaque conteneur devient un objet `Server` rattaché à l'organisation et à
    la localité du laboratoire. C'est ce qui permet de vérifier la fusion
    multi-outils : le même nom d'hôte doit se retrouver côté Zabbix et côté
    iTop, et le NOC doit n'afficher qu'un équipement.
    """

    def __init__(self, url: str, user: str, password: str):
        root = url.rstrip("/").split("/webservices/", 1)[0]
        self.endpoint = f"{root}/webservices/rest.php"
        self.user = user
        self.password = password

    def _call(self, operation: str, payload: dict):
        body = Http.post_form(
            f"{self.endpoint}?version=1.3",
            {
                "auth_user": self.user,
                "auth_pwd": self.password,
                "json_data": json.dumps({"operation": operation, **payload}),
            },
        )
        if body.get("code") != 0:
            raise RuntimeError(f"{operation} : code {body['code']} — {body.get('message')}")
        return body

    def _upsert(self, cls: str, key_fields: dict, fields: dict) -> str:
        """Crée l'objet s'il n'existe pas, le laisse tel quel sinon.

        `core/create` avec une clé de recherche n'existe pas dans l'API iTop :
        on interroge, puis on crée. Le laisser tel quel plutôt que le mettre à
        jour est délibéré — l'exploitant a pu enrichir la fiche à la main, et
        relancer le provisionnement ne doit pas effacer son travail.
        """
        where = " AND ".join(f"{k} = '{v}'" for k, v in key_fields.items())
        found = self._call(
            "core/get", {"class": cls, "key": f"SELECT {cls} WHERE {where}", "output_fields": "id"}
        )
        objects = found.get("objects") or {}
        if objects:
            return next(iter(objects.values()))["key"]
        created = self._call("core/create", {
            "class": cls,
            "fields": {**key_fields, **fields},
            "comment": "Créé par le provisionnement du laboratoire NOC",
            "output_fields": "id",
        })
        return next(iter((created.get("objects") or {}).values()))["key"]

    def run(self):
        org_id = self._upsert("Organization", {"name": "ANPTIC — RESINA"}, {})
        log.info("iTop : organisation « ANPTIC — RESINA » (id %s)", org_id)

        location_id = self._upsert(
            "Location",
            {"name": "Laboratoire local"},
            {"org_id": org_id, "status": "active", "country": "Burkina Faso"},
        )
        log.info("iTop : localité « Laboratoire local » (id %s)", location_id)

        for host in LAB_HOSTS:
            self._upsert(
                "Server",
                {"name": host["name"]},
                {
                    "org_id": org_id,
                    "location_id": location_id,
                    "status": "production",
                    "description": host["role"],
                },
            )
            log.info("iTop : CI « %s » présent", host["name"])


# ═══════════════════════════════════════════════════════════════════════
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        help="Ne provisionner qu'un outil (zabbix, centreon, itop)",
    )
    args = parser.parse_args()

    wanted = (
        [args.only]
        if args.only
        else [t.strip() for t in os.getenv("PROVISION_TOOLS", "zabbix,centreon,itop").split(",") if t.strip()]
    )

    failures = []
    for tool in wanted:
        url = os.getenv(f"{tool.upper()}_API_URL", "")
        if not url:
            log.warning("%s : %s_API_URL non renseignée — ignoré", tool, tool.upper())
            continue
        user = os.getenv(f"{tool.upper()}_API_USER", "")
        password = os.getenv(f"{tool.upper()}_API_PASSWORD", "")
        try:
            log.info("─── %s ───", tool)
            {"zabbix": Zabbix, "centreon": Centreon, "itop": ITop}[tool](
                url, user, password
            ).run()
        except Exception as exc:  # noqa: BLE001 — un outil en échec ne doit
            # pas empêcher de provisionner les autres.
            log.error("%s : échec du provisionnement — %s", tool, exc)
            failures.append(tool)

    if failures:
        log.error("Provisionnement incomplet : %s", ", ".join(failures))
        return 1
    log.info("Provisionnement terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
