def _collapse_spaces(value: str) -> str:
    return value.strip()


def render_label(value: str) -> str:
    return f"[{_collapse_spaces(value)}]"
