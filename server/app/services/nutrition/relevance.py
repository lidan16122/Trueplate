"""Deciding whether a database row is about the food that was asked for.

Shared by both name-searched upstreams, because both fail the same way: asked
for something they do not have, they answer with something they do, confidently
and with no signal that it is unrelated. Open Food Facts returns a mayonnaise
for "scrambled eggs"; USDA has answered "almonds raw" with *Abiyuch, raw* and
"salmon fillet cooked" with *Emu, fan fillet, cooked, broiled*.

A wrong number the user cannot see is wrong is the failure this app exists to
avoid, so the bar here is about *identity* — is this the same food — and never
about quality. Ranking within a food is the caller's problem.
"""

import re

_TOKENS = re.compile(r"[a-z0-9]+")

# Words that describe preparation or size rather than identity. They are common
# in our search terms and common in descriptions, so counting them as evidence
# would let almost anything through: "cooked" alone would make a bratwurst a
# plausible answer for shredded chicken.
_STOPWORDS = frozenset(
    {
        "and",
        "the",
        "with",
        "for",
        "raw",
        "cooked",
        "fresh",
        "plain",
        "whole",
        "large",
        "medium",
        "small",
    }
)


# Words marking a row as a *stand-in* for the food rather than the food. FDC
# carries "Chicken, meatless", "Bacon, meatless", "Fish sticks, meatless", and
# their names match a query for the real thing perfectly — "Chicken, meatless"
# beat every actual chicken row for the term "chicken", because one extra word
# is the smallest possible amount of noise to carry.
#
# A demotion, never a rejection: someone photographing a soy analogue should
# still be able to log it, and can pick it from the alternatives.
SUBSTITUTE_MARKERS = frozenset(
    {"meatless", "substitute", "imitation", "vegetarian", "analog", "analogue"}
)


def _singular(token: str) -> str:
    """One canonical form per word, so both sides of a comparison agree.

    The previous version added ``token[:-1]`` alongside the original, which
    turns "potatoes" into "potatoe" — a form nothing else ever produces. A query
    for "potato" therefore failed to match a row named "Potatoes", and the
    nearest thing that did match was *Sweet potato leaves*. Stemming to a shared
    form rather than guessing at variants is what makes the comparison
    symmetric.
    """
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("oes"):
        # potatoes, tomatoes — dropping only the "s" would strand a trailing "e".
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def content_tokens(text: str) -> set[str]:
    """The words in ``text`` that say what the food *is*."""
    return {
        _singular(token)
        for token in _TOKENS.findall(text.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def is_relevant(term: str, name: str) -> bool:
    """Does this row plausibly answer the query at all?

    One shared content word is a deliberately low bar. It is not trying to rank
    quality — callers do that, and every free-text hit is flagged rough anyway —
    only to reject answers about a different food entirely.
    """
    query = content_tokens(term)
    if not query:
        return True
    return bool(query & content_tokens(name))
