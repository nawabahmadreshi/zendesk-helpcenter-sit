from app.crag_gate import CRAGGate

def test_crag_gate_logic():
    print("\n--- Testing CRAG Gate Logic ---")
    gate = CRAGGate()
    
    query = "How do I configure the ADP ServiceNow integration?"
    
    # 1. Correct Match
    correct_chunks = [{"text": "To configure the ADP and ServiceNow integration, you must first setup the API keys."}]
    res1 = gate.score_context(query, correct_chunks)
    print(f"Correct match status: {res1['status']} (Score: {res1['score']:.2f})")
    
    # 2. Incorrect Match (Garbage)
    incorrect_chunks = [{"text": "The price of tea in China is rising due to climate change."}]
    res2 = gate.score_context(query, incorrect_chunks)
    print(f"Incorrect match status: {res2['status']} (Score: {res2['score']:.2f})")

    # 3. Ambiguous Match
    ambiguous_chunks = [{"text": "ServiceNow is a popular ITSM tool."}]
    res3 = gate.score_context(query, ambiguous_chunks)
    print(f"Ambiguous match status: {res3['status']} (Score: {res3['score']:.2f})")

    if res1['status'] == 'CORRECT' and res2['status'] == 'INCORRECT':
        print("✅ CRAG Gate logic verified.")
    else:
        print("❌ CRAG Gate logic failed expectation.")

if __name__ == "__main__":
    test_crag_gate_logic()
