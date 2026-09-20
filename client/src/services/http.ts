/**
 * HTTP client for the Trueplate API.
 *
 * Auth is entirely cookie-based and the tokens are httpOnly, so nothing here
 * ever sees or stores a token — `credentials: "include"` is the whole of it.
 * That also means JavaScript cannot check whether the access token has expired:
 * the only signal is a 401 coming back, which is what drives the refresh below.
 */

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

/** Raised when the server rejects the session, rather than failing to answer. */
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

/** Shares renewal within a tab to avoid duplicate requests when access expires. */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });

      // Only an explicit rejection ends the session. A gateway or network failure
      // leaves it available for recovery on a later request.
      if (response.status === 401) return false;
      if (!response.ok) {
        throw new ApiError(response.status, await readErrorMessage(response));
      }
      return true;
    } finally {
      // A settled attempt must not prevent the next request from recovering.
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

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
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
    // Stop after one renewal if the new JWT is also rejected, and update the UI
    // so it cannot keep showing an authenticated shell over a rejected session.
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

export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, body?: unknown, options: RequestOptions = {}) =>
  request<T>(path, { ...options, method: "POST", body: body ? JSON.stringify(body) : undefined });
export const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });
