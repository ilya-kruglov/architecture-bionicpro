import redis
import os

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))