import asyncio
from app.ai_server import direct_search, AskRequest, PageContext

async def main():
    req = AskRequest(
        question="GAM-Draft",
        page_context=PageContext(
            page_title="",
            url_path="/",
            integration_id="None",
            product_version="v14"
        )
    )
    
    print("Testing direct_search for GAM-Draft...")
    res = await direct_search(req)
    
    print(f"Results returned: {len(res.results) if res.results else 0}")
    if res.results:
        for r in res.results:
            title = r.get('article_title', 'Unknown Title')
            text = r.get('chunk_text', '')
            article_id = r.get('article_id', '')
            print(f"- {title} (id: {article_id})")
            if 'gam-draft' in title.lower():
                print(f"  FOUND IT! text len: {len(text)}")
                print(f"  [TEXT] {text[:500]}...\n")
                
    else:
        print("Empty results.")
        if res.clarification_needed:
            print(f"Did you mean: {[c.title for c in (res.chips or [])]}")

if __name__ == "__main__":
    asyncio.run(main())
