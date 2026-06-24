# Generator Prompt Instruction — Option Length Balance

Paste this verbatim into your Gemini generator system prompt.

---

**OPTION LENGTH BALANCE:**

Keep all answer options within 15% of the same character length. After generating options, check: is the correct answer more than 15% longer than ANY wrong option? If yes, STOP and rewrite. Either trim the correct answer, or expand the wrong options to match. Never leave options at widely different lengths.

Specifically:
1. Count the characters in each option (including spaces and punctuation).
2. Find the longest option. Find the shortest option.
3. If longest / shortest > 1.18 (i.e., longest is more than 18% longer than shortest), rewrite.
4. The correct answer must NOT be the uniquely longest option.
5. When trimming the correct answer: remove only redundant qualifiers, trailing participial phrases, or parenthetical elaborations. Never remove the core claim.
6. When expanding wrong options: add a brief parallel qualifying phrase (e.g., "as described in the passage" or ", which affects the overall process") — do NOT add new facts or false claims.
7. Every wrong option must remain a complete, grammatically parallel sentence after expansion.

**Quick check before submitting any MCQ:**
- List character lengths: [len(A), len(B), len(C), len(D)]
- max(lengths) / min(lengths) must be <= 1.18
- The keyed option must NOT be the uniquely longest
- If either condition fails: revise and re-check
