// Proxies the report request to the backend and streams back the PDF.
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
    const r = await fetch(`${backend}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-app-password": password },
      body,
    });
    if (!r.ok) {
      const text = await r.text();
      return new Response(text, { status: r.status, headers: { "Content-Type": "application/json" } });
    }
    const buf = await r.arrayBuffer();
    return new Response(buf, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": r.headers.get("content-disposition") ?? 'attachment; filename="assessment.pdf"',
      },
    });
  } catch {
    return Response.json({ error: "Could not reach the report backend." }, { status: 502 });
  }
}
