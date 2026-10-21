"""Loader for `data/mock/` (spec §12.2, M5-01)."""

import json
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from homehelper.knowledge.web import SearchHit
from homehelper.mcp_servers.schemas import (
    Appliance,
    MockVideo,
    Part,
    RepairRecord,
    Technician,
    UserProfile,
)


def _load[M: BaseModel](path: Path, item: type[M]) -> list[M]:
    return [item.model_validate(row) for row in json.loads(path.read_text())]


class MockData(BaseModel):
    users: list[UserProfile]
    appliances: list[Appliance]
    repair_history: list[RepairRecord]
    parts: list[Part]
    technicians: list[Technician]
    videos: list[MockVideo]
    web_results: list[SearchHit]

    @classmethod
    def load(cls, mock_dir: Path) -> "MockData":
        return cls(
            users=_load(mock_dir / "users.json", UserProfile),
            appliances=_load(mock_dir / "appliances.json", Appliance),
            repair_history=_load(mock_dir / "repair_history.json", RepairRecord),
            parts=_load(mock_dir / "parts.json", Part),
            technicians=_load(mock_dir / "technicians.json", Technician),
            videos=_load(mock_dir / "videos.json", MockVideo),
            web_results=_load(mock_dir / "web_results.json", SearchHit),
        )

    def user(self, user_id: str) -> UserProfile | None:
        return next((u for u in self.users if u.user_id == user_id), None)


@cache
def load_mock_data(mock_dir: Path) -> MockData:
    """Cached per directory; callers must not mutate the result (stores copy what they change)."""
    return MockData.load(mock_dir)
