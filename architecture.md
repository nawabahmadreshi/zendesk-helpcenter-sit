# Aquera Help Center - AI Search Architecture

This document provides a comprehensive overview of the Aquera AI Help Center architecture. It is designed to provide state-of-the-art (SOTA) hierarchical search capabilities specifically tailored for complex, multi-section integration guides.

## High-Level Architecture Diagram

```mermaid
flowchart TD
    subgraph Frontend ["Frontend UI Widget"]
        A["Floating Search Widget"] -->|"User Query"| B("Query Processor")
        B -->|"Search Within"| C{"Article Filter Active?"}
        C -->|"Yes"| D["Filter by specific Guide ID"]
        C -->|"No"| E["Global Search"]
        F["Iframe Document Viewer"] -->|"Smart Scroll & Highlight"| G["Native window.find fallback algorithm"]
    end

    subgraph Backend ["FastAPI Backend Server"]
        H["API: /api/help/search"]
        I["API: /article/{id}"]
        
        H --> J["Query Expansion"]
        J -->|"Acronym Expansion"| K["Template HyDE"]
        
        K --> L{"Retrieval Engine"}
        L -->|"Vector Search"| M[("ChromaDB - Gemini Embeddings")]
        L -->|"Lexical Search"| N[("BM25 In-Memory Index")]
        L -->|"Exact Match Injection"| O["Section Title Matcher"]
        
        M --> P("Result Merger & RRF")
        N --> P
        O --> P
        
        P --> Q["Contextual Filters"]
        Q -->|"Exclude Internal/Draft"| R["ML Cross-Encoder Reranker"]
        R --> S["Feedback Loop/LTR Booster"]
        
        S --> T["Result Formatter"]
        T -->|"Clarification Card"| U["Return UI Response"]
        T -->|"Direct Results"| U
    end

    subgraph Data_Ingestion ["Data Sync & Processing Pipeline"]
        V["Zendesk API / Markdown"] --> W["HTML Parser & Cleaner"]
        W --> X["Hierarchical Semantic Chunker"]
        X --> Y["Metadata Extractor"]
        Y -->|"Integration ID, Guide Name"| Z["Indexer"]
        Z --> M
        Z --> N
    end

    D --> H
    E --> H
    U --> Frontend
    I --> F
    
    %% Styling
    classDef frontend fill:#f3e8ff,stroke:#a855f7,stroke-width:2px,color:#000
    classDef backend fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#000
    classDef data fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#000
    classDef db fill:#fef08a,stroke:#ca8a04,stroke-width:2px,color:#000
    
    class A,B,C,D,E,F,G,Frontend frontend
    class H,I,J,K,L,P,Q,R,S,T,U,Backend backend
    class V,W,X,Y,Z,Data_Ingestion data
    class M,N db
```

---

## 1. Data Ingestion & Processing Pipeline
The foundation of the architecture relies on converting complex, heavily formatted Zendesk HTML documents into clean, hierarchical chunks.
* **Source:** Zendesk API (`sync_category.py`) or Local Markdown files (`local_ingest.py`).
* **Hierarchical Chunker:** Uses `BeautifulSoup` to parse HTML, preserving heading boundaries (`<h1>`, `<h2>`, `<h3>`). It maps every paragraph to its parent "Guide" and "Section", creating highly contextualized semantic blocks.
* **Metadata Extraction:** Automatically tags chunks with their `integration_id`, `article_id`, `article_title`, and product versions.

## 2. Dual-Index Retrieval Engine
Unlike standard RAG pipelines that rely solely on vector search, this system uses a hybrid retrieval engine for maximum recall:
* **Vector Search (ChromaDB):** Uses Gemini Dense Embeddings to find conceptually similar text (e.g., "how to add users" matching "user provisioning").
* **Lexical Search (BM25):** An in-memory statistical index that excels at exact keyword matches (e.g., specific error codes, specific product names).
* **Exact Lexical Injection:** A custom heuristic that instantly boosts a chunk to the #1 position (`score: 1000.0`) if the user's query exactly matches a section title, heavily prioritizing direct navigation.
* **Template HyDE:** "Hypothetical Document Expansion". Expands queries locally without LLM latency (e.g., converting "Overview" into "To configure Overview, navigate to the integration settings...").

## 3. Reranking & Feedback Loop
Retrieval ensures we find the needle in the haystack, but reranking ensures it's placed at the very top.
* **ML Cross-Encoder (`reranker.py`):** Uses a pre-trained `ms-marco-MiniLM` model. It takes the top combined results from Vector and Lexical search and scores them based on deep semantic relationship, effectively re-ordering the list with incredible accuracy.
* **LTR (Learning to Rank) / Feedback Loop:** Listens to user interactions (clicks, feedback buttons). If a user frequently clicks a specific guide for a specific query, the system permanently boosts that guide for future similar searches.
* **Contextual Filters:** Strictly enforces UI constraints (like `article_filter` for the "Search Within" feature) and scrubs out internal draft documents or "Do Not Publish" markers.

## 4. Frontend UI & Intelligent Viewer
A vanilla JS floating widget that provides a seamless user experience.
* **Clarification Engine:** If a search is too generic (e.g., "Exceptions Details View") and returns multiple valid sections, the backend returns a `clarification_needed` flag. The UI renders dynamic chips (e.g., "Prerequisites", "Troubleshooting") to guide the user.
* **Iframe Smart Highlighter:** When a user clicks "Read Section", the UI opens the full Zendesk article in an iframe. It uses a custom cascading javascript algorithm built around `window.find()` to locate the exact paragraph in the rendered DOM (dynamically handling unexpected HTML tags or bullet points) and snaps the user directly to the answer with a yellow highlight.
