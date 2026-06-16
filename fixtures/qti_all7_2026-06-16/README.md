# New TimeBack build output — handoff for upload

This folder contains sample `qti-sdk build` output for all supported question types.

| Item ID | Type | Stimulus |
|---------|------|----------|
| `sample-mcq-no-stimulus` | MCQ (single-select) | No |
| `sample-mcq-with-stimulus` | MCQ (single-select) | Yes (text passage) |
| `sample-mcq-with-image-stimulus` | MCQ (single-select) | Yes (image) |
| `sample-msq-no-stimulus` | MSQ (multi-select) | No |
| `sample-msq-with-stimulus` | MSQ (multi-select) | Yes (text passage) |
| `sample-order-summative` | Order / sequence | No |
| `sample-order-partial-credit` | Order / sequence (partial credit) | No |
| `sample-hot-text-single` | Hot text (single-select) | No |
| `sample-hot-text-multi-feedback` | Hot text (multi-select + feedback) | No |
| `sample-fill-in-single` | Fill-in (single blank) | No |
| `sample-fill-in-multi` | Fill-in (multi-blank) | No |
| `sample-match-drag-drop` | Match (drag-and-drop) | No |
| `sample-ebsr` | EBSR (two-part: MCQ + evidence) | Yes (text passage) |

## How this was generated

```bash
python -m qti_sdk build \
  -i examples/new_timeback_build_samples.json \
  -o examples/new_timeback_build_output \
  --stimulus-mode separate
```

The command prints a JSON manifest to stdout. `manifest.json` in this folder is a saved copy.

## Output layout

```
new_timeback_build_output/
  manifest.json
  items/
    <item_id>.xml          # one per item
  stimuli/
    stim_<hash>.xml        # one per unique stimulus content
```

## Upload mapping (new TimeBack QTI API)

**Items** — POST `https://qti.alpha-1edtech.ai/api/assessment-items`

```json
{
  "format": "xml",
  "xml": "<contents of items/<item_id>.xml>",
  "metadata": {},
  "stimulus": { "identifier": "<stimulus_id from manifest>" }
}
```

Omit the `stimulus` field when `stimulus_id` is null.

**Stimuli** — POST `https://qti.alpha-1edtech.ai/api/stimuli` **before** the item that references it.

Extract the inner HTML from `<qti-stimulus-body>` in `stimuli/<id>.xml` and send:

```json
{
  "identifier": "<stimulus_id>",
  "title": "Passage title",
  "content": "<inner HTML from qti-stimulus-body>"
}
```

Use the `stimulus_id` from `manifest.json` for each item.

## Notes

- Stimulus hrefs inside item XML use relative paths (`stimuli/<id>.xml`). For the new API, link via the JSON `stimulus.identifier` field or rewrite href to `https://qti.alpha-1edtech.ai/api/stimuli/<id>`.
- Rebuild anytime from `examples/new_timeback_build_samples.json`.
