const DEFAULT_BACKEND_URL = "http://127.0.0.1:5000";
const RAILWAY_BACKEND_FALLBACK = "http://adhikar-backend.railway.internal";
const RAILWAY_BACKEND_FALLBACK_ALT = "http://backend.railway.internal";

export function getBackendBaseUrl() {
  const productionDefault = process.env.RAILWAY_BACKEND_INTERNAL_URL || RAILWAY_BACKEND_FALLBACK;
  const defaultBaseUrl = process.env.NODE_ENV === "production" ? productionDefault : DEFAULT_BACKEND_URL;
  return (process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || defaultBaseUrl).replace(/\/$/, "");
}

function getBackendBaseUrlCandidates() {
  const values = [
    process.env.BACKEND_API_URL,
    process.env.RAILWAY_BACKEND_INTERNAL_URL,
    process.env.BACKEND_INTERNAL_URL,
    process.env.NEXT_PUBLIC_API_BASE_URL,
    process.env.NODE_ENV === "production" ? RAILWAY_BACKEND_FALLBACK : DEFAULT_BACKEND_URL,
    process.env.NODE_ENV === "production" ? RAILWAY_BACKEND_FALLBACK_ALT : null,
  ];

  const unique = [];
  for (const value of values) {
    if (!value) continue;
    const trimmed = String(value).replace(/\/$/, "");
    if (!trimmed || unique.includes(trimmed)) continue;
    unique.push(trimmed);
  }

  if (unique.length === 0) {
    unique.push(getBackendBaseUrl());
  }

  return unique;
}

export async function proxyJsonRequest(path, request) {
  const backendBaseCandidates = getBackendBaseUrlCandidates();
  const timeoutMs = Number(process.env.BACKEND_PROXY_TIMEOUT_MS || 45000);

  let apiKey;
  if (path.startsWith("/chat")) {
    apiKey = process.env.CHAT_API_KEY;
  } else if (path.startsWith("/courtroom/turn")) {
    // In the courtroom, the user is the lawyer
    apiKey = process.env.LAWYER_API_KEY;
  } else if (path.startsWith("/courtroom/evaluate") || path.startsWith("/courtroom/start")) {
    // Assume judge key for starting and evaluating
    apiKey = process.env.JUDGE_API_KEY;
  }

  const init = {
    method: request.method,
    headers: {
      "Content-Type": request.headers.get("content-type") || "application/json",
    },
    cache: "no-store",
  };

  if (apiKey) {
    init.headers["X-API-Key"] = apiKey;
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  let response = null;
  let lastError = null;

  for (const base of backendBaseCandidates) {
    const backendUrl = new URL(path, base);
    const controller = new AbortController();
    const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);

    try {
      response = await fetch(backendUrl, { ...init, signal: controller.signal });
      break;
    } catch (error) {
      lastError = {
        name: error?.name || "Error",
        message: error?.message || "Unknown error",
        backendUrl: backendUrl.toString(),
      };
      continue;
    } finally {
      clearTimeout(timeoutHandle);
    }
  }

  if (!response) {
    const timeoutError = lastError?.name === "AbortError";
    const message = timeoutError
      ? `Backend request timed out after ${timeoutMs}ms`
      : "Backend is unreachable";

    return new Response(
      JSON.stringify({
        error: message,
        details: {
          attempted_backends: backendBaseCandidates,
          last_error: lastError,
        },
      }),
      {
        status: 504,
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  const contentType = response.headers.get("content-type") || "application/json";
  const body = await response.text();

  return new Response(body, {
    status: response.status,
    headers: {
      "Content-Type": contentType,
    },
  });
}