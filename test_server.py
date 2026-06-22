import requests
import time

max_retries = 10
for i in range(max_retries):
    try:
        response = requests.post(
            "http://localhost:8000/api/chat",
            json={"messages": [{"role": "user", "content": "How do I configure ADP WFN integration?"}]},
            timeout=10
        )
        print("Success:", response.json().get('response', '')[:200])
        break
    except Exception as e:
        print(f"Waiting for server... {e}")
        time.sleep(2)
