import asyncio
import json
import time

import httpx
import websockets

base_url = "http://127.0.0.1:8000/api"
workspace_id = "00000000-0000-0000-0000-000000000000"

async def test_upload_and_chat():
    print("Uploading file...")
    try:
        with open("../../docs/test.pdf", "rb") as f:
            response = httpx.post(
                f"{base_url}/ingestion/upload",
                files={"file": f},
                data={"source_type": "pdf"},
                headers={"x-workspace-id": workspace_id},
                timeout=60.0
            )
        print("Upload response:", response.status_code, response.text)
        if response.status_code != 200:
            return
        data = response.json()
        job_id = data["job_id"]
    except Exception as e:
        print(f"Failed to upload: {e}")
        return
    
    print("Polling job status...")
    while True:
        job_res = httpx.get(f"{base_url}/ingestion/jobs/{job_id}", headers={"x-workspace-id": workspace_id})
        job_data = job_res.json()
        print("Job status:", job_data)
        if job_data["stage"] == "done":
            break
        elif job_data["stage"] == "failed":
            print("Ingestion failed!")
            return
        time.sleep(2)
        
    print("Connecting to chat...")
    uri = "ws://127.0.0.1:8000/api/research/ws"
    async with websockets.connect(uri, additional_headers={"x-workspace-id": workspace_id}) as ws:
        question = 'chapter 4. Aristocracy, Democracy, and System Design'
        print(f"Sending question: {question}")
        await ws.send(json.dumps({"question": question}))
        
        while True:
            msg = await ws.recv()
            print("Received:", msg)
            data = json.loads(msg)
            if data.get("type") in ["answer", "error"]:
                break

asyncio.run(test_upload_and_chat())
