import hashlib
from functools import lru_cache
from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parent / "prompts"

AGENT_PROMPT_FILES = {
    "goal_architect": PROMPTS_ROOT / "goal_architect" / "v1.md",
    "evidence": PROMPTS_ROOT / "evidence" / "v1.md",
    "research": PROMPTS_ROOT / "research" / "v1.md",
    "critic": PROMPTS_ROOT / "critic" / "v1.md",
    "intervention": PROMPTS_ROOT / "intervention" / "v1.md",
    "strategy": PROMPTS_ROOT / "strategy" / "v1.md",
    "source_planner": PROMPTS_ROOT / "source_planner" / "v1.md",
}


class PromptSpec:
    def __init__(self, agent: str, version: str, text: str) -> None:
        self.agent = agent
        self.version = version
        self.text = text
        self.checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache
def load_prompt(agent: str) -> PromptSpec:
    path = AGENT_PROMPT_FILES[agent]
    return PromptSpec(
        agent=agent,
        version=path.parent.name + "/" + path.stem,
        text=path.read_text(encoding="utf-8"),
    )
