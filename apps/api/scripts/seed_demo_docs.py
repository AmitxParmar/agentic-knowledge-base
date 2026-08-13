"""
Seed demo documents locally.
Bypasses Render's resource constraints by running the full pipeline locally:
extract (pypdf) → chunk (simple) → embed (Cohere) → persist (Neon + B2).
"""
import asyncio
import re
import uuid
from pathlib import Path

import asyncpg
import boto3
from pypdf import PdfReader

from app.settings import settings

WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
PDF_DIR = Path(__file__).parent
PDF_FILES = [
    "great-front-end-guide.pdf",
    "Loop-Engineering-IEEE.pdf",
    "Best AI Agent Courses You Must Know in 2026.pdf",
]

CHUNK_SIZE = 600
CHUNK_OVERLAP = 60


def simple_chunk(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and len(p.strip()) > 20]

    if not paragraphs:
        paragraphs = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20]

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > CHUNK_SIZE * 2:
            if current:
                chunks.append(current.strip())
                current = ""
            words = para.split()
            buf = []
            length = 0
            for w in words:
                buf.append(w)
                length += len(w) + 1
                if length >= CHUNK_SIZE:
                    chunks.append(" ".join(buf))
                    buf = buf[max(0, len(buf) - int(len(buf) * CHUNK_OVERLAP / CHUNK_SIZE)):]
                    length = sum(len(x) + 1 for x in buf)
            if buf:
                current = " ".join(buf) + " "
        elif current and len(current) + len(para) > CHUNK_SIZE * 2:
            chunks.append(current.strip())
            current = para + "\n\n"
        else:
            current += para + "\n\n"

    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 20]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    import cohere
    client = cohere.AsyncClientV2(api_key=settings.COHERE_API_KEY)
    all_vectors = []
    batch_size = 64
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = await client.embed(
            model=settings.COHERE_EMBED_MODEL,
            input_type="search_document",
            texts=batch,
            embedding_types=["float"],
        )
        all_vectors.extend([list(v) for v in resp.embeddings.float_])
    return all_vectors


def upload_to_b2(file_path: Path, key: str) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name=settings.R2_REGION,
    )
    client.upload_file(str(file_path), settings.R2_BUCKET, key)


async def main() -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    try:
        for pdf_name in PDF_FILES:
            pdf_path = PDF_DIR / pdf_name
            if not pdf_path.exists():
                print(f"SKIP {pdf_name} (not found)")
                continue

            print(f"Processing: {pdf_name}")
            doc_id = uuid.uuid4()
            storage_key = f"uploads/{WORKSPACE_ID}/{doc_id}_{pdf_name}"

            print("  -> extracting text...")
            reader = PdfReader(str(pdf_path))
            text = ""
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
            print(f"     extracted {len(text)} chars, {len(reader.pages)} pages")

            print("  -> uploading to B2...")
            await asyncio.to_thread(upload_to_b2, pdf_path, storage_key)

            print("  -> chunking...")
            chunks = simple_chunk(text)
            print(f"     {len(chunks)} chunks")

            print("  -> embedding via Cohere...")
            vectors = await embed_texts(chunks)
            print(f"     {len(vectors)} vectors")

            print("  -> writing to Neon...")
            await conn.execute(
                """INSERT INTO documents (id, workspace_id, source_type, filename, source_ref, storage_path, processing_status, created_at)
                   VALUES ($1, $2, 'pdf', $3, $4, $5, 'done', now())""",
                str(doc_id), str(WORKSPACE_ID), pdf_name, storage_key, storage_key,
            )

            for i, (chunk_text, vector) in enumerate(zip(chunks, vectors)):
                chunk_id = uuid.uuid4()
                await conn.execute(
                    """INSERT INTO chunks (id, document_id, position, text, turbovec_id, embedding, chunk_metadata, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, now())""",
                    str(chunk_id), str(doc_id), i, chunk_text,
                    str(chunk_id), str(vector), f'{{"page_count": {len(reader.pages)}, "chunk_index": {i}}}',
                )

            print(f"  DONE: {pdf_name} ({len(chunks)} chunks indexed)\n")
    finally:
        await conn.close()
    print("All demo documents seeded.")


if __name__ == "__main__":
    asyncio.run(main())
