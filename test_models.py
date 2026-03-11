import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

models_to_test = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.0-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest"
]

for model in models_to_test:
    try:
        response = client.models.generate_content(
            model=model,
            contents="test",
            config=types.GenerateContentConfig(max_output_tokens=10)
        )
        print(f"✅ {model} works!")
    except Exception as e:
        err_msg = str(e).replace('\n', ' ')
        print(f"❌ {model} failed: {err_msg[:100]}...")

