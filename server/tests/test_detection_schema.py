"""The load-bearing property: the model cannot return a calorie number."""

import pytest
from pydantic import ValidationError

from app.schemas.detection import (
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
