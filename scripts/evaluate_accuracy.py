#!/usr/bin/env python3
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path("/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync")
sys.path.insert(0, str(ROOT))

load_dotenv()

from config import Config
from app.lexical_search import LexicalIndex

# Mapping duplicate test folders to their real guide equivalent
def resolve_slug(slug: str) -> str:
    slug = slug.lower()
    # These directories are copies of ADP Workforce Now Configuration Guide
    if slug in ["nawab", "api-1", "validator-guide", "wfn-fix-tables", "gam-for-review"]:
        return "adp-workforce-now-configuration-guide"
    return slug

# Test suite of 15 queries across different integrations
TEST_SUITE = [
    {
        "query": "How do I generate an API token for Zendesk?",
        "expected": "zendesk-initial-setup-guide"
    },
    {
        "query": "What are the configuration steps for the Zapier connector?",
        "expected": "zapier-configuration-guide"
    },
    {
        "query": "How to setup a Palantir integration connector?",
        "expected": "palantir-configuration-guide"
    },
    {
        "query": "What are the prerequisites for ADP Workforce Now?",
        "expected": "adp-workforce-now-configuration-guide"
    },
    {
        "query": "How do I configure the HaloITSM connector basic details?",
        "expected": "haloitsm-initial-setup-guide"
    },
    {
        "query": "Front configuration guide user permissions",
        "expected": "front-configuration-guide"
    },
    {
        "query": "MongoDB Cloud Manager Okta partnership guide",
        "expected": "-okta-partnership-guide-mongodb-cloud-manager-by-aquera"
    },
    {
        "query": "Okta partnership Codefresh by Aquera settings",
        "expected": "-okta-partnership-codefresh-by-aquera"
    },
    {
        "query": "How to setup Brivo Security Suite Paylocity integration?",
        "expected": "brivo-security-suite-paylocity-integration-guide"
    },
    {
        "query": "How do I configure Asana integration connector?",
        "expected": "asana-configuration-guide"
    },
    {
        "query": "Prerequisites for 8x8 connector setup",
        "expected": "8x8-configuration-guide"
    },
    {
        "query": "BambooHR employees to Active Directory users integration guide",
        "expected": "bamboohr-employees-to-active-directory-users-integration-guide"
    },
    {
        "query": "ADP Workforce Now Worker Report Integration Setup Guide attributes",
        "expected": "adp-workforce-now-worker-report-integration-setup-guide"
    },
    {
        "query": "How to sync ADP Workforce Now to Microsoft 365 Users",
        "expected": "adp-workforce-now-workers-to-microsoft-365-users"
    },
    {
        "query": "Zendesk connector configuration basic details authentication",
        "expected": "zendesk-configuration-guide"
    }
]

def run_evaluation():
    cfg = Config()
    lexical_dir = ROOT / "storage" / "site_lexical_index"
    lex_index = LexicalIndex(str(lexical_dir))
    
    if not lex_index.load():
        print("Error: Could not load the lexical search index. Run scripts/index_all_md.py first.")
        return
        
    print("\n==================================================")
    print("      THOROUGH KB RETRIEVAL ACCURACY TEST (15 CASES)")
    print("==================================================\n")
    
    total = len(TEST_SUITE)
    hit_at_1 = 0
    hit_at_3 = 0
    
    for i, test_case in enumerate(TEST_SUITE):
        query = test_case["query"]
        expected = test_case["expected"].lower().strip("-")
        
        # Search index
        results = lex_index.search_with_indices(query, top_k=3)
        
        print(f"Test case #{i+1}:")
        print(f"  Query   : \"{query}\"")
        print(f"  Expected: {expected}")
        
        if not results:
            print("  Result  : FAIL (No documents returned)\n")
            continue
            
        # Extract matches
        retrieved_list = []
        matched_1 = False
        matched_3 = False
        
        for rank, res in enumerate(results):
            meta = res["metadata"]
            title = meta.get("title", "")
            slug = resolve_slug(meta.get("integration_id", "")).strip("-")
            
            match_status = False
            # Check if expected is in title or slug
            if (expected in slug) or (expected in title.lower().replace(" ", "-")):
                match_status = True
                matched_3 = True
                if rank == 0:
                    matched_1 = True
            
            label = "✅ Match" if match_status else "❌ Miss"
            retrieved_list.append(f"Rank {rank+1}: {title} (slug: {meta.get('integration_id')}) [Score: {res['score']:.2f}] - {label}")
            
        if matched_1:
            hit_at_1 += 1
            print("  Result  : ✅ HIT at Rank 1")
        elif matched_3:
            print("  Result  : ⚠️ HIT at Rank 2/3")
        else:
            print("  Result  : ❌ MISS")
            
        if matched_3:
            hit_at_3 += 1
            
        print("  Top retrieved pages:")
        for r in retrieved_list:
            print(f"    - {r}")
        print()
        
    accuracy_1 = (hit_at_1 / total) * 100
    accuracy_3 = (hit_at_3 / total) * 100
    
    print("==================================================")
    print(f"Thorough Accuracy Summary:")
    print(f"  - Hit Rate @ 1 (First result correct): {accuracy_1:.1f}% ({hit_at_1}/{total})")
    print(f"  - Hit Rate @ 3 (In top 3 results)    : {accuracy_3:.1f}% ({hit_at_3}/{total})")
    print("==================================================\n")

if __name__ == "__main__":
    run_suite = True
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"Running individual search check for: '{query}'")
        lexical_dir = ROOT / "storage" / "site_lexical_index"
        lex_index = LexicalIndex(str(lexical_dir))
        if lex_index.load():
            res = lex_index.search_with_indices(query, top_k=5)
            for i, r in enumerate(res):
                meta = r["metadata"]
                print(f"[{i+1}] Score: {r['score']:.2f} | Title: {meta['title']} | Slug: {meta['integration_id']}")
            run_suite = False
            
    if run_suite:
        run_evaluation()
