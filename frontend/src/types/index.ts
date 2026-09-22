export interface User {
  id: number;
  username: str;
  account_name: string;
  age: number | null;
  job: string;
  role: 'user' | 'admin';
  is_active: boolean;
  timezone: string;
  calendar: 'jalali' | 'gregorian';
  storage_used_bytes: number;
  created_at_ms: number;
}

export type str = string;

export interface Speaker {
  id: number;
  room_id: number;
  order_index: number;
  name: string;
  gender: string;
  age: number | null;
  description: string;
  speaking_seconds: number;
  is_finished: boolean;
  finished_at_ms: number;
  elapsed_ms: number;
  overtime_ms: number;
}

export interface SpeechFile {
  id: number;
  room_id: number;
  speaker_id: number | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  upload_type: 'common' | 'speaker' | 'recording';
  duration_ms: number | null;
  speaker_name: string;
  created_at_ms: number;
}

export interface RoomSummary {
  id: number;
  name: string;
  description: string;
  capacity: number;
  recording_enabled: boolean;
  live_files_enabled: boolean;
  public_enabled: boolean;
  timing_mode: 'global' | 'individual';
  global_seconds: number;
  order_mode: 'manual' | 'alpha' | 'age';
  storage_used_bytes: number;
  created_at_ms: number;
  speaker_count: number;
  active_speaker_count: number;
}

export interface RoomDetail extends RoomSummary {
  public_token: string | null;
  speakers: Speaker[];
  files: SpeechFile[];
  recordings: SpeechFile[];
}

export interface TimerState {
  room_id: number;
  version: number;
  running: boolean;
  awaiting_decision: boolean;
  stop_reason: string;
  current_index: number;
  current_speaker_id: number | null;
  current_speaker: Speaker | null;
  elapsed_ms: number;
  remaining_ms: number;
  overtime_ms: number;
  limit_ms: number;
  total_speakers: number;
  finished_speakers: number;
  speakers: Speaker[];
  live_files: SpeechFile[];
  recording_status: 'inactive' | 'recording' | 'paused' | 'saving';
}

export interface PublicRoomState {
  room_name: string;
  public_enabled: boolean;
  running: boolean;
  awaiting_decision: boolean;
  current_index: number;
  current_speaker: Speaker | null;
  elapsed_ms: number;
  remaining_ms: number;
  overtime_ms: number;
  limit_ms: number;
  total_speakers: number;
  finished_speakers: number;
  speakers: Speaker[];
  live_files: SpeechFile[];
}

export interface AdminStats {
  users_count: number;
  rooms_count: number;
  recordings_count: number;
  total_storage_bytes: number;
}

export interface AdminUser {
  id: number;
  username: string;
  account_name: string;
  role: string;
  is_active: boolean;
  rooms_count: number;
  storage_used_bytes: number;
  created_at_ms: number;
  last_login_at_ms: number;
}

export interface AdminRoom {
  id: number;
  owner_id: number;
  owner_username: string;
  name: string;
  capacity: number;
  speakers_count: number;
  storage_used_bytes: number;
  created_at_ms: number;
}

export interface AuditLog {
  id: number;
  actor_username: string;
  action: string;
  severity: string;
  target_type: string;
  target_id: string;
  detail: string;
  ip: string;
  created_at_ms: number;
}
