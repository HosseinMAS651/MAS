from __future__ import annotations

from typing import Optional
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    account_name: Mapped[str] = mapped_column(String(120), default="")
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    job: Mapped[str] = mapped_column(String(120), default="")
    profile_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rooms: Mapped[list["Room"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    last_seen_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user: Mapped[User] = relationship(back_populates="sessions")


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    id: Mapped[int] = mapped_column(primary_key=True)
    bucket_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    window_started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    live_files_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timing_mode: Mapped[str] = mapped_column(String(20), default="global", nullable=False)
    global_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    order_mode: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    public_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True, nullable=True)
    __mapper_args__ = {"version_id_col": version}
    owner: Mapped[User] = relationship(back_populates="rooms")
    speakers: Mapped[list["Speaker"]] = relationship(back_populates="room", cascade="all, delete-orphan", order_by="Speaker.order_index")
    files: Mapped[list["SpeechFile"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    state: Mapped[Optional["RoomState"]] = relationship(back_populates="room", uselist=False, cascade="all, delete-orphan")


class Speaker(Base):
    __tablename__ = "speakers"
    __table_args__ = (UniqueConstraint("room_id", "order_index", name="uq_speaker_room_order"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    gender: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    speaking_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    room: Mapped[Room] = relationship(back_populates="speakers")
    files: Mapped[list["SpeechFile"]] = relationship(back_populates="speaker")


class SpeechFile(Base):
    __tablename__ = "speech_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    speaker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("speakers.id", ondelete="CASCADE"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream", nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    upload_type: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    speaker_name_snapshot: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    room_name_snapshot: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    room: Mapped[Room] = relationship(back_populates="files")
    speaker: Mapped[Optional[Speaker]] = relationship(back_populates="files")


class RoomState(Base):
    __tablename__ = "room_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), unique=True)
    current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_speaker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    overtime_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __mapper_args__ = {"version_id_col": version}
    room: Mapped[Room] = relationship(back_populates="state")


class SpeakerTimerState(Base):
    __tablename__ = "speaker_timer_states"
    __table_args__ = (UniqueConstraint("room_id", "speaker_id", name="uq_timer_room_speaker"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    speaker_id: Mapped[int] = mapped_column(ForeignKey("speakers.id", ondelete="CASCADE"), index=True)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": version}


class FileCleanupQueue(Base):
    __tablename__ = "file_cleanup_queue"
    id: Mapped[int] = mapped_column(primary_key=True)
    storage_name: Mapped[str] = mapped_column(String(255), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SchemaInfo(Base):
    __tablename__ = "schema_info"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
