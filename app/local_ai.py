"""Embedded local AI engine using llama-cpp-python.

No external services required — the model runs entirely inside the app process.

Model management:
- Default: Phi-3-mini-4k-instruct-q4.gguf (~2.2 GB, fast, high quality)
- Stored in: storage/models/
- Auto-downloaded from HuggingFace on first use via /api/local-ai/download

Smart fallback modes (set AI_FALLBACK_MODE in .env or admin panel):
  'auto'       – use Gemini, auto-fallback to local on any API error
  'local_only' – always local, zero cloud cost
  'gemini'     – always Gemini (default behaviour, no change)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

DEFAULT_MODEL_REPO = "microsoft/Phi-3-mini-4k-instruct-gguf"
DEFAULT_MODEL_FILE = "Phi-3-mini-4k-instruct-q4.gguf"
DEFAULT_CTX = 4096
DEFAULT_THREADS = 4

_llm: Optional[Any] = None
_model_path_cached: Optional[Path] = None


def _models_dir() -> Path:
    try:
        from config import Config
        return Config().STORAGE_DIR / "models"
    except Exception:
        return Path("storage/models")


def install_info() -> Dict[str, Any]:
    """Return install status without loading the model."""
    mp = _models_dir() / DEFAULT_MODEL_FILE
    try:
        import llama_cpp
        cpp_installed = True
        cpp_version = getattr(llama_cpp, "__version__", "unknown")
    except ImportError:
        cpp_installed = False
        cpp_version = None

    return {
        "llama_cpp_installed": cpp_installed,
        "llama_cpp_version": cpp_version,
        "model_file": str(mp),
        "model_exists": mp.exists(),
        "model_size_mb": round(mp.stat().st_size / 1_048_576, 1) if mp.exists() else 0,
        "models_dir": str(_models_dir()),
        "default_model_repo": DEFAULT_MODEL_REPO,
        "default_model_file": DEFAULT_MODEL_FILE,
    }


def is_ready() -> bool:
    """True if llama-cpp-python is installed AND the model file exists."""
    info = install_info()
    return info["llama_cpp_installed"] and info["model_exists"]


def download_model() -> Dict[str, Any]:
    """Download the default model from HuggingFace if not present."""
    target = _models_dir() / DEFAULT_MODEL_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        return {"ok": True, "message": "Model already present.", "path": str(target)}

    # Try huggingface_hub first (cleanest)
    try:
        from huggingface_hub import hf_hub_download
        log.info("Downloading via huggingface_hub...")
        dl = hf_hub_download(
            repo_id=DEFAULT_MODEL_REPO,
            filename=DEFAULT_MODEL_FILE,
            local_dir=str(target.parent),
        )
        return {"ok": True, "message": "Download complete.", "path": dl}
    except ImportError:
        pass
    except Exception as e:
        return {"ok": False, "message": f"huggingface_hub download failed: {e}"}

    # Fallback: requests streaming download
    try:
        import requests
        url = f"https://huggingface.co/{DEFAULT_MODEL_REPO}/resolve/main/{DEFAULT_MODEL_FILE}"
        log.info(f"Downloading from {url}...")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(target, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        return {"ok": True, "message": "Download complete.", "path": str(target)}
    except Exception as e:
        return {"ok": False, "message": f"Download failed: {e}", "path": str(target)}


def get_llm() -> Any:
    """Return a cached Llama instance, loading on first call."""
    global _llm, _model_path_cached
    target = _models_dir() / DEFAULT_MODEL_FILE

    if _llm is not None and _model_path_cached == target:
        return _llm

    from llama_cpp import Llama
    log.info(f"Loading local model from {target} ...")
    _llm = Llama(
        model_path=str(target),
        n_ctx=DEFAULT_CTX,
        n_threads=DEFAULT_THREADS,
        n_gpu_layers=-1,   # Metal (Mac) or CUDA auto-detected
        verbose=False,
    )
    _model_path_cached = target
    log.info("Local model ready.")
    return _llm


def chat(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> Dict[str, Any]:
    """Run chat completion locally.

    Returns agent-compatible dict:
      { response, tokens_in, tokens_out, tokens_total }
    """
    llm = get_llm()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    text = out["choices"][0]["message"]["content"]
    usage = out.get("usage", {})
    t_in  = usage.get("prompt_tokens", 0)
    t_out = usage.get("completion_tokens", 0)
    return {
        "response": text,
        "tokens_in": t_in,
        "tokens_out": t_out,
        "tokens_total": t_in + t_out,
        "_provider": "local",
    }
