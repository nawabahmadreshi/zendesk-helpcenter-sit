import asyncio
from app.ai_server import direct_search, AskRequest, PageContext

async def main():
    req = AskRequest(
        question="User Expiry",
        page_context=PageContext(
            page_title="",
            url_path="/",
            integration_id="None",
            product_version="v14"
        ),
        article_filter="site_ca6ca3774b9f" # Guest Account Management Setup Guide
    )
    
    print("Testing direct_search for zendesk configuration steps...")
    res = await direct_search(req)
    
    # Depending on how the model is returned, it might be dict or Pydantic
    results = res.results if hasattr(res, 'results') else res.get('results', [])
    
    if results:
        for r in results:
            title = r.get('article_title', 'Unknown Title')
            text = r.get('chunk_text', '')
            print(f"- {title}")
            print(f"  text len: {len(text)}")
            if len(text) < 10:
                print(f"  [WARNING] text is almost empty: {repr(text)}")
            else:
                print(f"  [TEXT] {text[:500]}...\n")
    else:
        print("Empty results.")

if __name__ == "__main__":
    asyncio.run(main())
