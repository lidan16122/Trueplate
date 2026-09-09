# Composite-food detection research

Research date: 2026-09-09. Scope: investigate why a photo of two pizza slices became separate crust, cheese, sauce, and topping entries, and plan dish-level detection. This records the pre-implementation findings; see the [implementation outcome and verification](composite-food-detection-plan.md) for the subsequent changes.

## Product conclusion

The user's proposed behavior is sensible: recognize pizza as a prepared dish and resolve its nutrition from a matching whole-pizza database record. Represent two similar slices with their combined estimated edible mass. Detect rice and a separate chicken portion as separate foods. The distinction should follow what is served: pasta beside beef can be separate, while a recognizable lasagna or other integrated dish can be one entry.

This is a Trueplate product recommendation, not a USDA rule for image recognition. It preserves the existing invariant: the model estimates food identity and grams; the server obtains every nutrition value from a source row.

## What USDA establishes

USDA FNDDS 2021–2023 lists 91 codes in its pizza category. It already codes most sandwiches and burgers, and many Mexican dishes, as single items; its documentation explains that respondents often cannot report detailed component amounts. Its food profiles are per 100 g of edible food, with separate portion descriptions and gram weights. Many profiles use USDA recipe calculations that represent variants of a dish, rather than a specific household recipe. Therefore, a whole-dish entry is still an estimate, but ingredient reconstruction by an image model is not required. [USDA FNDDS documentation, pp. 11, 14, 17–18, 40](https://www.ars.usda.gov/ARSUserFiles/80400530/pdf/fndds/2021_2023_FNDDS_Doc.pdf)

The source types have different purposes. FNDDS describes foods and portions reported in dietary surveys; Foundation Foods emphasizes commodity and minimally processed foods; SR Legacy provides historical analytical and calculated food data; Branded Foods uses manufacturer label information. **Inference:** FNDDS is an appropriate source to consider for a generic prepared dish; an identifiable product can justify an exact branded record. A data-type preference alone cannot establish food identity. [FoodData Central data-type comparison](https://fdc.nal.usda.gov/data-documentation/)

## Whole-pizza records verified directly

The following identities were verified using USDA's public API on the research date, via `POST /fdc/v1/foods` with the listed IDs and `format: full`. All three records returned `Survey (FNDDS)` and nutrient fields including energy, protein, fat, and carbohydrate. These are examples of available records, not a claim about which matches the user's unseen photo. [USDA API guide](https://fdc.nal.usda.gov/api-guide/)

| FDC ID | FNDDS food code | Official description |
| --- | --- | --- |
| [2708616](https://fdc.nal.usda.gov/food-details/2708616/nutrients) | 58106225 | Pizza, cheese, from restaurant or fast food, medium crust |
| [2708612](https://fdc.nal.usda.gov/food-details/2708612/nutrients) | 58106200 | Pizza, cheese, from frozen, thin crust |
| [2708630](https://fdc.nal.usda.gov/food-details/2708630/nutrients) | 58106347 | Pizza with cheese and extra vegetables, medium crust |

The medium-crust restaurant cheese-pizza record assigns different piece weights to different pizza sizes: 80 g for small, 86 g for medium, 119 g for large, and 128 g for extra-large. Thus, “two slices” is useful count information but does not determine a universal mass or calorie total. The model should estimate the combined grams, with user correction available. [Verified USDA record 2708616](https://fdc.nal.usda.gov/food-details/2708616/nutrients)

Portion arithmetic remains `source value per 100 g × estimated grams ÷ 100`. USDA documents this scaling explicitly; source portion weights are examples for their associated records and should not replace a measured or corrected weight. [Foundation Foods: Weights](https://fdc.nal.usda.gov/Foundation_Foods_Documentation/)

## Search and matching implications

Direct API observations used `POST /fdc/v1/foods/search`, public `DEMO_KEY`, and `dataType: ["Survey (FNDDS)"]`:

- `query: "pizza"`, `pageSize: 10`: results began with dessert pizza, Mexican pizza, and pizza rolls; topping-only rows also appeared.
- `query: "pizza cheese"`, `pageSize: 30`: the first result was topping-only record 2705787, followed by a cheese-free pizza. Ordinary restaurant cheese-pizza record 2708616 did not appear in these first 30 results.

These observations concern candidate discovery, not nutrition comparison. They demonstrate that returning a dish label alone does not guarantee a suitable database match. USDA's search documentation describes broad word matching and operators for required words, exact phrases, and exclusions, but changes to the app's API query construction should be verified against recorded API responses. [USDA search help](https://fdc.nal.usda.gov/help/), [USDA API guide](https://fdc.nal.usda.gov/api-guide/)

The reduced candidate lists are preserved in [pizza-search-candidates.json](pizza-search-candidates.json). Replaying these lists through the app's actual `rank_foods` function ranked **2708675, Pizza, no cheese, thick crust** first for both `pizza` and `pizza cheese`. The latter contradicts the requested cheese. The current [tokenizer](../server/app/services/nutrition/relevance.py) drops two-letter words such as `no`, and the [ranker](../server/app/services/nutrition/usda.py) has no check for that negation.

This is a deterministic ranking finding on the recorded candidates, not a reproduction of the user's upload or the live resolver. The research API requests used POST, FNDDS filtering, and page sizes 10/30; the app uses GET, no data-type filter, and page size 25. The reduced records omit nutrients, so they also do not exercise nutrient validation or caching. Capture the actual app request shape before implementing a query change.

The replay command, from `server`, is:

```powershell
@'
import json
from pathlib import Path
from app.services.nutrition.usda import rank_foods
payload = json.loads(Path('../docs/pizza-search-candidates.json').read_text(encoding='utf-8'))
for case in payload['queries']:
    ranked = rank_foods(case['query'], case['foods'])
    print(case['query'])
    for item in ranked[:3]:
        print(str(item['fdcId']) + ': ' + item['description'])
'@ | .\.venv\Scripts\python.exe -
```

**Recommendation:** preserve whole-dish identity through every fallback. A whole pizza must not silently become crust, topping, pizza sauce, pizza rolls, or dessert pizza. Crust style and visible topping class can narrow a query when supported by the image or user text; do not invent a brand, preparation source, or precise recipe. If a reliable whole-dish row is unavailable, use the existing unresolved/review path rather than silently rebuilding an arbitrary recipe.

## Evidence limits

- The original uploaded photo and its exact detector output were not available to this research. The reported behavior has not been reproduced with that image.
- The API checks were read-only and used no app database or paid model calls. They verified source identities, portions, and search ordering, not calorie accuracy for the actual pizza.
- USDA detail pages did not render in the web text extractor; record identities and portions were verified through the first-party API instead. The table links are the corresponding official record pages.
- A generic dish row can misrepresent an unusual recipe. This supports showing a recognizable dish, editable mass, and source provenance; it does not justify promising photo-level nutritional precision.

## Local code findings and implementation plan

The [implementation plan](composite-food-detection-plan.md) records the conflicting detector instructions, the single-food provisional rule, the food-grouping policy, and the implementation results. The research baseline passed **82 tests** before application changes began.
