"""Rule-level TF-IDF retrieval with calibrated relevance rejection."""

from pathlib import Path
import re

from langchain_core.documents import Document
from sklearn.feature_extraction.text import TfidfVectorizer


# Calibrated with tests/fixtures/rule_queries.json, see docs/stage-c-validation.md.
MIN_RELEVANCE = 0.13
RULE_HEADER = re.compile(r"^## (CS-\d{3}) \| (.+)$", re.MULTILINE)


class MetricKnowledgeBase:
    def __init__(self, knowledge_dir, top_k=4, min_relevance=MIN_RELEVANCE):
        self.knowledge_dir = Path(knowledge_dir)
        self.top_k = top_k
        self.min_relevance = min_relevance
        self.documents = self._load_documents()
        if not self.documents:
            raise ValueError(f"No versioned rules found in {self.knowledge_dir}")
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform([document.page_content for document in self.documents])
        self.by_id = {document.metadata["rule_id"]: document for document in self.documents}
        if len(self.by_id) != len(self.documents):
            raise ValueError("规则编号不能重复")

    def _load_documents(self):
        documents = []
        for path in sorted(self.knowledge_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            headers = list(RULE_HEADER.finditer(text))
            for index, header in enumerate(headers):
                end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
                original = text[header.start():end].strip()
                metric = re.search(r"^指标：(.+)$", original, re.MULTILINE)
                version = re.search(r"^版本：(.+)$", original, re.MULTILINE)
                if not metric or not version:
                    raise ValueError(f"规则 {header[1]} 缺少指标或版本")
                documents.append(Document(page_content=original, metadata={
                    "rule_id": header[1], "title": header[2], "version": version[1].strip(),
                    "metric_ids": [value.strip() for value in metric[1].split(",")],
                    "source": path.relative_to(self.knowledge_dir.parent).as_posix(),
                    "line": text[:header.start()].count("\n") + 1,
                    "chunk": len(documents) + 1,
                }))
        return documents

    def scored_rules(self, query):
        if not query or not query.strip():
            return []
        scores = (self.matrix @ self.vectorizer.transform([query.strip()]).T).toarray().ravel()
        order = sorted(range(len(scores)), key=lambda index: float(scores[index]), reverse=True)
        return [(self.documents[index], float(scores[index])) for index in order]

    def search(self, query):
        return [document for document, score in self.scored_rules(query)[:self.top_k] if score >= self.min_relevance]

    def retrieve(self, query):
        hits = [{**document.metadata, "score": round(score, 6), "text": document.page_content}
                for document, score in self.scored_rules(query)[:self.top_k] if score >= self.min_relevance]
        return {"query": query, "status": "matched" if hits else "not_found",
                "message": "找到相关规则" if hits else "未找到规则",
                "threshold": self.min_relevance,
                "sources": [{key: value for key, value in hit.items() if key not in {"text", "score"}} for hit in hits],
                "hits": hits, "context": "\n\n".join(hit["text"] for hit in hits)}

    def rule(self, rule_id):
        document = self.by_id.get(rule_id)
        return {**document.metadata, "text": document.page_content} if document else None


def default_knowledge_base():
    return MetricKnowledgeBase(Path(__file__).resolve().parent / "knowledge")
