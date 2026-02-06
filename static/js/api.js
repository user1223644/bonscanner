const API_URL = "http://localhost:5000";

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || `Request failed: ${res.status}`);
  }
  return res.json();
}
