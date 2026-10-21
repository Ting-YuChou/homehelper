"""LLM-assisted relevance labels for chunk-level Recall@5 (spec §16.2, M1-07).

For a deterministic sample of test cases, candidate chunks are pulled from the correct manual
only, and the `judge` model marks which ones contain information that solves the scenario,
using the dataset's `solution_steps` as the reference. Labels are stored as (doc_id, page)
pairs so they survive re-chunking. Labels are LLM-made; spot-check them before trusting them.

    uv run python -m homehelper_evals.retrieval.labels --n 100
"""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field

from homehelper.core.config import get_settings
from homehelper.core.logging import configure_logging
from homehelper.db.engine import create_engine
from homehelper.knowledge.backends import OpenAIQueryEmbedder, PgSearchBackend, resolve_kb_version
from homehelper.knowledge.retriever import Filters, rrf
from homehelper.knowledge.store import open_store
from homehelper.llm import Message, ModelRegistry, build_llm_client
from homehelper_evals import SCENARIOS_PATH
from homehelper_evals.retrieval.dataset import RetrievalCase, load_cases

LABELS_PATH = Path(__file__).with_name("chunk_labels.json")
CANDIDATES = 15


class Judgement(BaseModel):
    relevant_chunk_numbers: list[int] = Field(
        description="Numbers of the chunks that contain steps or facts that solve the problem"
    )


class CaseLabel(BaseModel):
    case_id: str
    doc_id: str
    relevant_pages: list[int]
    candidates: int


def sample_cases(cases: list[RetrievalCase], n: int) -> list[RetrievalCase]:
    test = [c for c in cases if c.split == "test"]
    step = max(1, len(test) // n)
    return test[::step][:n]


def solution_steps() -> dict[str, str]:
    with SCENARIOS_PATH.open() as f:
        return {str(row["id"]): row["solution_steps"] for row in map(json.loads, f)}


async def main(n: int) -> None:
    settings = get_settings()
    configure_logging("WARNING")
    registry = ModelRegistry.load()
    engine = create_engine(settings.database_url)
    kb_version = await resolve_kb_version(engine, settings.kb_version)
    backend = PgSearchBackend(open_store(settings.database_url, kb_version, 1536))
    embedder = OpenAIQueryEmbedder(
        registry.embedding.model.split("/", 1)[-1], settings.openai_api_key.get_secret_value()
    )
    llm = build_llm_client(settings)
    steps = solution_steps()
    semaphore = asyncio.Semaphore(6)

    async def label(case: RetrievalCase) -> CaseLabel:
        async with semaphore:
            filters: Filters = {"doc_id": [case.doc_id]}
            embedding = await embedder.embed_query(case.query)
            dense = await backend.dense(embedding, CANDIDATES, filters)
            sparse = await backend.sparse(case.query, CANDIDATES, filters)
            candidates = [s.candidate for s in rrf([(1.0, dense), (1.0, sparse)], 60)][:CANDIDATES]
            listing = "\n\n".join(
                f"[{i}] (page {c.metadata['page_start']})\n{c.text[:1200]}"
                for i, c in enumerate(candidates, start=1)
            )
            judgement = await llm.structured(
                "judge",
                [
                    Message(
                        role="system",
                        content=(
                            "You label search results for a retrieval benchmark. Mark a chunk "
                            "relevant only if it contains concrete steps, causes, or facts from "
                            "the reference solution for this specific problem. Generic safety "
                            "text, tables of contents, and warranty text are not relevant."
                        ),
                    ),
                    Message(
                        role="user",
                        content=(
                            f"Problem: {case.query}\n\nReference solution:\n"
                            f"{steps[case.case_id]}\n\nChunks:\n{listing}"
                        ),
                    ),
                ],
                Judgement,
            )
        pages = sorted(
            {
                candidates[i - 1].metadata["page_start"]
                for i in judgement.relevant_chunk_numbers
                if 1 <= i <= len(candidates)
            }
        )
        return CaseLabel(
            case_id=case.case_id,
            doc_id=case.doc_id,
            relevant_pages=pages,
            candidates=len(candidates),
        )

    labels = await asyncio.gather(*(label(c) for c in sample_cases(load_cases(), n)))
    LABELS_PATH.write_text(
        json.dumps(
            {"kb_version": kb_version, "labels": [lab.model_dump() for lab in labels]}, indent=1
        )
        + "\n"
    )
    print(
        f"{len(labels)} labels, {sum(1 for lab in labels if lab.relevant_pages)} with relevant "
        f"pages -> {LABELS_PATH}"
    )
    await backend.close()
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=100)
    asyncio.run(main(parser.parse_args().n))
