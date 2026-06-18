# Shared-bundle content bugs — Grade-3 Reading (found via adversarial QA of the live powerpath course)

Found while QA-ing **576** deployed items from the shared `course_bundle.jsonl`. 
**38 items removed** from our live course (`grade3-reading-ela-pp-9701`): **20 must-fix** (broken/unanswerable) + **18 consider** (ambiguous/unclear). 
These are **content-level** defects in the shared bundle — they will ship broken in **any** deployment of this content (incl. the AlphaRead reading flow) unless pruned/fixed. Keyed by bundle `item_id`.


## MUST-FIX — unanswerable / wrong key (20)

| item_id | unit | type | substandard | category | issue |
|---|---|---|---|---|---|
| `8bdf39e1-28fd-4762-8589-552fc25c9a08` | Animals & Classification | match | RI.3.1 | unanswerable-outside-knowledge | match cites a source text not embedded in the item |
| `d5fc7dce-277a-451a-85cf-09aa8411cffe` | Animals & Classification | match | RI.3.1 | unanswerable-outside-knowledge | match cites a source text not embedded in the item |
| `aac37d34-715c-4249-bcf0-7ad26f32b177` | Animals & Classification | match | RI.3.1 | unanswerable-outside-knowledge | match cites a source text not embedded in the item |
| `3d26ce05-eb25-4247-83d2-bcde1e1154c6` | Norse Mythology | mcq | RL.3.7 | unanswerable-needs-visual | asks how a picture/diagram helps; image not rendered |
| `a3931c54-8b39-41e0-b45d-a70cbc092bd3` | Norse Mythology | mcq | RL.3.7 | unanswerable-needs-visual | asks how a picture/diagram helps; image not rendered |
| `7357bfce-b602-4178-8e91-5e2bfafeb2b5` | Norse Mythology | mcq | RL.3.7 | unanswerable-needs-visual | asks how a picture/diagram helps; image not rendered |
| `d1a1bbd9-895a-4d12-a907-d2b6588a0986` | Norse Mythology | mcq | RL.3.7 | unanswerable-needs-visual | asks how a picture/diagram helps; image not rendered |
| `81cebfd5-75d6-4051-9c81-ff4d00254520` | Space | match | RI.3.7 | unanswerable-needs-visual | Confirmed via live QTI rawXml. The q01-match stimulus body contains ONLY the instruction s |
| `b840c8fc-9bfe-4360-8beb-b89d7f17fcbf` | Space | match | RI.3.7 | unanswerable-needs-visual | match needs diagram labels |
| `7c037ae7-6bca-4001-9301-2e6451f9a3cd` | Ancient Rome | ebsr | RI.3.1 | key-error | Part A key marks B 'To let smoke from cooking fires escape' as correct, but the shown pass |
| `470905be-9fdf-4855-a7c1-d710896cc435` | Light & Sound | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |
| `5183b852-3216-492f-8ef3-da3c55a02e9b` | Light & Sound | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |
| `ddc4ddd0-201f-4fad-b24f-83d3ee99586d` | Light & Sound | match | RI.3.7 | unanswerable-needs-visual | match needs diagram labels |
| `4cc49ccd-23fb-40c0-bd8f-668cf7345985` | Light & Sound | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |
| `cee5dd26-7676-4134-b1d0-f444a05726c6` | The Human Body | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |
| `1c8fd18f-79d8-43d0-a1e4-347a43876b9f` | The Human Body | sequence | RI.3.2 | key-error | Passage explicitly orders the bone layers outside-to-inside: compact bone (very outside) - |
| `33b17990-3e58-45ba-af4f-f0462025b222` | The Human Body | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |
| `fa1f0847-dfeb-48b2-bc19-3c342b2ed6fb` | The Human Body | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |
| `f550a849-f30d-4761-9d95-02afe9a99224` | The Human Body | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |
| `b9e95e4f-fc50-4c36-922a-ef3a1beb1852` | The Human Body | mcq | RI.3.7 | unanswerable-needs-visual | stem asks for diagram-only info |

## CONSIDER — ambiguous / unclear (18)

| item_id | unit | type | substandard | category | issue |
|---|---|---|---|---|---|
| `6c961138-e3c6-4d45-9963-8bda33e00d05` | Animals & Classification | hot-text | RI.3.4 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `1f451e4c-2367-4b60-be69-6a94e63f18c8` | Norse Mythology | mcq | RL.3.1 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `239efcf5-03de-43f7-9bfc-a2657fc083d8` | Space | match | RI.3.7 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `1ebb61e0-a540-4302-aeba-0853d2f18dff` | Space | hot-text | RI.3.7 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `7ab71e5b-c287-442a-8c77-e24c745ad866` | Ancient Rome | mcq | RI.3.8 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `bb5d8f84-6d99-44a4-b92f-0db670eda666` | Ancient Rome | hot-text | RI.3.8 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `99a9fd53-b1f3-4742-b8de-fa96d622449c` | Ancient Rome | hot-text | RI.3.8 | ambiguous-multiple-correct | Confirmed against live content. Passage tokens: t1 (lead-in), t2 'First, the engineer foun |
| `d8cec5dc-a741-4a2e-bca6-659f5bdbd190` | Native Americans | hot-text | RI.3.2 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `6b1e0dec-bc58-4c22-823a-b96049e72e03` | Light & Sound | hot-text | RI.3.3 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `3204f989-cd4c-417a-8bd4-98dfabfaf86a` | Light & Sound | hot-text | RI.3.1 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `7759ba61-da40-453d-8793-714f52eabdc5` | The Human Body | match | RI.3.8 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `ce019097-3ebe-419f-be78-b1b9ec10f00c` | The Human Body | hot-text | RI.3.8 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `00a7b18a-202a-4cbd-a90d-79a394feb565` | The Human Body | hot-text | RI.3.3 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `d5662914-5ac0-4c86-a121-6ecda215cfd7` | The Age of Exploration | match | L.3.6 | unclear-stem | Verified against the live deployed stimulus. The full qti-stimulus-body for grade3-reading |
| `aa085cac-36a6-4382-92f0-090756f65efd` | Classic Literature | hot-text | RL.3.3 | ambiguous/unclear (QA-flagged) | flagged by adversarial QA; pruned conservatively |
| `107c357e-1395-4d00-b968-b646b4b318d1` | Classic Literature | hot-text | RL.3.9 | ambiguous-multiple-correct | Confirmed against live dump. Q9 (hottext) stem: 'Click the ONE sentence that uses a transi |
| `4ae5dd56-a1f7-48dc-ada2-efd20930609e` | Ecology & Environment | match | RI.3.3 | ambiguous-multiple-correct | Confirmed against the live passage. The passage is one continuous transitive causal chain: |
| `dcf6c75d-9388-4e1e-a700-74e43a0d1175` | Ecology & Environment | match | L.3.6 | unclear-stem | Confirmed against live dump. The q13 PASSAGE field contains ONLY the instruction line: "Re |
