"""Local metric-knowledge retrieval used by the Commerce Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sklearn.feature_extraction.text import TfidfVectorizer


class MetricKnowledgeBase:
    """Small deterministic RAG index for metric definitions and business rules."""

    def __init__(self, knowledge_dir: str | Path, top_k: int = 4):
        self.knowledge_dir = Path(knowledge_dir)
        self.top_k = top_k
        self.documents = self._load_documents()
        if not self.documents:
            raise ValueError(f"No knowledge documents found in {self.knowledge_dir}")
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform([document.page_content for document in self.documents])

    def _load_documents(self) -> list[Document]:
        source_documents = []
        splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=80)
        for path in sorted(self.knowledge_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            source_documents.extend(
                splitter.create_documents(
                    [text],
                    metadatas=[{"source": str(path.relative_to(self.knowledge_dir.parent)).replace("\\", "/")}],
                )
            )
        for index, document in enumerate(source_documents):
            document.metadata["chunk"] = index + 1
        return source_documents

    def search(self, query: str) -> list[Document]:
        if not query or not query.strip():
            return []
        scores = self.matrix @ self.vectorizer.transform([query.strip()]).T
        score_values = scores.toarray().ravel()
        ranked = sorted(range(len(score_values)), key=lambda index: float(score_values[index]), reverse=True)
        return [self.documents[index] for index in ranked[: self.top_k] if score_values[index] > 0]

    def retrieve(self, query: str) -> dict[str, Any]:
        documents = self.search(query)
        sources = [
            {
                "source": document.metadata.get("source", "unknown"),
                "chunk": document.metadata.get("chunk"),
            }
            for document in documents
        ]
        return {
            "query": query,
            "sources": sources,
            "context": "\n\n".join(document.page_content for document in documents),
        }


def default_knowledge_base() -> MetricKnowledgeBase:
    return MetricKnowledgeBase(Path(__file__).resolve().parent / "knowledge")

