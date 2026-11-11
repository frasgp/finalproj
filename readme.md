## Objectives

Find empirical methods or metrics to detect suspicious scientific citations behavior, such as citation laundering, accidental citations or citations cartels.

## Methods 

These metrics could be meaningful for the question : 

- Cosine similarity between abstracts of papers referencing each other
- Cosine similarity between abstracts of papers sharing a reference
- Bibliographical coupling between papers linked by a citation -> share of shared references
- Authors clusters having a high in-group citation rate and lower external rate than by chance
- Venue-to-venue boosting : high number of same-journal referencing
- Citations towards low in-degree papers only (might be hard because reliable in-degree requires a large dataset) 
- Graph distance between 2 papers on the undirected graph

## Data expansion

Openalex provides additional data with the Works API that could be worth processing, such as :

- topics
- keywords
- concepts
- counts_by_year (in-degree)