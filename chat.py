"""Open-ended Q&A over the EU AI Act (chat mode, separate from the audit graph)."""
import anthropic
from dotenv import load_dotenv

import config
from retriever import retrieve

load_dotenv()
client = anthropic.Anthropic()

SYSTEM_PROMPT = """You are a compliance assistant answering questions about the EU AI Act \
(Regulation 2024/1689), using ONLY the legal context provided below each question.

Rules:
- Answer strictly from the provided context. If the context doesn't cover the question, \
say so explicitly — never fill gaps from general knowledge about AI law.
- Always cite the specific article, annex, or recital number your answer relies on.
- The user may ask in Dutch, French, English or Spanish — answer in the same language they used.
- Distinguish clearly between what the law requires and what is common practice or your \
interpretation; flag the latter as such.
- If the question depends on facts about a specific company or system that weren't given, \
ask a clarifying question instead of guessing.
- Keep answers concise and structured (short paragraphs or bullet points), not a legal essay.
- End with: "This is informational, not legal advice — confirm with counsel for binding decisions."
"""


def ask(question: str, history: list[dict] | None = None) -> dict:
    """Answer a free-form question about the EU AI Act. Returns {answer, sources}."""
    passages = retrieve(question, k=config.TOP_K)
    context = "\n\n".join(f"[{p['source']}]\n{p['text']}" for p in passages)

    messages = list(history or [])
    messages.append({
        "role": "user",
        "content": f"LEGAL CONTEXT:\n{context}\n\nQUESTION:\n{question}",
    })

    resp = client.messages.create(
        model=config.LLM_MODEL,
        max_tokens=config.LLM_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    answer = next((b.text for b in resp.content if b.type == "text"), "")
    sources = sorted({p["source"] for p in passages})
    return {"answer": answer, "sources": sources}


if __name__ == "__main__":
    # Quick smoke test (requires ingest.py to have been run + ANTHROPIC_API_KEY set)
    result = ask("What are the obligations for a high-risk AI system under Annex III?")
    print(result["answer"])
    print("\nSources:", result["sources"])
