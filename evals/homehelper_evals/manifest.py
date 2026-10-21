"""Read-only lookup from a scenario's `appliance_name` (PDF filename) to the manifest `doc_id`
(spec §10.1, §16.2). The manifest is owned by the knowledge track; until it is filled in, every
lookup returns None and citation checks are reported as not applicable."""

from pathlib import Path, PurePosixPath

import yaml

from homehelper_evals import MANIFEST_PATH


def load_doc_ids(path: Path = MANIFEST_PATH) -> dict[str, str]:
    entries = yaml.safe_load(path.read_text()) or []
    doc_ids: dict[str, str] = {}
    for entry in entries:
        for filename in [entry["file"], *entry.get("aliases", [])]:
            doc_ids[PurePosixPath(filename).name] = entry["doc_id"]
    return doc_ids
