"""
Pousse vers Zabbix, par le protocole Sender, des mesures CPU/mémoire/débit
lues RÉELLEMENT sur les conteneurs de la pile via l'API Docker.

POURQUOI CE DÉTOUR, ET POURQUOI CE N'EST PAS DE LA DONNÉE INVENTÉE.
`tools/provision/` supervise les conteneurs en ICMP (latence, perte,
disponibilité — voir integrations/zabbix.py::_ITEM_KEYS) : une sonde de ce
type ne demande rien à la cible, elle marche donc sur n'importe quel
conteneur. CPU, mémoire et débit sont différents : Zabbix ne les obtient que
d'un AGENT installé dans la cible. Installer zabbix-agent dans les images
backend/frontend/redis/postgres de ce laboratoire les alourdirait pour un
besoin qui n'existe que le temps de la démonstration.

Ce script contourne l'agent, pas la mesure : `docker stats` interroge le
démon Docker, qui connaît le CPU et la mémoire réels de chaque conteneur
sans rien lui demander — exactement ce que fait une sonde ICMP pour la
disponibilité. Values poussées en Trapper sont donc des mesures réelles
d'une machine réelle, au même titre que l'ICMP, seulement lues par une porte
différente. Ce n'est PAS un générateur de données de démonstration : aucun
nombre ici n'est tiré au hasard ni composé à la main.

DÉCOUVERTE DES HÔTES. Aucune liste n'est dupliquée depuis
tools/provision/provision.py::LAB_HOSTS. Ce script interroge Zabbix pour les
hôtes du groupe « RESINA — Laboratoire local » et lit le nom DNS que
provision.py a posé sur chaque interface — c'est CE nom qui sert de clé de
recherche côté Docker (label `com.docker.compose.service`), pas le nom
d'hôte Zabbix. Un hôte ajouté un jour à LAB_HOSTS est donc alimenté sans
toucher à ce fichier.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import struct
import time
import urllib.error
import urllib.request

import docker

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("zabbix-sender")

ZABBIX_API_URL = os.environ["ZABBIX_API_URL"]
ZABBIX_API_USER = os.environ["ZABBIX_API_USER"]
ZABBIX_API_PASSWORD = os.environ["ZABBIX_API_PASSWORD"]
ZABBIX_SERVER_HOST = os.environ.get("ZABBIX_SERVER_HOST", "zabbix-server")
ZABBIX_SERVER_PORT = int(os.environ.get("ZABBIX_SERVER_PORT", "10051"))
INTERVAL_S = int(os.environ.get("ZABBIX_SENDER_INTERVAL_S", "60"))
LAB_GROUP = "RESINA — Laboratoire local"


# ─────────────────────────── API Zabbix (JSON-RPC) ───────────────────────────
class ZabbixApi:
    def __init__(self, url: str, user: str, password: str):
        self.endpoint = url.rstrip("/") + ("" if url.endswith(".php") else "/api_jsonrpc.php")
        self._id = 0
        self.token = self._call("user.login", {"username": user, "password": password}, auth=False)

    def _call(self, method: str, params: dict, auth: bool = True):
        self._id += 1
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(
                {"jsonrpc": "2.0", "method": method, "params": params, "id": self._id}
            ).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read())
        if "error" in body:
            raise RuntimeError(f"{method} : {body['error']}")
        return body["result"]

    def lab_hosts(self) -> list[dict]:
        """[{zabbix_host, dns}, …] pour chaque hôte du groupe laboratoire."""
        groups = self._call("hostgroup.get", {"filter": {"name": [LAB_GROUP]}})
        if not groups:
            return []
        hosts = self._call(
            "host.get",
            {"groupids": [groups[0]["groupid"]], "output": ["host"], "selectInterfaces": ["dns"]},
        )
        result = []
        for host in hosts:
            interfaces = host.get("interfaces") or []
            dns = next((i["dns"] for i in interfaces if i.get("dns")), None)
            if dns:
                result.append({"zabbix_host": host["host"], "dns": dns})
        return result


# ─────────────────────────── protocole Zabbix Sender ───────────────────────────
def send_trapper_values(values: list[dict]) -> None:
    """values : [{"host":…, "key":…, "value":…}, …]

    Format du protocole (stable depuis Zabbix 4.0, documenté officiellement) :
    b"ZBXD" + octet de version (0x01) + longueur du corps sur 4 octets
    little-endian + 4 octets réservés (0) + corps JSON.
    """
    payload = json.dumps({"request": "sender data", "data": values}).encode()
    header = b"ZBXD\x01" + struct.pack("<I", len(payload)) + struct.pack("<I", 0)
    with socket.create_connection((ZABBIX_SERVER_HOST, ZABBIX_SERVER_PORT), timeout=15) as sock:
        sock.sendall(header + payload)
        raw = sock.recv(4096)
    if len(raw) > 13:
        try:
            ack = json.loads(raw[13:])
            log.info("Zabbix sender : %s", ack.get("info", ack))
        except ValueError:
            pass


# ─────────────────────────── lecture Docker ───────────────────────────
# Débit en octets/s : docker stats ne rend qu'un compteur cumulé, il faut donc
# deux lectures espacées pour en tirer un débit — comme le ferait un vrai
# agent Zabbix entre deux de ses propres cycles.
_previous: dict[str, tuple[float, int, int]] = {}  # container_id -> (t, rx, tx)


def _cpu_pct(stats: dict) -> float:
    cpu = stats["cpu_stats"]
    precpu = stats["precpu_stats"]
    cpu_delta = cpu["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
    system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
    online_cpus = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
    if system_delta <= 0 or cpu_delta < 0:
        return 0.0
    return (cpu_delta / system_delta) * online_cpus * 100.0


def _mem_pct(stats: dict) -> float:
    mem = stats["memory_stats"]
    limit = mem.get("limit") or 1
    usage = mem.get("usage", 0) - (mem.get("stats", {}).get("cache", 0))
    return max(0.0, usage / limit * 100.0)


def _net_bytes(stats: dict) -> tuple[int, int]:
    networks = stats.get("networks") or {}
    rx = sum(n.get("rx_bytes", 0) for n in networks.values())
    tx = sum(n.get("tx_bytes", 0) for n in networks.values())
    return rx, tx


def read_container_metrics(client: docker.DockerClient, dns: str) -> dict | None:
    matches = client.containers.list(filters={"label": f"com.docker.compose.service={dns}"})
    if not matches:
        log.warning("aucun conteneur avec le label com.docker.compose.service=%s", dns)
        return None
    container = matches[0]
    stats = container.stats(stream=False)

    now = time.monotonic()
    rx, tx = _net_bytes(stats)
    rx_rate = tx_rate = 0.0
    previous = _previous.get(container.id)
    if previous:
        prev_t, prev_rx, prev_tx = previous
        elapsed = max(now - prev_t, 1e-6)
        rx_rate = max(0.0, (rx - prev_rx) / elapsed)
        tx_rate = max(0.0, (tx - prev_tx) / elapsed)
    _previous[container.id] = (now, rx, tx)

    return {
        "system.cpu.util": round(_cpu_pct(stats), 2),
        "vm.memory.util": round(_mem_pct(stats), 2),
        "net.if.in": round(rx_rate, 2),
        "net.if.out": round(tx_rate, 2),
    }


# ─────────────────────────── boucle ───────────────────────────
def cycle(api: ZabbixApi, docker_client: docker.DockerClient) -> None:
    hosts = api.lab_hosts()
    if not hosts:
        log.warning(
            "aucun hôte dans le groupe « %s » — lancer le provisionnement d'abord "
            "(docker compose --profile provision run --rm provision --only zabbix)",
            LAB_GROUP,
        )
        return

    values = []
    for host in hosts:
        metrics = read_container_metrics(docker_client, host["dns"])
        if metrics is None:
            continue
        for key, value in metrics.items():
            values.append({"host": host["zabbix_host"], "key": key, "value": value})

    if not values:
        log.warning("aucune mesure à envoyer ce cycle")
        return
    send_trapper_values(values)
    log.info("%d valeurs envoyées pour %d hôtes", len(values), len(hosts))


def main() -> None:
    docker_client = docker.from_env()
    api = None
    while api is None:
        try:
            api = ZabbixApi(ZABBIX_API_URL, ZABBIX_API_USER, ZABBIX_API_PASSWORD)
        except (urllib.error.URLError, RuntimeError) as exc:
            log.info("Zabbix pas encore prêt (%s) — nouvel essai dans 10 s", exc)
            time.sleep(10)

    log.info("zabbix-sender démarré — cycle toutes les %d s", INTERVAL_S)
    while True:
        started = time.monotonic()
        try:
            cycle(api, docker_client)
        except Exception:  # noqa: BLE001 — un cycle raté ne doit pas arrêter la boucle
            log.exception("échec du cycle — nouvelle tentative au prochain intervalle")
        time.sleep(max(0.0, INTERVAL_S - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
