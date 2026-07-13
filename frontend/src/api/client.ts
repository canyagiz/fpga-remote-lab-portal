import {
  ApiError,
  CalendarEntry,
  CaptchaResponse,
  Lab,
  LabAccess,
  LoginResult,
  MessageResponse,
  MyStats,
  Profile,
  PublicProfile,
  Reservation,
  User,
} from "./types";

// FastAPI's own validation errors (422) send `detail` as an ARRAY of
// {loc, msg, type} objects, not a string - passing that straight to
// ApiError's Error-subclass constructor stringified the array as the
// unhelpful "[object Object]" seen in toasts (e.g. the email
// deliverability check's message never actually reached the user).
// A plain string detail (every other error in this app) passes through
// unchanged.
function extractErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((e) => {
      const msg = e && typeof e === "object" && "msg" in e ? String(e.msg) : String(e);
      // Pydantic prefixes every raised ValueError with this - it's
      // meaningless to a user reading the toast.
      return msg.replace(/^Value error, /, "");
    });
    if (messages.length) return messages.join(" ");
  }
  return fallback;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let detail: string = response.statusText;
    try {
      const body = await response.json();
      detail = extractErrorMessage(body.detail, detail);
    } catch {
      // Response body wasn't JSON - fall back to the status text above.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
const put = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

// --- auth ---

export const getCsrfToken = () => get<{ success: boolean; token: string }>("/api/auth/csrf-token");
export const getCaptcha = () => get<CaptchaResponse>("/api/auth/captcha");

export const register = (data: {
  username: string;
  email: string;
  password: string;
  captcha_answer: number;
  csrf_token: string;
  website?: string;
}) => post<MessageResponse>("/api/auth/register", { website: "", ...data });

export const login = (username: string, password: string) =>
  post<LoginResult>("/api/auth/login", { username, password });

export const verify2FA = (code: string) => post<User>("/api/auth/verify-2fa", { code });
export const resend2FA = () => post<MessageResponse>("/api/auth/resend-2fa");
export const logout = () => post<MessageResponse>("/api/auth/logout");
export const getMe = () => get<User>("/api/auth/me");

// --- labs ---

export const getLabs = () => get<Lab[]>("/api/labs");
export const createLab = (name: string, description: string) =>
  post<Lab>("/api/labs", { name, description });
export const accessLab = (id: number) => get<LabAccess>(`/api/labs/${id}/access`);

// --- reservations ---

export const getMyReservations = () => get<Reservation[]>("/api/reservations/mine");

export const makeReservation = (labId: number, date: string, time: string) =>
  post<Reservation>("/api/reservations", {
    lab_id: labId,
    reservation_date: date,
    reservation_time: time,
  });

export const accessNow = (labId: number) =>
  post<Reservation>("/api/reservations/access-now", { lab_id: labId });
export const cancelReservation = (id: number) => post<Reservation>(`/api/reservations/${id}/cancel`);
export const completeLabUsage = (id: number) => post<Reservation>(`/api/reservations/${id}/complete`);
export const getCalendar = () => get<CalendarEntry[]>("/api/reservations/calendar");

// --- stats ---

export const getMyStats = () => get<MyStats>("/api/stats/me");

// --- profile ---

export const getMyProfile = () => get<Profile>("/api/profile");
export const updateMyProfile = (data: Profile) => put<Profile>("/api/profile", data);
export const getUserProfile = (username: string) =>
  get<PublicProfile>(`/api/profile/${encodeURIComponent(username)}`);

// --- users (admin) ---

export const getUsers = () => get<User[]>("/api/users");
export const deleteUser = (id: number) => del<MessageResponse>(`/api/users/${id}`);

export { ApiError };
