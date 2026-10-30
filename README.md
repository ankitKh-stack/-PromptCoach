# Prompt Coach

A local Streamlit app that turns a rough prompt into a well-built one. You type what you want, pick a
detail score (1-10) and the AI you'll paste the prompt into. The app asks plain-language follow-up
questions (none at score 1, about 20 at score 10), then writes the final prompt, explains what it
added, and runs a pre-send checklist.

## Setup (Windows, Python 3.12+)

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add the key for your provider:

```
PROVIDER=deepseek          # or anthropic / openai
DEEPSEEK_API_KEY=sk-...
```

## Run

```bash
.venv\Scripts\streamlit run app.py
```

The app opens at http://localhost:8501. The sidebar shows the active provider and model.

## Providers

| PROVIDER | Model (config.yaml) | Structured output |
| --- | --- | --- |
| `deepseek` (default) | `deepseek-flash`, thinking disabled (chat mode) | JSON mode + example in prompt, validated in code |
| `anthropic` | `claude-sonnet-5-5` | `output_config.format` JSON Schema, validated in code |
| `openai` | `gpt-6.1-sol` | Responses API strict JSON Schema, validated in code |

Every call is validated with Pydantic. On empty, truncated or invalid output the app retries once
with the error included, then shows a clear message. Rate limits, server errors and timeouts are
retried with exponential backoff (`request` in `config.yaml`).

## How many questions are asked

At the start of each session, one small call (`prompts/judge.v1.md`) decides whether the rough
prompt is already detailed: does it state at least 4 of goal, audience, material, format and
constraints? The score is not part of this judgement.

- **Vague rough prompt:** the interview must reach the score's minimum (`min_questions`). If the
  model tries to stop early, the code asks it once more for deeper questions.
- **Detailed rough prompt:** the interview stops as soon as nothing left would change the final
  prompt, even below the minimum.
- **Either way:** it never goes over `max_questions`.

## What you can tune without touching code

- `config.yaml` — models, max tokens, score bands (question ranges, features, slider descriptions),
  target AIs, banned-pattern lists, batch size, long-input warning.
- `knowledge/prompting_rules.md` — the rules included in every prompt-writing and checking call.
- `prompts/*.vN.md` — the app's system prompts. To change one, copy it to the next version and
  update `PROMPT_FILES` in `coach/prompts_loader.py`; logs record which file was used. Older
  versions are kept for comparison.

## Layout

```
app.py                  Streamlit UI: input → interview → review → result
coach/providers.py      provider interface (DeepSeek / Anthropic / OpenAI), retries, error messages
coach/engine.py         questions, final prompt, checklist, one automatic revision
coach/schemas.py        JSON Schemas + Pydantic validators
coach/lint.py           code checks for CAPS emphasis, tips/threats, "think step by step"
coach/prompts_loader.py loads prompts and wraps user text as delimited data
coach/logger.py         session log
evals/                  test cases and eval runner
logs/sessions.jsonl     one line per finished session (git-ignored)
```

## Evals

```bash
.venv\Scripts\python evals\run_evals.py
```

Runs the 10 cases in `evals/cases.jsonl` at scores 1, 5 and 10 with DeepSeek and checks question
counts, JSON validity, banned patterns, and that score-10 prompts are longer and contain success
criteria and a missing-information rule. Add `--providers deepseek,anthropic,openai` to include other
providers (skipped if their key isn't set), or `--cases vague_help --scores 10` to run a subset.
Full output goes to `evals/results.jsonl`.
