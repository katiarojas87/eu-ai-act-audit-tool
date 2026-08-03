import Anthropic from "@anthropic-ai/sdk";
import { KNOWLEDGE_TEXT } from "@/lib/knowledge";

export const runtime = "nodejs";
export const maxDuration = 60;

const MODEL = "claude-opus-4-8";

const SYSTEM = `You are an EU AI Act (Regulation 2024/1689) compliance classifier.
Classify the described AI system using ONLY the curated legal knowledge below.
The description may be in Dutch, French, English or Spanish; answer field values in English.

CURATED LEGAL KNOWLEDGE:
${KNOWLEDGE_TEXT}

Do three things:
1. RISK TIER (pick one, based on the USE CASE): PROHIBITED, ANNEX_I (high-risk in
   regulated products), ANNEX_III (high-risk use case), LIMITED (transparency only),
   MINIMAL. Do NOT use GPAI as a tier.
2. GPAI FLAG (independent of tier): is_gpai=true ONLY if the organisation builds,
   fine-tunes, or integrates/distributes a general-purpose FOUNDATION model (LLM,
   large vision/multimodal model). Merely calling such a model via API, using
   pre-trained embeddings as-is, or training a small classical model (regression,
   decision tree) is NOT GPAI.
3. OBLIGATIONS that apply to this tier (plus GPAI obligations if is_gpai). If a
   component/architecture list is given, REASON from it and set each obligation's
   status to "likely_gap" (architecture suggests it is missing — e.g. auto-sent
   rejection emails => no human oversight; a model fine-tuned on past decisions =>
   likely training-data bias), "likely_in_place" (a component is evidence it is
   partly met — e.g. a database storing scores => logging), or "needs_confirmation"
   (cannot tell). With no components, set every status to "needs_confirmation".
   Add a one-line "reasoning" citing the component(s), and a "gap_question" to ask
   the client.

Reply with ONLY valid JSON, no prose, in this exact shape:
{"tier":"...","annex_category":"...","rationale":"...","triggering_articles":["..."],
"confidence":"high|medium|low","is_gpai":true,"gpai_rationale":"...",
"obligations":[{"obligation":"...","deadline":"...","status":"likely_gap|likely_in_place|needs_confirmation","reasoning":"...","gap_question":"..."}]}`;

export async function POST(req: Request) {
  const password = req.headers.get("x-app-password") ?? "";
  if (process.env.APP_PASSWORD && password !== process.env.APP_PASSWORD) {
    return Response.json({ error: "Incorrect password." }, { status: 401 });
  }
  if (!process.env.ANTHROPIC_API_KEY) {
    return Response.json({ error: "Server missing ANTHROPIC_API_KEY." }, { status: 500 });
  }

  let body: { name?: string; description?: string; components?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid request body." }, { status: 400 });
  }
  const { name = "", description = "", components = "" } = body;
  if (!name.trim() || !description.trim()) {
    return Response.json({ error: "System name and description are required." }, { status: 400 });
  }

  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const user = `AI SYSTEM
Name: ${name}
Description: ${description}
Components: ${components.trim() || "(none provided)"}`;

  try {
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: 4000,
      system: SYSTEM,
      messages: [{ role: "user", content: user }],
    });
    const text = resp.content
      .filter((b): b is Anthropic.TextBlock => b.type === "text")
      .map((b) => b.text)
      .join("");
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start === -1 || end === -1) {
      return Response.json({ error: "Model returned no JSON." }, { status: 502 });
    }
    const data = JSON.parse(text.slice(start, end + 1));
    data.system_name = name;
    return Response.json(data);
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    const status = msg.toLowerCase().includes("credit balance") ? 402 : 500;
    return Response.json({ error: msg }, { status });
  }
}
