"use client";

import { useState } from "react";

// "operative" = binding enacting terms. "recital" = non-binding preamble, shown
// with a warning so it is never read as the rule itself.
type SourceQuote = { ref: string; quote: string; location: string; url: string; kind?: string };
type Conclusion = { result: string; detail: string; articles: string[]; trigger: string; status: string; sources: SourceQuote[]; unsourced: string[] };
type Obligation = { obligation: string; deadline: string; status: string; reasoning: string; gap_question: string; role?: string; article?: string };
type Assessment = {
  system_name: string; tier: string; is_gpai: boolean;
  is_ai_system: Conclusion; prohibited_practice: Conclusion; high_risk: Conclusion;
  transparency: Conclusion; gpai: Conclusion;
  territorial_scope?: Conclusion | null;
  organisation_role: string; roles?: string[]; role_basis?: Conclusion | null;
  application_date: string; confidence: string;
  missing_information: string[]; human_review_required: boolean; obligations: Obligation[];
};

const TIER_LABEL: Record<string, string> = {
  PROHIBITED: "Prohibited", ANNEX_I: "High-risk — Annex I", ANNEX_III: "High-risk — Annex III",
  LIMITED: "Limited risk", MINIMAL: "Minimal risk", NOT_AI: "Not an AI system",
  UNDETERMINED: "Undetermined — not enough facts",
  OUT_OF_SCOPE: "Outside the scope of the Regulation",
};
const TIER_VAR: Record<string, string> = {
  PROHIBITED: "var(--prohibited)", ANNEX_I: "var(--high)", ANNEX_III: "var(--high)",
  LIMITED: "var(--limited)", MINIMAL: "var(--minimal)", NOT_AI: "var(--notai)",
  UNDETERMINED: "var(--notai)", OUT_OF_SCOPE: "var(--notai)",
};
const OBL_STATUS: Record<string, string> = {
  likely_gap: "⚠ likely gap", likely_in_place: "✓ likely in place",
  needs_confirmation: "? confirm",
};
const ROLES = ["unknown", "provider", "deployer", "importer", "distributor"] as const;

// Article 2. A description almost never volunteers "our output is not used in
// the EU" or "this is pre-market testing", so scope has to be askable directly —
// otherwise an out-of-scope system is never identified as one.
const NEXUS_OPTIONS: { value: string; label: string }[] = [
  { value: "unknown", label: "Infer from the description" },
  { value: "eu_market", label: "Placed on the EU market / put into service in the EU" },
  { value: "output_in_eu", label: "Outside the EU, but its output is used in the EU" },
  { value: "none", label: "No EU nexus at all" },
];
const CARVE_OUTS: { key: keyof ScopeOverride; label: string }[] = [
  { key: "military_defence_national_security", label: "Military, defence or national security only — Art. 2(3)" },
  { key: "sole_purpose_scientific_research", label: "Sole purpose of scientific research & development — Art. 2(6)" },
  { key: "prerelease_research_testing", label: "Research / testing before being placed on the market — Art. 2(8)" },
  { key: "real_world_testing", label: "…and that testing is in real-world conditions (cancels Art. 2(8))" },
  { key: "personal_non_professional_use", label: "Purely personal, non-professional use — Art. 2(10)" },
];

type ScopeOverride = {
  nexus: string;
  military_defence_national_security: boolean;
  sole_purpose_scientific_research: boolean;
  prerelease_research_testing: boolean;
  real_world_testing: boolean;
  personal_non_professional_use: boolean;
};

const EMPTY_SCOPE: ScopeOverride = {
  nexus: "unknown",
  military_defence_national_security: false,
  sole_purpose_scientific_research: false,
  prerelease_research_testing: false,
  real_world_testing: false,
  personal_non_professional_use: false,
};
const ROLE_HEADING: Record<string, string> = {
  provider: "As provider", deployer: "As deployer", importer: "As importer",
  distributor: "As distributor", all: "Applies to everyone in scope",
};

/** Group obligations by the role that owes them, so a deployer never reads the
 *  provider's duties as their own. */
function byRole(obligations: Obligation[]): [string, Obligation[]][] {
  const groups = new Map<string, Obligation[]>();
  for (const o of obligations) {
    const r = o.role || "all";
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r)!.push(o);
  }
  return [...groups.entries()].sort(
    ([a], [b]) => Number(a === "all") - Number(b === "all") || a.localeCompare(b),
  );
}

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
  const [role, setRole] = useState<string>("unknown");
  const [scope, setScope] = useState<ScopeOverride>(EMPTY_SCOPE);
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
        body: JSON.stringify({
          name, description: desc, components,
          organisation_role: role, scope,
        }),
      });
      const data = await res.json();
      if (!res.ok) setError(data.detail || data.error || "Something went wrong.");
      else {
        setSystems((s) => [...s, data]);
        setName(""); setDesc(""); setComponents("");
        setRole("unknown"); setScope(EMPTY_SCOPE);
      }
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
              <label>Demo cases</label>
              <div className="demos">
                {DEMOS.map((d) => (
                  <button key={d.label} className="demo-btn" onClick={() => loadDemo(d)}>{d.label}</button>
                ))}
              </div>
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
            <div className="field">
              <label htmlFor="role">Client&apos;s role for this system</label>
              <select id="role" value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r === "unknown" ? "Infer from the description" : r}
                  </option>
                ))}
              </select>
              <p className="hint">
                Provider = built it, or supplies it under their own name (Art. 3(3)).
                Deployer = uses it in their own operations (Art. 3(4)). Setting this
                beats inference — a deployer owes no CE marking.
              </p>
            </div>

            <details className="scope">
              <summary>Scope (Art. 2) — set what you already know</summary>
              <div className="field">
                <label htmlFor="nexus">Connection to the Union</label>
                <select
                  id="nexus"
                  value={scope.nexus}
                  onChange={(e) => setScope({ ...scope, nexus: e.target.value })}
                >
                  {NEXUS_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Carve-outs — tick only what you can confirm</label>
                {CARVE_OUTS.map((c) => (
                  <label key={c.key} className="check">
                    <input
                      type="checkbox"
                      checked={Boolean(scope[c.key])}
                      onChange={(e) => setScope({ ...scope, [c.key]: e.target.checked })}
                    />
                    <span>{c.label}</span>
                  </label>
                ))}
              </div>
              <p className="hint">
                A description rarely says &ldquo;our output is not used in the EU&rdquo;,
                so without this the tool assumes the Regulation applies. Anything left
                untouched is inferred from the description, not assumed false.
              </p>
            </details>

            <button className="btn-primary" onClick={classify} disabled={loading}>
              {loading ? "Classifying…" : "Classify system"}
            </button>
            {loading && <div className="loading"><span className="spinner" />Running the rule engine…</div>}
            {error && <div className="err">{error}</div>}
          </section>

          <section>
            {systems.length === 0 && (
              <div className="empty">No systems assessed yet. Fill in the form (or load a demo case) and classify.</div>
            )}

            {systems.map((a, i) => {
              const tc = TIER_VAR[a.tier] ?? "var(--notai)";
              const dims: [string, Conclusion][] = [
                ...(a.territorial_scope
                  ? ([["In scope (Art. 2)?", a.territorial_scope]] as [string, Conclusion][])
                  : []),
                ["Is it an AI system?", a.is_ai_system],
                ["Prohibited practice", a.prohibited_practice],
                ["High-risk system", a.high_risk],
                ["Transparency obligations", a.transparency],
                [a.gpai.result === "Downstream"
                  ? "GPAI — downstream provider"
                  : "GPAI relationship", a.gpai],
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
                    {a.tier === "OUT_OF_SCOPE" && a.territorial_scope && (
                      <div className="miss-note">
                        <b>{a.territorial_scope.detail}</b>{" "}
                        ({a.territorial_scope.articles.join(", ")}). No obligations arise
                        under Regulation (EU) 2024/1689 on this basis. Other Union or
                        national law may still apply. Re-assess if the system is placed on
                        the EU market, its output becomes used in the Union, or its purpose
                        changes.
                      </div>
                    )}
                    <div className="kv">
                      <b>Role(s):</b> {(a.roles?.length ? a.roles : [a.organisation_role]).join(" + ")}
                      &nbsp;·&nbsp; <b>Application date:</b> {a.application_date}
                    </div>
                    {a.role_basis?.detail && (
                      <div className="kv role-basis">
                        <b>Role derived from:</b> {a.role_basis.detail}
                        {a.role_basis.articles?.length > 0 && ` (${a.role_basis.articles.join(", ")})`}
                      </div>
                    )}

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
                                      {s.kind === "recital" && (
                                        <span className="recital">recital — non-binding, interpretive only</span>
                                      )}
                                      <q>{s.quote}</q>
                                      <a href={s.url} target="_blank" rel="noreferrer">official text ↗</a>
                                    </div>
                                  ))}
                                </details>
                              )}
                              {c.unsourced?.length > 0 && (
                                <div className="unsourced">
                                  confirmation needed — wording not located for {c.unsourced.join(", ")}
                                </div>
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
                        <div className="miss-note">
                          The description did not establish the facts below. They were left
                          unresolved rather than assumed — confirm them with the client before
                          relying on this assessment.
                        </div>
                        {a.missing_information.map((m, k) => <div className="miss" key={k}>• {m}</div>)}
                      </>
                    )}

                    {a.obligations.length > 0 && (
                      <>
                        <div className="mrow-title">Potential obligations &amp; gaps</div>
                        {(a.roles?.length ? a.roles : ["unknown"])[0] === "unknown" && (
                          <div className="miss-note">
                            <b>Role not established.</b> Both the provider and the deployer
                            list are shown — they are <b>not cumulative</b>. Set the role
                            above and re-classify: a deployer owes no conformity assessment
                            or CE marking.
                          </div>
                        )}
                        {byRole(a.obligations).map(([r, rows]) => (
                          <div key={r}>
                            <div className="role-heading">{ROLE_HEADING[r] ?? r}</div>
                            <table className="obl">
                              <thead><tr>
                                <th>Obligation</th><th>Article</th><th>Deadline</th>
                                <th>Gap check</th><th>Assessment</th><th>Status</th>
                              </tr></thead>
                              <tbody>
                                {rows.map((o, k) => (
                                  <tr key={k}>
                                    <td>{o.obligation}</td>
                                    <td className="arts">{o.article}</td>
                                    <td className="deadline">{o.deadline}</td>
                                    <td>{o.gap_question}</td>
                                    <td>{o.reasoning}</td>
                                    <td className={`status ${o.status}`}>{OBL_STATUS[o.status] ?? "confirm"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ))}
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
