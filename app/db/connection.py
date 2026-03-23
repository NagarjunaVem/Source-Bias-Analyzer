import asyncpg

async def get_pool(dsn: str):
    return await asyncpg.create_pool(dsn)