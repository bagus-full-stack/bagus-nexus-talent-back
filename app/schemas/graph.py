from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    properties: dict


class GraphLink(BaseModel):
    source: str
    target: str
    type: str


class SubgraphResponse(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
    truncated: bool
