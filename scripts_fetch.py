"""Run (and resume) the OpenAlex slice download: python scripts_fetch.py"""
import sys
from src.openalex_fetch import fetch_slice
from src.slice_config import ALL_SOURCES, YEARS

done = fetch_slice(list(ALL_SOURCES), YEARS, "data/raw/openalex")
print("COMPLETE" if done else "INCOMPLETE - rerun later")
sys.exit(0 if done else 1)
