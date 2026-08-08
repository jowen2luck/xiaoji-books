"""Embedding Model abstraction (M5).

Provides a swappable interface for generating text embeddings.
Current implementation: bge-small-zh-v1.5 (local, offline).

Interface:
    model = EmbeddingModel.create("bge-small-zh-v1.5")
    vectors = model.encode(["text1", "text2", ...])

Usage:
    python scripts/embedding/model.py --test "测试文本"
"""
import os
import sys
import time
from pathlib import Path
from typing import Optional


class EmbeddingModel:
    """Abstract embedding model interface.
    
    Implement must provide:
        - dim: vector dimensionality
        - encode(texts: list[str]) -> list[list[float]]
    """
    
    def __init__(self, model_name: str, model_path: Optional[str] = None):
        self.model_name = model_name
        self._model_path = model_path
        self._model = None
        self.dim = 0
    
    def load(self):
        """Load model into memory (lazy — called on first encode)."""
        raise NotImplementedError
    
    def encode(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.
        
        Returns: list of float vectors, one per input text.
        """
        raise NotImplementedError
    
    @staticmethod
    def create(model_name: str, **kwargs) -> "EmbeddingModel":
        """Factory method to create model by name."""
        if model_name == "bge-small-zh-v1.5" or model_name.startswith("bge-small"):
            return BGESmallZhModel(model_name=model_name, **kwargs)
        elif model_name.startswith("sentence-transformers/") or model_name.startswith("st/"):
            return SentenceTransformerModel(model_name=model_name, **kwargs)
        elif model_name == "random" or model_name == "mock":
            return MockEmbeddingModel(dim=kwargs.get("dim", 512))
        else:
            raise ValueError(f"Unknown model: {model_name}")


class BGESmallZhModel(EmbeddingModel):
    """BAAI/bge-small-zh-v1.5 via sentence-transformers."""
    
    def __init__(self, model_name: str = "bge-small-zh-v1.5", model_path: Optional[str] = None):
        super().__init__(model_name, model_path)
        self.dim = 512
    
    def load(self):
        if self._model is not None:
            return
        
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
        
        # Try local path first, then download
        if self._model_path and Path(self._model_path).exists():
            self._model = SentenceTransformer(self._model_path)
        else:
            self._model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        
        print(f"Loaded {self.model_name} (dim={self.dim})", file=sys.stderr)
    
    def encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self.load()
        
        # BGE models benefit from a retrieval instruction prefix
        # For Chinese: "为这个句子生成表示以用于相关文章检索："
        instruction = "为这个句子生成表示以用于相关文章检索："
        instructioned_texts = [f"{instruction}{t}" for t in texts]
        
        import numpy as np
        embeddings = self._model.encode(
            instructioned_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()


class SentenceTransformerModel(EmbeddingModel):
    """Generic sentence-transformers model (configurable)."""
    
    def __init__(self, model_name: str, model_path: Optional[str] = None, dim: int = 768):
        super().__init__(model_name, model_path)
        self.dim = dim
    
    def load(self):
        if self._model is not None:
            return
        
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("sentence-transformers not installed.")
        
        name = self._model_path or self.model_name.replace("sentence-transformers/", "").replace("st/", "")
        self._model = SentenceTransformer(name)
        self.dim = self._model.get_sentence_embedding_dimension()
    
    def encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self.load()
        import numpy as np
        embeddings = self._model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True
        )
        return embeddings.tolist()


class MockEmbeddingModel(EmbeddingModel):
    """Deterministic mock for testing — random but reproducible vectors."""
    
    def __init__(self, dim: int = 512, seed: int = 42):
        super().__init__("mock")
        self.dim = dim
        self._seed = seed
    
    def load(self):
        pass
    
    def encode(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        import math
        
        results = []
        for text in texts:
            # Deterministic hash-based vector
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()
            vec = []
            for i in range(0, self.dim * 4, 4):
                val = int(h[i % len(h): (i % len(h)) + 4], 16) / 0xFFFFFFFF
                vec.append(val * 2 - 1)  # -1 to 1
            # Normalize
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results


def main():
    """Quick test."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", default="测试中文embedding")
    parser.add_argument("--model", default="mock")
    args = parser.parse_args()
    
    model = EmbeddingModel.create(args.model)
    t0 = time.time()
    vectors = model.encode([args.test])
    elapsed = time.time() - t0
    
    print(f"Model: {args.model}, dim={len(vectors[0])}")
    print(f"Input: {args.test}")
    print(f"Output: [{', '.join(f'{v:.4f}' for v in vectors[0][:5])}...]")
    print(f"Time: {elapsed*1000:.1f}ms")


if __name__ == "__main__":
    main()
