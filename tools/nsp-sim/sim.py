"""
Simulateur Nokia NSP — LABORATOIRE LOCAL UNIQUEMENT.

Nokia ne distribue pas NSP : il n'existe aucune instance à monter en
conteneur. Ce simulateur répond aux requêtes que fait le connecteur
(integrations/nsp.py), pour voir comment le NOC affiche, fusionne et alerte
sur des données NSP. Il NE PROUVE PAS que le connecteur fonctionne avec le
vrai NSP de l'agence : il a été écrit d'après ce que le connecteur attend.
Cette preuve-là vient de `python -m collector.probe nsp` sur l'instance réelle.

Requêtes servies (les mêmes que le connecteur) :

    POST /rest-gateway/rest/api/v1/auth/token        Basic -> jeton Bearer
    GET  /restconf/data/nsp-equipment:network/network-element    (mode yang)
    GET  /restconf/data/nsp-fault:alarms/alarm-list              (mode yang)
    GET  /nbi-fm/api/v1/fm/alarms                                (mode classic)

Pilotage du laboratoire (sans authentification, port local uniquement) :

    GET    /_sim/state                    état courant
    POST   /_sim/alarms                   lever une alarme  {"ne_id", "severity", "text"}
    DELETE /_sim/alarms/<id>              effacer une alarme (severity -> cleared)
    POST   /_sim/ne/<ne_id>/state         {"state": "up" | "down" | "degraded"}

Le scénario de départ est `scenario.json` (relu s'il change). Les équipements
qui ont un `flap` tombent d'eux-mêmes `down_min` minutes toutes les
`period_min` minutes, avec leur alarme : le NOC voit une panne apparaître et
disparaître sans qu'on touche à rien.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

USER = os.getenv("NSP_SIM_USER", "admin")
PASSWORD = os.getenv("NSP_SIM_PASSWORD", "NspLab!2026")
TOKEN_TTL_S = int(os.getenv("NSP_SIM_TOKEN_TTL_S", "3600"))
SCENARIO = os.getenv("NSP_SIM_SCENARIO", "/app/scenario.json")
STARTED = datetime.now(timezone.utc)

_lock = threading.Lock()
_tokens: dict[str, float] = {}
_state = {"mtime": None, "nes": {}, "alarms": {}, "manual": {}}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load() -> None:
    """(Re)charge le scénario s'il a changé ; les alarmes levées à la main
    survivent au rechargement."""
    try:
        mtime = os.path.getmtime(SCENARIO)
    except OSError:
        return
    if mtime == _state["mtime"]:
        return
    with open(SCENARIO, encoding="utf8") as handle:
        scenario = json.load(handle)
    now = datetime.now(timezone.utc)
    _state["nes"] = {ne["ne-id"]: dict(ne) for ne in scenario.get("network-elements", [])}
    alarms = {}
    for index, alarm in enumerate(scenario.get("alarms", []), start=1):
        alarm_id = alarm.get("id") or f"scn-{index}"
        alarms[alarm_id] = {
            "id": alarm_id,
            "ne_id": alarm["ne_id"],
            "severity": alarm.get("severity", "major"),
            "text": alarm.get("text", "Alarm"),
            "name": alarm.get("name", alarm.get("text", "Alarm")),
            "since": now - timedelta(minutes=alarm.get("since_minutes", 30)),
            "acknowledged": bool(alarm.get("acknowledged")),
        }
    _state["alarms"] = alarms
    _state["mtime"] = mtime


def _flapping(ne: dict, now: datetime) -> tuple[bool, datetime | None]:
    """L'équipement est-il dans sa fenêtre de panne ? (et depuis quand)"""
    flap = ne.get("flap")
    if not flap:
        return False, None
    period = flap.get("period_min", 60) * 60
    down = flap.get("down_min", 10) * 60
    offset = flap.get("offset_min", 0) * 60
    position = (now.timestamp() - offset) % period
    if position < down:
        return True, now - timedelta(seconds=position)
    return False, None


def _current() -> tuple[list[dict], list[dict]]:
    """Équipements et alarmes à l'instant, flaps et pilotage compris."""
    now = datetime.now(timezone.utc)
    with _lock:
        _load()
        nes = []
        alarms = [dict(a) for a in _state["alarms"].values()]
        alarms += [dict(a) for a in _state["manual"].values()]
        for ne in _state["nes"].values():
            record = {k: v for k, v in ne.items() if k != "flap"}
            down, since = _flapping(ne, now)
            if down:
                record["communication-state"] = "down"
                flap = ne["flap"]
                alarms.append({
                    "id": f"flap-{ne['ne-id']}-{int(since.timestamp())}",
                    "ne_id": ne["ne-id"],
                    "severity": flap.get("severity", "critical"),
                    "text": flap.get("text", "Equipment unreachable"),
                    "name": flap.get("name", "Communication failure"),
                    "since": since,
                    "acknowledged": False,
                })
            nes.append(record)
        return nes, alarms


def _fdn(alarm: dict) -> str:
    return f"fdn:model:fm:Alarm:{alarm['id']}"


def _yang_alarm(alarm: dict, names: dict) -> dict:
    return {
        "alarm-fdn": _fdn(alarm),
        "ne-id": alarm["ne_id"],
        "ne-name": names.get(alarm["ne_id"]),
        "severity": alarm["severity"],
        "alarm-name": alarm["name"],
        "additional-text": alarm["text"],
        "first-time-detected": _iso(alarm["since"]),
        "last-time-detected": _iso(datetime.now(timezone.utc)),
        "acknowledged": alarm["acknowledged"],
        "is-cleared": alarm["severity"] == "cleared",
    }


def _classic_alarm(alarm: dict, names: dict) -> dict:
    return {
        "alarmFdn": _fdn(alarm),
        "neId": alarm["ne_id"],
        "neName": names.get(alarm["ne_id"]),
        "severity": alarm["severity"],
        "alarmName": alarm["name"],
        "additionalText": alarm["text"],
        "firstTimeDetected": int(alarm["since"].timestamp() * 1000),
        "isAcknowledged": alarm["acknowledged"],
        "isCleared": alarm["severity"] == "cleared",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "NSP-Simulator/1.0"

    def log_message(self, fmt, *args):  # journal compact
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _send(self, status: int, body: dict | list | None = None) -> None:
        payload = json.dumps(body if body is not None else {}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        # Un terminal Windows envoie parfois autre chose que de l'UTF-8 (un
        # accent dans le texte d'une alarme) : on remplace plutôt que rejeter.
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw or "{}")
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        expiry = _tokens.get(token)
        return expiry is not None and expiry > time.time()

    # -- API NSP ---------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        if self.path == "/rest-gateway/rest/api/v1/auth/token":
            header = self.headers.get("Authorization", "")
            try:
                user, _, password = base64.b64decode(header[6:]).decode().partition(":")
            except ValueError:
                user, password = "", ""
            if not header.startswith("Basic ") or (user, password) != (USER, PASSWORD):
                return self._send(401, {"error": "invalid_client"})
            token = secrets.token_hex(16)
            _tokens[token] = time.time() + TOKEN_TTL_S
            return self._send(200, {
                "access_token": token, "token_type": "Bearer", "expires_in": TOKEN_TTL_S,
            })
        if self.path == "/_sim/alarms":
            body = self._json()
            if not body.get("ne_id"):
                return self._send(400, {"error": "ne_id requis"})
            alarm_id = f"man-{secrets.token_hex(3)}"
            with _lock:
                _state["manual"][alarm_id] = {
                    "id": alarm_id,
                    "ne_id": body["ne_id"],
                    "severity": body.get("severity", "major"),
                    "text": body.get("text", "Alarme levée à la main"),
                    "name": body.get("name", body.get("text", "Manual alarm")),
                    "since": datetime.now(timezone.utc),
                    "acknowledged": bool(body.get("acknowledged")),
                }
            return self._send(201, {"id": alarm_id})
        if self.path.startswith("/_sim/ne/") and self.path.endswith("/state"):
            ne_id = unquote(self.path[len("/_sim/ne/"):-len("/state")])
            with _lock:
                _load()
                if ne_id not in _state["nes"]:
                    return self._send(404, {"error": "équipement inconnu"})
                _state["nes"][ne_id]["communication-state"] = self._json().get("state", "up")
            return self._send(200, {"ne_id": ne_id})
        return self._send(404, {"error": "inconnu"})

    def do_DELETE(self):  # noqa: N802
        if self.path.startswith("/_sim/alarms/"):
            alarm_id = unquote(self.path[len("/_sim/alarms/"):])
            with _lock:
                for pool in (_state["manual"], _state["alarms"]):
                    if alarm_id in pool:
                        pool[alarm_id]["severity"] = "cleared"
                        return self._send(200, {"id": alarm_id, "severity": "cleared"})
            return self._send(404, {"error": "alarme inconnue"})
        return self._send(404, {"error": "inconnu"})

    def do_GET(self):  # noqa: N802
        if self.path == "/_sim/health":
            return self._send(200, {"status": "ok"})
        if self.path == "/_sim/state":
            nes, alarms = _current()
            return self._send(200, {
                "started_at": _iso(STARTED),
                "network_elements": nes,
                "alarms": [{**a, "since": _iso(a["since"])} for a in alarms],
            })
        if not self._authorised():
            return self._send(401, {"error": "invalid_token"})
        nes, alarms = _current()
        names = {ne["ne-id"]: ne.get("ne-name") for ne in nes}
        if self.path.startswith("/restconf/data/nsp-equipment:network/network-element"):
            return self._send(200, {"nsp-equipment:network-element": nes})
        if self.path.startswith("/restconf/data/nsp-fault:alarms/alarm-list"):
            return self._send(200, {
                "nsp-fault:alarm-list": {"alarm": [_yang_alarm(a, names) for a in alarms]}
            })
        if self.path.startswith("/nbi-fm/api/v1/fm/alarms"):
            return self._send(200, {
                "response": {"status": 0, "data": [_classic_alarm(a, names) for a in alarms]}
            })
        return self._send(404, {"error": "inconnu"})


if __name__ == "__main__":
    port = int(os.getenv("NSP_SIM_PORT", "8080"))
    print(f"Simulateur NSP sur :{port} — scénario {SCENARIO}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
