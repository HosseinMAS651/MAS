"""Regression coverage for additive upgrades of populated legacy databases."""
from __future__ import annotations

import sqlite3

from alembic import command
from sqlalchemy import inspect, text

from mas_app.config import Settings
from mas_app.db.migrator import _alembic_config, run_database_migrations
from mas_app.db.session import Database


def _settings(database_path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{database_path}",
        secret_key="legacy-migration-test-secret-at-least-32-chars",
        storage_backend="local",
    )


def test_populated_legacy_database_is_upgraded_without_losing_data(tmp_path):
    database_path = tmp_path / "existing-mas.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username VARCHAR(32) NOT NULL,
            password_hash VARCHAR(256) NOT NULL,
            account_name VARCHAR(120) NOT NULL
        );
        CREATE TABLE rooms (
            id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            name VARCHAR(160) NOT NULL,
            capacity INTEGER NOT NULL
        );
        CREATE TABLE speakers (
            id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL,
            order_index INTEGER NOT NULL,
            name VARCHAR(120) NOT NULL
        );
        CREATE TABLE room_states (
            id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL,
            current_speaker_id INTEGER,
            elapsed_ms BIGINT NOT NULL
        );
        CREATE TABLE speech_files (
            id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL,
            filename VARCHAR(255) NOT NULL,
            storage_key VARCHAR(400) NOT NULL
        );
        CREATE TABLE recording_sessions (
            id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL,
            speaker_id INTEGER,
            status VARCHAR(16) NOT NULL
        );
        CREATE UNIQUE INDEX uq_recording_sessions_one_active_per_room
            ON recording_sessions (room_id)
            WHERE status IN ('recording', 'paused', 'finalizing');
        CREATE TABLE recording_chunks (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL,
            storage_key VARCHAR(400) NOT NULL
        );

        INSERT INTO users VALUES (1, 'historic_user', 'existing-password-hash', 'Legacy owner');
        INSERT INTO rooms VALUES (11, 1, 'Retained room', 1);
        INSERT INTO speakers VALUES (21, 11, 0, 'Retained speaker');
        INSERT INTO room_states VALUES (31, 11, 21, 1234);
        INSERT INTO speech_files VALUES (41, 11, 'historic.webm', 'rooms/11/historic.webm');
        INSERT INTO recording_sessions VALUES (51, 11, 21, 'paused');
        INSERT INTO recording_chunks VALUES (61, 51, 'recordings/51/chunks/00000000.webm');
        """
    )
    connection.commit()
    connection.close()

    settings = _settings(database_path)
    database = Database(settings)
    run_database_migrations(database, settings)

    with database.engine.connect() as migrated:
        assert migrated.execute(
            text("SELECT username, password_hash, account_name FROM users WHERE id = 1")
        ).one() == ("historic_user", "existing-password-hash", "Legacy owner")

        assert migrated.execute(
            text(
                "SELECT name, recording_enabled, live_files_enabled, speaker_mode_enabled, "
                "speaker_uploads_enabled, public_enabled FROM rooms WHERE id = 11"
            )
        ).one() == ("Retained room", 0, 0, 0, 0, 0)
        assert migrated.execute(
            text(
                "SELECT name, is_finished, speaker_code_hash, presence_status "
                "FROM speakers WHERE id = 21"
            )
        ).one() == ("Retained speaker", 0, None, "offline")
        assert migrated.execute(
            text("SELECT current_speaker_id, elapsed_ms, running, awaiting_decision FROM room_states")
        ).one() == (21, 1234, 0, 0)
        assert migrated.execute(
            text("SELECT filename, storage_key, approval_status FROM speech_files WHERE id = 41")
        ).one() == ("historic.webm", "rooms/11/historic.webm", "approved")
        assert migrated.execute(
            text("SELECT room_id, speaker_id, status FROM recording_sessions WHERE id = 51")
        ).one() == (11, 21, "paused")
        assert migrated.execute(
            text("SELECT session_id, storage_key FROM recording_chunks WHERE id = 61")
        ).one() == (51, "recordings/51/chunks/00000000.webm")

    index_names = {index["name"] for index in inspect(database.engine).get_indexes("speakers")}
    recording_index_names = {
        index["name"] for index in inspect(database.engine).get_indexes("recording_sessions")
    }
    assert "uq_speaker_room_code_hash" in index_names
    assert "uq_recording_sessions_one_active_per_room" not in recording_index_names
    assert "uq_recording_sessions_one_active_per_room_speaker" in recording_index_names
    database.engine.dispose()


def test_versioned_migration_0005_preserves_existing_records(tmp_path):
    database_path = tmp_path / "versioned-mas.db"
    settings = _settings(database_path)
    command.upgrade(_alembic_config(settings), "0004_legacy_auth_schema_compat")

    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        INSERT INTO users (
            id, username, username_key, password_hash, account_name, age, job,
            profile_completed, role, is_active, timezone, calendar, storage_used_bytes,
            failed_login_count, locked_until_ms, created_at_ms, updated_at_ms,
            last_login_at_ms, version
        ) VALUES (1, 'versioned_user', 'versioned_user', 'existing-hash', 'Versioned owner',
                  NULL, '', 0, 'user', 1, 'UTC', 'gregorian', 0, 0, 0, 100, 100, 0, 1);
        INSERT INTO rooms (
            id, owner_id, name, description, capacity, recording_enabled, live_files_enabled,
            public_enabled, public_token, public_token_created_at_ms, timing_mode,
            global_seconds, order_mode, storage_used_bytes, created_at_ms, updated_at_ms, version
        ) VALUES (11, 1, 'Versioned room', '', 1, 0, 0, 0, NULL, 0, 'global',
                  300, 'manual', 0, 100, 100, 1);
        INSERT INTO speakers (
            id, room_id, order_index, name, gender, age, description, speaking_seconds,
            is_finished, finished_at_ms, created_at_ms, updated_at_ms
        ) VALUES (21, 11, 0, 'Versioned speaker', '', NULL, '', 300, 0, 0, 100, 100);
        INSERT INTO speech_files (
            id, room_id, speaker_id, filename, storage_key, backend, content_type,
            size_bytes, upload_type, duration_ms, speaker_name, sha256, created_at_ms, updated_at_ms
        ) VALUES (41, 11, 21, 'retained.webm', 'rooms/11/retained.webm', 'local',
                  'audio/webm', 17, 'recording', 1000, 'Versioned speaker',
                  'existing-file-hash', 100, 100);
        INSERT INTO recording_sessions (
            id, room_id, speaker_id, speaker_name, status, mime_type, chunk_seq,
            bytes_received, recorded_ms, active_since_ms, started_at_ms, last_chunk_at_ms,
            ended_at_ms, final_file_id, error, version
        ) VALUES (51, 11, 21, 'Versioned speaker', 'paused', 'audio/webm', 1,
                  17, 1000, 0, 100, 100, 0, NULL, '', 1);
        INSERT INTO recording_chunks (
            id, session_id, seq, storage_key, backend, size_bytes, created_at_ms
        ) VALUES (61, 51, 0, 'recordings/51/chunks/00000000.webm', 'local', 17, 100);
        """
    )
    connection.commit()
    connection.close()

    database = Database(settings)
    run_database_migrations(database, settings)
    with database.engine.connect() as migrated:
        assert migrated.execute(
            text("SELECT username, password_hash, recovery_code_hash FROM users WHERE id = 1")
        ).one() == ("versioned_user", "existing-hash", None)
        assert migrated.execute(
            text("SELECT speaker_mode_enabled, speaker_uploads_enabled FROM rooms WHERE id = 11")
        ).one() == (0, 0)
        assert migrated.execute(
            text(
                "SELECT name, speaker_code_hash, presence_status, presence_last_seen_at_ms "
                "FROM speakers WHERE id = 21"
            )
        ).one() == ("Versioned speaker", None, "offline", 0)
        assert migrated.execute(
            text("SELECT filename, storage_key, approval_status FROM speech_files WHERE id = 41")
        ).one() == ("retained.webm", "rooms/11/retained.webm", "approved")
        assert migrated.execute(
            text("SELECT room_id, speaker_id, status FROM recording_sessions WHERE id = 51")
        ).one() == (11, 21, "paused")
        assert migrated.execute(
            text("SELECT session_id, storage_key FROM recording_chunks WHERE id = 61")
        ).one() == (51, "recordings/51/chunks/00000000.webm")

    database.engine.dispose()


def test_versioned_migration_0005_recovers_when_old_recording_index_is_missing(tmp_path):
    database_path = tmp_path / "repairable-versioned-mas.db"
    settings = _settings(database_path)
    command.upgrade(_alembic_config(settings), "0004_legacy_auth_schema_compat")

    # Simulate a manually repaired legacy database where the 0002 index was
    # removed before the new versioned migration reached production.
    connection = sqlite3.connect(database_path)
    connection.execute("DROP INDEX uq_recording_sessions_one_active_per_room")
    connection.commit()
    connection.close()

    database = Database(settings)
    run_database_migrations(database, settings)

    recording_index_names = {
        index["name"] for index in inspect(database.engine).get_indexes("recording_sessions")
    }
    assert "uq_recording_sessions_one_active_per_room" not in recording_index_names
    assert "uq_recording_sessions_one_active_per_room_speaker" in recording_index_names
    database.engine.dispose()
