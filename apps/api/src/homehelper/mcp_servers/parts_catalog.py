"""`parts_catalog` MCP server: mock parts and tools catalog from `parts.json` (spec §12.1, M5-03).

JSON-backed in both modes; nothing is scraped. Compatibility uses the same model-number matching
as retrieval (`knowledge.model_numbers`).
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from homehelper.knowledge.model_numbers import matches_any
from homehelper.knowledge.schemas import CategoryId
from homehelper.mcp_servers.common import mcp_tool, new_server, words
from homehelper.mcp_servers.schemas import Part

INSTRUCTIONS = (
    "Replacement parts and tools for home appliances, filtered by category, brand, model "
    "number and symptom, with price and image. Prices are from a demo catalog."
)


def symptom_score(part: Part, symptom: str) -> float:
    """Best fraction of one of the part's symptom phrases that the user's words cover."""
    said = words(symptom)
    best = 0.0
    for phrase in part.symptoms:
        wanted = words(phrase)
        if wanted:
            best = max(best, len(wanted & said) / len(wanted))
    return best


def search(
    parts: list[Part],
    *,
    category: CategoryId | None,
    brand: str | None,
    model: str | None,
    symptom: str | None,
    limit: int,
) -> list[Part]:
    scored: list[tuple[float, Part]] = []
    for part in parts:
        if category and part.category not in (None, category):
            continue
        if brand and part.brands and brand.lower() not in {b.lower() for b in part.brands}:
            continue
        if model and part.compatible_models and not matches_any(model, part.compatible_models):
            continue
        score = 0.0
        if symptom:
            score = symptom_score(part, symptom)
            if score == 0:
                continue
        elif part.category is None:
            continue  # general-purpose tools only show up for a matching symptom
        # Prefer parts made for this exact model, then brand, over generic ones.
        if model and part.compatible_models:
            score += 1.0
        if brand and part.brands:
            score += 0.5
        scored.append((score, part))
    scored.sort(key=lambda sp: (-sp[0], sp[1].price_usd))
    return [part for _, part in scored[:limit]]


def build_parts_catalog_server(parts: list[Part]) -> FastMCP:
    server = new_server("parts_catalog", INSTRUCTIONS)
    by_id = {p.part_id: p for p in parts}

    @mcp_tool(server, title="Search parts and tools")
    async def search_parts(
        category: CategoryId | None = None,
        brand: str | None = None,
        model: Annotated[str | None, Field(description="The appliance's model number")] = None,
        symptom: Annotated[
            str | None, Field(description="The problem in a few words, e.g. 'won't drain'")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
    ) -> list[Part]:
        """Parts and tools that fit the appliance and the symptom, best matches first."""
        if not any((category, brand, model, symptom)):
            raise ToolError("Give at least one of category, brand, model or symptom")
        return search(
            parts, category=category, brand=brand, model=model, symptom=symptom, limit=limit
        )

    @mcp_tool(server, title="Get part")
    async def get_part(part_id: str) -> Part:
        """One catalog entry by id."""
        part = by_id.get(part_id)
        if part is None:
            raise ToolError(f"Unknown part {part_id!r}")
        return part

    return server
