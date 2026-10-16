export const BASE = "/steuer/";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = { "X-KESt-Request": "1" };
  if (body !== undefined && !(body instanceof FormData))
    headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(BASE + "api" + path, {
      method,
      headers,
      body:
        body instanceof FormData
          ? body
          : body === undefined
            ? undefined
            : JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(
      0,
      "Server nicht erreichbar. Verbindung prüfen; Eingaben bleiben im Formular.",
    );
  }
  const data = await response
    .json()
    .catch(() => ({
      detail: "Ungültige Serverantwort. Serverprotokoll prüfen.",
    }));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail
          .map((x: any) => `${x.loc?.slice(1).join(".")}: ${x.msg}`)
          .join("; ")
      : data.detail;
    throw new ApiError(
      response.status,
      String(detail || "Anfrage fehlgeschlagen."),
    );
  }
  return data as T;
}
export function original(id: number, download = false) {
  return (
    BASE + `api/documents/${id}/original${download ? "?download=true" : ""}`
  );
}
export function editable(schema: any, values: Record<string, any>) {
  return Object.fromEntries(
    Object.keys(schema.properties)
      .filter((k) => k in values)
      .map((k) => [k, values[k]]),
  );
}
