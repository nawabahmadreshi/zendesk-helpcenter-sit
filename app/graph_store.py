import json
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Any

@dataclass
class Entity:
    id: str
    type: str  # "integration", "field", "version", "action"
    properties: Dict[str, Any]

@dataclass
class Relationship:
    source: str
    target: str
    type: str  # "REQUIRES", "UPGRADES", "COMPATIBLE_WITH", "MAPS_TO"

class GraphStore:
    """
    Lightweight NodeRAG Graph Store for tracking relationships 
    between integration entities and versions.
    """
    def __init__(self, storage_path: str):
        self.path = storage_path
        self.nodes: Dict[str, Entity] = {}
        self.edges: List[Relationship] = []

    def add_entity(self, entity_id: str, entity_type: str, props: Dict = None):
        self.nodes[entity_id] = Entity(id=entity_id, type=entity_type, properties=props or {})

    def add_relationship(self, src: str, tgt: str, rel_type: str):
        if src in self.nodes and tgt in self.nodes:
            self.edges.append(Relationship(source=src, target=tgt, type=rel_type))

    def get_related_entities(self, entity_id: str, rel_type: str = None) -> List[str]:
        related = []
        for edge in self.edges:
            if edge.source == entity_id:
                if not rel_type or edge.type == rel_type:
                    related.append(edge.target)
        return related

    def get_relationships_for_entity(self, entity_id: str) -> List[Dict[str, str]]:
        rels = []
        for edge in self.edges:
            if edge.source == entity_id or edge.target == entity_id:
                rels.append({"source": edge.source, "target": edge.target, "type": edge.type})
        return rels

    def save(self):
        data = {
            "nodes": {k: {"type": v.type, "props": v.properties} for k, v in self.nodes.items()},
            "edges": [{"s": e.source, "t": e.target, "type": e.type} for e in self.edges]
        }
        with open(self.path, "w") as f:
            json.dump(data, f)

    def load(self):
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
                for eid, edata in data.get("nodes", {}).items():
                    self.add_entity(eid, edata["type"], edata["props"])
                for edata in data.get("edges", []):
                    self.add_relationship(edata["s"], edata["t"], edata["type"])
        except FileNotFoundError:
            pass
