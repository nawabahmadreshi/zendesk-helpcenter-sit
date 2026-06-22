from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
import re

@dataclass
class WorkflowNode:
    id: str  # e.g., "setup_basics"
    label: str  # human readable
    required_fields: List[str] = field(default_factory=list)  # IDs of input fields
    optional_fields: List[str] = field(default_factory=list)
    description: Optional[str] = None

@dataclass
class WorkflowEdge:
    from_node: str
    to_node: str
    condition: Optional[str] = None  # e.g., "all_required_met"

class WorkflowEngine:
    """
    Manages a Directed Acyclic Graph (DAG) of UI steps.
    Tracks user progress and detects skips or missing mandatory fields.
    """
    def __init__(self):
        self.nodes: Dict[str, WorkflowNode] = {}
        self.edges: List[WorkflowEdge] = []
        self._build_default_dag()

    def _build_default_dag(self):
        # Default DAG for Aquera Integration Setup
        self.add_node(WorkflowNode(
            id="basics",
            label="Basic Configuration",
            required_fields=["#instance_url", "#auth_type"],
            description="Enter the target system URL and authentication method."
        ))
        
        self.add_node(WorkflowNode(
            id="auth",
            label="Authentication Details",
            required_fields=["#api_key", "#client_id", "#client_secret"],
            description="Provide credentials for the chosen authentication method."
        ))
        
        self.add_node(WorkflowNode(
            id="mapping",
            label="Field Mapping",
            required_fields=["#ext_id_field"],
            optional_fields=["#sync_direction", "#provisioning_type"],
            description="Map external identity attributes to Aquera schema."
        ))

        self.add_edge("basics", "auth")
        self.add_edge("auth", "mapping")

    def add_node(self, node: WorkflowNode):
        self.nodes[node.id] = node

    def add_edge(self, from_id: str, to_id: str, condition: str = "all_required_met"):
        if from_id in self.nodes and to_id in self.nodes:
            self.edges.append(WorkflowEdge(from_id, to_id, condition))

    def analyze_progress(self, event_stream: List[dict], current_form_values: Dict[str, str]) -> dict:
        """
        Analyzes the event stream against the DAG to determine:
        1. Current Node
        2. Progress percentage
        3. Missing mandatory fields in current or previous nodes
        4. "Skip" detection (user interacting with future node without completing current)
        """
        # 1. Identify current focus area
        last_focus = next((e for e in reversed(event_stream) if e.get("type") == "focus"), None)
        target_id = last_focus.get("target") if last_focus else None
        
        current_node_id = "basics" # Start
        for node_id, node in self.nodes.items():
            if target_id and (target_id in node.required_fields or target_id in node.optional_fields):
                current_node_id = node_id
                break

        # 2. Check completions
        completions = {}
        for node_id, node in self.nodes.items():
            missing = [f for f in node.required_fields if not current_form_values.get(f)]
            completions[node_id] = {
                "is_complete": len(missing) == 0,
                "missing_required": missing
            }

        # 3. Detect Skips
        # If user is in a "later" node but "earlier" nodes are incomplete
        skipped_nodes = []
        is_past_current = False
        for node_id in self.nodes.keys():
            if node_id == current_node_id:
                is_past_current = True
                continue
            
            if not is_past_current and not completions[node_id]["is_complete"]:
                skipped_nodes.append(node_id)

        return {
            "current_node": current_node_id,
            "completions": completions,
            "skipped_nodes": skipped_nodes,
            "advice": self._generate_advice(current_node_id, skipped_nodes, completions)
        }

    def _generate_advice(self, current_node_id: str, skipped_nodes: List[str], completions: dict) -> str:
        if skipped_nodes:
            missing_fields = completions[skipped_nodes[0]]["missing_required"]
            return f"You're working on {self.nodes[current_node_id].label}, but you missed some mandatory fields in {self.nodes[skipped_nodes[0]].label} ({', '.join(missing_fields)})."
        
        current_missing = completions[current_node_id]["missing_required"]
        if current_missing:
            return f"Focusing on {self.nodes[current_node_id].label}. Don't forget to fill out {', '.join(current_missing)}."
            
        return f"{self.nodes[current_node_id].label} looks good! Proceed when ready."
