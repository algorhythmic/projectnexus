/**
 * Fetch wrapper for the Nexus REST API.
 */

const API_BASE =
  import.meta.env.VITE_NEXUS_API_URL || "https://projectnexus.fly.dev";

export async function nexusFetch<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  const url = new URL(path, API_BASE);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") {
        url.searchParams.set(k, String(v));
      }
    }
  }
  const resp = await fetch(url.toString());
  if (!resp.ok) {
    throw new Error(`Nexus API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}
