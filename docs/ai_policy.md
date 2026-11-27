# Using AI in this tutorial

한국어: [ai_policy_ko.md](ai_policy_ko.md)

You may use AI tools (Claude, ChatGPT, Copilot, Codex and others) **as a tutor, not as an answer key**. The goal of
the course is that you can do and explain earthquake source work yourself. This page says what is allowed, what is
not, how to log AI help, and why.

## Allowed

- Asking what an error message means and where to look for the cause.
- Asking for explanations of concepts, equations, figures and library functions (in Korean too).
- Asking for a review of code **you** wrote: what looks wrong and why.
- Asking for test ideas: small cases you can work out by hand, edge cases, unit checks.
- General Python, NumPy, pandas, Matplotlib, PyGMT, git and shell questions with generic examples.
- Help with plot cosmetics (labels, colors, layout) and with English or Korean wording of your own text.
- Help reading a paper you are reading: a paragraph, an equation or a figure you show it.

## Not allowed

- Letting AI write, complete or fix a **task function** (any function with `# YOUR CODE HERE` or tested by a check),
  even partly.
- Letting AI write your **predictions**, your **Explain** answers or your project **analysis plan**.
- **Looping on the checker**: pasting check output into an AI and trying its suggestions until the check passes.
- Asking AI to **summarize a paper you have not read**.
- Pasting into an AI chat: passwords, tokens, your JupyterLab link, STP or GitHub settings, data files, or anything
  from other people's directories.
- Letting an AI agent start heavy or long jobs on the shared server ([server_manners.md](server_manners.md)).

Tell your AI tool these rules yourself. For example, start a chat with: "I am a student in a course. Explain errors,
ideas and library functions, but do not write, complete or fix my task functions, predictions or Explain answers."
No software enforces this policy; following it is your job.

## The AI log

Keep one file per module in `work/ai_log/`, for example `work/ai_log/M04.md`, and add an entry **every time** AI
help shaped your work. Copy the format from [templates/ai_log_template.md](templates/ai_log_template.md). Each entry
says: date, task id, tool, what you asked, what you used, what you changed and why, and what you still do not
understand. If you used no AI for a module, write one line saying so.

An honest log never counts against you, even when it records a mistake ("I pasted the check output; I should
not have, and here is what I did next"). A missing or dishonest log fails the gate.

## How it is checked

- The **checks** test your functions on cases you cannot memorize (your own random seed).
- The **AI log** is part of every gate.
- The weekly **oral check** ("explain this cell", about 15 minutes): you explain a cell from your work without notes.
  Code you cannot explain is treated as code you did not write.

## Why these rules

Research on students learning with AI points the same way. In a large field experiment with high-school math students,
those who practiced with an unrestricted AI assistant did better during practice but worse once it was taken away,
while a tutor-style version with guardrails reduced that harm (Bastani et al., 2025, *PNAS*,
<https://doi.org/10.1073/pnas.2422633122>). Studies of novice programmers found that AI code generators help some
learners and can leave others with an illusion of competence: the feeling of understanding code they could not
write themselves (Prather et al., 2024, ICER, <https://doi.org/10.1145/3632620.3671116>), and that how a learner uses
the tool, writing first and asking second, matters (Kazemitabaar et al., 2023, CHI,
<https://doi.org/10.1145/3544548.3580919>). For this course that means: think first, write first, then ask.
