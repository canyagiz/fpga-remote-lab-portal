// Mirrors backend/app/schemas.py and backend/app/models.py enums.

export type UserRole = "user" | "admin";

export interface User {
  id: number;
  username: string;
  email: string;
  role: UserRole;
}

export interface CaptchaResponse {
  success: boolean;
  background_image: string;
  piece_image: string;
  canvas_width: number;
  canvas_height: number;
  piece_width: number;
  piece_height: number;
  piece_top: number;
}

export interface MessageResponse {
  success: boolean;
  message: string;
}

export interface LoginResult {
  success: boolean;
  require_2fa: boolean;
  message?: string;
}

export type LabStatus = "available" | "occupied";

export interface Lab {
  id: number;
  name: string;
  description: string | null;
  status: LabStatus;
  queue_count: number;
  image_url: string | null;
  keywords: string[] | null;
  features: string[] | null;
  is_public: boolean;
  next_available_at: string | null;
  guide_url: string | null;
}

export interface LabAccess {
  backend_url: string;
}

export type ReservationStatus = "pending" | "active" | "completed" | "cancelled" | "expired";

export interface Reservation {
  id: number;
  lab_id: number;
  lab_name: string;
  reservation_date: string | null;
  reservation_time: string | null;
  status: ReservationStatus;
  queue_position: number;
  created_at: string;
  usage_start_time: string | null;
  session_ends_at: string | null;
  access_deadline: string | null;
}

export interface Profile {
  full_name: string | null;
  school: string | null;
  department: string | null;
  age: number | null;
  bio: string | null;
  social_links: Record<string, string> | null;
  is_public: boolean;
  hidden_fields: string[] | null;
}

export interface PublicProfile {
  username: string;
  is_public: boolean;
  full_name: string | null;
  school: string | null;
  department: string | null;
  age: number | null;
  bio: string | null;
  social_links: Record<string, string> | null;
}

export interface LabUsageStat {
  lab_id: number;
  lab_name: string;
  image_url: string | null;
  session_count: number;
}

export interface MyStats {
  labs_demoed: LabUsageStat[];
  labs_completed: LabUsageStat[];
  total_reservations: number;
  completed_count: number;
  cancelled_count: number;
  expired_count: number;
  upcoming_count: number;
  login_times: string[];
}

export interface CalendarEntry {
  lab_id: number;
  lab_name: string;
  username: string;
  status: ReservationStatus;
  start_time: string;
  end_time: string;
}

export interface AdminUserSummary {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  created_at: string;
  is_root_admin: boolean;
  completed_labs: number;
  completed_sessions: number;
  total_reservations: number;
  has_profile: boolean;
}

export interface AdminReservation {
  id: number;
  lab_id: number;
  lab_name: string;
  status: ReservationStatus;
  reservation_date: string | null;
  reservation_time: string | null;
  created_at: string;
  usage_start_time: string | null;
  usage_end_time: string | null;
}

export interface AdminUserDetail {
  id: number;
  username: string;
  email: string;
  role: UserRole;
  created_at: string;
  is_root_admin: boolean;
  profile: Profile | null;
  reservations: AdminReservation[];
}

export interface AdminEntry {
  email: string;
  is_root_admin: boolean;
  is_registered: boolean;
  user_id: number | null;
  username: string | null;
  granted_at: string | null;
}

export class ApiError extends Error {
  status: number;
  // Set from the response's Retry-After header when present (e.g. the
  // registration and resend-2fa rate limits) so callers can drive a live
  // countdown instead of just showing the static message once.
  retryAfterSeconds?: number;

  constructor(status: number, message: string, retryAfterSeconds?: number) {
    super(message);
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}
