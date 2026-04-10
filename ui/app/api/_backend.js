const DEFAULT_BACKEND_URL = "http://127.0.0.1:5000";
const RAILWAY_PRIVATE_BACKEND_URL = "http://adhikar-backend.railway.internal:5000";

function normalizeBaseUrl(url) {
  return (url || "").replace(/\/$/, "");
}

export function getBackendBaseUrl() {
  const configuredUrl = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (configuredUrl) {
    return normalizeBaseUrl(configuredUrl);
  }

  if (process.env.NODE_ENV === "production") {
    return RAILWAY_PRIVATE_BACKEND_URL;
  }

  return DEFAULT_BACKEND_URL;
}

function getBackendBaseUrlCandidates() {
  const configuredUrl = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  const candidates = [];

  if (configuredUrl) {
    candidates.push(normalizeBaseUrl(configuredUrl));
  }

  if (process.env.NODE_ENV === "production") {
    candidates.push(RAILWAY_PRIVATE_BACKEND_URL);
  } else {
    candidates.push(DEFAULT_BACKEND_URL);
  }

  return [...new Set(candidates)];
}

export async function proxyJsonRequest(path, request) {
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

  const baseUrlCandidates = getBackendBaseUrlCandidates();

  for (let index = 0; index < baseUrlCandidates.length; index += 1) {
    const baseUrl = baseUrlCandidates[index];
    const backendUrl = new URL(path, baseUrl);

    try {
      const response = await fetch(backendUrl, init);
      const contentType = response.headers.get("content-type") || "application/json";
      const body = await response.text();

      const isLikelyRouteMismatch =
        response.status === 405 &&
        request.method === "POST" &&
        !contentType.includes("application/json");

      if (isLikelyRouteMismatch && index < baseUrlCandidates.length - 1) {
        continue;
      }

      if (!contentType.includes("application/json")) {
        return new Response(
          JSON.stringify({
            error: body || "Backend returned a non-JSON response",
            upstream_status: response.status,
            upstream_content_type: contentType,
            upstream_url: backendUrl.toString(),
          }),
          {
            status: response.status,
            headers: {
              "Content-Type": "application/json",
            },
          }
        );
      }

      return new Response(body, {
        status: response.status,
        headers: {
          "Content-Type": contentType,
        },
      });
    } catch (error) {
      if (index < baseUrlCandidates.length - 1) {
        continue;
      }

      return new Response(
        JSON.stringify({
          error: "Backend request failed",
          detail: String(error),
          upstream_url: backendUrl.toString(),
        }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    }
  }

  return new Response(
    JSON.stringify({
      error: "No backend targets available",
    }),
    {
      status: 500,
      headers: {
        "Content-Type": "application/json",
      },
    }
  );
}