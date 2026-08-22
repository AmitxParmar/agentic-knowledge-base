import sys

from chonkie import CodeChunker
from src.ingestion.extractors import ExtractedContent
from src.ingestion.chunker import chunk_document

NESTING = int(sys.argv[1]) if len(sys.argv) > 1 else 200

tests = {
    "deep_js": "const x = " + "[" * NESTING + "0" + "]" * NESTING,
    "deep_py_brackets": "x = " + "[" * NESTING + "0" + "]" * NESTING,
    "deep_py_indent": "\n".join("    " * i + "if True:" for i in range(NESTING)),
    "big_js_repeat": ("const longName = {a: 1, b: (c) => c * 2, d: [1,2,3]};\n" * 3000),
}

for name, text in tests.items():
    print(f"--- {name} (len={len(text)}) ---", flush=True)
    try:
        result = chunk_document(ExtractedContent(text=text, doc_metadata={}), source_type="repo")
        print(f"ok, {len(result)} chunks", flush=True)
    except Exception as exc:
        print(f"exception: {type(exc).__name__}: {exc}", flush=True)

print("DONE", flush=True)