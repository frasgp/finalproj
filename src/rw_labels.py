"""Load Retraction Watch and derive weak labels for manipulation-type retractions.

Retraction Watch has no explicit "citation manipulation" reason, so labels are:
  paper_mill   - "Paper Mill"
  peer_review  - "Compromised Peer Review" or "Rogue Editor"
  referencing  - "Concerns/Issues about Referencing/Attributions" (weak proxy)
  manipulation - paper_mill or peer_review (the primary positive class)
"""
import pandas as pd


def _has(reasons, needle):
    return reasons.str.contains(needle, regex=False)


def load_retraction_watch(path):
    """Retractions with a usable DOI, lower-cased, with boolean reason flags."""
    df = pd.read_csv(path, encoding="cp1252", low_memory=False)
    df = df[df["RetractionNature"] == "Retraction"].copy()
    df["doi"] = df["OriginalPaperDOI"].fillna("").str.strip().str.lower()
    df = df[df["doi"].str.startswith("10.")].drop_duplicates("doi")
    reasons = df["Reason"].fillna("")
    df["paper_mill"] = _has(reasons, "Paper Mill")
    df["peer_review"] = _has(reasons, "Compromised Peer Review") | _has(reasons, "Rogue Editor")
    df["referencing"] = _has(reasons, "Referencing/Attributions")
    df["manipulation"] = df["paper_mill"] | df["peer_review"]

    print(f"retraction watch papers with doi : {len(df)}")
    
    return df[["doi", "Title", "Journal", "paper_mill", "peer_review", "referencing", "manipulation"]].reset_index(drop=True)
