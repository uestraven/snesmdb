# Example workflows

Repository-only. These are **not** part of the published distribution, and
`DATASET.md` deliberately does not reference them: a document that ships
inside `dist/` must not point at files a download does not contain. An earlier
version of `DATASET.md` did, alongside two other such references
(`records/*.json` and `raw/*.jsonl.gz`), and an evaluator reasonably reported
all three as missing from the release.

[`workflows.py`](workflows.py) runs three research workflows against a
published tree using the standard library alone:

```sh
python3 examples/workflows.py <dist-dir> discover --game Actraiser
python3 examples/workflows.py <dist-dir> pitch    --game Actraiser
python3 examples/workflows.py <dist-dir> samples  --game Actraiser
```

- **discover** — filter the index by game, `track_class` and extraction
  status, then load the named event tables
- **pitch** — pitch distribution and range, separating pitched attacks from
  all sounded pitches, with every excluded event attributed to a reason
- **sample recurrence** — which sample content recurs across tracks and
  games, and the pitch span of each recurring sample

It imports nothing from `src/snesmdb`, which a test enforces: a workflow
needing the extraction library would say nothing about whether the
*published* artifact can be read. Each one documents the mistake it avoids.

`make workflows` runs all three against `DIST_DIR`.
