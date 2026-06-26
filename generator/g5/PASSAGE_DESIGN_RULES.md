# PASSAGE DESIGN RULES — Making MCQ Items Genuinely Passage-Dependent

## The Problem

The root failure mode in generated reading assessments is passage leak: items that can be answered correctly by a student who studied the topic in school but never read the specific passage. This happens when passages summarize well-documented curriculum content — famous scientists, standard scientific processes, major historical events with known outcomes — because the answer lives in the student's prior knowledge, not in the text. The passage becomes decorative. Any item that tests a fact the student already carries is measuring background knowledge, not reading comprehension. The fix is not to write harder distractors; it is to write passages that carry information the student cannot have encountered before opening this specific text.

## The Test Question

> **Could a student who studied this topic in school — but never read this specific passage — answer every one of my questions correctly using only prior knowledge?**
>
> If the answer is YES for any item, the passage is leaking. Do not patch the item — fix the passage first.

---

## The 8 Rules

---

### P1 — Hinge on a specific character's decision, reaction, or moment of doubt

**Rule:** Every passage must hinge on a specific character's decision, reaction, or moment of doubt that is not predictable from general knowledge about the topic.

**Rationale:** Decisions and reactions are unique to the story being told. A student who knows Marie Curie was a famous chemist cannot guess that in THIS passage she almost quit her research after a particular lab setback — so any question about that decision forces reading.

**Good example:**
> After three failed attempts to isolate radium, Marie Curie wrote in her notebook that she had considered abandoning the project and returning to teaching. Her husband Pierre's single argument — "the element is there; we simply have not been patient enough" — changed her mind.

**Bad example:**
> Marie Curie was a pioneering chemist who discovered radium and polonium. She was the first woman to win a Nobel Prize.

---

### P2 — Take an explicit argumentative stance

**Rule:** Every passage must take an explicit argumentative stance or present an author's opinion on a debatable question, not merely report settled facts.

**Rationale:** Facts are retrievable from prior knowledge; an opinion embedded in this passage is not. A question testing whether the student grasped the author's specific position cannot be answered from memory.

**Good example:**
> Despite its cost, the author argues that the Transcontinental Railroad was a net harm to the Great Plains ecosystem because the speed of construction prevented any meaningful environmental survey — a claim many historians dispute.

**Bad example:**
> The Transcontinental Railroad was completed in 1869 when workers from the Central Pacific and Union Pacific met at Promontory Summit, Utah.

---

### P3 — Anchor to a non-headline specific figure

**Rule:** Anchor at least one central claim to a specific number, date, proportion, or measurement that is NOT the famous headline figure for the topic.

**Rationale:** Famous headline figures (speed of light, boiling point of water, year of the moon landing) are pre-loaded in student memory. An obscure but specific figure forces reading and makes the correct answer inaccessible without the text.

**Good example:**
> Monarch butterflies cluster at roughly 27.5 million individuals at the Michoacan overwintering sites in a strong year, down from an estimated 682 million in the early 1990s — a 96% collapse the passage attributes specifically to herbicide-resistant crop expansion.

**Bad example:**
> Monarch butterflies migrate thousands of miles every year from Canada to Mexico. Scientists are concerned their numbers are declining.

---

### P4 — Include a counterintuitive or surprising consequence

**Rule:** Include at least one counterintuitive or surprising consequence — something that contradicts the obvious expectation a student would bring to the topic.

**Rationale:** Students answer from schema. If the passage delivers information that violates the expected schema, only a reader who encountered the surprise can answer correctly. The surprise functions as a passage key.

**Good example:**
> When the Chestnut blight killed virtually every American chestnut tree by 1950, it unexpectedly benefited a competing species — the red maple — so dramatically that today red maple is the most common hardwood in the eastern United States, a dominance the passage attributes entirely to the blight.

**Bad example:**
> The American chestnut tree was nearly wiped out by a fungal blight introduced from Asia in the early 1900s. Scientists are working to restore the species.

---

### P5 — Build around a non-obvious comparison

**Rule:** Build the passage around a specific comparison between two named things where the outcome or winner is non-obvious and depends on criteria introduced in the passage.

**Rationale:** General comparisons ("A is faster than B") may already be known. When the passage invents its own evaluative criteria and applies them to a pair, the conclusion is traceable only through the text — not prior knowledge.

**Good example:**
> When judged by water consumption per kilogram of food produced, almonds require nearly four times as much water as beef cattle — a reversal of the common public perception that meat production is always the more resource-intensive choice.

**Bad example:**
> Beef production requires a lot of land and water. Many people are switching to plant-based diets to help the environment.

---

### P6 — Set in a specific, less-documented time and place

**Rule:** Set the passage in a specific, less-documented time and place so that the context itself is unfamiliar, not merely the topic.

**Rationale:** Well-documented events (the moon landing, World War II, the American Revolution) are curriculum staples. A less-documented setting guarantees that the specific details — cause, outcome, participants — are new to the reader and cannot be recalled from prior study.

**Good example:**
> In 1783, a volcanic eruption in Iceland known as the Laki fissure eruption released enough sulfur dioxide to lower summer temperatures across Europe by 1.3 degrees Celsius, triggering crop failures that historians now link to the social unrest preceding the French Revolution.

**Bad example:**
> Volcanoes are powerful natural events. Famous volcanic eruptions include Mount Vesuvius and Mount St. Helens.

---

### P7 — Assign a specific motivation, belief, or misconception to a named person or group

**Rule:** Assign a specific motivation, belief, or misconception to a named individual or group within the passage, and make that motivation the object of at least one question.

**Rationale:** Motivations are internal to the narrative; they cannot be looked up. Even if the historical figure is famous, their specific reasoning as presented in this passage is constructed here and retrievable only here.

**Good example:**
> Chief Plenty Coups agreed to lead Crow warriors as scouts for the U.S. Army not out of loyalty to the government, the passage explains, but because he believed that allying with the stronger power was the only path to preserving Crow territory — a bet he later judged a partial failure in his autobiography.

**Bad example:**
> Many Native American tribes were forced to sign treaties with the United States government during the 19th century. These treaties often took away their land.

---

### P8 — Make the organizing structure itself carry information

**Rule:** Make the passage's organizing structure itself carry information — sequence, ranking, or cause-chain — so that positional relationships (first, caused, led to, more than) are testable and text-bound.

**Rationale:** When the answer depends on the order of events, the ranking of effects, or the specific link in a causal chain as the passage lays it out, the student must trace the structure of this text rather than retrieve a memorized fact.

**Good example:**
> The passage presents a four-step chain: invasive zebra mussels filter the water, clearer water lets sunlight penetrate deeper, deeper sunlight grows more aquatic plants, and denser plant beds crowd out the native fish nurseries — with the passage specifying that removing step two would break the entire chain.

**Bad example:**
> Invasive species can harm ecosystems. The zebra mussel is one example of an invasive species that has spread through the Great Lakes.

---

## Prompt Addition for Abdul's Generator

```
## PASSAGE-NECESSITY RULES

Every passage you generate must be passage-dependent: a student who studied this topic in school should be UNABLE to answer the questions without reading THIS specific passage. The rules below define how to achieve that.

### Passages that produce leaked items — AVOID these

**Curriculum-fact passages** summarize well-documented topics: famous scientists and their discoveries, major historical events with known outcomes, standard definitions of scientific terms, or consensus positions on environmental issues. These topics are taught in grades K-8 and any student who paid attention in class already carries the answer. Questions built on these passages test background knowledge, not reading.

**Headline-figure passages** anchor around the famous number or date everyone knows: the year of the moon landing, the speed of light, the boiling point of water, the population of a major country. These figures are pre-loaded. A student does not need the passage to retrieve them.

**Summary-of-a-famous-person passages** list what a well-known figure did, achieved, or was known for. The biography of Marie Curie, Neil Armstrong, or Frederick Douglass is curriculum content. Any question about "what was this person famous for" can be answered without the text.

**Generic-process passages** explain how a standard process works — photosynthesis, the water cycle, plate tectonics — using only the textbook explanation. Students have seen these processes described dozens of times. No new angle, no new information, no leak prevention.

### Passages that produce passage-dependent items — USE these

**Decision-and-reaction passages** place a specific individual at a moment of choice or emotional response. The character's specific reasoning, doubt, or reversal is only accessible through this passage. Questions about that decision cannot be answered from memory.

**Argument-stance passages** take an explicit, debatable position on a question where reasonable people disagree. The author's specific claim, the evidence marshaled to support it, and the concession made to the opposing view are all created inside this text. Questions testing whether the student understood the stance are passage-keyed.

**Obscure-consequence passages** treat a famous event or phenomenon, but approach it from a side the student has not encountered in school: the ecological aftermath of a well-known disaster, the economic ripple from a famous law, the unintended beneficiary of a celebrated invention. The famous event is the hook; the unfamiliar angle is the lock.

**Surprising-reversal passages** present information that contradicts the student's likely prior expectation. The reversal is the key piece of content, and any question that asks about it cannot be answered by someone who did not encounter the surprise.

**Specific-comparison passages** adjudicate between two named things using criteria introduced in the passage itself. The conclusion is derivable only by following the passage's logic, not by retrieving a memorized ranking.

**Causal-chain passages** present a sequence of causes and effects in a specific order, and the questions test the links in that chain. A student who knows only the beginning and end of the story cannot answer questions about the intermediate steps.

### The passage-necessity test

Before writing any MCQ item for a passage, run this check:

> Could a student who studied this topic in school — but did NOT read this specific passage — answer this question correctly?

If the answer is YES for any item, the passage is leaking. Do not patch the item; fix the passage first. Revise the passage to introduce at least one of the following: a character's specific decision, the author's explicit argumentative stance, a counterintuitive consequence, a non-obvious comparison outcome, or an obscure-angle fact. Then rebuild the items from the revised passage.

If the passage topic is inherently curriculum-level (e.g., "the water cycle"), either replace the topic entirely with a less-documented subject, or reframe the passage so that it takes a specific, arguable position rather than summarizing the standard account.

Apply this test to every passage you generate before writing the first distractor.
```

---

## What NOT to Do (Passage Anti-Patterns)

- Passages about famous scientists (Lind, Leeuwenhoek, van Leeuwenhoek, Curie, Darwin, Newton)
- Passages about well-known processes (photosynthesis, the water cycle, migration patterns, plate tectonics)
- Passages about defined scientific terms used as the organizing frame (geothermal, bioluminescence, plucking, osmosis)
- Passages about widely taught historical events (Library of Alexandria, Great Wall, Panama Canal, moon landing, American Revolution, World War II)
- Passages that summarize a famous person's biography or list of achievements
- Passages whose central fact is the headline figure everyone already knows (year, speed, temperature, population)
- Passages that describe a process using only the standard textbook explanation with no new angle, specific data, or arguable position
