"""
Collecteur du NOC.

Interroge les outils sources toutes les COLLECT_INTERVAL_S secondes,
normalise et fusionne leurs réponses en mémoire, et publie l'\''instantané
dans Redis. N'\''écrit sur disque que les agrégats journaliers.

Voir ARCHITECTURE.md pour le pourquoi, collector/state.py pour le contrat
exact des clés Redis.
"""
