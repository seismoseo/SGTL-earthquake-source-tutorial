# Analysis plan: the Suncheon earthquakes

- Author: [write here]
- Started: {{date}}
- Mentor sign-off: [write here: your mentor's name and the day they signed off this plan, as "Name, YYYY-MM-DD"]
- Frozen on: [write here: the date you freeze this plan, YYYY-MM-DD]
- MD5 checksum of `criteria.yaml` at the freeze: [write here: 32 hexadecimal characters]

How to use this file: answer every question in your own words, under the question, and replace each placeholder
(square brackets that start with "write here") with your answer. The questions are the lines that start with `>`;
keep them as they are: they show the reader what you were asked, and the check of module M60 looks for them. Before
the freeze, your mentor reads this plan and `criteria.yaml` and writes the sign-off line above (their name and the
day). After the freeze, change nothing above the section "Amendments": add a dated amendment instead.

## 1. Questions

> - Which questions about the Suncheon earthquakes do you want to answer? Write each one so that a number, with an
>   uncertainty, answers it.

[write here]

> - Which question comes first, and why? Which one would you drop if time runs short?

[write here]

## 2. Prior exposure

> - What have you already seen about Suncheon before writing this plan: papers (which sections and figures), catalog
>   plots, your M60 inventory, talks, conversations? Which of these could have shaped your hypotheses or your choice
>   of tests?

[write here]

## 3. Hypotheses

Each hypothesis starts from a question that a source raises; the source is named under its heading. Write the
hypothesis in your own words, as a statement that your test can support or reject.

### H1 · Depth groups

Source: the KMA catalog that ships with the course (the subset `suncheon`). The catalog depths suggest a main group
near 10 km and a smaller set at 20 km or deeper (your M60 inventory prints the counts). The question: are there two
depth populations, and are both real, not made by the location method, the velocity model or the stations that
recorded each era?

> - What exactly does "two populations" mean in numbers (which depths, how many events, how far apart)?

[write here]

> - Which test will you use, on which events, with which stations and phases? What does it assume?

[write here]

> - Which result would support H1, and which would make you reject it? (Write the numbers into `criteria.yaml`.)

[write here]

> - Which other explanations could make two depth groups appear when there is only one (or hide a real second
>   group)? How will you tell them apart?

[write here]

### H2 · The geometry of the persistent cluster

Source: the KMA catalog that ships with the course, and Kwak et al. (2022) (reference key `kwak2022`; its claims go
into `claims.csv`). The question: is the persistent cluster about 10 km west-northwest of Suncheon one plane, and if
so, what are its strike and dip?

> - How will you decide which events belong to that cluster, before you look at the relocated positions?

[write here]

> - How will you measure whether the events lie on one plane, and its strike and dip (which method, which
>   uncertainty)?

[write here]

> - Which result would support one plane, and which would make you reject it? (Write the numbers into
>   `criteria.yaml`.)

[write here]

> - Which other explanations could make a cluster look like one plane (or not), or tilt the fitted plane? How will
>   you tell them apart?

[write here]

## 4. Data

> - Which events, which years, which stations and which phases will you use? Use the numbers of your M60 inventory.

[write here]

> - Which velocity model will you locate with? For your deepest event in that model, compute the crossover distance
>   per phase, P and S, for every boundary below the source (your `head_wave` of module M30, task 2), and write the
>   numbers here. Does your locator predict the direct wave only, or the first arrival (module M32)? Which stations
>   does that leave you?

[write here]

> - What does the station coverage of each era allow, and what does it not allow?

[write here]

## 5. Methods and order of the work

> - Which steps, in which order, with which tools and settings? For each step: what is its independent check?

[write here]

> - What will you run first on synthetic data with a known answer?

[write here]

## 6. Tests and criteria

> - For each hypothesis: the test, the number it gives, the threshold and the decision rule. They must equal the
>   entries of `criteria.yaml`.

[write here]

## 7. What would change the conclusion

> - Which single result, setting or data problem would change your conclusion about H1? About H2?

[write here]

> - Which settings will you change one at a time to see whether the conclusion holds?

[write here]

## 8. Risks and fallbacks

> - What could stop the plan (data, tools, time), and what will you do then?

[write here]

## Amendments

Add one row for every change after the freeze. Never delete a row.

| date (YYYY-MM-DD) | what changed | why | had you seen results that bear on it? |
|---|---|---|---|
