import asyncio
from dotenv import load_dotenv

load_dotenv()
from sqlalchemy import text

from src.shared.database import engine

QUERY = """
SELECT
    d.id,
    d.source_type,
    d.filename,
    d.processing_status,
    d.content_hash,
    d.storage_path,
    j.stage AS job_stage,
    j.error_detail,
    (SELECT length(text) FROM chunks WHERE document_id = d.id ORDER BY position ASC LIMIT 1) AS first_chunk_len,
    (SELECT count(*) FROM chunks WHERE document_id = d.id) AS chunk_count
FROM documents d
LEFT JOIN ingestion_jobs j ON j.document_id = d.id
ORDER BY d.created_at DESC
LIMIT 10
"""


async def main() -> None:
    async with engine.connect() as conn:
        r = await conn.execute(text(QUERY))
        rows = r.fetchall()
        for row in rows:
            print(dict(row._mapping))


asyncio.run(main())