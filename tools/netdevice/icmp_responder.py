"""
Répondeur ICMP de l'équipement de laboratoire : applique la latence et les
pertes du lien simulé.

POURQUOI PAS `tc netem`. Le noyau WSL2 de Docker Desktop est compilé sans
NET_SCH_NETEM, sans TBF et sans cible NFQUEUE : aucun moyen, côté noyau, de
retarder un paquet. Le conteneur coupe donc la réponse automatique du noyau
(sysctl net.ipv4.icmp_echo_ignore_all=1, propre à son espace réseau) et ce
programme répond lui-même aux demandes d'écho, après DELAY_MS ± JITTER_MS,
en en ignorant LOSS_PCT %.

Le ping de Zabbix (fping) ou de Centreon (check_icmp) reçoit de VRAIES
réponses ICMP et mesure lui-même le temps d'aller-retour : la latence
affichée dans le NOC est une mesure, pas une valeur lue.

Pendant une coupure (fichier OUTAGE_FLAG présent), rien n'est renvoyé.
"""
from __future__ import annotations

import asyncio
import os
import random
import socket
import struct

DELAY_MS = float(os.environ.get("DELAY_MS", "0") or 0)
JITTER_MS = float(os.environ.get("JITTER_MS", "0") or 0)
LOSS_PCT = float(os.environ.get("LOSS_PCT", "0") or 0)
OUTAGE_FLAG = os.environ.get("OUTAGE_FLAG", "/run/outage")


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def reply_for(packet: bytes) -> tuple[bytes, str] | None:
    """Réponse d'écho à un paquet IP reçu, ou None s'il n'en appelle pas."""
    header_len = (packet[0] & 0x0F) * 4
    icmp = packet[header_len:]
    if len(icmp) < 8 or icmp[0] != 8:  # 8 = demande d'écho
        return None
    source = socket.inet_ntoa(packet[12:16])
    body = b"\x00\x00\x00\x00" + icmp[4:]  # type 0 (réponse), code 0, somme nulle
    body = body[:2] + struct.pack("!H", checksum(body)) + body[4:]
    return body, source


def main() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    sock.setblocking(False)
    loop = asyncio.new_event_loop()

    def send(body: bytes, source: str) -> None:
        if os.path.exists(OUTAGE_FLAG):
            return
        try:
            sock.sendto(body, (source, 0))
        except OSError:
            pass

    def on_readable() -> None:
        while True:
            try:
                packet = sock.recv(65535)
            except BlockingIOError:
                return
            answer = reply_for(packet)
            if answer is None or os.path.exists(OUTAGE_FLAG):
                continue
            if LOSS_PCT and random.uniform(0, 100) < LOSS_PCT:
                continue
            delay = max(0.0, random.gauss(DELAY_MS, JITTER_MS) if JITTER_MS else DELAY_MS)
            loop.call_later(delay / 1000.0, send, *answer)

    loop.add_reader(sock.fileno(), on_readable)
    print(f"répondeur ICMP : {DELAY_MS:g} ms ± {JITTER_MS:g}, pertes {LOSS_PCT:g} %", flush=True)
    loop.run_forever()


if __name__ == "__main__":
    main()
