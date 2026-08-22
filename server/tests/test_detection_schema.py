"""The load-bearing property: the model cannot return a calorie number."""

import json

import pytest
from pydantic import ValidationError

from app.schemas.detection import (
    _UNSUPPORTED_SCHEMA_KEYS,
    DetectedFood,
    FoodDetectionResult,
    anthropic_tool_schema,
)

NUTRITION_WORDS = {
    "calorie",
    "calories",
    "kcal",
    "energy",
    "protein",
    "carb",
    "carbs",
    "carbohydrate",
    "fat",
    "macro",
    "macros",
    "nutrition",
}


def _all_property_names(schema: dict) -> set[str]:
    names: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    names.update(value.keys())
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return names


class TestModelCannotReturnNutrition:
    def test_no_nutrition_field_exists_anywhere_in_the_schema(self):
        properties = _all_property_names(FoodDetectionResult.model_json_schema())

        offending = {
            name
            for name in properties
            if any(word in name.lower().split("_") for word in NUTRITION_WORDS)
        }
        assert offending == set(), f"model-facing schema exposes nutrition fields: {offending}"

    def test_unknown_fields_are_rejected(self):
        # Without this, a model that volunteers "calories": 450 would sail
        # through and the number could reach a user.
        with pytest.raises(ValidationError):
            DetectedFood(
                label="grilled chicken",
                estimated_grams=150,
                confidence=0.9,
                calories=450,
            )

    def test_result_rejects_unknown_fields_too(self):
        with pytest.raises(ValidationError):
            FoodDetectionResult(foods=[], total_calories=1200)


class TestToolSchema:
    def test_strict_mode_is_on(self):
        assert anthropic_tool_schema()["strict"] is True

    def test_additional_properties_are_disallowed(self):
        # Strict tool use requires this; extra="forbid" is what produces it.
        schema = anthropic_tool_schema()["input_schema"]
        assert schema["additionalProperties"] is False

        for definition in schema.get("$defs", {}).values():
            assert definition.get("additionalProperties") is False

    def test_the_description_tells_the_model_not_to_estimate_nutrition(self):
        assert "do not estimate calories" in anthropic_tool_schema()["description"].lower()

    def test_tool_name_is_stable(self):
        assert anthropic_tool_schema()["name"] == "record_detected_foods"


class TestValidation:
    def test_grams_must_be_positive(self):
        with pytest.raises(ValidationError):
            DetectedFood(label="rice", estimated_grams=0, confidence=0.5)

    def test_confidence_is_bounded_to_zero_one(self):
        with pytest.raises(ValidationError):
            DetectedFood(label="rice", estimated_grams=100, confidence=1.5)

    def test_an_absurd_portion_is_rejected(self):
        with pytest.raises(ValidationError):
            DetectedFood(label="rice", estimated_grams=99_999, confidence=0.5)

    def test_a_reasonable_detection_validates(self):
        food = DetectedFood(
            label="jasmine rice, cooked",
            estimated_grams=200,
            confidence=0.6,
            preparation="boiled",
            search_terms=["jasmine rice cooked", "white rice cooked"],
            portion_reasoning="about a cup, judged against the fork",
        )
        assert food.estimated_grams == 200
        assert food.preparation == "boiled"


class TestStrictToolCompatibility:
    """The schema has to survive the API, not just Pydantic.

    Strict tool use accepts a subset of JSON Schema. Anything outside it is
    rejected for the whole request, so a schema that is perfectly valid locally
    can still 400 on every call — a failure no substituted test sees, because
    the fake never validates the schema it is handed.
    """

    def test_no_constraint_keywords_strict_mode_rejects(self):
        """Regression: `Field(gt=0, le=5000)` emitted exclusiveMinimum/maximum,
        and the API answered 400 on every detection until they were stripped."""
        rendered = json.dumps(anthropic_tool_schema())
        present = sorted(key for key in _UNSUPPORTED_SCHEMA_KEYS if f'"{key}"' in rendered)
        assert present == [], f"schema carries keywords strict tool use rejects: {present}"

    def test_bounds_are_still_enforced_when_parsing_the_reply(self):
        """Stripping them from the wire schema must not stop them validating.

        Every other field is supplied deliberately: with one missing, this
        passes on the missing field alone and would keep passing if the gram
        bound were deleted outright.
        """
        with pytest.raises(ValidationError):
            DetectedFood(
                label="rice", estimated_grams=99_999, confidence=0.5, search_terms=["rice"]
            )

    def test_search_terms_is_required(self):
        """Regression, seen live: the model returned a food with no terms at all.

        ``default_factory=list`` reads as a harmless convenience and is not one
        — Pydantic drops a defaulted field from ``required``, so the schema
        stopped asking for the only input the resolution ladder has. The food
        came back, resolved against a bare label, and nothing anywhere failed.
        """
        schema = anthropic_tool_schema()["input_schema"]
        assert "search_terms" in schema["$defs"]["DetectedFood"]["required"]

    def test_household_unit_is_a_closed_set(self):
        """As free text this field attracted a paragraph of the model's own
        working, which consumed the output budget and truncated the food list."""
        schema = anthropic_tool_schema()["input_schema"]
        unit = schema["$defs"]["DetectedFood"]["properties"]["household_unit"]
        options = [o for o in unit["anyOf"] if o.get("type") != "null"]
        assert options and "enum" in options[0], "household_unit must be an enum, not free text"

    def test_every_object_is_strict_mode_ready(self):
        schema = anthropic_tool_schema()["input_schema"]
        for name, node in [("<root>", schema), *schema.get("$defs", {}).items()]:
            if node.get("type") != "object":
                continue
            assert node.get("additionalProperties") is False, f"{name} allows extra properties"
            assert node.get("required"), f"{name} has no required array"
