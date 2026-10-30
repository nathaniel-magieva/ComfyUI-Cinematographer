# Research — the evidence base this pack is built on

These two documents are the source material behind every claim this pack makes about
Cinema Studio 4.0. They ship **in this repository** so that each citation in the code
resolves: a citation a reader cannot open is not evidence, it is a promise.

| File | What it is |
|---|---|
| [`cinema-studio-4.0-api-schema.txt`](cinema-studio-4.0-api-schema.txt) | A verbatim capture of Cinema Studio 4.0's first-party Generate API reference, taken 2026-10-29. This is the authority for every enum in `cinematographer/director.py` and `cinematographer/prompt.py`. |
| [`20-workflow-walkthrough.md`](20-workflow-walkthrough.md) | A walkthrough of the shipped product, with every sourced claim tagged by provenance tier. This is the authority for the five-stage flow, the Director's Panel control groups, and the Element taxonomy. |

## The tier system is load-bearing

The walkthrough tags each sourced claim with a tier printed on the line:

- **T1** — Higgsfield's own material (`docs.higgsfield.ai`, the higgsfield.ai blog).
  T1 licenses the sentence *"the product does this."*
- **V1 / V2 / V3** — third-party reviewers. These license *"reviewer V2 reports this,"*
  and require naming the reviewer. They do **not** license a product claim.

**The rule is to grep the tier, not the words.** A word-grep cannot catch a tier error,
because the words are right — only the attribution is wrong. This is not hypothetical:
two claims in this pack were written from a V-tier source as though they were T1, and
both were caught by grepping the tier rather than by reading the sentence.

## Two honest limits

**The API capture is truncated.** Its trailing JSON block ends mid-object. The prose
sections are complete, and for `camera_movement` and `color_palette` the prose is the
authoritative path — the JSON `properties` block does not contain those fields at all.
An earlier revision of this pack read only the JSON, shipped 9 of 33 camera moves and
8 of 50 palettes, and described the remainder as "not published in any source we hold."
That claim was false, and the prose list is why.

**The walkthrough is a capture, not a specification.** Where the shipped UI and the API
disagree, the API is treated as the authority and the disagreement is recorded rather
than smoothed over. The UI scrolls, truncates and omits; several on-screen lists were
only partially legible.

## Provenance

Both documents describe a third-party commercial product and are included here as
research. They contain no confidential material, no credentials, and no personal data.
Cinema Studio 4.0 is a product of Higgsfield; this pack is an independent,
open-source reimplementation of the *directorial control surface* concept and is not
affiliated with or endorsed by them.
