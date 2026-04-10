const DEFAULT_BACKEND_URL = "http://127.0.0.1:5000";

export function getBackendBaseUrl() {
  const configuredUrl = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (configuredUrl) {
    return configuredUrl.replace(/\/$/, "");
  }

  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "BACKEND_API_URL must be set on Railway to the public backend service URL. " +
        "The default docker host (http://backend:5000) does not work on Railway."
    );
  }

  return DEFAULT_BACKEND_URL;
}

export async function proxyJsonRequest(path, request) {
  const backendUrl = new URL(path, getBackendBaseUrl());

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

  const response = await fetch(backendUrl, init);
  const contentType = response.headers.get("content-type") || "application/json";
  const body = await response.text();

  return new Response(body, {
    status: response.status,
    headers: {
      "Content-Type": contentType,
    },
  });
}