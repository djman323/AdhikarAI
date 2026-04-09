const DEFAULT_BACKEND_URL = "http://127.0.0.1:5000";

export function getBackendBaseUrl() {
  const dockerDefault = process.env.NODE_ENV === "production" ? "http://backend:5000" : DEFAULT_BACKEND_URL;
  return (process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || dockerDefault).replace(/\/$/, "");
}

export async function proxyJsonRequest(path, request) {
  const backendUrl = new URL(path, getBackendBaseUrl());
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

  const controller = new AbortController();
  const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);

  let response;
  try {
    response = await fetch(backendUrl, { ...init, signal: controller.signal });
  } catch (error) {
    const message =
      error?.name === "AbortError"
        ? `Backend request timed out after ${timeoutMs}ms`
        : "Backend is unreachable";

    return new Response(JSON.stringify({ error: message }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    });
  } finally {
    clearTimeout(timeoutHandle);
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