from redis.asyncio import Redis


def create_redis(redis_url: str) -> Redis:
    # Connections are opened lazily on first use.
    return Redis.from_url(redis_url, decode_responses=True)
