"""Versioned prompt templates (spec §7.7): `<name>.j2` files next to this module, rendered with
Jinja2. Each template starts with a comment stating its purpose, inputs and output schema.

Every interpolated string is treated as untrusted: tag-like text in it is neutralized so a user
message, an excerpt or a transcript line cannot close the tag around it. A block built by code
with its own tags (the web findings) is passed as `Trusted`.
"""

from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

from homehelper.core.text import neutralize_tags

PROMPTS_DIR = Path(__file__).parent


class Trusted(str):
    """Prompt text built by code, interpolated as is."""

    __slots__ = ()


def _finalize(value: object) -> object:
    if isinstance(value, str) and not isinstance(value, Trusted):
        return neutralize_tags(value)
    return value


@cache
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,  # a missing variable is a bug, not an empty string
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        autoescape=False,  # plain-text prompts, not HTML
        finalize=_finalize,
    )


def template(name: str) -> Template:
    return _environment().get_template(f"{name}.j2")


def render(name: str, **variables: object) -> str:
    return template(name).render(**variables).strip()
