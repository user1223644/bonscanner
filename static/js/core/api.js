const API_URL = "http://localhost:5000";

function normalizeEndpoint(path) {
  if (!path) return API_URL;
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  if (path.startsWith("/")) {
    return `${API_URL}${path}`;
  }
  return `${API_URL}/${path}`;
}

async function parseResponse(res) {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await res.json();
    } catch (error) {
      return null;
    }
  }
  try {
    return await res.text();
  } catch (error) {
    return null;
  }
}

async function requestJSON(path, options = {}) {
  const res = await fetch(normalizeEndpoint(path), options);
  const data = await parseResponse(res);
  if (!res.ok) {
    const message =
      (data && data.error) ||
      (data && data.message) ||
      (typeof data === "string" ? data : null) ||
      `Request failed: ${res.status}`;
    throw new Error(message);
  }
  return data;
}

async function requestWithResponse(path, options = {}) {
  const res = await fetch(normalizeEndpoint(path), options);
  const data = await parseResponse(res);
  if (!res.ok) {
    const message =
      (data && data.error) ||
      (data && data.message) ||
      (typeof data === "string" ? data : null) ||
      `Request failed: ${res.status}`;
    throw new Error(message);
  }
  return { data, res };
}

async function fetchJSON(url, options) {
  return requestJSON(url, options);
}

const API = {
  baseUrl: API_URL,
  requestJSON,
  requestWithResponse,
  get(path) {
    return requestJSON(path);
  },
  post(path, payload) {
    return requestJSON(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
  },
  postForm(path, formData) {
    return requestJSON(path, {
      method: "POST",
      body: formData,
    });
  },
  patch(path, payload) {
    return requestJSON(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
  },
  delete(path) {
    return requestJSON(path, { method: "DELETE" });
  },
};

window.API = API;
