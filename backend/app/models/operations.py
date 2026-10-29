"""
Tables propres au NOC — miroir de backend/sql/schema.sql.

RIEN ICI NE DÉCRIT UN ÉQUIPEMENT, UNE ALERTE NI UN INCIDENT. Ils vivent dans
l'instantané Redis et chez les outils sources (iTop pour les incidents) ; le
NOC ne les crée ni ne les traite. Les tables ci-dessous ne portent que ce que
le NOC produit lui-même : comptes, objectifs SLA, journal d'audit, trace des
notifications envoyées et bilans journaliers de la collecte.
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
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


class SlaTarget(Base):
    __tablename__ = "ops_sla_target"

    id = Column(Integer, primary_key=True)
    severity = Column(Text, unique=True, nullable=False)
    tta_target_minutes = Column(Integer, nullable=False)
    ttr_target_minutes = Column(Integer, nullable=False)
    availability_target_pct = Column(Float, nullable=False, default=99.0)


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


class NotificationRetry(Base):
    """Envoi échoué en attente d'une nouvelle tentative, par alerte et canal.

    `ops_alert_notified` décide QUI envoie (un seul backend) ; cette table
    garde ce qui n'a pas pu partir. Le message est conservé tel qu'il a été
    composé à la première tentative. Pour le courriel, les destinataires sont
    relus à chaque tentative : un compte désactivé entre-temps ne reçoit rien.
    Pour le SMS, seuls les numéros en échec sont gardés : ceux qui ont reçu
    le message ne le reçoivent pas deux fois.
    """

    __tablename__ = "ops_notification_retry"
    __table_args__ = (UniqueConstraint("alert_key", "channel"),)

    id = Column(Integer, primary_key=True)
    alert_key = Column(Text, nullable=False)
    channel = Column(Text, nullable=False)          # email | sms
    subject = Column(Text)
    text_body = Column(Text, nullable=False)
    html_body = Column(Text)
    site = Column(Text)
    recipients = Column(Text)                       # SMS : numéros restant à prévenir
    attempts = Column(Integer, nullable=False, default=1)
    status = Column(Text, nullable=False, default="pending")  # pending | sent | abandoned
    last_error = Column(Text)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class HistState(Base):
    """Période d'état d'un équipement (`node`) ou d'un lien surveillé (`link`).

    Écrite par le collecteur (collector/history.py), lue ici. Voir
    backend/sql/schema.sql pour les règles d'ouverture et de clôture.
    """

    __tablename__ = "hist_state"

    id = Column(BigInteger, primary_key=True)
    subject_kind = Column(Text, nullable=False)
    subject_id = Column(Text, nullable=False)
    node_id = Column(Text, nullable=False)
    name = Column(Text)
    site = Column(Text)
    province = Column(Text)
    region = Column(Text)
    tools = Column(Text)
    state = Column(Text, nullable=False)
    measured_state = Column(Text)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


class HistAlert(Base):
    """Une alerte, de son ouverture à sa fermeture (collector/history.py)."""

    __tablename__ = "hist_alert"

    id = Column(BigInteger, primary_key=True)
    alert_key = Column(Text, nullable=False)
    tool = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    node_id = Column(Text)
    node_name = Column(Text)
    site = Column(Text)
    province = Column(Text)
    region = Column(Text)
    severity = Column(Text, nullable=False)
    message = Column(Text)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True))


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

    day = Column(Date, nullable=False)
    # NULL = tous sites confondus. Sans cette ligne de total, la somme des
    # sites ne ferait pas le parc : les équipements sans localité connue en
    # seraient absents.
    site = Column(Text)
    samples = Column(Integer, nullable=False)
    avg_nodes = Column(Float)
    avg_up = Column(Float)
    avg_down = Column(Float)
    avg_degraded = Column(Float)
    avg_alerts = Column(Float)
    avg_critical = Column(Float)
    fleet_availability_pct = Column(Float)

    # PostgreSQL enforces uniqueness through an expression index so NULL can
    # represent the total row. SQLAlchemy still needs an identity key for ORM
    # reads; this mapper key does not create a database primary-key constraint.
    __mapper_args__ = {"primary_key": [day, site]}
