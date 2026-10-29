"""Assemble the labelled works table (OpenAlex slice joined to Retraction Watch by DOI)."""
import pandas as pd

from src.rw_labels import load_retraction_watch
from src.slice_config import HIGH_LABEL

LABEL_COLUMNS = ["paper_mill", "peer_review", "referencing", "manipulation"]


def load_labeled_works(works_path="data/raw/openalex/works.jsonl",
                       rw_path="data/raw/retraction-watch-data/retraction_watch.csv"):
    works = pd.read_json(works_path, lines=True).drop_duplicates("id").reset_index(drop=True)
    labels = load_retraction_watch(rw_path)[["doi"] + LABEL_COLUMNS]
    merged = works.merge(labels, on="doi", how="left")
    merged[LABEL_COLUMNS] = merged[LABEL_COLUMNS].fillna(False).astype(bool)
    merged["high_label_journal"] = merged["source"].isin(HIGH_LABEL)
    return merged
