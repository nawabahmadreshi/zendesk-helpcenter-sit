import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer
from typing import Dict, List

class SpladeEncoder:
    """
    Implements SPLADE (Sparse Lexical and Expansion Model) for Neural Sparse Retrieval.
    Used to mathematically extract and inject missing synonyms into chunks.
    """
    def __init__(self, model_id="naver/splade-cocondenser-ensembledistil"):
        try:
            self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            print(f"DEBUG SPLADE: Loading {model_id} on {self.device}...")
            self.tokenizer = AutoTokenizer.from_pretrained(model_id)
            self.model = AutoModelForMaskedLM.from_pretrained(model_id).to(self.device)
            self.model.eval()
            self._is_ready = True
            print("DEBUG SPLADE: Loaded successfully!")
        except Exception as e:
            print(f"DEBUG SPLADE: Failed to load model: {e}")
            self._is_ready = False

    def get_sparse_dict(self, text: str) -> Dict[str, float]:
        """Returns a dict of token -> mathematical weight."""
        if not self._is_ready or not text.strip():
            return {}
            
        inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512).to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        
        # SPLADE pooling (max over sequence length)
        logits = outputs.logits
        attention_mask = inputs["attention_mask"].unsqueeze(-1)
        relu_logits = torch.relu(logits) * attention_mask
        sparse_vec, _ = torch.max(relu_logits, dim=1)
        sparse_vec = sparse_vec.squeeze(0)
        
        # Extract non-zero weights
        indices = sparse_vec.nonzero().squeeze(-1)
        weights = sparse_vec[indices]
        
        result = {}
        for idx, weight in zip(indices, weights):
            token = self.tokenizer.decode([idx]).strip()
            # filter out subwords/special tokens
            if len(token) > 2 and not token.startswith("[") and token.isalpha():
                result[token] = float(weight.item())
                
        return result

    def expand_text(self, text: str, top_k: int = 30) -> str:
        """
        Takes raw text and uses SPLADE to find the top mathematically inferred 
        synonyms and related concepts. Returns the original text PLUS the synonyms.
        This enables BM25 to act as a Neural Retriever.
        """
        sparse_dict = self.get_sparse_dict(text)
        if not sparse_dict:
            return text
            
        # Sort by weight descending
        sorted_tokens = sorted(sparse_dict.items(), key=lambda x: x[1], reverse=True)
        
        # Take the highest weighted tokens (that aren't already explicitly in the text to save space)
        # Actually, repeating them is fine for BM25 (increases term frequency).
        expansion_words = []
        for token, weight in sorted_tokens[:top_k]:
            expansion_words.append(token)
            
        expansion_str = " ".join(expansion_words)
        return text + "\n" + expansion_str

# Global Singleton to prevent memory leaks
_GLOBAL_SPLADE = None

def get_splade() -> SpladeEncoder:
    global _GLOBAL_SPLADE
    if _GLOBAL_SPLADE is None:
        _GLOBAL_SPLADE = SpladeEncoder()
    return _GLOBAL_SPLADE
