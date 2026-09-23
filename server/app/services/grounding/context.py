"""Build the evidence catalog whose facts are the only permitted response vocabulary."""

from app.schemas.detection import FoodDetectionResponse
from app.schemas.grounding import GroundedStatement
from app.schemas.nutrition_context import NutritionContext, NutritionEvidence

# Bump when changing the context or sentence templates so saved summaries are regenerated.
CONTEXT_VERSION = "1"


async def build_context(response: FoodDetectionResponse) -> NutritionContext:
    """Use selected records only; alternatives have not been chosen for this portion."""
    evidence = [
        NutritionEvidence(
            item_index=index,
            label=item.detected.label,
            estimated_grams=item.detected.estimated_grams,
            record=item.matched,
            portion=item.nutrition if item.matched is not None else None,
            is_rough=item.is_rough,
        )
        for index, item in enumerate(response.items)
    ]
    matched = [item.item_index for item in evidence if item.record is not None]
    missing = [item.item_index for item in evidence if item.record is None]
    rough = [item.item_index for item in evidence if item.record is not None and item.is_rough]
    totals = response.totals
    summary = (
        f"The matched foods total {totals.calories:,.1f} kcal, "
        f"{totals.protein_g:,.1f} g protein, {totals.carbs_g:,.1f} g carbs "
        f"and {totals.fat_g:,.1f} g fat, based on the estimated portions."
        if matched
        else "No usable nutrition records were found; nutrition totals are unavailable."
    )
    facts = [GroundedStatement(fact_id="totals", text=summary, item_indices=matched)]
    required = ["totals"]
    if missing:
        facts.append(
            GroundedStatement(
                fact_id="unresolved",
                text="Unmatched foods are excluded from the totals; their nutrition is unknown.",
                item_indices=missing,
            )
        )
        required.append("unresolved")
    if rough:
        facts.append(
            GroundedStatement(
                fact_id="rough",
                text="Some food matches or portions are approximate. Review them before saving.",
                item_indices=rough,
            )
        )
        required.append("rough")
    if response.is_provisional:
        facts.append(
            GroundedStatement(
                fact_id="provisional",
                text=(
                    "The food inventory may be incomplete, "
                    "so these totals may omit part of the meal."
                ),
                item_indices=list(range(len(evidence))),
            )
        )
        required.append("provisional")

    for item in evidence:
        portion = item.portion
        if portion is None:
            continue
        facts.append(
            GroundedStatement(
                fact_id=f"portion_{item.item_index}",
                text=(
                    f"Item {item.item_index + 1}, at an estimated {item.estimated_grams:,.1f} g, "
                    f"contributes {portion.calories:,.1f} kcal, "
                    f"{portion.protein_g:,.1f} g protein, "
                    f"{portion.carbs_g:,.1f} g carbs and {portion.fat_g:,.1f} g fat."
                ),
                item_indices=[item.item_index],
            )
        )

    # Comparisons are computed here, so the model cannot declare an unsupported "main source".
    for nutrient, label in (("protein_g", "protein"), ("carbs_g", "carbs"), ("fat_g", "fat")):
        candidates = [item for item in evidence if item.portion is not None]
        if not candidates:
            break
        highest = max(getattr(item.portion, nutrient) for item in candidates)
        leaders = [
            item.item_index for item in candidates if getattr(item.portion, nutrient) == highest
        ]
        if highest <= 0 or len(leaders) != 1:
            continue
        index = leaders[0]
        facts.append(
            GroundedStatement(
                fact_id=f"largest_{nutrient}",
                text=(
                    f"Among the matched foods, item {index + 1} contributes the most {label} "
                    f"({highest:,.1f} g)."
                ),
                item_indices=[index],
            )
        )
    return NutritionContext(
        items=evidence,
        matched_totals=totals,
        is_provisional=response.is_provisional,
        facts=facts,
        required_fact_ids=required,
    )
