"""Central configuration for the EU AI Act audit tool."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # repo root — data/knowledge/chroma/reports live there, not in src/
DATA_DIR = BASE_DIR / "data"          # raw EU AI Act source documents
KNOWLEDGE_DIR = BASE_DIR / "knowledge"  # curated structured reference (annexes, obligations)
CHROMA_DIR = BASE_DIR / "chroma"      # persisted vector store
REPORTS_DIR = BASE_DIR / "reports"    # generated client PDF reports

# --- LLM ---
# Opus 4.8 = best legal reasoning (default). Swap to "claude-sonnet-4-6" for ~2x cheaper/faster.
LLM_MODEL = "claude-opus-4-8"
LLM_MAX_TOKENS = 8000

# --- Embeddings (local, multilingual: NL / FR / EN / ES) ---
# e5-small (~470MB) chosen to fit limited disk; e5-large (~2.2GB) is marginally
# more accurate if you have the space. Same "query:/passage:" prefix convention.
EMBED_MODEL = "intfloat/multilingual-e5-small"
COLLECTION_NAME = "eu_ai_act"

# --- RAG ---
CHUNK_SIZE = 1000        # characters per chunk
CHUNK_OVERLAP = 150
TOP_K = 6                # how many law passages to retrieve per query

# --- Branding (for the PDF report) ---
COMPANY_NAME = "KRS Solutions"
CONSULTANT_NAME = "Katia Rojas Sandoval"
