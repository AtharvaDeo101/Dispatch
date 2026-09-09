# backend/models.py
from sqlalchemy import (
    JSON, Column, Integer, String, Text, Boolean, DateTime, ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from db import Base
from datetime import datetime

# Every row in `emails` and `folders` belongs to one Gmail account, and every
# query filters on it — without that these tables are shared across all users.
# Nullable because the column was added to populated tables; rows predating it
# have owner NULL and are visible to nobody, which is the safe way to fail.
# ScheduledEmail deliberately has no owner of its own: it reaches ownership
# through its email_id, so the two can never disagree.

class Folder(Base):
    __tablename__ = "folders"
    # names are unique per account, not globally — two users may both have "Work"
    __table_args__ = (UniqueConstraint("owner", "name", name="folders_owner_name_key"),)

    id = Column(Integer, primary_key=True, index=True)
    owner = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    emails = relationship("Email", back_populates="folder")

class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    owner = Column(String(255), nullable=True, index=True)
    subject = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    to_address = Column(String(255), nullable=False)
    from_address = Column(String(255), nullable=False)
    is_draft = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)

    # send_email/create_draft already write these; without the columns the
    # insert raises TypeError and the row is silently rolled back.
    gmail_message_id = Column(String(255), nullable=True)
    gmail_draft_id = Column(String(255), nullable=True)

    folder = relationship("Folder", back_populates="emails")
    scheduled = relationship("ScheduledEmail", back_populates="email", uselist=False)

class UserSettings(Base):
    """Per-Gmail-account preferences (display, theme, notifications).

    Stored as one JSON blob: the settings page owns the shape, so adding a
    preference never needs a migration.
    """
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    email_address = Column(String(255), unique=True, nullable=False, index=True)
    data = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduledEmail(Base):
    __tablename__ = "scheduled_emails"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    status = Column(String(50), default="pending")  # pending, sent, failed

    email = relationship("Email", back_populates="scheduled")