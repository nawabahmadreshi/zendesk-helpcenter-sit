import time
import asyncio
import functools
import random
from typing import Any, Callable, TypeVar, Union, Optional

T = TypeVar("T")

def retry_with_backoff(
    retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exponential: bool = True
):
    """
    Decorator for retrying functions that might hit Rate Limits (429).
    Exposes a unified interface for both Gemini and OpenAI/OpenRouter errors.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_err: Optional[Exception] = None
            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    err_str = str(e).lower()
                    # Catch common rate limit indicators
                    is_rate_limit = any(indicator in err_str for indicator in [
                        "429", "resource_exhausted", "rate_limit", "quota exceeded"
                    ])
                    
                    if not is_rate_limit or attempt == retries:
                        raise e
                    
                    delay = base_delay * (2 ** attempt if exponential else 1)
                    delay = min(delay, max_delay)
                    delay += random.uniform(0, 1) # Add jitter
                    
                    print(f"RATE LIMIT DETECTED: {e}. Retrying in {delay:.1f}s (Attempt {attempt + 1}/{retries})...")
                    time.sleep(delay)
                    last_err = e
            if last_err:
                raise last_err
            raise Exception("Unknown retry failure")
        return wrapper
    return decorator

async def async_retry_with_backoff(
    retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exponential: bool = True
):
    """Async version of the backoff retry."""
    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_err: Optional[Exception] = None
            for attempt in range(retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    err_str = str(e).lower()
                    is_rate_limit = any(indicator in err_str for indicator in [
                        "429", "resource_exhausted", "rate_limit", "quota exceeded"
                    ])
                    
                    if not is_rate_limit or attempt == retries:
                        raise e
                    
                    delay = base_delay * (2 ** attempt if exponential else 1)
                    delay = min(delay, max_delay)
                    delay += random.uniform(0, 1)
                    
                    print(f"RATE LIMIT DETECTED (Async): {e}. Retrying in {delay:.1f}s (Attempt {attempt + 1}/{retries})...")
                    await asyncio.sleep(delay)
                    last_err = e
            if last_err:
                raise last_err
            raise Exception("Unknown async retry failure")
        return wrapper
    return decorator

def run_simple_llm_call(
    prompt: str,
    system_instruction: str = "You are a helpful assistant.",
    max_tokens: int = 500,
    temperature: float = 0.3,
    config: Any = None,
    prioritize_ollama: bool = False
) -> str:
    """
    Executes a single-turn LLM call with provider-agnostic routing and fallback.
    Useful for tasks like Query Rewriting, HyDE, and Reranking.
    """
    if config is None:
        from config import Config
        config = Config()

    provider = config.AI_PROVIDER
    fallback_mode = config.AI_FALLBACK_MODE
    
    # If explicitly asked to prioritize ollama (e.g. for local-first sessions)
    if prioritize_ollama or provider == "ollama":
        effective_chain = ["ollama", "gemini", "openrouter"]
    else:
        effective_chain = [provider, "gemini", "openrouter", "ollama"]
    
    # Remove duplicates but keep order
    seen = set()
    providers_to_try = []
    for p in effective_chain:
        if p not in seen:
            providers_to_try.append(p)
            seen.add(p)

    def _attempt_call(prov: str) -> str:
        if prov == "gemini":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=temperature
                )
            )
            return response.text.strip()
            
        elif prov in ("openrouter", "openai"):
            from openai import OpenAI
            client = OpenAI(
                api_key=config.OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
            )
            resp = client.chat.completions.create(
                model=config.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                extra_headers={
                    "HTTP-Referer": config.OPENROUTER_SITE_URL,
                    "X-Title": "Aquera AI Help",
                }
            )
            content = resp.choices[0].message.content
            return content.strip() if content else ""
            
        elif prov == "ollama":
            from openai import OpenAI
            client = OpenAI(base_url=f"{config.OLLAMA_BASE_URL}/v1", api_key="ollama")
            resp = client.chat.completions.create(
                model=config.OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )
            content = resp.choices[0].message.content
            return content.strip() if content else ""
        elif prov == "claude_proxy":
            from openai import OpenAI
            client = OpenAI(base_url=config.CLAUDE_PROXY_URL, api_key="sk-ant-proxy-local")
            resp = client.chat.completions.create(
                model="claude-sonnet-4-6", # ID matches proxy config
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )
            content = resp.choices[0].message.content
            return content.strip() if content else ""
        elif prov == "openrouter":
            from openai import OpenAI
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=config.OPENROUTER_API_KEY,
                default_headers={
                    "HTTP-Referer": config.OPENROUTER_SITE_URL,
                    "X-Title": "Aquera AI Help",
                }
            )
            resp = client.chat.completions.create(
                model=config.OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )
            content = resp.choices[0].message.content
            return content.strip() if content else ""
        elif prov == "nvidia":
            from openai import OpenAI
            client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=config.NVIDIA_API_KEY
            )
            resp = client.chat.completions.create(
                model=config.NVIDIA_MODEL,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )
            content = resp.choices[0].message.content
            return content.strip() if content else ""
        else:
            raise ValueError(f"Unknown AI Provider: {prov}")

    errors = []
    for current_prov in providers_to_try:
        try:
            return _attempt_call(current_prov)
        except Exception as e:
            print(f"Provider {current_prov} failed: {e}")
            errors.append(f"{current_prov}: {e}")
            if fallback_mode == "none" and current_prov == provider:
                break
    
    raise Exception(f"All LLM providers failed. Errors: {'; '.join(errors)}")
