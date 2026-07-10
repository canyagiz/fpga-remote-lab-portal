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
  question: string;
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
}

export interface Profile {
  full_name: string | null;
  school: string | null;
  department: string | null;
  age: number | null;
  bio: string | null;
  social_links: Record<string, string> | null;
}

export interface CalendarEntry {
  lab_id: number;
  lab_name: string;
  username: string;
  status: ReservationStatus;
  start_time: string;
  end_time: string;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
