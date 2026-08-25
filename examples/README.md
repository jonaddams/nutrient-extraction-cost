# Example report

`example-report.html` is a real run, not a mockup, and it is exactly what
`costlab` with no arguments produces when you answer **both** to "cost, accuracy,
or both?" — a cost run and an accuracy run, joined into one report.

17 documents from the bundled Nutrient sample corpus, on 2026-08-25, against four
models across three rungs:

| | |
|---|---|
| Claude Sonnet 5 | frontier |
| OpenAI gpt-5.4 | frontier |
| Qwen3-VL 235B on Bedrock | hosted |
| Qwen3-VL 8B, self-hosted | your own hardware |

272 calls: 136 for the cost run, 136 for the accuracy run. **271 succeeded.** One
Bedrock direct cell returned a 500 and is shown in the report as unpriced rather
than guessed at — which is what the tool does with any cell it cannot measure.

Cost and accuracy in this report are computed from **different records**, because
the two runs ask the models different things: the cost run sends one shared schema
so payload differences are attributable to the document, and the accuracy run
sends each document's own answer-key fields so the result can be scored. Their
token counts are not comparable with each other, and the report says so where the
two bands meet.

Open it before configuring anything. It is what `costlab` produces on your own
documents, with your own keys and your own models — and it is measured on our
sample documents rather than yours, which the provenance block at the top states.
