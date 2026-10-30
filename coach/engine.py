"""The coaching pipeline: questions -> final prompt -> checklist -> optional revision."""
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ValidationError

from coach import lint as linter
from coach.config import band_for, features_for, load_config, target_for
from coach.prompts_loader import interview_text, prompt_version, settings_block, system_prompt, tag
from coach.providers import CoachError, EmptyOrTruncated, Provider
from coach.schemas import (CHECKLIST_ITEMS, CHECKLIST_SCHEMA, FINAL_PROMPT_SCHEMA, QUESTION_BATCH_SCHEMA,
                           ROUGH_JUDGEMENT_SCHEMA, Checklist, FinalPrompt, QuestionBatch, RoughJudgement)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass
class QuestionStep:
    questions: list[dict]
    done: bool
    reason: str
    rough_detailed: bool | None  # the model's judgement of the rough prompt, kept for later batches


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

    def judge_rough(self, rough: str) -> bool:
        """Was the rough prompt already detailed? Judged once per session, without the score."""
        judgement = self._structured("judge", tag("rough_prompt", rough), "rough_judgement",
                                     ROUGH_JUDGEMENT_SCHEMA, RoughJudgement)
        self.calls[-1].update(rough_prompt_detailed=judgement.detailed, stated=judgement.stated)
        return judgement.detailed

    def next_questions(self, rough: str, score: int, target_key: str, qa: list[dict],
                       rough_detailed: bool | None = None, batch_size: int | None = None) -> QuestionStep:
        """Ask for the next batch. rough_detailed is the judgement from the first batch (None before it).

        The score's minimum is enforced only when the rough prompt was judged vague; a detailed
        rough prompt may stop early once nothing useful is left to ask.
        """
        band = band_for(score)
        remaining = band["max_questions"] - len(qa)
        if remaining <= 0:
            return QuestionStep([], True, "question budget for this score is used up", rough_detailed)
        n = min(batch_size or load_config()["interview"]["batch_size"], remaining)
        detailed = rough_detailed if rough_detailed is not None else self.judge_rough(rough)

        def ask(push: str = "") -> QuestionBatch:
            still_needed = 0 if detailed else max(0, band["min_questions"] - len(qa))
            parts = [
                settings_block({
                    "detail_score": f"{score} of 10",
                    "target_ai": target_for(target_key)["label"],
                    "questions_asked_so_far": len(qa),
                    "batch_maximum": n,
                    "overall_minimum": band["min_questions"],
                    "overall_maximum": band["max_questions"],
                    "rough_prompt_detailed": str(detailed).lower(),
                    "minimum_enforced": "yes" if still_needed else "no",
                    "questions_still_needed_for_minimum": still_needed,
                    "required_features": features_for(score),
                }),
                tag("rough_prompt", rough),
                tag("interview_so_far", interview_text(qa)),
            ]
            if push:
                parts.append(push)
            batch = self._structured("questions", "\n\n".join(parts), "question_batch",
                                     QUESTION_BATCH_SCHEMA, QuestionBatch)
            self.calls[-1]["open_gaps"] = batch.open_gaps
            return batch

        def new_questions(batch: QuestionBatch) -> list[dict]:
            asked = {item["question"].strip().lower() for item in qa}
            out = []
            for q in batch.questions:
                if q.text.strip().lower() in asked or len(out) >= n:
                    continue
                asked.add(q.text.strip().lower())
                out.append({"id": uuid.uuid4().hex[:8], **q.model_dump()})
            return out

        batch = ask()
        has_gaps = any(g.strip() for g in batch.open_gaps)
        questions = new_questions(batch) if (has_gaps or not detailed) else []
        below_min = len(qa) + len(questions) < band["min_questions"]

        if not detailed and below_min and len(questions) < n:
            # The model wanted to stop, but a vague rough prompt must reach the minimum: ask once more.
            still_needed = band["min_questions"] - len(qa) - len(questions)
            push = ("<minimum_not_reached>\nThe rough prompt was judged vague, so this interview must reach "
                    f"the overall minimum. Return {min(n, still_needed + len(questions))} questions in total for "
                    "this batch by going deeper at this score's level (success criteria, edge cases and things "
                    "to avoid, task-specific details), without rewording any earlier question.\n"
                    "</minimum_not_reached>")
            retry = new_questions(ask(push))
            if len(retry) > len(questions):
                questions = retry
            below_min = len(qa) + len(questions) < band["min_questions"]

        total = len(qa) + len(questions)
        if not questions or total >= band["max_questions"]:
            done = True
        elif not detailed and below_min:
            done = False
        else:
            done = batch.done or not has_gaps
        return QuestionStep(questions, done, batch.done_reason, detailed)

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
    rough_detailed = None
    while not done:
        step = coach.next_questions(rough, score, target_key, qa, rough_detailed)
        done, rough_detailed = step.done, step.rough_detailed
        for q in step.questions:
            status, answer = answer_fn(q)
            qa.append({"id": q["id"], "category": q["category"], "question": q["text"],
                       "type": q["type"], "options": q["options"], "status": status, "answer": answer})
    return qa, coach.finalize(rough, score, target_key, qa)
