"""Page-aware chunking of parsed manuals (spec §10.2 step 3, M1-03).

Each parsed page is split into heading / table / text blocks. Headings build a section path that
carries across pages. Tables become their own chunk (whole if they fit, otherwise split by rows
with the header repeated); text runs within a section are split with LlamaIndex's
`SentenceSplitter` (512 tokens, 64 overlap). Every chunk keeps the page range it came from, so
citations can point at the right page.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.utils import get_tokenizer
from pydantic import BaseModel

from homehelper.ingestion.manifest import ManualEntry
from homehelper.ingestion.parse import ParsedManual
from homehelper.knowledge.schemas import ChunkMetadata, ChunkType

CHUNK_TOKENS = 512
CHUNK_OVERLAP = 64
MIN_CHUNK_CHARS = 40
MERGE_BELOW_TOKENS = 150

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_CONTINUED = re.compile(r"\s*[\(\[]?\b(cont(inued)?\.?)[\)\]]?\s*$", re.IGNORECASE)
_NUMBERED_STEP = re.compile(r"^\s*(?:\d+[.)]|step\s+\d+)\s+\S", re.IGNORECASE | re.MULTILINE)

_EN = {"the", "and", "to", "of", "is", "your", "with", "for", "not", "if", "you", "this", "be"}
_OTHER = {
    # French and Spanish function words (bilingual North American manuals).
    *("le", "les", "des", "et", "pour", "votre", "avec", "pas", "vous", "une", "est", "du"),
    *("el", "los", "las", "y", "para", "su", "con", "usted", "una", "del", "por", "que"),
}


class Chunk(BaseModel):
    chunk_id: str
    text: str  # context header + body; this is what gets embedded and shown to the LLM
    metadata: ChunkMetadata


@dataclass
class _Block:
    kind: str  # "heading" | "table" | "text"
    page: int
    text: str
    level: int = 0


@dataclass
class _Run:
    """Consecutive text blocks under one section."""

    section: tuple[str, ...]
    parts: list[tuple[int, str]] = field(default_factory=list)  # (page, text)


def clean_heading(raw: str) -> str:
    text = re.sub(r"<sup>.*?</sup>", "", raw)  # trademark marks
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[*_`]+", "", text).strip()
    text = _CONTINUED.sub("", text).strip(" :-\u2013")  # also strip en dashes
    text = re.sub(r"^\d{1,3}\s+(?=[A-Za-z])", "", text)  # "26 Operation" (printed page number)
    return text.title() if text.isupper() and len(text) > 3 else text


def is_probably_english(text: str) -> bool:
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    if len(words) < 30:
        return True  # too little text to judge; keep it
    en = sum(w in _EN for w in words)
    other = sum(w in _OTHER for w in words)
    return en >= other * 0.8


def _blocks(page: int, markdown: str) -> Iterator[_Block]:
    text_lines: list[str] = []
    table_lines: list[str] = []

    def flush_text() -> Iterator[_Block]:
        body = "\n".join(text_lines).strip()
        text_lines.clear()
        if body:
            yield _Block("text", page, body)

    def flush_table() -> Iterator[_Block]:
        body = "\n".join(table_lines).strip()
        table_lines.clear()
        if body:
            yield _Block("table", page, body)

    for line in markdown.splitlines():
        if line.lstrip().startswith("|"):
            yield from flush_text()
            table_lines.append(line.strip())
            continue
        yield from flush_table()
        heading = _HEADING.match(line)
        if heading:
            yield from flush_text()
            title = clean_heading(heading.group(2))
            if title:
                yield _Block("heading", page, title, level=len(heading.group(1)))
        else:
            text_lines.append(line)
    yield from flush_table()
    yield from flush_text()


def _is_table_of_contents(section: tuple[str, ...]) -> bool:
    return any(re.fullmatch(r"(table of )?contents?", title.strip().lower()) for title in section)


def classify(section: tuple[str, ...], body: str, is_table: bool) -> ChunkType:
    heading = " / ".join(section).lower()
    lowered = body.lower()
    table_header = lowered.split("\n", 1)[0] if is_table else ""
    error_words = ("error code", "error message", "information code", "fault code", "error display")
    if (
        re.search(r"\berror", heading)
        or any(word in table_header for word in ("error", "code", "display"))
        or (is_table and any(word in lowered[:400] for word in error_words))
    ):
        return "error_code"
    if is_table and (
        re.search(r"troubleshoot|problem|before (you )?call|what to do", heading)
        or re.search(r"problem|issue|symptom|possible cause|solution", table_header)
    ):
        return "troubleshooting_table"
    if re.search(r"\b(safety|warning|caution|safeguard)", heading):
        return "safety"
    if re.search(r"troubleshoot|problem", heading):
        return "troubleshooting_table" if is_table else "procedure"
    if len(_NUMBERED_STEP.findall(body)) >= 2 or re.search(
        r"\b(how to|clean|install|maintenance|care|replac|descal|setting up|using)", heading
    ):
        return "procedure"
    return "general"


def split_table(table: str, max_tokens: int, count_tokens: Callable[[str], int]) -> list[str]:
    if count_tokens(table) <= max_tokens:
        return [table]
    lines = table.splitlines()
    has_separator = len(lines) > 1 and re.fullmatch(r"\|[\s:|-]+\|?", lines[1]) is not None
    header = lines[:2] if has_separator else lines[:1]
    rows = lines[len(header) :]
    pieces: list[str] = []
    current: list[str] = []
    for row in rows:
        candidate = "\n".join([*header, *current, row])
        if current and count_tokens(candidate) > max_tokens:
            pieces.append("\n".join([*header, *current]))
            current = []
        current.append(row)
    if current:
        pieces.append("\n".join([*header, *current]))
    return pieces


class ManualChunker:
    def __init__(self, chunk_tokens: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP) -> None:
        self._tokenizer = get_tokenizer()
        self._splitter = SentenceSplitter(chunk_size=chunk_tokens, chunk_overlap=overlap)
        self._chunk_tokens = chunk_tokens

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer(text))

    def chunk(self, entry: ManualEntry, parsed: ParsedManual) -> list[Chunk]:
        pieces: list[
            tuple[tuple[str, ...], int, int, str, bool]
        ] = []  # section, p0, p1, body, table
        stack: list[tuple[int, str]] = []
        run: _Run | None = None

        def section() -> tuple[str, ...]:
            return tuple(title for _, title in stack)

        def flush_run() -> None:
            nonlocal run
            if run and run.parts:
                pieces.extend(self._split_run(run))
            run = None

        for page in parsed.pages:
            if page.error or not page.markdown.strip() or not is_probably_english(page.markdown):
                continue
            for block in _blocks(page.page, page.markdown):
                if block.kind == "heading":
                    if stack and stack[-1][1] == block.text:
                        continue  # "Troubleshooting (cont.)" on the next page: same section
                    flush_run()
                    while stack and stack[-1][0] >= block.level:
                        stack.pop()
                    stack.append((block.level, block.text))
                elif block.kind == "table":
                    flush_run()
                    for part in split_table(block.text, self._chunk_tokens, self.count_tokens):
                        pieces.append((section(), block.page, block.page, part, True))
                else:
                    if run is None or run.section != section():
                        flush_run()
                        run = _Run(section())
                    run.parts.append((block.page, block.text))
        flush_run()

        chunks: list[Chunk] = []
        for seq, (path, page_start, page_end, body, is_table) in enumerate(pieces):
            if len(body) < MIN_CHUNK_CHARS or _is_table_of_contents(path):
                continue
            header = f"[{entry.brand} {entry.title}" + (f" — {' > '.join(path)}]" if path else "]")
            chunks.append(
                Chunk(
                    chunk_id=f"{entry.doc_id}:p{page_start}:{seq:04d}",
                    text=f"{header}\n{body}",
                    metadata=ChunkMetadata(
                        doc_id=entry.doc_id,
                        category=entry.category,
                        brand=entry.brand,
                        model_patterns=entry.model_patterns,
                        section_path=list(path),
                        page_start=page_start,
                        page_end=page_end,
                        chunk_type=classify(path, body, is_table),
                    ),
                )
            )
        return chunks

    def _split_run(self, run: _Run) -> list[tuple[tuple[str, ...], int, int, str, bool]]:
        # Split per page so every piece's page range is exact. A short page fragment (e.g. the
        # end of a paragraph that spilled onto the next page) is merged with its neighbour.
        groups: list[tuple[list[int], str]] = []
        for page, text in run.parts:
            if groups and groups[-1][0][-1] == page:
                groups[-1] = (groups[-1][0], f"{groups[-1][1]}\n\n{text}")
            elif (
                groups
                and min(self.count_tokens(groups[-1][1]), self.count_tokens(text))
                < MERGE_BELOW_TOKENS
            ):
                groups[-1] = ([*groups[-1][0], page], f"{groups[-1][1]}\n\n{text}")
            else:
                groups.append(([page], text))
        return [
            (run.section, pages[0], pages[-1], piece, False)
            for pages, text in groups
            for piece in self._splitter.split_text(text)
        ]
