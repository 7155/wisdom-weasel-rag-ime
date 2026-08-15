from __future__ import annotations


def compose_persona_layer(persona_prompt: str, role_book_prompt: str = "") -> str:
    """Attach only an exact pinned Role Book; absence is a literal no-op."""

    persona = str(persona_prompt or "").strip()
    if not persona:
        raise ValueError("persona prompt must not be empty")
    role_book = str(role_book_prompt or "").strip()
    if not role_book:
        return persona
    return (
        f"{persona}\\n\\n"
        "<agent-profile>\\n"
        f"{role_book}\\n"
        "</agent-profile>"
    )
