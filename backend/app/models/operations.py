"""
Tables propres au NOC — miroir de backend/sql/schema.sql.

RIEN ICI NE DÉCRIT UN ÉQUIPEMENT NI UNE ALERTE. Ces objets vivent dans
l'instantané Redis et chez les outils sources ; les modèles ci-dessous ne
portent que ce que le NOC AJOUTE : qui a acquitté, avec quel commentaire,
quelle cause a été retenue, quelle maintenance était prévue.

Les liaisons se font par CLÉ TEXTUELLE (`alert_key`, `node_key`) et non par
clé étrangère : l'objet désigné n'est pas dans cette base. Conséquence
assumée — une note peut survivre à l'alerte qu'elle commente, et c'est
voulu : l'historique d'exploitation du NOC doit persister même après que
Zabbix a purgé l'événement d'origine.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.session import Base


class User(Base):
    __tablename__ = "noc_user"

    id = Column(Integer, primary_key=True)
    username = Column(Text, unique=True, nullable=False)
    full_name = Column(Text)
    role = Column(Text, nullable=False, default="agent_terrain")
    password_hash = Column(Text)
    # Code court saisi sur mobile par les agents de terrain. Distinct du mot
    # de passe : taper une phrase de passe sur un téléphone, en haut d'un
    # pylône, n'est pas réaliste.
    pin_hash = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True))
    # Rattachement en TEXTE : la géographie appartient aux outils sources
    # (groupes Zabbix/Centreon, Location iTop). Le NOC n'en tient plus de
    # référentiel propre, qui finirait par diverger du leur.
    site = Column(Text)
    organisation = Column(Text)
    phone_number = Column(Text)
    employee_code = Column(Text)
    team = Column(Text)
    # Adresse de notification et abonnement aux alertes graves par courriel
    # (services/notification_service.py). Désactivé par défaut : une alerte
    # que tout le monde reçoit est une alerte que personne ne lit.
    email = Column(Text)
    notify_email = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AlertState(Base):
    """Travail du NOC sur une alerte.

    Une ligne n'existe QUE pour les alertes que le NOC a touchées : la table
    ne double pas l'instantané Redis, elle ne porte que la valeur ajoutée
    humaine. Le parc peut compter dix mille alertes sur un mois sans que
    cette table dépasse quelques centaines de lignes.
    """

    __tablename__ = "ops_alert_state"

    alert_key = Column(Text, primary_key=True)

    # Recopiés au moment de la prise en charge pour que la fiche reste
    # lisible quand l'alerte a quitté l'instantané. C'est la SEULE
    # duplication tolérée dans ce schéma, et elle est FIGÉE : jamais
    # rafraîchie, sinon elle deviendrait une seconde source de vérité.
    node_key = Column(Text)
    node_name = Column(Text)
    severity_at_pickup = Column(Text)
    message_at_pickup = Column(Text)
    detected_at = Column(DateTime(timezone=True))

    acknowledged_by = Column(Integer, ForeignKey("noc_user.id", ondelete="SET NULL"))
    acknowledged_at = Column(DateTime(timezone=True))
    assigned_to = Column(Integer, ForeignKey("noc_user.id", ondelete="SET NULL"))
    assigned_at = Column(DateTime(timezone=True))
    escalation_level = Column(Integer, nullable=False, default=0)
    escalated_at = Column(DateTime(timezone=True))
    # Diagnostic humain : aucun outil ne le connaît, et c'est la donnée la
    # plus précieuse de ce schéma.
    cause = Column(Text)
    resolution_note = Column(Text)
    resolved_at = Column(DateTime(timezone=True))
    ticket_ref = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class AlertTimeline(Base):
    """Journal des actions.

    Séparé de `AlertState` parce que l'état répond à « où en est-on ? » et le
    journal à « que s'est-il passé ? » — l'un est écrasé à chaque changement,
    l'autre ne l'est jamais.
    """

    __tablename__ = "ops_alert_timeline"

    id = Column(Integer, primary_key=True)
    alert_key = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey("noc_user.id", ondelete="SET NULL"))
    action = Column(Text, nullable=False)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_ops_timeline_alert", "alert_key", "created_at"),
    )


class ManualIncident(Base):
    """Incident signalé à la main, qu'aucune sonde ne voit.

    Un agent constate un câble sectionné sur un site sans supervision, ou un
    groupe électrogène en panne. Ces incidents n'ont pas d'outil source : ils
    vivent ici, et le backend les fusionne avec l'instantané au moment de
    servir le mur d'alertes.
    """

    __tablename__ = "ops_manual_incident"

    id = Column(Integer, primary_key=True)
    node_key = Column(Text)
    node_name = Column(Text)
    site = Column(Text)
    severity = Column(Text, nullable=False, default="medium")
    title = Column(Text, nullable=False)
    description = Column(Text)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))
    created_by = Column(Integer, ForeignKey("noc_user.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def alert_key(self) -> str:
        """Clé d'alerte de cet incident.

        Le préfixe `manual:` ne peut entrer en collision avec aucune clé du
        collecteur : celui-ci ne produit que des clés préfixées du nom d'un
        outil configuré, et « manual » n'en est pas un.
        """
        return f"manual:{self.id}"


class SlaTarget(Base):
    __tablename__ = "ops_sla_target"

    id = Column(Integer, primary_key=True)
    severity = Column(Text, unique=True, nullable=False)
    tta_target_minutes = Column(Integer, nullable=False)
    ttr_target_minutes = Column(Integer, nullable=False)
    availability_target_pct = Column(Float, nullable=False, default=99.0)


class MaintenanceWindow(Base):
    """Fenêtre de maintenance planifiée.

    Les alertes qui y tombent sont marquées et exclues des indicateurs : une
    coupure voulue n'est pas une panne, et la compter fausserait à la fois le
    volume d'incidents et le respect du SLA.
    """

    __tablename__ = "ops_maintenance_window"

    id = Column(Integer, primary_key=True)
    node_key = Column(Text)
    site = Column(Text)
    reason = Column(Text, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    suppress_alerts = Column(Boolean, nullable=False, default=True)
    created_by = Column(Integer, ForeignKey("noc_user.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Sans cette contrainte, une fenêtre sans portée s'appliquerait à tout
        # le parc et éteindrait la supervision entière.
        CheckConstraint(
            "node_key IS NOT NULL OR site IS NOT NULL", name="ops_maintenance_scope"
        ),
        CheckConstraint("ends_at > starts_at", name="ops_maintenance_period"),
    )


class FieldIntervention(Base):
    __tablename__ = "ops_field_intervention"

    id = Column(Integer, primary_key=True)
    alert_key = Column(Text)
    node_key = Column(Text, nullable=False)
    node_name = Column(Text)
    agent_user_id = Column(
        Integer, ForeignKey("noc_user.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(Text, nullable=False, default="scheduled")
    scheduled_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    # Position relevée au pointage, pour attester la présence sur site.
    checkin_latitude = Column(Float)
    checkin_longitude = Column(Float)
    report_text = Column(Text)
    photo_urls = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(Base):
    __tablename__ = "ops_push_subscription"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("noc_user.id", ondelete="CASCADE"), nullable=False
    )
    endpoint = Column(Text, unique=True, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NotificationLog(Base):
    __tablename__ = "ops_notification_log"

    id = Column(Integer, primary_key=True)
    alert_key = Column(Text)
    channel = Column(Text, nullable=False)
    recipient = Column(Text)
    status = Column(Text, nullable=False)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AlertNotified(Base):
    """Verrou anti-double-notification.

    La contrainte d'unicité EST le verrou : deux backends qui traiteraient la
    même alerte au même instant, l'un se verra refuser l'insertion et
    n'enverra rien. Plus sûr qu'un verrou applicatif, qui ne survit pas à un
    redémarrage.
    """

    __tablename__ = "ops_alert_notified"

    alert_key = Column(Text, primary_key=True)
    notified_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "ops_audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("noc_user.id", ondelete="SET NULL"))
    action = Column(Text, nullable=False)
    target = Column(Text)
    detail = Column(JSONB)
    ip_address = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KpiDaily(Base):
    """Bilan journalier écrit par le collecteur.

    Voir backend/sql/schema.sql pour le raisonnement complet : c'est ce qui
    permet aux courbes du tableau Direction de porter sur douze mois sans
    interroger les outils sources sur toute la période à chaque affichage,
    pour quelques mégaoctets par an.
    """

    __tablename__ = "kpi_daily"

    day = Column(Date, primary_key=True)
    # NULL = tous sites confondus. Sans cette ligne de total, la somme des
    # sites ne ferait pas le parc : les équipements sans localité connue en
    # seraient absents.
    site = Column(Text, primary_key=True, nullable=True)
    samples = Column(Integer, nullable=False)
    avg_nodes = Column(Float)
    avg_up = Column(Float)
    avg_down = Column(Float)
    avg_degraded = Column(Float)
    avg_alerts = Column(Float)
    avg_critical = Column(Float)
    fleet_availability_pct = Column(Float)
