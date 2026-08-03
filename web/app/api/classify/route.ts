// Proxies the classify request to the Python/FastAPI backend (deterministic
// rule engine + RAG). Keeps the backend URL server-side.
export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(req: Request) {
  const backend = process.env.BACKEND_URL;
  if (!backend) {
    return Response.json({ error: "BACKEND_URL not configured on the server." }, { status: 500 });
  }
  const password = req.headers.get("x-app-password") ?? "";
  const body = await req.text();
  try {
    const r = await fetch(`${backend}/classify`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-app-password": password },
      body,
    });
    const text = await r.text();
    return new Response(text, {
      status: r.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json({ error: "Could not reach the classification backend." }, { status: 502 });
  }
}
