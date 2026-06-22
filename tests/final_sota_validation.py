
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import json

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from app.agent import contextual_help_agent, IntentType

class TestSOTAFinal(unittest.TestCase):
    def setUp(self):
        self.page_context = {
            "page_title": "ADW Workforce Now Integration Setup",
            "url_path": "/integrations/adp/setup",
            "headings": ["Configure ADP Connection", "Map Fields"],
            "form_labels": ["Client ID", "Client Secret", "Base URL"],
            "integration_id": "adp-workforce-now",
            "product_version": "v14.2"
        }
        self.api_key = "fake-key"
        self.persist_dir = "storage/chroma_db"
        self.articles_dir = Path("storage/processed/articles")

    @patch("app.tools.search_integration_kb")
    @patch("app.crag_gate.CRAGGate")
    @patch("mcp_servers.analytics_server.report_retrieval_gap")
    @patch("app.agent._route_agent_loop")
    def test_adaptive_grounding_incorrect_trigger(self, mock_route, mock_report, mock_crag_gate, mock_search):
        # Scenario: CRAG identifies INCORRECT retrieval
        mock_search.return_value = json.dumps([{"text": "wrong info", "metadata": {"title": "Wrong", "article_id": "999"}, "score": 2.0}])
        
        mock_crag = MagicMock()
        mock_crag.score_context.return_value = {"status": "INCORRECT"}
        mock_crag_gate.return_value = mock_crag
        
        # Call agent
        contextual_help_agent(
            page_context=self.page_context,
            predicted_intent=IntentType.SETUP_DISCOVERY,
            ai_provider="gemini",
            api_key=self.api_key,
            persist_dir=self.persist_dir,
            articles_dir=self.articles_dir
        )
        
        # Check if Analytics MCP was notified
        mock_report.assert_called_once()
        print("SUCCESS: Analytics MCP gap reporting verified on INCORRECT CRAG signal.")

    @patch("app.tools.search_integration_kb")
    @patch("app.crag_gate.CRAGGate")
    @patch("app.agent._route_agent_loop")
    def test_adaptive_grounding_correct_article(self, mock_route, mock_crag_gate, mock_search):
        # Scenario: CRAG identifies CORRECT retrieval
        mock_search.return_value = json.dumps([{"text": "ADP setup guide content", "metadata": {"title": "ADP Guide", "article_id": "123"}, "score": 0.5}])
        
        mock_crag = MagicMock()
        mock_crag.score_context.return_value = {"status": "CORRECT"}
        mock_crag_gate.return_value = mock_crag
        
        # Call agent
        contextual_help_agent(
            page_context=self.page_context,
            predicted_intent=IntentType.SETUP_DISCOVERY,
            ai_provider="gemini",
            api_key=self.api_key,
            persist_dir=self.persist_dir,
            articles_dir=self.articles_dir
        )
        
        # Verify article was attached to user_message
        args, kwargs = mock_route.call_args
        self.assertIn("ADAPTIVE KNOWLEDGE CONTEXT (CORRECT)", kwargs["user_message"])
        self.assertIn("ADP setup guide content", kwargs["user_message"])
        print("SUCCESS: Adaptive grounding correctly attached relevant article context.")

    @patch("app.agent.GraphStore")
    @patch("app.agent._route_agent_loop")
    def test_graphstore_integration(self, mock_route, mock_graph_cls):
        # Scenario: GraphStore provides relational context
        mock_graph = MagicMock()
        mock_graph.get_relationships_for_entity.return_value = [
            {"source": "adp-workforce-now", "target": "okta", "type": "COMPATIBLE_WITH"}
        ]
        mock_graph_cls.return_value = mock_graph
        
        # Call agent
        contextual_help_agent(
            page_context=self.page_context,
            predicted_intent=IntentType.SETUP_DISCOVERY,
            ai_provider="gemini",
            api_key=self.api_key,
            persist_dir=self.persist_dir,
            articles_dir=self.articles_dir
        )
        
        # Verify relational context was attached to user_message
        args, kwargs = mock_route.call_args
        self.assertIn("[RELATIONAL CONTEXT]", kwargs["user_message"])
        self.assertIn("adp-workforce-now --(COMPATIBLE_WITH)--> okta", kwargs["user_message"])
        print("SUCCESS: GraphStore relational context correctly injected into agent prompt.")

if __name__ == "__main__":
    unittest.main()
