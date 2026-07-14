from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.sql import func

from app.db.session import Base


class PushSubscription(Base):
    __tablename__ = "push_subscription"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("dim_user.id"), nullable=False)
    endpoint = Column(Text, unique=True, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
