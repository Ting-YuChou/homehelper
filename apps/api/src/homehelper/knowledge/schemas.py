"""Knowledge-layer contracts shared by ingestion, retrieval, the agent, and evals (spec §10)."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class CategoryId(StrEnum):
    DISHWASHER = "dishwasher"
    WASHING_MACHINE = "washing_machine"
    DRYER = "dryer"
    REFRIGERATOR = "refrigerator"
    MICROWAVE = "microwave"
    COFFEE_MAKER = "coffee_maker"
    BLENDER_FOOD_PROCESSOR = "blender_food_processor"
    VACUUM = "vacuum"
    TELEVISION = "television"
    WATER_PURIFIER = "water_purifier"


ChunkType = Literal["troubleshooting_table", "error_code", "procedure", "safety", "general"]

# How far the metadata filter had to relax before enough results were found (spec §10.4 ①).
# `candidates`: the manuals the user's appliance may be, without a model number (ADR-013).
FilterLevel = Literal["model", "candidates", "brand_category", "category", "all"]
# What web results do to the manual's (spec §10.6, ADR-013): replace an insufficient result
# (the baseline), join it, or join every result.
WebMode = Literal["replace", "add_when_insufficient", "always_add"]

RetrievalSource = Literal["manual", "web", "none"]


class ChunkMetadata(BaseModel):
    doc_id: str
    category: CategoryId
    brand: str
    model_patterns: list[str] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)  # heading trail, outermost first
    page_start: int
    page_end: int
    chunk_type: ChunkType = "general"


class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    score: float  # final score after fusion / rerank; higher is better
    metadata: ChunkMetadata


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    page: int
    section: str | None = None

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> "Citation":
        path = chunk.metadata.section_path
        return cls(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.metadata.doc_id,
            page=chunk.metadata.page_start,
            section=path[-1] if path else None,
        )


class WebFinding(BaseModel):
    """A claim extracted from untrusted web content by a tool-less LLM call (spec §10.6)."""

    claim: str
    url: str
    # Set by code once the claim passed the checks: plan items cite it by id (ADR-013).
    id: str = ""
    title: str | None = None  # the page's title, for the source shown to the user


class RetrievalQuery(BaseModel):
    query_en: str
    category: CategoryId | None = None
    brand: str | None = None
    model_number: str | None = None
    error_code: str | None = None
    top_k: int = 5
    # Without a model number (ADR-013): the manuals the appliance may be, searched before
    # brand + category; at most `per_doc` chunks from each, so the planner sees which steps
    # they share; what the user sees on it, for the web search; and what web results do.
    doc_ids: list[str] | None = None
    per_doc: int | None = None
    appearance: list[str] = Field(default_factory=list)
    web: WebMode = "replace"


class RetrievalResult(BaseModel):
    query: RetrievalQuery
    source: RetrievalSource
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    web_findings: list[WebFinding] = Field(default_factory=list)
    filter_level: FilterLevel | None = None
    top_score: float | None = None
    sufficient: bool = False
    kb_version: str | None = None

    def chunk_ids(self) -> set[str]:
        return {chunk.chunk_id for chunk in self.chunks}
