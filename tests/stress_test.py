import asyncio
import aiohttp
import time
import statistics
import random

async def simulate_user(session, user_id):
    """Simulates a single user asking a question."""
    payload = {
        "question": random.choice([
            "How do I setup Okta?",
            "What is the difference between v11 and v14?",
            "How to fix 404 error in Zendesk?",
            "Show me the release notes for latest version",
            "How do I rotate my API key?"
        ]),
        "user_id": f"user_{user_id}",
        "page_context": {
            "page_title": "Setup Guide",
            "url_path": "/setup"
        }
    }
    
    start = time.time()
    try:
        async with session.post("http://localhost:8000/api/help/ask", json=payload) as resp:
            status = resp.status
            await resp.json()
            latency = (time.time() - start) * 1000
            return status, latency
    except Exception as e:
        return 500, 0

async def run_stress_test(concurrency=10, total_calls=50):
    print(f"--- Starting Stress Test (Concurrency: {concurrency}, Total: {total_calls}) ---")
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(total_calls):
            tasks.append(simulate_user(session, i))
            if len(tasks) >= concurrency:
                # Simple batching for concurrency control
                results = await asyncio.gather(*tasks)
                tasks = []
                
        if tasks:
            results += await asyncio.gather(*tasks)

    latencies = [r[1] for r in results if r[0] == 200]
    errors = [r for r in results if r[0] != 200]
    
    print("\n--- RESULTS ---")
    print(f"Total Calls:   {total_calls}")
    print(f"Success Rate:  {len(latencies)/total_calls * 100}%")
    print(f"Error Count:   {len(errors)}")
    
    if latencies:
        print(f"P50 Latency:   {statistics.median(latencies):.2f}ms")
        print(f"P95 Latency:   {statistics.quantiles(latencies, n=20)[18]:.2f}ms")
        print(f"Max Latency:   {max(latencies):.2f}ms")

if __name__ == "__main__":
    asyncio.run(run_stress_test(concurrency=5, total_calls=20))
