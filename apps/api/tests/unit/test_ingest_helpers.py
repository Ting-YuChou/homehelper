from pathlib import Path

from llama_index.core.vector_stores.utils import node_to_metadata_dict

from homehelper.ingestion.chunking import Chunk
from homehelper.ingestion.pipeline import manifest_hash, referenced_versions, to_node
from homehelper.knowledge.schemas import CategoryId, ChunkMetadata
from homehelper.knowledge.store import open_store, table_for


def test_manifest_hash_changes_with_manifest_and_embedding_model(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("- doc_id: a\n")
    base = manifest_hash(manifest, "text-embedding-3-small")
    assert base == manifest_hash(manifest, "text-embedding-3-small")
    assert base != manifest_hash(manifest, "text-embedding-3-large")
    manifest.write_text("- doc_id: b\n")
    assert base != manifest_hash(manifest, "text-embedding-3-small")


def test_referenced_versions_reads_release_manifests(tmp_path: Path) -> None:
    (tmp_path / "r1.yaml").write_text("id: r1\nkb_version: kb_20261021_02\n")
    (tmp_path / "notes.txt").write_text("kb_20261020_01")
    assert referenced_versions(tmp_path) == {"kb_20261021_02"}


def test_to_node_keeps_id_text_embedding_and_json_metadata() -> None:
    chunk = Chunk(
        chunk_id="lg-wm3400:p4:0002",
        text="[LG Washer — Error Codes]\n| OE | Drain error |",
        metadata=ChunkMetadata(
            doc_id="lg-wm3400",
            category=CategoryId.WASHING_MACHINE,
            brand="LG",
            section_path=["Troubleshooting", "Error Codes"],
            page_start=4,
            page_end=4,
            chunk_type="error_code",
        ),
    )
    node = to_node(chunk, [0.1, 0.2])
    assert node.node_id == chunk.chunk_id
    assert node.embedding == [0.1, 0.2]
    assert node.metadata["category"] == "washing_machine"
    assert node.metadata["section_path"] == ["Troubleshooting", "Error Codes"]
    # What PGVectorStore persists: our doc_id must survive LlamaIndex's reserved keys.
    stored = node_to_metadata_dict(node, remove_text=True, flat_metadata=False)
    assert stored["doc_id"] == stored["ref_doc_id"] == "lg-wm3400"


def test_store_naming_and_urls() -> None:
    assert table_for("kb_20261021_02") == "data_kb_20261021_02"
    try:
        open_store("postgresql+asyncpg://u:p@h/d", "kb; drop table x", 1536)
    except ValueError as exc:
        assert "invalid kb_version" in str(exc)
    else:
        raise AssertionError("expected ValueError")
