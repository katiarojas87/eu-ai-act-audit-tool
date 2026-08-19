"""
Build the RAG knowledge base.

1. Loads the EU AI Act source text + the curated knowledge/ markdown files.
2. Chunks them.
3. Embeds locally with multilingual-e5 (free, private, NL/FR/EN/ES).
4. Stores vectors in a local ChromaDB collection.

Run once (and again whenever you add/update source documents):
    python ingest.py
"""
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

import config


def load_documents() -> list[tuple[str, str]]:
    """Return list of (source_name, full_text)."""
    docs: list[tuple[str, str]] = []

    # Curated structured knowledge (always present)
    for md in config.KNOWLEDGE_DIR.glob("*.md"):
        docs.append((f"knowledge/{md.name}", md.read_text(encoding="utf-8")))

    # Raw EU AI Act source docs you drop into data/ (.txt or extracted .pdf text)
    for txt in config.DATA_DIR.glob("*.txt"):
        docs.append((f"data/{txt.name}", txt.read_text(encoding="utf-8")))

    for pdf in config.DATA_DIR.glob("*.pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            docs.append((f"data/{pdf.name}", text))
        except Exception as e:  # noqa: BLE001
            print(f"  ! could not read {pdf.name}: {e}")

    return docs


def chunk(text: str, size: int, overlap: int) -> list[str]:
    chunks, start = [], 0
    text = text.strip()
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if c.strip()]


def main() -> None:
    docs = load_documents()
    if not docs:
        print("No documents found. Add EU AI Act .txt/.pdf files to data/ "
              "(knowledge/ files are included automatically).")
        return

    print(f"Loaded {len(docs)} document(s). Chunking...")
    ids, texts, metas = [], [], []
    for source, text in docs:
        for i, c in enumerate(chunk(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)):
            ids.append(f"{source}::{i}")
            texts.append(c)
            metas.append({"source": source})
    print(f"  {len(texts)} chunks.")

    print(f"Loading embedding model ({config.EMBED_MODEL})... (first run downloads it)")
    model = SentenceTransformer(config.EMBED_MODEL)
    # e5 models expect a "passage: " prefix on indexed text.
    embeddings = model.encode(
        [f"passage: {t}" for t in texts],
        show_progress_bar=True,
        normalize_embeddings=True,
    ).tolist()

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    # Rebuild cleanly each run.
    try:
        client.delete_collection(config.COLLECTION_NAME)
    except Exception:  # noqa: BLE001
        pass
    coll = client.create_collection(config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    coll.add(ids=ids, documents=texts, embeddings=embeddings, metadatas=metas)

    print(f"\nDone. {coll.count()} chunks indexed in {config.CHROMA_DIR}")


if __name__ == "__main__":
    main()
