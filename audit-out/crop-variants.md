# Display crops are now modelled as renditions, not rival works

## The problem

The archive keeps a painting more than once on purpose: a master alongside
16:9 and 9:16 re-cuts prepared for picture frames. Where those re-cuts were
ingested as their own `work_id` instead of as `files.variants[]`, three things
followed — the rendition repeated the parent's identity and the copies drifted;
both claimed the same work Q-ID, which the uniqueness guard could only read as
a collision; and a rendition with no identity at all looked like an unresolved
work, sending enrichment back to the network for what the parent already knew.

## Detection

Not "is the file 16:9" — a painting that genuinely is 16:9 would be caught and
a crop cut to another ratio missed. Instead the work's own recorded
`dimensions_original` says what shape the painting is; if the image file's
aspect disagrees, the file has been cropped.

```
Monet, Rocks at Port-Goulphar   dims 66.0 x 81.8 cm -> 1.239
  bb3ca9a  file aspect 1.248  agrees    -> master
  7c413c9  file aspect 1.777  disagrees -> display crop  (correlation 0.96)
```

Of 3,047 works with both a readable master and recorded dimensions, **2,239**
have a file aspect that disagrees with their own dimensions, and **2,190 of
those sit exactly on 9:16 (1,218) or 16:9 (972)** — the frame ratios. The
archive is mostly display crops, which is what it is for.

A crop is only bound to a parent when a crop-tolerant image correlation
confirms it (>= 0.70). In the clustering pass **84 candidate pairs were
rejected on that test** — same recorded size and same artist, but different
paintings. The size alone was never enough.

## What was written

- **56 links** where an uncropped master exists
- **16 links** where none does, and the least-cropped rendition
  becomes the parent (19 contested groups kept only a 16:9 and a 9:16 re-cut)
- **97 sidecars** now carry `derived_from`: 70 display-crop, 19 detail, 8 capture
- contested work Q-IDs recognised as renditions of one work: **44 of 83**

## Inheritance is non-destructive

`variants.inherit` fills only what a rendition lacks and never overwrites.
Where the two disagree the field is reported, not replaced — most disagreements
are cosmetic drift between renditions of one work:

```
artist   'Monet'                    vs 'Claude Monet'          (both Q296)
title    'The Feast of St Nicholas' vs 'The Feast of Saint Nicholas'
year     '1888'                     vs 'May 1888'
medium   'oil on canvas'            vs 'oil paint, canvas'
```

Normalising those is a separate decision and was not taken here.

## Material conflicts to adjudicate (6)

A rendition holding a *different* work Q-ID from its parent means one of the
two is wrong. These are left as they are:

```
050f152-the-feast-of-st-nicholas-steen  Q97377049
  parent eaecdc4-the-feast-of-saint-nicholas-steen  Q764831   correlation 0.983
78b9781-orchard-in-bloom-louveciennes  Q50775636
  parent f667a90-camille-pissarro-louveciennes  Q20188754   correlation 0.997
c470f36-water-lily-pond-monet  Q102422380
  parent 59a3275-water-lily-pond-monet  Q20268712   correlation 0.807
dec2301-the-adoration-of-the-kings-elder  Q3605524
  parent d6ac0cd-the-adoration-of-the-kings-elder  Q4680634   correlation 0.968
f1e777a-emperor-maximilian-i-durer  Q3937442
  parent 7325be5-emperor-maximilian-i-1459-1519-durer  Q107443977   correlation 0.995
e20faae-moonrise-over-the-sea-friedrich  Q1423223
  parent 8509549-solitary-tree-friedrich  Q1198515   correlation 0.731
```

## The guard

`WorkQidClaims` now takes an optional `same_object` predicate. A shared Q-ID
between renditions of one work passes; anything else is still a collision, and
with no predicate supplied the behaviour is exactly as before. The guard is
only ever relaxed by evidence of derivation.
