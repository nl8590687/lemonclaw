# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
TF-IDF 记忆检索模块

- ``ChineseTokenizer``：jieba 分词（必选），import 失败时防御性回退到正则
- ``TFIDFRetriever``：TF-IDF + 余弦相似度，内存倒排索引
- ``MemorySearcher``：组合 TF-IDF，叠加时间衰减 + 重要性加权

为何必须 jieba：TF-IDF 靠词项区分度，中文按单字切分会使「的、是、不」等高频字
IDF 趋零、复合词（如「数据库」）被拆散，倒排索引退化为全量低分匹配。
"""

import math
import re
from collections import defaultdict
from datetime import datetime

from dao.memory import MemoryChunk


class ChineseTokenizer:
    """中文分词器：优先 jieba，不可用时回退到正则（英文按词、中文按单字）"""

    def __init__(self):
        try:
            import jieba
            self.jieba = jieba
            self.available = True
        except ImportError:  # 防御性回退，正常路径不应走到
            self.jieba = None
            self.available = False

    def tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        english_parts = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
        number_parts = re.findall(r"\d+", text)
        cleaned_text = re.sub(r"[a-zA-Z0-9_]+", " ", text)
        if self.available:
            chinese_parts = list(self.jieba.cut_for_search(cleaned_text))
        else:
            chinese_parts = list(cleaned_text)
        tokens: list[str] = []
        for part in chinese_parts + english_parts + number_parts:
            part = part.strip()
            if part:
                tokens.append(part.lower())
        return tokens


class TFIDFRetriever:
    """TF-IDF + 余弦相似度检索器（内存倒排索引）"""

    def __init__(self):
        self.tokenizer = ChineseTokenizer()
        self.documents: dict[int, str] = {}
        self.doc_info: dict[int, dict] = {}
        self.idf: dict[str, float] = {}
        self.doc_count = 0
        self.next_doc_id = 1

    def add_document(self, content: str, metadata: dict | None = None) -> int:
        doc_id = self.next_doc_id
        self.documents[doc_id] = content
        self.doc_info[doc_id] = metadata or {}
        self.next_doc_id += 1
        self.doc_count += 1
        self._recompute_idf()
        return doc_id

    def clear(self):
        self.documents = {}
        self.doc_info = {}
        self.idf = {}
        self.doc_count = 0
        self.next_doc_id = 1

    def _recompute_idf(self):
        """重新计算 IDF（平滑：log(1 + N/(1+df))）"""
        if self.doc_count == 0:
            self.idf = {}
            return
        df: dict[str, int] = defaultdict(int)
        for doc in self.documents.values():
            for token in set(self.tokenizer.tokenize(doc)):
                df[token] += 1
        self.idf = {token: math.log(1 + self.doc_count / (1 + freq))
                    for token, freq in df.items()}

    def _compute_tfidf(self, text: str) -> dict[str, float]:
        tokens = self.tokenizer.tokenize(text)
        if not tokens:
            return {}
        tf: dict[str, int] = defaultdict(int)
        for t in tokens:
            tf[t] += 1
        max_freq = max(tf.values())
        return {t: (cnt / max_freq) * self.idf.get(t, 0.0) for t, cnt in tf.items()}

    @staticmethod
    def _cosine(vec1: dict[str, float], vec2: dict[str, float]) -> float:
        common = set(vec1) & set(vec2)
        if not common:
            return 0.0
        dot = sum(vec1[t] * vec2[t] for t in common)
        n1 = math.sqrt(sum(v * v for v in vec1.values()))
        n2 = math.sqrt(sum(v * v for v in vec2.values()))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float, dict]]:
        """返回 [(doc_id, score, metadata), ...]"""
        if self.doc_count == 0:
            return []
        qvec = self._compute_tfidf(query)
        scores: list[tuple[int, float]] = []
        for doc_id, doc in self.documents.items():
            sim = self._cosine(qvec, self._compute_tfidf(doc))
            if sim > 0:
                scores.append((doc_id, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [(d, s, self.doc_info[d]) for d, s in scores[:top_k]]


class MemorySearcher:
    """记忆搜索器：TF-IDF + 时间衰减 + 重要性加权"""

    def __init__(self):
        self.retriever = TFIDFRetriever()
        self.chunks: dict[int, MemoryChunk] = {}  # doc_id -> chunk

    def add_chunk(self, chunk: MemoryChunk) -> int:
        """添加记忆块到检索索引"""
        search_text = chunk.title + " " + chunk.content
        if chunk.keywords:
            search_text += " " + " ".join(chunk.keywords)
        metadata = {
            "chunk_id": chunk.id,
            "chunk_type": chunk.chunk_type,
            "importance": chunk.importance,
            "created_at": chunk.created_at,
            "access_count": chunk.access_count,
        }
        doc_id = self.retriever.add_document(search_text, metadata)
        self.chunks[doc_id] = chunk
        return doc_id

    def search(
        self,
        query: str,
        top_k: int = 5,
        time_decay_days: int = 30,
        importance_weight: float = 0.3,
    ) -> list[tuple[MemoryChunk, float]]:
        """搜索记忆，返回 [(chunk, final_score), ...]"""
        tfidf_results = self.retriever.search(query, top_k=top_k * 2)
        now = datetime.now()
        results: list[tuple[MemoryChunk, float]] = []
        for doc_id, tfidf_score, metadata in tfidf_results:
            # 时间权重（指数衰减）
            created_at = metadata.get("created_at")
            time_weight = 1.0
            if created_at:
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    except ValueError:
                        created_at = None
                if created_at:
                    days = (now - created_at).total_seconds() / 86400
                    time_weight = math.exp(-days / time_decay_days)
            # 重要性权重（1-10 归一化）
            importance_score = metadata.get("importance", 5) / 10.0
            final = (
                tfidf_score * (1 - importance_weight)
                + importance_score * importance_weight
            ) * time_weight
            chunk = self.chunks.get(doc_id)
            if chunk:
                results.append((chunk, final))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def clear(self):
        self.retriever = TFIDFRetriever()
        self.chunks = {}
