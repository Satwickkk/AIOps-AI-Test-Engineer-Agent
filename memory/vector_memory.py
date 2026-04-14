"""
memory/vector_memory.py
------------------------
Vector Store Memory — Long-Term Incident Memory
================================================
FUTURE WORK ITEM #8: Vector store memory

Stores past RCA results as vector embeddings.
On each new anomaly, retrieves similar past incidents to enrich the LLM prompt.
This gives the agent "memory" across restarts and long time periods.

Implementation:
  - Uses sentence-transformers for local text embeddings (no API needed)
  - Uses FAISS for fast approximate nearest-neighbor search
  - Falls back to keyword search if sentence-transformers not installed
  - Persists index to memory/vector_index/ on disk

Usage in agent_loop:
  from memory.vector_memory import incident_memory
  similar = incident_memory.search(dominant_issue, root_cause, n=3)
  # Inject similar into LLM prompt for richer context
"""

import json
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MEMORY_DIR   = Path("memory")
STORE_FILE   = MEMORY_DIR / "incidents.json"
INDEX_FILE   = MEMORY_DIR / "faiss_index.pkl"
EMBED_FILE   = MEMORY_DIR / "embeddings.pkl"
MAX_MEMORIES = 500   # keep last 500 incidents


@dataclass
class IncidentMemory:
    """A stored past incident."""
    incident_id: str
    timestamp: str
    severity: str
    dominant_issue: str
    root_cause: str
    suggested_fixes: list[str]
    outcome: str = "UNKNOWN"   # filled in by feedback module
    tags: list[str] = field(default_factory=list)


@dataclass
class SimilarIncident:
    """A retrieved similar incident with similarity score."""
    incident: IncidentMemory
    similarity_score: float
    retrieval_method: str   # "vector" or "keyword"


class VectorMemoryStore:
    """
    Long-term incident memory backed by FAISS vector search.

    If sentence-transformers + faiss-cpu are not installed,
    automatically falls back to keyword-based TF-IDF search.
    """

    def __init__(self):
        MEMORY_DIR.mkdir(exist_ok=True)
        self._incidents: list[IncidentMemory] = []
        self._embeddings = None
        self._index = None
        self._encoder = None
        self._use_vectors = False

        self._load_incidents()
        self._try_init_vectors()

    def _load_incidents(self):
        """Load incidents from JSON store."""
        if STORE_FILE.exists():
            try:
                data = json.loads(STORE_FILE.read_text())
                self._incidents = [IncidentMemory(**d) for d in data]
                print(f"[Memory] Loaded {len(self._incidents)} past incidents")
            except Exception as e:
                print(f"[Memory] Could not load incidents: {e}")
                self._incidents = []

    def _try_init_vectors(self):
        """Try to initialize FAISS + sentence-transformers. Falls back gracefully."""
        try:
            from sentence_transformers import SentenceTransformer
            import faiss
            import numpy as np

            self._encoder = SentenceTransformer("all-MiniLM-L6-v2")  # 80MB, fast
            self._np = np
            self._faiss = faiss

            # Load existing index if available
            if INDEX_FILE.exists() and EMBED_FILE.exists():
                with open(INDEX_FILE, "rb") as f:
                    self._index = pickle.load(f)
                with open(EMBED_FILE, "rb") as f:
                    self._embeddings = pickle.load(f)

            self._use_vectors = True
            print("[Memory] Vector search enabled (sentence-transformers + FAISS)")

        except ImportError:
            self._use_vectors = False
            print("[Memory] Vector libs not found — using keyword search fallback")
            print("[Memory] To enable: pip install sentence-transformers faiss-cpu")

    def _text_for_incident(self, inc: IncidentMemory) -> str:
        """Build searchable text representation of an incident."""
        fixes = " ".join(inc.suggested_fixes[:3])
        return f"{inc.severity} {inc.dominant_issue} {inc.root_cause} {fixes}"

    def _rebuild_index(self):
        """Rebuild FAISS index from all stored incidents."""
        if not self._use_vectors or not self._incidents:
            return
        try:
            import numpy as np
            texts = [self._text_for_incident(inc) for inc in self._incidents]
            embeddings = self._encoder.encode(texts, show_progress_bar=False)
            embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

            dim = embeddings.shape[1]
            index = self._faiss.IndexFlatIP(dim)  # Inner product = cosine on normalized vecs
            index.add(embeddings.astype("float32"))

            self._index = index
            self._embeddings = embeddings

            # Persist
            with open(INDEX_FILE, "wb") as f:
                pickle.dump(index, f)
            with open(EMBED_FILE, "wb") as f:
                pickle.dump(embeddings, f)

        except Exception as e:
            print(f"[Memory] Index rebuild failed: {e}")

    def _keyword_search(self, query: str, n: int) -> list[SimilarIncident]:
        """Fallback keyword search using simple TF-IDF-like scoring."""
        query_words = set(query.lower().split())
        scored = []
        for inc in self._incidents:
            doc_words = set(self._text_for_incident(inc).lower().split())
            overlap = len(query_words & doc_words)
            union = len(query_words | doc_words)
            score = overlap / union if union > 0 else 0
            if score > 0:
                scored.append((score, inc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [SimilarIncident(incident=inc, similarity_score=round(score, 3),
                                retrieval_method="keyword")
                for score, inc in scored[:n]]

    def add_incident(self, rca_result, outcome: str = "UNKNOWN"):
        """
        Store a new incident in memory.
        Call this after each RCA to build up the memory bank.
        """
        import uuid
        inc = IncidentMemory(
            incident_id=str(uuid.uuid4())[:8],
            timestamp=rca_result.timestamp,
            severity=rca_result.severity,
            dominant_issue=rca_result.dominant_issue,
            root_cause=rca_result.root_cause,
            suggested_fixes=rca_result.suggested_fixes,
            outcome=outcome,
            tags=self._extract_tags(rca_result.dominant_issue + " " + rca_result.root_cause),
        )
        self._incidents.append(inc)

        # Keep only last MAX_MEMORIES
        if len(self._incidents) > MAX_MEMORIES:
            self._incidents = self._incidents[-MAX_MEMORIES:]

        # Persist JSON
        STORE_FILE.write_text(json.dumps(
            [vars(i) for i in self._incidents], indent=2
        ))

        # Rebuild vector index periodically (every 10 new incidents)
        if self._use_vectors and len(self._incidents) % 10 == 0:
            self._rebuild_index()

        print(f"[Memory] Stored incident: {inc.incident_id} ({inc.severity})")

    def _extract_tags(self, text: str) -> list[str]:
        """Extract simple keyword tags from text."""
        keywords = ["database", "cpu", "memory", "latency", "timeout",
                    "connection", "pool", "error", "crash", "slow", "spike"]
        text_lower = text.lower()
        return [kw for kw in keywords if kw in text_lower]

    def search(self, dominant_issue: str, root_cause: str = "",
               n: int = 3) -> list[SimilarIncident]:
        """
        Search for similar past incidents.

        Args:
            dominant_issue: Primary anomaly signal
            root_cause: LLM-generated root cause
            n: Number of similar incidents to return

        Returns:
            List of SimilarIncident sorted by similarity (most similar first)
        """
        if not self._incidents:
            return []

        query = f"{dominant_issue} {root_cause}".strip()

        # Vector search
        if self._use_vectors and self._index is not None:
            try:
                import numpy as np
                q_emb = self._encoder.encode([query], show_progress_bar=False)
                q_emb = q_emb / np.linalg.norm(q_emb)
                scores, indices = self._index.search(q_emb.astype("float32"), min(n, len(self._incidents)))
                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < len(self._incidents) and score > 0.3:
                        results.append(SimilarIncident(
                            incident=self._incidents[idx],
                            similarity_score=round(float(score), 3),
                            retrieval_method="vector"
                        ))
                return results
            except Exception as e:
                print(f"[Memory] Vector search failed: {e}, falling back to keyword")

        # Keyword fallback
        return self._keyword_search(query, n)

    def format_for_prompt(self, similar: list[SimilarIncident]) -> str:
        """
        Format similar incidents for injection into the LLM prompt.
        Returns empty string if no similar incidents found.
        """
        if not similar:
            return ""

        lines = ["\n## Similar Past Incidents (for context):"]
        for s in similar:
            inc = s.incident
            fixes = "; ".join(inc.suggested_fixes[:2])
            lines.append(
                f"- [{inc.timestamp[:10]}] {inc.severity} — {inc.dominant_issue}\n"
                f"  Root cause: {inc.root_cause[:100]}\n"
                f"  Fixes tried: {fixes[:100]}\n"
                f"  Outcome: {inc.outcome} | Similarity: {s.similarity_score:.0%}"
            )
        return "\n".join(lines)

    def update_outcome(self, incident_id: str, outcome: str):
        """Update the outcome of a stored incident (called by feedback module)."""
        for inc in self._incidents:
            if inc.incident_id == incident_id:
                inc.outcome = outcome
                STORE_FILE.write_text(json.dumps(
                    [vars(i) for i in self._incidents], indent=2
                ))
                print(f"[Memory] Updated incident {incident_id} outcome: {outcome}")
                return
        print(f"[Memory] Incident {incident_id} not found")

    def stats(self) -> dict:
        """Return memory statistics for dashboard display."""
        if not self._incidents:
            return {"total": 0, "by_severity": {}, "by_outcome": {}}
        by_sev = {}
        by_out = {}
        for inc in self._incidents:
            by_sev[inc.severity] = by_sev.get(inc.severity, 0) + 1
            by_out[inc.outcome]  = by_out.get(inc.outcome, 0) + 1
        return {
            "total": len(self._incidents),
            "by_severity": by_sev,
            "by_outcome": by_out,
            "vector_search_enabled": self._use_vectors,
        }


# Singleton
incident_memory = VectorMemoryStore()