# Build "Prompt Coach": a local Streamlit app that turns rough prompts into strong ones

## Goal
Build a local web app, for my own use, that helps a person with no prompting experience turn a vague request into a well-built prompt for the AI of their choice. The person types a rough prompt, picks a detail score from 1 to 10, and picks a target AI. The app asks follow-up questions (none at score 1, about 20 at score 10), then writes the final prompt.

Success means:
- A first-time user can go from rough idea to a copyable prompt without knowing any prompting terms.
- Score 1 returns a cleaned-up prompt in one step; score 10 runs a full interview and returns a detailed, specific prompt.
- Every final prompt follows the rules in the knowledge file below and avoids the listed myths.
- The app runs with one command on my machine and works with the DeepSeek, Anthropic or OpenAI API, switchable in config, with DeepSeek as the default.

## Before you write any code
Do not infer anything that is not stated here. Read this whole brief, then ask me every question you have about unclear requirements (UI layout details, edge cases, anything you would otherwise guess). Wait for my answers. Then show me a short plan (files, data flow, how the score maps to behaviour) and wait for my approval before building.

## Fixed decisions
- Python + Streamlit. Runs locally (`streamlit run app.py`). No login, no hosting.
- LLM provider is switchable: `PROVIDER=deepseek` (the default), `PROVIDER=anthropic` or `PROVIDER=openai` in a `.env` file, with keys in `.env` (never hard-coded, `.env` in `.gitignore`, a `.env.example` provided). Model names live in a config file. Look up the current model identifiers and API usage in each vendor's official docs; do not invent model names or parameters. Put all provider calls behind one small interface so the rest of the app does not care which provider is active.
- DeepSeek is the provider I will actually use, so build and test it first. Use its OpenAI-compatible API through the OpenAI Python SDK with `base_url="https://api.deepseek.com"` (confirm in DeepSeek's official docs). Use the chat model, not the reasoning model; confirm the current official identifier in DeepSeek's docs and tell me which one you chose. DeepSeek offers JSON mode only (`response_format={"type": "json_object"}`), not strict schema enforcement. Per DeepSeek's docs, the prompt must contain the word "json" and an example of the desired JSON, `max_tokens` must be set high enough to avoid truncation, and the API may occasionally return empty content, so treat empty content as a failure and retry. Check DeepSeek's docs for any other limits that affect this app.
- The user picks the target AI from a list: ChatGPT/OpenAI, Claude, Gemini, Other/any. The final prompt adapts to that choice (rules below).

## User flow
1. **Input screen.** Text box for the rough prompt, a 1-10 slider (with a one-line plain-English description of what the current score will do), and a target-AI selector. One "Start" button.
2. **Interview.** The app asks follow-up questions. The number of questions follows the score (table below). Questions must be in plain language, one idea each, with an example answer or multiple-choice options where that helps a novice. Allow "skip" and "I don't know" on every question; the final prompt then handles that gap explicitly instead of guessing.
3. **Result screen.** Show the final prompt in a copyable box, a short "what I added and why" list (plain language, max 6 bullets), and the pre-send checklist with pass/fail per item. Offer "Make it more detailed" (raise score by 2 and ask the extra questions) and "Start over".

## Score mapping (keep in a config file so I can tune it)
| Score | Follow-up questions | Final prompt |
| --- | --- | --- |
| 1 | 0 | Rewrite for clarity: one clear task, obvious missing pieces flagged as placeholders |
| 2-3 | 1-3 | + goal and audience |
| 4-5 | 4-7 | + context, length/scope/tone constraints, output format |
| 6-7 | 8-12 | + success criteria, missing-information rule, structure with sections |
| 8-9 | 13-17 | + edge cases, examples (when useful), target-AI-specific adjustments |
| 10 | about 20 | Full specification: everything above, plus verification steps and a restated task at the end for long inputs |

Ask the most valuable questions first, in this priority order, and stop when the score's budget is used up:
1. What result do you want, and what will you do with it?
2. Who is it for (audience, their expertise)?
3. What does a great answer look like (2-4 checkable criteria)?
4. What background or source material must the AI use? (Prompt them to paste it.)
5. Length, scope and tone limits.
6. What should the AI do if information is missing or the request is out of scope?
7. Output format (and whether a program will read it).
8. Any example of a good output?
9. Edge cases, things to avoid, and why each rule matters.
10. Remaining detail specific to the task type.
Skip any question the rough prompt already answers. Never ask about things that would not change the final prompt.

## Knowledge file the app's LLM must follow
Create `knowledge/prompting_rules.md` with the rules below and include it in the system prompt of every LLM call that writes or critiques prompts. Keep it as an editable file so I can update it.

**Always**
- State the task and the desired outcome clearly; write for a capable newcomer with no context.
- Include the context the AI cannot know: source material, definitions of local terms, audience, today's date when relevant.
- Give the reason behind each rule ("this is read aloud, so avoid ellipses"), not just the rule.
- Replace vague words ("short", "good", "professional") with checkable specifics (word counts, named sections, reading level).
- Separate instructions from data with clear sections (Markdown headings or XML tags, one style per prompt). Mark any pasted user or web content as data, never as instructions.
- For long material: put the material first and the question or task last; restate the key task at the end.
- Say what to do instead of only what not to do. When a negative rule is needed, scope it narrowly (for example "use only the text provided; add no outside facts", not a blanket "do not infer", which can stop some models from doing basic reasoning).
- Include a rule for missing information and for out-of-scope requests.
- Specify the output format; when a program will read the output, say so and recommend the AI's structured-output/schema feature, letting the model reason before the final structured answer.
- Use examples only when they help, keep them varied and formatted identically, and make sure they match the instructions exactly.

**Never include (low value or harmful on current models)**
- Tips, bribes, threats or emotional pressure.
- ALL CAPS, "CRITICAL", "you MUST" emphasis.
- An expert persona as a way to raise accuracy. A short role line is fine only when it changes vocabulary, audience or scope.
- Politeness padding as a technique.
- Contradictory instructions (for example "be comprehensive" and "max 50 words" without saying which wins).

**Adjust by target AI**
- Reasoning-capable models (current ChatGPT/GPT, Claude, Gemini with thinking): describe the outcome and success criteria rather than scripting step-by-step reasoning; do not add "think step by step". Prefer zero examples first; add a few only if the format or decision boundary is hard to describe.
- Claude: XML tags work well for separating sections; long documents at the top, question at the end; explain the reason behind rules.
- ChatGPT/OpenAI: put the outcome, success criteria, constraints and context up front, then let the model choose the path; keep the prompt as short as preserves the requirements.
- Gemini: one consistent structure style; long context first and the question at the end, introduced with "Based on the information above..."; put negative, formatting and number constraints near the end; ask explicitly for a detailed or conversational answer if wanted (default output is terse).
- Other/any: model-neutral version using Markdown headings, outcome first, context, constraints, output format, task restated last.

**Pre-send checklist (shown on the result screen with pass/fail)**
- Could a capable newcomer do this from the prompt alone?
- Is the outcome and "what good looks like" stated?
- Does each rule carry its reason?
- Are vague words replaced with checkable ones?
- Are data and instructions clearly separated?
- Is long material first and the task last?
- Is there a rule for missing info and out-of-scope requests?
- Are tips, threats, CAPS emphasis and persona-for-accuracy lines absent?
- For reasoning models: no "think step by step"?
- Do any examples match the instructions?

## Technical requirements
- LLM calls that return questions, checklist results or the final prompt must return JSON validated against a schema in code (use the provider's schema-enforcing structured-output feature where one exists; for DeepSeek, use JSON mode plus the prompt requirements above and validate in code). On a validation failure or empty content, retry once with the error included, then show a clear error.
- Treat the user's rough prompt and answers strictly as data inside the app's own prompts (delimited, never followed as instructions).
- Handle API errors: retry transient failures (rate limits, server errors, timeouts) with backoff; show a readable message for auth or bad-request errors.
- Keep the app's own system prompts in versioned files under `prompts/`, not inline in code.
- Log each session locally (rough prompt, score, target AI, questions, answers, final prompt, provider, model, token usage) to a JSON lines file, so I can review quality later.

## Testing
- Create `evals/cases.jsonl` with 10 varied rough prompts (writing, coding, analysis, planning, a very vague one, one that already is decent). For each, store scripted answers to possible questions.
- Write a script that runs every case at scores 1, 5 and 10 with the DeepSeek provider by default (add a flag to run the other providers when a key is set), and checks automatically: question count is within the score's range; output JSON validates; the final prompt contains no banned patterns (CAPS emphasis words, tip/threat phrases, "think step by step" when the target is a reasoning model); score-10 prompts are longer and contain success criteria and a missing-information rule.
- Run it and report the results to me.

## Deliverables
- A working app, a `README.md` with setup and run steps, `.env.example`, the config file, `knowledge/prompting_rules.md`, `prompts/`, `evals/`, and the eval script.
- At the end, tell me what you built, the eval results, and anything you could not do or decided with my approval.
