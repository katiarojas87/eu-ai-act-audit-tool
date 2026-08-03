"use client";

import { useState } from "react";

type Obligation = {
  obligation: string;
  deadline: string;
  status: "likely_gap" | "likely_in_place" | "needs_confirmation";
  reasoning: string;
  gap_question: string;
};
type Result = {
  system_name: string;
  tier: string;
  annex_category?: string;
  rationale: string;
  triggering_articles?: string[];
  confidence: string;
  is_gpai: boolean;
  gpai_rationale?: string;
  obligations?: Obligation[];
};

const TIER_LABEL: Record<string, string> = {
  PROHIBITED: "Prohibited",
  ANNEX_I: "High-risk — Annex I",
  ANNEX_III: "High-risk — Annex III",
  LIMITED: "Limited risk",
  MINIMAL: "Minimal risk",
};
const TIER_VAR: Record<string, string> = {
  PROHIBITED: "var(--prohibited)",
  ANNEX_I: "var(--high)",
  ANNEX_III: "var(--high)",
  LIMITED: "var(--limited)",
  MINIMAL: "var(--minimal)",
};
const STATUS_LABEL: Record<string, string> = {
  likely_gap: "Likely gap",
  likely_in_place: "Likely in place",
  needs_confirmation: "Confirm",
};

export default function Page() {
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [components, setComponents] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  async function classify() {
    setError("");
    setResult(null);
    if (!name.trim() || !desc.trim()) {
      setError("Enter a system name and a description first.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-app-password": password },
        body: JSON.stringify({ name, description: desc, components }),
      });
      const data = await res.json();
      if (!res.ok) setError(data.error || "Something went wrong.");
      else setResult(data);
    } catch {
      setError("Network error — please try again.");
    } finally {
      setLoading(false);
    }
  }

  const tierColor = result ? TIER_VAR[result.tier] ?? "var(--ink-3)" : "var(--ink-3)";

  return (
    <>
      <header className="masthead">
        <div className="wrap">
          <p className="eyebrow">Compliance instrument</p>
          <h1>EU AI Act compliance audit</h1>
          <p>
            Describe an AI system in plain language — Dutch, French, English or Spanish —
            and get its risk classification, GPAI obligations, and the compliance gaps to
            address.
          </p>
          <p className="reg">Regulation (EU) 2024/1689 · Annexes I &amp; III · Article 5 · GPAI rules</p>
        </div>
      </header>

      <main>
        <div className="wrap">
          <div className="legend">
            <span><b>Risk:</b></span>
            <span><span className="dot" style={{ background: "var(--prohibited)" }} />Prohibited</span>
            <span><span className="dot" style={{ background: "var(--high)" }} />High-risk</span>
            <span><span className="dot" style={{ background: "var(--limited)" }} />Limited</span>
            <span><span className="dot" style={{ background: "var(--minimal)" }} />Minimal</span>
            <span><span className="dot" style={{ background: "var(--gpai)" }} />GPAI flag</span>
          </div>

          <section className="panel">
            <h2>Assess a system</h2>
            <p className="hint">One AI system at a time. The more detail, the sharper the gap analysis.</p>

            <div className="field">
              <label htmlFor="pw">Access password</label>
              <input id="pw" type="password" value={password}
                onChange={(e) => setPassword(e.target.value)} placeholder="Shared password" />
            </div>
            <div className="field">
              <label htmlFor="name">System name</label>
              <input id="name" type="text" value={name}
                onChange={(e) => setName(e.target.value)} placeholder="e.g. CV screener & ranker" />
            </div>
            <div className="field">
              <label htmlFor="desc">Plain-language description</label>
              <textarea id="desc" value={desc} onChange={(e) => setDesc(e.target.value)}
                placeholder="What does it do? Who is affected? What decisions does it influence?" />
            </div>
            <div className="field">
              <label htmlFor="comp">Components / architecture — optional</label>
              <textarea id="comp" value={components} onChange={(e) => setComponents(e.target.value)}
                placeholder={"- AI Agent (GPT-4o)\n- Ranking model (fine-tuned on past hires)\n- PostgreSQL (candidates, scores)\n- Email integration (auto rejection)"} />
            </div>

            <button className="btn-primary" onClick={classify} disabled={loading}>
              {loading ? "Classifying…" : "Classify system"}
            </button>
            {loading && (
              <div className="loading"><span className="spinner" />Reasoning over the EU AI Act…</div>
            )}
            {error && <div className="err">{error}</div>}
          </section>

          {result && (
            <section className="verdict">
              <div className="verdict-top">
                <div className="tier-band" style={{ background: tierColor }} />
                <div className="verdict-head">
                  <p className="verdict-sys">{result.system_name}</p>
                  <p className="verdict-tier" style={{ color: tierColor }}>
                    {TIER_LABEL[result.tier] ?? result.tier}
                  </p>
                  <div className="chips">
                    {result.is_gpai && <span className="chip chip-gpai">+ GPAI provider</span>}
                    <span className="chip chip-conf">{result.confidence} confidence</span>
                  </div>
                </div>
              </div>

              <div className="verdict-body">
                {result.annex_category && <div className="cat">{result.annex_category}</div>}
                <p>{result.rationale}</p>
                {result.is_gpai && result.gpai_rationale && (
                  <p><strong style={{ color: "var(--gpai)" }}>Also GPAI:</strong> {result.gpai_rationale}</p>
                )}
                {result.triggering_articles && result.triggering_articles.length > 0 && (
                  <p className="arts">Triggering provisions: {result.triggering_articles.join(" · ")}</p>
                )}

                {result.obligations && result.obligations.length > 0 && (
                  <>
                    <div className="obl-title">Obligations &amp; gaps</div>
                    <table className="obl">
                      <thead>
                        <tr>
                          <th>Obligation</th><th>Deadline</th><th>Status</th><th>Assessment</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.obligations.map((o, i) => (
                          <tr key={i}>
                            <td className="oblig">{o.obligation}</td>
                            <td className="deadline">{o.deadline}</td>
                            <td className={`status ${o.status}`}>{STATUS_LABEL[o.status] ?? "Confirm"}</td>
                            <td className="assess">{o.reasoning || o.gap_question}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </div>
            </section>
          )}

          <p className="disclaimer">
            This is a structured assessment to support compliance planning, not legal advice.
            High-risk and prohibited determinations should be confirmed with qualified counsel.
          </p>
        </div>
      </main>
    </>
  );
}
