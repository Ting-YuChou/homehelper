"""Simulated users (spec §16.3): an LLM role-player for real runs and a scripted one for CI."""

from homehelper_evals.simulator.base import SimulatorTurn, UserSimulator
from homehelper_evals.simulator.llm import LLMUserSimulator
from homehelper_evals.simulator.scripted import ScriptedUserSimulator

__all__ = ["LLMUserSimulator", "ScriptedUserSimulator", "SimulatorTurn", "UserSimulator"]
