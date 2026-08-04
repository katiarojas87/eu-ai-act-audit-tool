"use client";

import { useState } from "react";

type SourceQuote = { ref: string; quote: string; location: string; url: string };
type Conclusion = { result: string; detail: string; articles: string[]; trigger: string; status: string; sources: SourceQuote[] };
type Obligation = { obligation: string; deadline: string; status: string; reasoning: string; gap_question: string };
type Assessment = {
  system_name: string; tier: string; is_gpai: boolean;
  is_ai_system: Conclusion; prohibited_practice: Conclusion; high_risk: Conclusion;
  transparency: Conclusion; gpai: Conclusion;
  organisation_role: string; application_date: string; confidence: string;
  missing_information: string[]; human_review_required: boolean; obligations: Obligation[];
};

const TIER_LABEL: Record<string, string> = {
  PROHIBITED: "Prohibited", ANNEX_I: "High-risk — Annex I", ANNEX_III: "High-risk — Annex III",
  LIMITED: "Limited risk", MINIMAL: "Minimal risk", NOT_AI: "Not an AI system",
};
const TIER_VAR: Record<string, string> = {
  PROHIBITED: "var(--prohibited)", ANNEX_I: "var(--high)", ANNEX_III: "var(--high)",
  LIMITED: "var(--limited)", MINIMAL: "var(--minimal)", NOT_AI: "var(--notai)",
};
const OBL_STATUS: Record<string, string> = {
  likely_gap: "⚠ likely gap", likely_in_place: "✓ likely in place",
  needs_confirmation: "? confirm",
};

const DEMOS: { label: string; name: string; description: string; components: string }[] = [
  {
    label: "① Recruitment / CV-ranking",
    name: "CV Screener & Ranker",
    description: "An AI assistant that screens and ranks job applicants for recruiters. It parses CVs, matches them against the job requirements, scores and ranks candidates, and sends interview or rejection emails automatically.",
    components: "- AI Agent (GPT-4o)\n- Ranking model (fine-tuned on past hiring decisions)\n- PostgreSQL (candidates, scores)\n- Email integration (auto rejection / interview invites)",
  },
  {
    label: "② Customer-service chatbot",
    name: "Careers Chatbot",
    description: "A chatbot on the website that answers candidate questions about vacancies. It talks directly with people and does not make any hiring decisions.",
    components: "- Web chat widget\n- LLM via API (no fine-tuning)\n- FAQ knowledge base",
  },
  {
    label: "③ Emotion recognition at work",
    name: "Workplace Mood Monitor",
    description: "A system used by an employer that infers employees' emotions from webcam video during work to flag stress and disengagement.",
    components: "- Webcam video ingestion\n- Emotion-recognition model\n- Manager dashboard",
  },
];

export default function Page() {
  const [password, setPassword] = useState("");
  const [clientName, setClientName] = useState("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [components, setComponents] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [systems, setSystems] = useState<Assessment[]>([]);
  const [reporting, setReporting] = useState(false);

  function loadDemo(d: (typeof DEMOS)[number]) {
    setName(d.name); setDesc(d.description); setComponents(d.components); setError("");
  }

  async function classify() {
    setError("");
    if (!name.trim() || !desc.trim()) { setError("Enter a system name and a description first."); return; }
    setLoading(true);
    try {
      const res = await fetch("/api/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-app-password": password },
        body: JSON.stringify({ name, description: desc, components }),
      });
      const data = await res.json();
      if (!res.ok) setError(data.detail || data.error || "Something went wrong.");
      else { setSystems((s) => [...s, data]); setName(""); setDesc(""); setComponents(""); }
    } catch { setError("Network error — please try again."); }
    finally { setLoading(false); }
  }

  async function generateReport() {
    setError(""); setReporting(true);
    try {
      const res = await fetch("/api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-app-password": password },
        body: JSON.stringify({ client_name: clientName || "Client", systems }),
      });
      if (!res.ok) { const d = await res.json(); setError(d.detail || d.error || "Report failed."); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "eu_ai_act_assessment.pdf"; a.click();
      URL.revokeObjectURL(url);
    } catch { setError("Network error generating the report."); }
    finally { setReporting(false); }
  }

  return (
    <>
      <header className="masthead">
        <div className="wrap">
          <p className="eyebrow">EU AI Act · System classifier</p>
          <h1>Preliminary AI Act assessment</h1>
          <p>Describe an AI system in plain language (NL / FR / EN / ES). A deterministic
            rule engine classifies it across independent dimensions and cites the provision
            behind every conclusion. A decision-support tool — not legal advice.</p>
          <p className="reg">Regulation (EU) 2024/1689 · Annexes I &amp; III · Article 5 · GPAI</p>
        </div>
      </header>

      <main>
        <div className="wrap grid">
          <section className="panel">
            <h2>Assess a system</h2>
            <p className="hint">One system at a time. More detail → sharper analysis.</p>

            <div className="field">
              <label htmlFor="pw">Access password</label>
              <input id="pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Shared password" />
            </div>
            <div className="field">
              <label htmlFor="client">Client / company (for the report)</label>
              <input id="client" type="text" value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="e.g. Sample Public Sector NV" />
            </div>
            <div className="field">
              <label htmlFor="name">System name</label>
              <input id="name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. CV Screener" />
            </div>
            <div className="field">
              <label htmlFor="desc">Plain-language description</label>
              <textarea id="desc" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What does it do? Who is affected? What decisions does it influence?" />
            </div>
            <div className="field">
              <label htmlFor="comp">Components / architecture — optional</label>
              <textarea id="comp" value={components} onChange={(e) => setComponents(e.target.value)} placeholder={"- AI Agent (GPT-4o)\n- Fine-tuned ranking model\n- Email integration"} />
            </div>

            <button className="btn-primary" onClick={classify} disabled={loading}>
              {loading ? "Classifying…" : "Classify system"}
            </button>
            {loading && <div className="loading"><span className="spinner" />Running the rule engine…</div>}
            {error && <div className="err">{error}</div>}

            <div className="field" style={{ marginTop: 18 }}>
              <label>Demo cases</label>
              <div className="demos">
                {DEMOS.map((d) => (
                  <button key={d.label} className="demo-btn" onClick={() => loadDemo(d)}>{d.label}</button>
                ))}
              </div>
            </div>
          </section>

          <section>
            {systems.length === 0 && (
              <div className="empty">No systems assessed yet. Fill in the form (or load a demo case) and classify.</div>
            )}

            {systems.map((a, i) => {
              const tc = TIER_VAR[a.tier] ?? "var(--notai)";
              const dims: [string, Conclusion][] = [
                ["Is it an AI system?", a.is_ai_system],
                ["Prohibited practice", a.prohibited_practice],
                ["High-risk system", a.high_risk],
                ["Transparency obligations", a.transparency],
                ["GPAI relationship", a.gpai],
              ];
              return (
                <div className="verdict" key={i}>
                  <div className="verdict-top">
                    <div className="band" style={{ background: tc }} />
                    <div className="verdict-head">
                      <p className="vsys">{a.system_name}</p>
                      <p className="vtier" style={{ color: tc }}>{TIER_LABEL[a.tier] ?? a.tier}</p>
                      <div className="chips">
                        {a.is_gpai && <span className="chip" style={{ color: "var(--gpai)" }}>+ GPAI</span>}
                        <span className="chip" style={{ color: "var(--ink-3)" }}>{a.confidence} confidence</span>
                        {a.human_review_required && <span className="chip" style={{ color: "var(--amber-ink)" }}>human review</span>}
                        <button className="btn-ghost remove" onClick={() => setSystems((s) => s.filter((_, j) => j !== i))}>Remove</button>
                      </div>
                    </div>
                  </div>
                  <div className="vbody">
                    <div className="kv"><b>Organisation role:</b> {a.organisation_role} &nbsp;·&nbsp; <b>Application date:</b> {a.application_date}</div>

                    <div className="mrow-title">Classification matrix</div>
                    <table className="matrix">
                      <thead><tr><th>Dimension</th><th>Result</th><th>Provision(s)</th><th>Status</th></tr></thead>
                      <tbody>
                        {dims.map(([label, c]) => (
                          <tr key={label}>
                            <td className="dim">{label}</td>
                            <td>{c.result}</td>
                            <td className="arts">
                              {c.articles.join("  ")}
                              {c.sources?.length > 0 && (
                                <details className="src">
                                  <summary>source text</summary>
                                  {c.sources.map((s, si) => (
                                    <div className="srcq" key={si}>
                                      <span className="srcref">{s.ref}</span>
                                      <q>{s.quote}</q>
                                      <a href={s.url} target="_blank" rel="noreferrer">official text ↗</a>
                                    </div>
                                  ))}
                                </details>
                              )}
                            </td>
                            <td className={`status ${c.status}`}>{c.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    {a.missing_information.length > 0 && (
                      <>
                        <div className="mrow-title">Missing evidence</div>
                        {a.missing_information.map((m, k) => <div className="miss" key={k}>• {m}</div>)}
                      </>
                    )}

                    {a.obligations.length > 0 && (
                      <>
                        <div className="mrow-title">Potential obligations &amp; gaps</div>
                        <table className="obl">
                          <thead><tr>
                            <th>Obligation</th><th>Deadline</th><th>Gap check</th>
                            <th>Assessment</th><th>Status</th>
                          </tr></thead>
                          <tbody>
                            {a.obligations.map((o, k) => (
                              <tr key={k}>
                                <td>{o.obligation}</td>
                                <td className="deadline">{o.deadline}</td>
                                <td>{o.gap_question}</td>
                                <td>{o.reasoning}</td>
                                <td className={`status ${o.status}`}>{OBL_STATUS[o.status] ?? "confirm"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    )}
                  </div>
                </div>
              );
            })}

            {systems.length > 0 && (
              <div className="export">
                <button className="btn-amber" onClick={generateReport} disabled={reporting}>
                  {reporting ? "Generating…" : "Download PDF assessment"}
                </button>
              </div>
            )}
          </section>
        </div>

        <div className="wrap">
          <p className="disclaimer">Preliminary assessment — not legal advice, EU approval or
            certification. High-risk and prohibited determinations must be confirmed with counsel.</p>
        </div>
      </main>
    </>
  );
}
