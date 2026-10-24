from typing import Literal, Protocol

from pydantic import BaseModel, Field

from homehelper.channels.events import StepResult
from homehelper_evals.cases import EvalCase
from homehelper_evals.transcript import Turn


class SimulatorTurn(BaseModel):
    message: str = Field(default="", description="What the user types; may be empty.")
    step_result: StepResult | None = Field(
        default=None, description="Button to press on the latest step card, if any."
    )
    confirm_appliance: Literal["yes", "no"] | None = Field(
        default=None, description="Answer to the latest appliance confirmation card, if any."
    )
    booking_slot_id: str | None = Field(
        default=None, description="Booking slot to pick from the latest booking card, if any."
    )
    photo: Literal["nameplate", "exterior"] | None = Field(
        default=None,
        description=(
            "A photo to send with this message, only when the assistant asked for one and "
            "your situation says you can: the model sticker, or the appliance itself."
        ),
    )
    done: bool = Field(default=False, description="True when the user ends the conversation.")


class UserSimulator(Protocol):
    async def next_turn(self, case: EvalCase, history: list[Turn]) -> SimulatorTurn:
        """The user's next turn; `history` is empty for the opening message."""
        ...
