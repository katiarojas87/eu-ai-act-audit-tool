# GPAI Compliance Checklist — General-Purpose AI models

Use this when a system is flagged is_gpai = true. Source: European Commission
GPAI Code of Practice & factpages (digital-strategy.ec.europa.eu),
artificialintelligenceact.eu. GPAI obligations apply since 2 August 2025.

**Key distinction:** ALL GPAI providers owe documentation, copyright and
transparency duties. ONLY GPAI models with *systemic risk* (the largest, most
capable models, >10^25 FLOPs training compute) additionally owe risk evaluation,
mitigation, and serious-incident reporting.

## Technical requirements (all GPAI providers)
- Maintain sufficient technical documentation of the model and how it works
  (architecture, capabilities, limitations).
- Publish a summary of the training content using the Commission's required template.
- Provide enough transparency for downstream providers to understand the model's
  capabilities and limitations.
- Keep internal traceability of versions, relevant changes, and safety tests.

## Copyright (all GPAI providers)
- Adopt a written policy to comply with EU copyright law.
- Document how text-and-data-mining (TDM) opt-outs are respected where applicable.
- Keep internal evidence of training sources and the filters/controls used for
  protected material.
- Align the copyright policy with the GPAI Code of Practice copyright chapter.
- For commercial use, ensure legal can demonstrate compliance under audit.

## Systemic-risk GPAI only (largest models)
- Perform model evaluation including adversarial testing.
- Assess and mitigate possible systemic risks.
- Ensure an adequate level of cybersecurity protection.
- Notify serious incidents to the AI Office (and national authorities where relevant),
  using the Commission's reporting template.
- Have an internal procedure to detect, classify, and escalate serious incidents fast;
  define owners, deadlines, channels; keep records, root-cause analysis, corrective actions.

## Operational yes/no audit
| Area | Check |
|---|---|
| Technical documentation | Exists, up to date, describes architecture, capabilities and limits. |
| Training summary | Published in the required format. |
| Copyright | Written policy and compliance controls in place. |
| Systemic risk | Assessed whether the model falls under reinforced obligations. |
| Incidents | Notification procedure and template ready (systemic-risk models). |
| Evidence | Versions, tests and relevant logs are retained. |

## Provider vs downstream note
- If you build/fine-tune the model → you are a **GPAI provider** (full duties above).
- If you only integrate/distribute it in a product → you may have **downstream**
  duties: pass through documentation, respect the upstream provider's use restrictions,
  and meet the relevant use-case tier obligations (Annex I/III etc.).
