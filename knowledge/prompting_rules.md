# Prompting rules

These rules are included in the system prompt of every call that writes or critiques prompts.
Edit this file to change the app's behaviour; no code change is needed.

## Always
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

## Never include (low value or harmful on current models)
- Tips, bribes, threats or emotional pressure.
- ALL CAPS, "CRITICAL", "you MUST" emphasis.
- An expert persona as a way to raise accuracy. A short role line is fine only when it changes vocabulary, audience or scope.
- Politeness padding as a technique.
- Contradictory instructions (for example "be comprehensive" and "max 50 words" without saying which wins).

## Adjust by target AI
- Reasoning-capable models (current ChatGPT/GPT, Claude, Gemini with thinking): describe the outcome and success criteria rather than scripting step-by-step reasoning; do not add "think step by step". Prefer zero examples first; add a few only if the format or decision boundary is hard to describe.
- Claude: XML tags work well for separating sections; long documents at the top, question at the end; explain the reason behind rules.
- ChatGPT/OpenAI: put the outcome, success criteria, constraints and context up front, then let the model choose the path; keep the prompt as short as preserves the requirements.
- Gemini: one consistent structure style; long context first and the question at the end, introduced with "Based on the information above..."; put negative, formatting and number constraints near the end; ask explicitly for a detailed or conversational answer if wanted (default output is terse).
- Other/any: model-neutral version using Markdown headings, outcome first, context, constraints, output format, task restated last.

## Pre-send checklist
1. Could a capable newcomer do this from the prompt alone?
2. Is the outcome and "what good looks like" stated?
3. Does each rule carry its reason?
4. Are vague words replaced with checkable ones?
5. Are data and instructions clearly separated?
6. Is long material first and the task last?
7. Is there a rule for missing info and out-of-scope requests?
8. Are tips, threats, CAPS emphasis and persona-for-accuracy lines absent?
9. For reasoning models: no "think step by step"?
10. Do any examples match the instructions?
