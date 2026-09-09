"""Which FDC row a search term lands on.

Every case here is a match this app actually made and should not have. USDA
search is loose enough that the wrong answer is never absurd-looking — it is a
real food, with real numbers, that happens not to be the one on the plate.
"""

from typing import Any

import pytest

from app.services.nutrition.relevance import content_tokens, is_relevant
from app.services.nutrition.usda import rank_foods


def food(description: str, data_type: str = "SR Legacy", kcal: float = 100.0) -> dict[str, Any]:
    return {
        "fdcId": abs(hash(description)) % 10**6,
        "description": description,
        "dataType": data_type,
        "foodNutrients": [{"nutrientId": 1008, "value": kcal}],
    }


def top(term: str, *rows: dict[str, Any]) -> str:
    ranked = rank_foods(term, list(rows))
    return ranked[0]["description"] if ranked else ""


class TestRelevanceFloor:
    def test_a_row_about_a_different_food_is_dropped_entirely(self):
        """Seen live: "almonds raw" matched *Abiyuch, raw*, and "salmon fillet
        cooked" matched *Emu, fan fillet, cooked, broiled*. Returning nothing
        sends the resolver to a broader term, which is where the answer is."""
        ranked = rank_foods("almonds raw", [food("Abiyuch, raw"), food("Chicory roots, raw")])
        assert ranked == []

    def test_a_category_headed_row_is_demoted_with_the_stranger(self):
        """A known limitation, recorded rather than hidden.

        *Emu, fan fillet* shares "fillet" with the query, so the floor alone
        never rejected it — the identity segment is what demotes it. But FDC
        heads some foods with a bare category nobody searches for, and
        "Fish, salmon, Atlantic" hides the salmon in segment two, so it lands in
        the same demoted tier. What rescues the query in practice is a branded
        row whose description says salmon outright.

        Counting two segments as the identity fixes this case and scored *worse*
        overall — 27/31 against 29 — regressing "black beans cooked" to raw
        beans at 341 kcal. Left as it is on that evidence.
        """
        ranked = rank_foods(
            "salmon fillet cooked",
            [
                food("Emu, fan fillet, cooked, broiled"),
                food("Fish, salmon, Atlantic, farmed, cooked, dry heat"),
                food("SALMON FILLETS", "Branded"),
            ],
        )
        assert ranked[0]["description"] == "SALMON FILLETS"


class TestIdentityBeforeQualifiers:
    def test_the_head_segment_decides_what_the_food_is(self):
        """FDC descriptions are head-first, so *Spices*, curry powder announces
        itself. It was beating "Curry sauce" at 95 kcal with 325."""
        assert (
            top(
                "curry sauce",
                food("Spices, curry powder", kcal=325.0),
                food("Curry sauce", "Survey (FNDDS)", kcal=95.0),
            )
            == "Curry sauce"
        )

    def test_a_dish_containing_the_food_is_not_the_food(self):
        """A ranking that led with head coverage scored "Spanish rice with ground
        beef" as the best answer for ground beef: its head contains both query
        words, and three more besides."""
        assert (
            top(
                "ground beef cooked",
                food("Spanish rice with ground beef", "Survey (FNDDS)"),
                food("Beef, ground"),
            )
            == "Beef, ground"
        )

    def test_a_part_of_the_animal_does_not_beat_the_cut(self):
        """*Chicken, skin (drumsticks and thighs)* mentions a drumstick and is
        not one. 443 kcal against 206 — the largest single error in the set."""
        assert (
            top(
                "chicken drumstick cooked",
                food("Chicken, skin (drumsticks and thighs), cooked, braised", kcal=443.0),
                food("Chicken drumstick, rotisserie, skin eaten", "Survey (FNDDS)", kcal=206.0),
            )
            == "Chicken drumstick, rotisserie, skin eaten"
        )


class TestBrandedRows:
    def test_a_generic_row_wins_when_it_answers_the_same_query(self):
        """A branded description is the query typed back verbatim, so on word
        overlap alone a packaged product wins every plain food name."""
        assert (
            top(
                "greek yogurt plain",
                food("GREEK YOGURT PLAIN", "Branded", kcal=90.0),
                food("Yogurt, Greek, plain, nonfat", "Foundation", kcal=61.0),
            )
            == "Yogurt, Greek, plain, nonfat"
        )

    def test_a_branded_row_still_wins_when_nothing_generic_answers(self):
        """Demoted, not excluded. FDC has no generic row for plain "rice", and a
        branded one beats falling through to Open Food Facts."""
        assert top("rice", food("Crackers, rice", kcal=416.0), food("RICE", "Branded")) == "RICE"


class TestSubstitutes:
    def test_a_meatless_analogue_does_not_answer_for_the_meat(self):
        """Seen live on the photo path: "chicken cooked" matched *Chicken,
        meatless*. Its name matches perfectly and carries one extra word, which
        is the smallest possible amount of noise — so it beat every real chicken
        row on every other signal."""
        assert (
            top(
                "chicken cooked",
                food("Chicken, meatless", kcal=154.0),
                food("Chicken breast, rotisserie, skin eaten", "Survey (FNDDS)", kcal=175.0),
            )
            == "Chicken breast, rotisserie, skin eaten"
        )

    def test_someone_who_asks_for_the_analogue_still_gets_it(self):
        """Demoted, not banned — a soy product is a real thing to eat."""
        assert (
            top(
                "meatless chicken",
                food("Chicken breast, rotisserie, skin eaten", "Survey (FNDDS)"),
                food("Chicken, meatless"),
            )
            == "Chicken, meatless"
        )


class TestStemming:
    def test_a_plural_row_matches_a_singular_query(self):
        """The old stemmer added ``token[:-1]``, turning "potatoes" into
        "potatoe" — a form nothing else produces. "potato" therefore missed
        every row named "Potatoes", and the nearest thing that matched was
        *Sweet potato leaves*."""
        assert content_tokens("Potatoes, boiled") & content_tokens("potato")
        assert is_relevant("potato", "Potatoes, boiled, cooked in skin")

    def test_a_double_s_word_is_left_alone(self):
        assert "glass" in content_tokens("glass of milk")


class TestPreparedDishes:
    def test_pizza_rules_do_not_reinterpret_other_food_names(self) -> None:
        name = "Yogurt, Greek, nonfat"
        assert top("fat-free greek yogurt", food(name)) == name

    @pytest.mark.parametrize(
        "wrong",
        [
            "Pizza, no cheese, thick crust",
            "Pizza without cheese",
            "Cheese-free pizza",
            "Topping from cheese pizza",
            "Pizza cheese topping",
            "Pizza crust",
            "Pizza sauce",
            "Pizza rolls",
            "Dessert pizza",
            "Mexican pizza",
            "Pizza, rolls",
        ],
    )
    def test_cheese_pizza_does_not_resolve_to_a_different_food(self, wrong: str) -> None:
        assert rank_foods("pizza cheese", [food(wrong)]) == []

    @pytest.mark.parametrize(
        ("query", "description"),
        [
            ("pizza cheese", "Pizza, cheese, from restaurant, thin crust"),
            ("pizza cheese", "Thin crust cheese pizza"),
            ("pizza rolls", "Pizza rolls"),
            ("pizza crust", "Pizza crust, thin"),
            ("pizza sauce", "Sauce, pizza"),
            ("pizza topping", "Topping from cheese pizza"),
            ("dessert pizza", "Dessert pizza"),
            ("pizza, dessert", "Dessert pizza"),
            ("pizza no cheese", "Pizza, no cheese, thick crust"),
        ],
    )
    def test_an_explicit_pizza_variant_remains_searchable(
        self, query: str, description: str
    ) -> None:
        assert top(query, food(description)) == description

    def test_a_cheese_free_query_does_not_accept_regular_cheese_pizza(self) -> None:
        assert rank_foods("pizza no cheese", [food("Pizza, cheese, thin crust")]) == []

    def test_standard_cheese_pizza_beats_unrequested_recipe_variants(self) -> None:
        assert (
            top(
                "pizza cheese thin crust",
                food("Pizza, cheese, with fruit, thin crust"),
                food("Pizza, extra cheese, thin crust"),
                food("Pizza, cheese, whole wheat thin crust"),
                food("Pizza, cheese, from frozen, thin crust"),
            )
            == "Pizza, cheese, from frozen, thin crust"
        )

    def test_an_explicit_stuffed_crust_request_keeps_its_recipe(self) -> None:
        assert (
            top(
                "pizza cheese stuffed crust",
                food("Pizza, cheese, thin crust"),
                food("Pizza, cheese, stuffed crust"),
            )
            == "Pizza, cheese, stuffed crust"
        )


class TestAgainstRecordedResponses:
    @pytest.mark.parametrize(("group", "minimum"), [("baseline", 29), ("dishes", 5)])
    def test_the_eval_set_does_not_regress(self, group: str, minimum: int):
        """The eval is a script so it can be iterated on; this keeps its result
        from drifting unnoticed between times anyone remembers to run it.

        Ranking on recorded FDC payloads went 24/31 to 29/31. The floor is set
        at the achieved score: the two known misses are gaps in FDC's corpus —
        it carries no generic shredded chicken and no generic wet sauce — not
        ranking faults, and inventing a fix for them here would be fitting this
        function to two rows.
        """
        import json

        from scripts.eval_matching import BASE_CASES, DISH_CASES, FIXTURE, _kcal, judge

        recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
        passed = 0
        cases = BASE_CASES if group == "baseline" else DISH_CASES
        for case in cases:
            foods = recorded.get(case.term)
            assert foods is not None, f"{case.term!r} is not recorded; run --refresh"
            ranked = rank_foods(case.term, foods)
            best = next((f for f in ranked if _kcal(f) is not None), None)
            if judge(case, best) is None:
                passed += 1

        assert passed >= minimum, f"{group} ranking regressed to {passed}/{len(cases)}"
