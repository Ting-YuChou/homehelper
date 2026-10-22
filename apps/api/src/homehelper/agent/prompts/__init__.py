"""Versioned prompt templates (spec §7.7): `<name>.j2` files next to this module, rendered with
Jinja2. Each template starts with a comment stating its purpose, inputs and output schema."""

from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

PROMPTS_DIR = Path(__file__).parent


@cache
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,  # a missing variable is a bug, not an empty string
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        autoescape=False,  # plain-text prompts, not HTML
    )


def template(name: str) -> Template:
    return _environment().get_template(f"{name}.j2")


def render(name: str, **variables: object) -> str:
    return template(name).render(**variables).strip()
