"""Output schemas for every structured LLM call.

Each schema exists twice: a JSON Schema sent to providers that enforce it (kept to the
subset Anthropic and OpenAI strict mode both accept: all fields required, no
additionalProperties, no numeric/length limits), and a Pydantic model that validates
the reply in code, including the limits the JSON Schema cannot express.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CHECKLIST_ITEMS = [
    ("newcomer", "Could a capable newcomer do this from the prompt alone?"),
    ("outcome", "Is the outcome and \"what good looks like\" stated?"),
    ("reasons", "Does each rule carry its reason?"),
    ("specifics", "Are vague words replaced with checkable ones?"),
    ("separation", "Are data and instructions clearly separated?"),
    ("long_material", "Is long material first and the task last?"),
    ("missing_info", "Is there a rule for missing info and out-of-scope requests?"),
    ("no_pressure", "Are tips, threats, CAPS emphasis and persona-for-accuracy lines absent?"),
    ("no_step_by_step", "For reasoning models: no \"think step by step\"?"),
    ("examples_match", "Do any examples match the instructions?"),
]
CHECKLIST_IDS = [item_id for item_id, _ in CHECKLIST_ITEMS]


# ---------- questions ----------

class Question(BaseModel):
    category: int = Field(ge=1, le=10)
    text: str = Field(min_length=3, max_length=300)
    type: Literal["single", "multi", "text"]
    options: list[str]
    example: str = ""  # only a hint in the UI; DeepSeek sometimes leaves it out

    @model_validator(mode="after")
    def options_match_type(self):
        self.options = [o.strip() for o in self.options if o.strip()]
        if self.type in ("single", "multi") and len(self.options) < 2:
            raise ValueError(f"question '{self.text}' is type {self.type} but has fewer than 2 options")
        if self.type == "text":
            self.options = []
        return self


class QuestionBatch(BaseModel):
    open_gaps: list[str]
    questions: list[Question]
    # DeepSeek JSON mode sometimes drops these trailing fields; the engine also decides
    # from open_gaps and the budget, so a safe default is fine here.
    done: bool = False
    done_reason: str = ""


QUESTION_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        # Listed first so the model names the gaps before writing questions.
        "open_gaps": {"type": "array", "items": {"type": "string"}},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "integer"},
                    "text": {"type": "string"},
                    "type": {"type": "string", "enum": ["single", "multi", "text"]},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "example": {"type": "string"},
                },
                "required": ["category", "text", "type", "options", "example"],
                "additionalProperties": False,
            },
        },
        "done": {"type": "boolean"},
        "done_reason": {"type": "string"},
    },
    "required": ["open_gaps", "questions", "done", "done_reason"],
    "additionalProperties": False,
}


# ---------- rough-prompt judgement ----------

class RoughJudgement(BaseModel):
    stated: list[str]
    detailed: bool


ROUGH_JUDGEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "stated": {"type": "array", "items": {"type": "string"}},
        "detailed": {"type": "boolean"},
    },
    "required": ["stated", "detailed"],
    "additionalProperties": False,
}


# ---------- final prompt ----------

class Addition(BaseModel):
    what: str = Field(min_length=1)
    why: str = Field(min_length=1)


class FinalPrompt(BaseModel):
    final_prompt: str = Field(min_length=20)
    additions: list[Addition] = Field(max_length=6)


FINAL_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        # additions first: it is short, and writing it after a long prompt made DeepSeek drop it.
        "additions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"what": {"type": "string"}, "why": {"type": "string"}},
                "required": ["what", "why"],
                "additionalProperties": False,
            },
        },
        "final_prompt": {"type": "string"},
    },
    "required": ["additions", "final_prompt"],
    "additionalProperties": False,
}


# ---------- checklist ----------

class ChecklistItem(BaseModel):
    id: str
    status: Literal["pass", "fail", "n/a"]
    note: str

    @field_validator("status", mode="before")
    @classmethod
    def normalise_status(cls, v):
        v = str(v).strip().lower()
        return {"na": "n/a", "n.a.": "n/a", "not applicable": "n/a"}.get(v, v)


class Checklist(BaseModel):
    items: list[ChecklistItem]

    @model_validator(mode="after")
    def all_ids_once(self):
        ids = [i.id for i in self.items]
        if sorted(ids) != sorted(CHECKLIST_IDS):
            raise ValueError(f"items must contain each of these ids exactly once: {CHECKLIST_IDS}; got {ids}")
        order = {item_id: n for n, item_id in enumerate(CHECKLIST_IDS)}
        self.items.sort(key=lambda i: order[i.id])
        return self


CHECKLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": CHECKLIST_IDS},
                    "status": {"type": "string", "enum": ["pass", "fail", "n/a"]},
                    "note": {"type": "string"},
                },
                "required": ["id", "status", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}
