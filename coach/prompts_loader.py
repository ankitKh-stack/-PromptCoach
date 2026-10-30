"""Builds system prompts from prompts/*.md and wraps user content as delimited data."""
import re

from coach.config import path

PROMPT_FILES = {
    "judge": "judge.v1.md",
    "questions": "questions.v3.md",
    "final_prompt": "final_prompt.v2.md",
    "checklist": "checklist.v1.md",
    "revise": "revise.v2.md",
}


def system_prompt(name: str) -> str:
    template = (path("prompts_dir") / PROMPT_FILES[name]).read_text(encoding="utf-8")
    rules = path("knowledge").read_text(encoding="utf-8")
    return template.replace("{{rules}}", rules)


def prompt_version(name: str) -> str:
    return PROMPT_FILES[name]


RESERVED_TAGS = ("settings", "rough_prompt", "interview", "interview_so_far", "prompt_to_review",
                 "current_prompt", "current_additions", "failed_items", "required_features",
                 "prompting_rules", "validation_error")
_RESERVED = re.compile(rf"<(/?)({'|'.join(RESERVED_TAGS)})\s*>", re.IGNORECASE)


def _neutralise(text: str) -> str:
    """Stop user text from closing or opening the app's own delimiter tags."""
    return _RESERVED.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}&gt;", text)


def tag(name: str, content: str) -> str:
    return f"<{name}>\n{_neutralise(content.strip())}\n</{name}>"


def settings_block(settings: dict) -> str:
    """Settings are written by the app, so they are not neutralised."""
    lines = []
    for key, value in settings.items():
        if isinstance(value, list):
            items = "\n".join(f"- {v}" for v in value)
            lines.append(f"<{key}>\n{items}\n</{key}>")
        else:
            lines.append(f"{key}: {value}")
    return "<settings>\n" + "\n".join(lines) + "\n</settings>"


def interview_text(qa: list[dict]) -> str:
    if not qa:
        return "(no questions asked)"
    parts = []
    for n, item in enumerate(qa, 1):
        if item["status"] == "answered":
            answer = item["answer"]
        elif item["status"] == "unknown":
            answer = "(I don't know)"
        else:
            answer = "(skipped)"
        parts.append(f"Q{n} [category {item['category']}]: {item['question']}\nA{n}: {answer}")
    return "\n\n".join(parts)
