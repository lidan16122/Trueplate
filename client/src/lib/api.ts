/**
 * HTTP client for the Trueplate API.
 *
 * Auth is entirely cookie-based and the tokens are httpOnly, so nothing here
 * ever sees or stores a token — `credentials: "include"` is the whole of it.
 * That also means JavaScript cannot check whether the access token has expired:
 * the only signal is a 401 coming back, which is what drives the refresh below.
 */

import type {
  DayLog,
  DaySummary,
  FoodDetectionResponse,
  FoodEntryCreate,
  OnboardingPayload,
  Profile,
  Session,
  SignInResponse,
  Targets,
  User,
} from "@/types/api";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const API = `${BASE}/api/v1`;

export class ApiError extends Error {
  // Declared explicitly rather than as a constructor parameter property:
  // `erasableSyntaxOnly` requires TypeScript that vanishes on compile, and
  // parameter properties emit real assignments.
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/** Raised when refreshing fails — the session is genuinely over. */
export class SessionExpiredError extends ApiError {
  constructor(message = "Session expired") {
    super(401, message);
    this.name = "SessionExpiredError";
  }
}

type Listener = () => void;
const sessionExpiredListeners = new Set<Listener>();

/** Lets the auth provider react to a session ending mid-request. */
export function onSessionExpired(listener: Listener): () => void {
  sessionExpiredListeners.add(listener);
  return () => sessionExpiredListeners.delete(listener);
}

function notifySessionExpired() {
  for (const listener of sessionExpiredListeners) listener();
}

/**
 * The in-flight refresh, shared by every caller.
 *
 * This is load-bearing, not an optimisation. Refresh tokens are single-use and
 * rotated: if three requests 401 at once and each POSTs its own refresh, two of
 * them present a token the first has already consumed. The server forgives that
 * inside a short grace window, but outside it that is exactly the signature of
 * a stolen token — and the session gets revoked. One shared promise means one
 * rotation, so the situation never arises.
 */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });

      // 409 means a concurrent refresh won the race. The session is fine and
      // the winning cookie is already set, so the original request should just
      // be retried.
      return response.ok || response.status === 409;
    } catch {
      return false;
    } finally {
      // Cleared here so the *next* 401 starts a fresh rotation rather than
      // awaiting a settled promise forever. Callers already holding this
      // promise are unaffected — they resolve from the reference they captured,
      // not from the variable.
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

interface RequestOptions extends RequestInit {
  /** Set internally to stop a retry loop; not for callers. */
  _isRetry?: boolean;
  /** Endpoints that legitimately 401 (sign-in, refresh) opt out. */
  skipRefresh?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { _isRetry = false, skipRefresh = false, headers, ...init } = options;

  const response = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
  });

  if (response.status === 401 && !skipRefresh) {
    // A 401 on the retry means the freshly-rotated token was rejected too, so
    // the session really is gone. Falling through to a plain ApiError here — as
    // this did — skips notifySessionExpired(), and the app keeps rendering a
    // signed-in shell over a dead session, which is exactly what the listener
    // in AuthProvider exists to prevent.
    if (_isRetry) {
      notifySessionExpired();
      throw new SessionExpiredError();
    }

    const refreshed = await refreshSession();
    if (refreshed) {
      return request<T>(path, { ...options, _isRetry: true });
    }
    notifySessionExpired();
    throw new SessionExpiredError();
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    // FastAPI validation errors arrive as a list of field problems.
    if (Array.isArray(body?.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? "Invalid value").join(", ");
    }
  } catch {
    /* fall through to the status text */
  }
  return response.statusText || "Request failed";
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body?: unknown, options: RequestOptions = {}) =>
  request<T>(path, { ...options, method: "POST", body: body ? JSON.stringify(body) : undefined });
const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

export const api = {
  auth: {
    /** `skipRefresh`: a failure here means bad credentials, not a stale session. */
    signInWithGoogle: (credential: string) =>
      post<SignInResponse>("/auth/google", { credential }, { skipRefresh: true }),
    me: () => get<User>("/auth/me"),
    logout: () => post<{ detail: string }>("/auth/logout", undefined, { skipRefresh: true }),
    sessions: () => get<{ sessions: Session[] }>("/auth/sessions"),
    revokeSession: (familyId: string) => del<{ detail: string }>(`/auth/sessions/${familyId}`),
  },

  onboarding: {
    complete: (payload: OnboardingPayload) =>
      post<{ targets: Targets }>("/onboarding", payload),
    /** Live target preview while the wizard is still being filled in. */
    preview: (payload: OnboardingPayload) => post<Targets>("/onboarding/preview", payload),
  },

  profile: {
    read: () => get<Profile>("/profile"),
    update: (payload: Record<string, unknown>) => patch<Targets>("/profile", payload),
    targets: () => get<Targets>("/profile/targets"),
  },

  ai: {
    /** Multipart, so `request` omits the JSON Content-Type and lets fetch set the boundary. */
    detectPhoto: (image: File) => {
      const body = new FormData();
      body.append("image", image);
      return request<FoodDetectionResponse>("/ai/detect/photo", { method: "POST", body });
    },
    detectText: (description: string) =>
      post<FoodDetectionResponse>("/ai/detect/text", { description }),
  },

  logs: {
    day: (date: string) => get<DayLog>(`/logs/${date}`),
    range: (days: number, end?: string) =>
      get<DaySummary[]>(`/logs?days=${days}${end ? `&end=${end}` : ""}`),
    addEntries: (date: string, entries: FoodEntryCreate[]) =>
      post<DayLog>(`/logs/${date}/entries`, { entries }),
    updateEntry: (entryId: string, quantityG: number) =>
      patch<unknown>(`/logs/entries/${entryId}`, { quantity_g: quantityG }),
    deleteEntry: (entryId: string) => del<void>(`/logs/entries/${entryId}`),
  },
};
