import asyncio
from app.ai_server import direct_search, AskRequest
from pydantic import BaseModel
class PageContext(BaseModel):
    page_title: str = ""
    url_path: str = ""
    integration_id: str = "None"
    product_version: str = "v14"
req = AskRequest(question="GAM", page_context=PageContext())
async def main():
    res = await direct_search(req)
    print("Clarification needed:", res.clarification_needed)
    if res.results:
        print("Results found:", len(res.results))

asyncio.run(main())
