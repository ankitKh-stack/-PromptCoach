"""The coaching pipeline: questions -> final prompt -> checklist -> optional revision."""
import json
import re
import uuid
from datetime import date

from pydantic import BaseModel, ValidationError

from coach import lint as linter
from coach.config import band_for, features_for, load_config, target_for
from coach.prompts_loader import interview_text, prompt_version, settings_block, system_prompt, tag
from coach.providers import CoachError, EmptyOrTruncated, Provider
from coach.schemas import (CHECKLIST_ITEMS, CHECKLIST_SCHEMA, FINAL_PROMPT_SCHEMA, QUESTION_BATCH_SCHEMA,
                           Checklist, FinalPrompt, QuestionBatch)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class Coach:
    def __init__(self, provider: Provider):
        self.provider = provider
        self.calls: list[dict] = []

    # ---------- plumbing ----------

    def _structured(self, step: str, user: str, schema_name: str, schema: dict, model_cls: type[BaseModel]):
        """Call the provider, validate against the schema, retry once with the error included."""
        system = system_prompt(step)
        message = user
        error = ""
        for attempt in (1, 2):
            call = {"step": step, "prompt_file": prompt_version(step), "attempt": attempt,
                    "input_tokens": 0, "output_tokens": 0, "ok": False}
            self.calls.append(call)
            try:
                text, usage = self.provider.complete_json(system, message, schema_name, schema)
                call["input_tokens"], call["output_tokens"] = usage.input_tokens, usage.output_tokens
                parsed = model_cls.model_validate(json.loads(_FENCE.sub("", text.strip())))
                call["ok"] = True
                return parsed
            except EmptyOrTruncated as exc:
                error = str(exc)
            except json.JSONDecodeError as exc:
                error = f"the reply was not valid JSON ({exc})"
            except ValidationError as exc:
                error = f"the JSON did not match the required shape: {exc.errors(include_url=False)}"
            call["error"] = error
            message = (user + "\n\n<validation_error>\nYour previous reply could not be used: " + error +
                       "\nReply again with a single json object in exactly the shape shown in the instructions."
                       "\n</validation_error>")
        raise CoachError(f"The AI's reply could not be used even after a retry (step: {step}). Details: {error}")

    def usage_totals(self) -> dict:
        return {"input_tokens": sum(c["input_tokens"] for c in self.calls),
                "output_tokens": sum(c["output_tokens"] for c in self.calls),
                "calls": len(self.calls)}

    # ---------- questions ----------

    def next_questions(self, rough: str, score: int, target_key: str, qa: list[dict],
                       batch_size: int | None = None) -> tuple[list[dict], bool, str]:
        """Return (new questions, interview_done, done_reason)."""
        band = band_for(score)
        remaining = band["max_questions"] - len(qa)
        if remaining <= 0:
            return [], True, "question budget for this score is used up"
        n = min(batch_size or load_config()["interview"]["batch_size"], remaining)
        user = "\n\n".join([
            settings_block({
                "detail_score": f"{score} of 10",
                "target_ai": target_for(target_key)["label"],
                "questions_asked_so_far": len(qa),
                "batch_maximum": n,
                "overall_minimum": band["min_questions"],
                "overall_maximum": band["max_questions"],
            }),
            tag("rough_prompt", rough),
            tag("interview_so_far", interview_text(qa)),
        ])
        batch = self._structured("questions", user, "question_batch", QUESTION_BATCH_SCHEMA, QuestionBatch)
        asked = {item["question"].strip().lower() for item in qa}
        questions = []
        for q in batch.questions:
            if q.text.strip().lower() in asked or len(questions) >= n:
                continue
            asked.add(q.text.strip().lower())
            questions.append({"id": uuid.uuid4().hex[:8], **q.model_dump()})
        done = batch.done or not questions or len(qa) + len(questions) >= band["max_questions"]
        return questions, done, batch.done_reason

    # ---------- final prompt ----------

    def _prompt_settings(self, score: int, target_key: str) -> dict:
        target = target_for(target_key)
        return {
            "detail_score": f"{score} of 10",
            "target_ai": target["label"],
            "target_is_reasoning_model": "yes" if target["reasoning"] else "unknown (write a model-neutral prompt)",
            "today": date.today().isoformat(),
            "required_features": features_for(score),
        }

    def write_final(self, rough: str, score: int, target_key: str, qa: list[dict]) -> FinalPrompt:
        user = "\n\n".join([
            settings_block(self._prompt_settings(score, target_key)),
            tag("rough_prompt", rough),
            tag("interview", interview_text(qa)),
        ])
        return self._structured("final_prompt", user, "final_prompt", FINAL_PROMPT_SCHEMA, FinalPrompt)

    def check(self, prompt_text: str, target_key: str) -> list[dict]:
        target = target_for(target_key)
        user = "\n\n".join([
            settings_block({"target_ai": target["label"],
                            "target_is_reasoning_model": "yes" if target["reasoning"] else "no"}),
            tag("prompt_to_review", prompt_text),
        ])
        checklist = self._structured("checklist", user, "checklist", CHECKLIST_SCHEMA, Checklist)
        labels = dict(CHECKLIST_ITEMS)
        items = {i.id: {"id": i.id, "label": labels[i.id], "status": i.status, "note": i.note}
                 for i in checklist.items}

        # Code checks are authoritative for the banned patterns.
        found = linter.lint(prompt_text, target["reasoning"])
        if found["caps"] or found["pressure"]:
            items["no_pressure"].update(status="fail", note="Found: " + ", ".join(
                f'"{h}"' for h in found["caps"] + found["pressure"]))
        if not target["reasoning"]:
            items["no_step_by_step"].update(status="n/a", note="The target is not known to be a reasoning model.")
        elif found["step_by_step"]:
            items["no_step_by_step"].update(status="fail", note="Found: " + ", ".join(
                f'"{h}"' for h in found["step_by_step"]))
        return [items[item_id] for item_id, _ in CHECKLIST_ITEMS]

    def revise(self, rough, score, target_key, qa, current: FinalPrompt, failed: list[dict]) -> FinalPrompt:
        failed_text = "\n".join(f"- {f['id']} ({f['label']}): {f['note']}" for f in failed)
        additions_text = "\n".join(f"- {a.what}: {a.why}" for a in current.additions)
        user = "\n\n".join([
            settings_block(self._prompt_settings(score, target_key)),
            tag("rough_prompt", rough),
            tag("interview", interview_text(qa)),
            tag("current_prompt", current.final_prompt),
            tag("current_additions", additions_text or "(none)"),
            "<failed_items>\n" + failed_text + "\n</failed_items>",
        ])
        return self._structured("revise", user, "final_prompt", FINAL_PROMPT_SCHEMA, FinalPrompt)

    def finalize(self, rough: str, score: int, target_key: str, qa: list[dict]) -> dict:
        """Write the final prompt, check it, and revise once if any item fails."""
        result = self.write_final(rough, score, target_key, qa)
        checklist = self.check(result.final_prompt, target_key)
        failed = [c for c in checklist if c["status"] == "fail"]
        revised = False
        if failed:
            candidate = self.revise(rough, score, target_key, qa, result, failed)
            candidate_checklist = self.check(candidate.final_prompt, target_key)
            if sum(c["status"] == "fail" for c in candidate_checklist) <= len(failed):
                result, checklist, revised = candidate, candidate_checklist, True
        return {
            "final_prompt": result.final_prompt,
            "additions": [a.model_dump() for a in result.additions],
            "checklist": checklist,
            "revised": revised,
        }


def run_headless(coach: Coach, rough: str, score: int, target_key: str, answer_fn,
                 qa: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Run a full session without the UI. answer_fn(question) -> (status, answer)."""
    qa = list(qa or [])
    done = band_for(score)["max_questions"] <= len(qa)
    while not done:
        questions, done, _ = coach.next_questions(rough, score, target_key, qa)
        for q in questions:
            status, answer = answer_fn(q)
            qa.append({"id": q["id"], "category": q["category"], "question": q["text"],
                       "type": q["type"], "options": q["options"], "status": status, "answer": answer})
    return qa, coach.finalize(rough, score, target_key, qa)
