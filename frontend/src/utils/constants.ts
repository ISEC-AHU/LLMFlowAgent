// Use the environment-specific API base URL, with the local backend as a fallback.
export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

// The rubric and workflow APIs share the same service URL. Keep the legacy name for compatibility.
export const apiBaseUrl_rubic = apiBaseUrl;

