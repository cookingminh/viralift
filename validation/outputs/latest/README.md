# Latest run summaries

`<task>.summary.json` and `<task>.manifest.json` are refreshed by every
`python -m validation.valkit.runner <task>` run. They are the only run output
tracked in git; the full per-prediction tables live in the run folder next to
this one (git-ignored, reproducible).
