import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import fitz
from rank_bm25 import BM25Okapi


ROOT_DIR = Path(__file__).resolve().parent
VECTOR_DIR = ROOT_DIR / "vectorstore"
META_PATH = VECTOR_DIR / "metadata.json"
INDEX_VERSION = 2
MAX_PAGE_CHARS = 3000


@dataclass
class SearchResult:
    parent_id: str
    child_id: str
    page: int
    source: str
    section_hint: str
    text: str
    dense_rank: int
    bm25_rank: int
    rrf_score: float
    rerank_score: float


class ConstitutionRAGEngine:
    def __init__(self) -> None:
        self.parent_map: Dict[str, Dict] = {}
        self.child_map: Dict[str, Dict] = {}
        self.child_tokens: List[List[str]] = []
        self.bm25: BM25Okapi | None = None

    def ensure_index(self) -> None:
        pdf_paths = self._discover_pdf_paths()
        if not pdf_paths:
            raise FileNotFoundError(f"No PDF files found in: {ROOT_DIR}")

        if self._needs_rebuild(pdf_paths):
            self._build_index(pdf_paths)

        self._load_index()

    def _discover_pdf_paths(self) -> List[Path]:
        return sorted(
            [
                p
                for p in ROOT_DIR.glob("*.pdf")
                if p.is_file()
            ],
            key=lambda p: p.name.lower(),
        )

    def _current_file_fingerprints(self, pdf_paths: List[Path]) -> List[Dict]:
        fingerprints: List[Dict] = []
        for path in pdf_paths:
            stat = path.stat()
            fingerprints.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                }
            )
        return fingerprints

    def _needs_rebuild(self, pdf_paths: List[Path]) -> bool:
        if not META_PATH.exists():
            return True

        try:
            with META_PATH.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return True

        metadata = payload.get("index_metadata", {})
        if int(metadata.get("index_version", 0)) != INDEX_VERSION:
            return True

        previous_files = metadata.get("files", [])
        current_files = self._current_file_fingerprints(pdf_paths)
        return previous_files != current_files

    def _build_index(self, pdf_paths: List[Path]) -> None:
        VECTOR_DIR.mkdir(parents=True, exist_ok=True)

        parent_payload: List[Dict] = []
        child_payload: List[Dict] = []

        for doc_idx, pdf_path in enumerate(pdf_paths):
            with fitz.open(str(pdf_path)) as pdf:
                for page_idx, page in enumerate(pdf):
                    parent_id = f"p-{doc_idx}-{page_idx}"
                    page_number = page_idx + 1
                    source = pdf_path.name

                    try:
                        parent_text = (page.get_text("text") or "").strip()
                    except Exception:
                        continue

                    if len(parent_text) > MAX_PAGE_CHARS:
                        parent_text = parent_text[:MAX_PAGE_CHARS]

                    if not parent_text:
                        continue

                    section_hint = self._detect_section(parent_text)

                    parent_payload.append(
                        {
                            "id": parent_id,
                            "page": page_number,
                            "source": source,
                            "section_hint": section_hint,
                            "text": parent_text,
                        }
                    )

                    for child_offset, child_text in enumerate(self._split_text(parent_text, chunk_size=700, overlap=100)):
                        child_id = f"c-{doc_idx}-{page_idx}-{child_offset}"
                        child_payload.append(
                            {
                                "id": child_id,
                                "parent_id": parent_id,
                                "page": page_number,
                                "source": source,
                                "section_hint": section_hint,
                                "text": child_text.strip(),
                            }
                        )

        with META_PATH.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "index_metadata": {
                        "index_version": INDEX_VERSION,
                        "files": self._current_file_fingerprints(pdf_paths),
                    },
                    "parent_payload": parent_payload,
                    "child_payload": child_payload,
                },
                f,
                ensure_ascii=True,
                indent=2,
            )

    def _load_index(self) -> None:
        with META_PATH.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        parent_payload = payload.get("parent_payload", [])
        child_payload = payload.get("child_payload", [])

        self.parent_map = {item["id"]: item for item in parent_payload}
        self.child_map = {item["id"]: item for item in child_payload}

        self.child_tokens = [self._tokenize(item["text"]) for item in child_payload]
        self.bm25 = BM25Okapi(self.child_tokens)

    def search(self, query: str, dense_k: int = 12, bm25_k: int = 12, final_k: int = 5) -> List[SearchResult]:
        if not self.bm25 or not self.child_map:
            return []

        tokenized_query = self._tokenize(query)
        bm25_scores = self.bm25.get_scores(tokenized_query)
        bm25_indices = sorted(range(len(bm25_scores)), key=lambda idx: bm25_scores[idx], reverse=True)[:bm25_k]
        child_ids = list(self.child_map.keys())
        ranked_candidates: List[Tuple[str, float]] = []
        for rank, idx in enumerate(bm25_indices, start=1):
            child_id = child_ids[idx]
            score = float(bm25_scores[idx])
            ranked_candidates.append((child_id, score))

        ranked_candidates.sort(key=lambda item: item[1], reverse=True)
        top_candidates = ranked_candidates[: max(final_k * 3, 10)]

        merged = []
        for rank, (child_id, score) in enumerate(top_candidates, start=1):
            child = self.child_map[child_id]
            merged.append(
                SearchResult(
                    parent_id=child["parent_id"],
                    child_id=child_id,
                    page=child["page"],
                    source=child["source"],
                    section_hint=child["section_hint"],
                    text=child["text"],
                    dense_rank=rank,
                    bm25_rank=rank,
                    rrf_score=float(score),
                    rerank_score=float(score),
                )
            )

        merged.sort(key=lambda x: x.rrf_score, reverse=True)
        return merged[:final_k]

    def build_context(self, results: List[SearchResult], max_parents: int = 4) -> Tuple[str, List[Dict]]:
        if not results:
            return "", []

        picked_parents: List[str] = []
        sources: List[Dict] = []

        for result in results:
            if result.parent_id in picked_parents:
                continue
            picked_parents.append(result.parent_id)
            if len(picked_parents) >= max_parents:
                break

        context_blocks: List[str] = []
        for idx, parent_id in enumerate(picked_parents, start=1):
            parent = self.parent_map[parent_id]
            context_blocks.append(
                f"[Source {idx}]\\n"
                f"Section hint: {parent['section_hint']}\\n"
                f"Page: {parent['page']}\\n"
                f"Text: {parent['text']}"
            )
            sources.append(
                {
                    "source_id": idx,
                    "section_hint": parent["section_hint"],
                    "page": parent["page"],
                    "source": parent["source"],
                }
            )

        return "\\n\\n".join(context_blocks), sources

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-zA-Z0-9]+", text.lower())

    @staticmethod
    def _split_text(text: str, chunk_size: int, overlap: int) -> List[str]:
        if chunk_size <= 0:
            return [text]

        chunks: List[str] = []
        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(start + chunk_size, text_length)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_length:
                break
            start = max(end - overlap, start + 1)

        return chunks

    @staticmethod
    def _detect_section(text: str) -> str:
        patterns = [
            r"(Article\s+\d+[A-Z]?)",
            r"(Part\s+[IVXLC]+)",
            r"(Schedule\s+[A-Za-z0-9]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return "Document excerpt"
