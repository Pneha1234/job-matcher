// Calls go to /api/*, which next.config.ts rewrites to the FastAPI backend.

export type Health = {
  status: "ok" | "degraded";
  db: {
    ok: boolean;
    sqlite_vec_version: string | null;
    schema_version: number | null;
    error: string | null;
  };
  ollama: {
    ok: boolean;
    url: string;
    version: string | null;
    llm_model: string;
    embed_model: string;
    llm_model_ready: boolean;
    embed_model_ready: boolean;
    error: string | null;
  };
};

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}
