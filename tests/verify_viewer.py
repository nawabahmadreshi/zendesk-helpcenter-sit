import requests
import sys
from pathlib import Path

# Add project root to path to access config
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from config import Config

def test_viewer():
    cfg = Config()
    base_url = "http://localhost:8000"
    
    # We need a valid article_id to test. Let's look in the processed directory.
    articles_dir = cfg.processed_dir / "articles" / "integration"
    html_files = list(articles_dir.glob("*.html"))
    
    if not html_files:
        print("❌ No processed articles found to test with.")
        return False
    
    # Extract article ID from filename (e.g., ..._12345.html)
    test_file = html_files[0]
    article_id = test_file.stem.split("_")[-1]
    
    print(f"Testing local viewer for article_id: {article_id}")
    
    try:
        # Check /health first
        r_health = requests.get(f"{base_url}/health")
        if r_health.status_code != 200:
            print(f"❌ Server not running or unhealthy at {base_url}")
            return False
            
        # Test /article/{article_id}
        url = f"{base_url}/article/{article_id}"
        print(f"Requesting: {url}")
        r = requests.get(url)
        
        if r.status_code == 200:
            print("✅ Status 200 OK")
            content = r.text
            
            # Verify basic elements
            if "<link rel=\"stylesheet\" href=\"/static/viewer.css\">" in content:
                print("✅ viewer.css link found")
            else:
                print("❌ viewer.css link NOT found")
                
            if "Aquera" in content and "Intelligence" in content:
                print("✅ Branding 'Aquera Intelligence' found")
            else:
                print("❌ Branding NOT found")
                
            if f"ID: {article_id}" in content:
                print("✅ Article ID found in meta section")
            else:
                print("❌ Article ID NOT found in meta section")
                
            if "View in Zendesk" in content:
                print("✅ Link to Zendesk found")
            else:
                print("❌ Link to Zendesk NOT found")
                
            return True
        else:
            print(f"❌ Failed with status {r.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
        return False

if __name__ == "__main__":
    success = test_viewer()
    sys.exit(0 if success else 1)
