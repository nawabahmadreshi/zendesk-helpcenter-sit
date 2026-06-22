import json
import hashlib
from typing import Optional, Any, Dict
from config import Config

class SemanticCache:
    """
    A caching layer for AI responses using Redis.
    Provides basic exact-key caching with a TTL.
    In a SOTA implementation, this would use RedisVL for vector-based similarity,
    but we implement a robust exact-match version with local fallback.
    """
    def __init__(self):
        cfg = Config()
        self.enabled = cfg.SEMANTIC_CACHE_ENABLED
        self.ttl = cfg.CACHE_TTL
        self._redis = None
        self._local_cache = {} # Fallback

        if self.enabled:
            try:
                import redis
                self._redis = redis.Redis(
                    host=cfg.REDIS_HOST,
                    port=cfg.REDIS_PORT,
                    password=cfg.REDIS_PASSWORD,
                    db=cfg.REDIS_DB,
                    socket_timeout=1
                )
                self._redis.ping()
            except Exception as e:
                print(f"WARNING: Redis connection failed: {e}. Falling back to local cache.")
                self._redis = None

    def _get_key(self, query: str) -> str:
        # Normalize and hash the query
        return f"sota_cache:{hashlib.md5(query.strip().lower().encode()).hexdigest()}"

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        
        key = self._get_key(query)
        try:
            if self._redis:
                data = self._redis.get(key)
                if data:
                    return json.loads(data)
            else:
                return self._local_cache.get(key)
        except Exception as e:
            print(f"DEBUG: Cache get error: {e}")
        return None

    def set(self, query: str, response: str, metadata: Dict[str, Any] = None):
        if not self.enabled:
            return
        
        key = self._get_key(query)
        val = {
            "response": response,
            "metadata": metadata or {},
            "ts": __import__('time').time()
        }
        
        try:
            dump = json.dumps(val)
            if self._redis:
                self._redis.setex(key, self.ttl, dump)
            else:
                self._local_cache[key] = val
        except Exception as e:
            print(f"DEBUG: Cache set error: {e}")

    def clear(self):
        try:
            if self._redis:
                keys = self._redis.keys("sota_cache:*")
                if keys:
                    self._redis.delete(*keys)
            self._local_cache.clear()
        except:
            pass
