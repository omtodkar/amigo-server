import os
from functools import cache


@cache
def load_prompt(filename: str) -> str:
    """Load a prompt from a markdown file. Cached in memory after first load."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, "prompts", filename)

    with open(prompt_path, encoding="utf-8") as file:
        return file.read().strip()
