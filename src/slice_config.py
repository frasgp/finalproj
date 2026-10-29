"""Fixed study slice: CS-adjacent journals with many Retraction Watch manipulation labels
(HIGH_LABEL) plus large, rarely-retracted journals used as negative controls (CONTROL)."""

YEARS = (2019, 2022)

HIGH_LABEL = {
    "S179157397": "Journal of Intelligent & Fuzzy Systems",
    "S120683614": "Security and Communication Networks",
    "S72372694": "Computational Intelligence and Neuroscience",
    "S235346": "Wireless Communications and Mobile Computing",
    "S65753830": "Soft Computing",
    "S36625193": "Journal of Healthcare Engineering",
    "S96783963": "Journal of Sensors",
    "S152111507": "Mobile Information Systems",
    "S178238111": "Mathematical Problems in Engineering",
    "S207319443": "Complexity",
}
CONTROL = {
    "S192650101": "Information Sciences",
    "S10169007": "Knowledge-Based Systems",
    "S414566": "Pattern Recognition",
}
ALL_SOURCES = {**HIGH_LABEL, **CONTROL}
