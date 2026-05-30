"""
User Restrictions Model
Handles dietary restrictions, allergies, and preferences for nutrition recommendations
"""
from pydantic import BaseModel, Field
from typing import List
from enum import Enum


class DietType(str, Enum):
    OMNIVORE = "omnivore"
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    PESCATARIAN = "pescatarian"
    KETO = "keto"
    PALEO = "paleo"
    OTHER = "other"


class UserRestrictions(BaseModel):
    """User dietary and training restrictions"""
    diet_type: DietType = DietType.OMNIVORE
    allergies: List[str] = Field(default_factory=list, description="Food allergies")
    intolerances: List[str] = Field(default_factory=list, description="Food intolerances")
    dislikes: List[str] = Field(default_factory=list, description="Foods user dislikes")
    supplements: List[str] = Field(default_factory=list, description="Current supplements")
    avoid_meats: bool = Field(False, description="Avoid red meat")
    avoid_dairy: bool = Field(False, description="Avoid dairy")
    avoid_gluten: bool = Field(False, description="Avoid gluten")
    caffeine_sensitive: bool = Field(False, description="Caffeine sensitivity")
    lactose_intolerant: bool = Field(False, description="Lactose intolerance")
    orthorexia: bool = Field(False, description="Orthorexia risk flag")

    def get_supplement_recommendations(self) -> List[dict]:
        """Get supplement recommendations based on diet type"""
        base_supplements = [
            {
                "name": "Vitamin D",
                "dose": "2000-4000 IU/day",
                "timing": "Morning with fatty meal",
                "reason": "Most athletes are deficient"
            },
            {
                "name": "Omega-3 Fish Oil",
                "dose": "2-3g EPA+DHA",
                "timing": "With meals",
                "reason": "Anti-inflammatory, recovery support"
            }
        ]

        if self.diet_type == DietType.VEGAN:
            base_supplements.extend([
                {
                    "name": "Vitamin B12",
                    "dose": "1000mcg 2-3x/week",
                    "timing": "Any time",
                    "reason": "Only found in animal products"
                },
                {
                    "name": "Iron",
                    "dose": "18mg (women) / 8mg (men)",
                    "timing": "With vitamin C on empty stomach",
                    "reason": "Plant iron has low bioavailability"
                },
                {
                    "name": "Zinc",
                    "dose": "15-30mg",
                    "timing": "With food (zinc on empty stomach can cause nausea)",
                    "reason": "Important for immune and testosterone"
                },
                {
                    "name": "Creatine",
                    "dose": "5g/day",
                    "timing": "Any time, consistent",
                    "reason": "Vegans often have lower creatine stores"
                },
                {
                    "name": "BCAAs / EAAs",
                    "dose": "5-10g",
                    "timing": "Pre/intra workout",
                    "reason": "Complete amino profile from plant sources"
                }
            ])

        elif self.diet_type == DietType.VEGETARIAN:
            base_supplements.extend([
                {
                    "name": "Vitamin B12",
                    "dose": "1000mcg 2-3x/week",
                    "timing": "Any time",
                    "reason": "Limited in vegetarian diet"
                },
                {
                    "name": "Iron",
                    "dose": "18mg (women) / 8mg (men)",
                    "timing": "With vitamin C",
                    "reason": "Vegetarian iron is less bioavailable"
                },
                {
                    "name": "Creatine",
                    "dose": "5g/day",
                    "timing": "Any time",
                    "reason": "Supports high-intensity performance"
                }
            ])

        if self.avoid_dairy or self.lactose_intolerant:
            base_supplements.append({
                "name": "Calcium",
                "dose": "1000mg/day",
                "timing": "Split doses with meals",
                "reason": "Dairy is primary calcium source"
            })

        if self.caffeine_sensitive:
            # Remove caffeine recommendations
            base_supplements = [s for s in base_supplements if "caffeine" not in s.get("name", "").lower()]

        return base_supplements

    def get_protein_recommendations(self) -> dict:
        """Get protein recommendations based on diet type"""
        recommendations = {
            "daily_target_g_per_kg": 1.6,
            "per_meal_g": 25-40,
            "post_workout_g": 25-40,
            "best_sources": ["Chicken breast", "Fish", "Eggs", "Greek yogurt"],
            "timing": "Every 3-4 hours, including pre-bed"
        }

        if self.diet_type == DietType.VEGAN:
            recommendations = {
                "daily_target_g_per_kg": 1.8,
                "per_meal_g": 25-40,
                "post_workout_g": 30-45,
                "best_sources": [
                    "Tofu (firm)",
                    "Tempeh",
                    "Seitan",
                    "Edamame",
                    "Legumes + grains combo",
                    "Pea protein isolate",
                    "Hemp seeds"
                ],
                "timing": "Spread throughout day, leucine-rich foods important",
                "leucine_target_mg_per_meal": 2500,
                "leucine_rich_vegan": ["Tofu", "Tempeh", "Pea protein", "Soy milk"]
            }
        elif self.diet_type == DietType.VEGETARIAN:
            recommendations = {
                "daily_target_g_per_kg": 1.6,
                "per_meal_g": 25-35,
                "post_workout_g": 25-35,
                "best_sources": [
                    "Eggs",
                    "Greek yogurt",
                    "Cottage cheese",
                    "Paneer",
                    "Legumes",
                    "Whey protein"
                ],
                "timing": "Every 3-4 hours"
            }

        elif self.diet_type == DietType.KETO:
            recommendations = {
                "daily_target_g_per_kg": 1.8,
                "per_meal_g": 30-40,
                "post_workout_g": 25-30,
                "best_sources": [
                    "Beef",
                    "Fish",
                    "Eggs",
                    "Cheese",
                    "Poultry"
                ],
                "timing": "Higher protein on training days"
            }

        return recommendations

    def get_diet_specific_meal_suggestions(self) -> dict:
        """Get meal suggestions based on diet type"""
        suggestions = {
            "breakfast": [
                "Oatmeal with banana and honey",
                "Greek yogurt parfait",
                "Eggs with toast"
            ],
            "pre_workout": [
                "Banana with almond butter",
                "Rice cakes with avocado",
                "Small oatmeal serving"
            ],
            "post_workout": [
                "Protein shake with fruit",
                "Chicken with rice",
                "Greek yogurt with berries"
            ],
            "dinner": [
                "Grilled chicken with vegetables",
                "Salmon with sweet potato",
                "Lean beef with rice"
            ]
        }

        if self.diet_type == DietType.VEGAN:
            suggestions = {
                "breakfast": [
                    "Tofu scramble with vegetables",
                    "Overnight oats with chia seeds and fruit",
                    "Smoothie bowl with plant protein"
                ],
                "pre_workout": [
                    "Banana with peanut butter",
                    "Dates with almond butter",
                    "Small serving of oatmeal with maple syrup"
                ],
                "post_workout": [
                    "Pea protein shake with banana",
                    "Tempeh stir-fry with rice",
                    "Edamame bowl with quinoa"
                ],
                "dinner": [
                    "Tofu curry with basmati rice",
                    "Tempeh tacos with black beans",
                    "Seitan with roasted vegetables"
                ],
                "snacks": [
                    "Edamame",
                    "Hummus with vegetables",
                    "Mixed nuts and dried fruit",
                    "Rice cakes with avocado"
                ]
            }
        elif self.diet_type == DietType.VEGETARIAN:
            suggestions = {
                "breakfast": [
                    "Eggs with spinach and feta",
                    "Greek yogurt with granola and berries",
                    "Paneer bhurji with toast"
                ],
                "pre_workout": [
                    "Apple with cheese",
                    "Banana with yogurt",
                    "Oatmeal with milk"
                ],
                "post_workout": [
                    "Whey protein shake",
                    "Cottage cheese with fruit",
                    "Eggs with toast"
                ],
                "dinner": [
                    "Paneer tikka masala with rice",
                    "Chickpea curry with roti",
                    "Vegetable biryani with raita"
                ],
                "snacks": [
                    "Greek yogurt",
                    "Cheese cubes",
                    "Roasted chana",
                    "Protein bar"
                ]
            }

        if self.avoid_gluten:
            suggestions = {k: [s for s in v if "toast" not in s.lower() and "roti" not in s.lower()] for k, v in suggestions.items()}
            suggestions["dinner"].extend(["Rice bowl with proteins", "Quinoa salad", "GF pasta with vegetables"])

        if self.avoid_dairy or self.lactose_intolerant:
            suggestions = {k: [s for s in v if "greek yogurt" not in s.lower() and "cheese" not in s.lower() and "milk" not in s.lower()] for k, v in suggestions.items()}
            suggestions["breakfast"].extend(["Oatmeal with fruit", "Smoothie with plant milk", "Tofu scramble"])

        return suggestions

    def get_nutrition_warnings(self) -> List[str]:
        """Get warnings based on restrictions"""
        warnings = []

        if self.diet_type == DietType.VEGAN:
            warnings.append("Vegan athletes need to pay special attention to protein completeness and leucine intake")
            warnings.append("B12 supplementation is essential - no plant sources contain active B12")
            warnings.append("Consider creatine supplementation (5g/day) - vegan athletes often have lower stores")
            warnings.append("Iron and zinc absorption is reduced due to phytates in plants")

        if self.allergies:
            warnings.append(f"ALLERGIES: {', '.join(self.allergies)} - must be excluded from all recommendations")

        if self.intolerances:
            warnings.append(f"INTOLERANCES: {', '.join(self.intolerances)} - avoid these foods")

        if self.orthorexia:
            warnings.append("⚠️ Note: Athlete has flagged orthorexia risk - focus on balanced, sustainable nutrition")

        if len(self.dislikes) > 5:
            warnings.append(f"Athlete dislikes: {', '.join(self.dislikes[:5])} - avoid these foods in recommendations")

        return warnings


class NutritionTargets(BaseModel):
    """Daily nutrition targets based on goals and training"""
    calories: int = Field(2500, description="Daily calorie target")
    protein_g: int = Field(160, description="Daily protein in grams")
    carbs_g: int = Field(300, description="Daily carbs in grams")
    fat_g: int = Field(80, description="Daily fat in grams")

    protein_g_per_kg: float = Field(2.0, description="Protein per kg bodyweight")
    carbs_g_per_kg: float = Field(4.0, description="Carbs per kg bodyweight")
    fat_percent: float = Field(0.25, description="Fat as percent of calories")

    training_day_calories: int = Field(2800, description="Calories on training days")
    rest_day_calories: int = Field(2200, description="Calories on rest days")

    @classmethod
    def calculate_for_athlete(
        cls,
        bodyweight_kg: float,
        goals: List[str],
        training_days_per_week: int,
        diet_type: DietType = DietType.OMNIVORE,
        training_volume: str = "moderate"
    ) -> "NutritionTargets":
        """Calculate nutrition targets based on athlete profile"""

        # Base protein (varies by goal and diet)
        if "strength" in goals or "muscle" in goals:
            protein_multiplier = 2.0 if diet_type in [DietType.VEGAN, DietType.VEGETARIAN] else 1.8
        else:
            protein_multiplier = 1.6

        protein_g = int(bodyweight_kg * protein_multiplier)

        # Base calories (Harris-Benedict adjusted)
        bmr = 10 * bodyweight_kg + 600  # Simplified for active male
        tdee = bmr * 1.5  # Moderate activity

        # Adjust for goals
        if "weight_loss" in goals:
            tdee = tdee * 0.85
        elif "weight_gain" in goals or "muscle" in goals:
            tdee = tdee * 1.15

        calories = int(tdee)

        # Carbs based on training (higher for athletes)
        if training_volume == "high":
            carbs_g = int(bodyweight_kg * 6)
        elif training_volume == "moderate":
            carbs_g = int(bodyweight_kg * 4)
        else:
            carbs_g = int(bodyweight_kg * 3)

        # Fat (remainder)
        protein_cal = protein_g * 4
        carbs_cal = carbs_g * 4
        fat_cal = calories - protein_cal - carbs_cal
        fat_g = int(fat_cal / 9)

        # Training vs rest day adjustments
        if training_volume == "high":
            training_cal = int(calories * 1.1)
            rest_cal = int(calories * 0.85)
        elif training_volume == "moderate":
            training_cal = calories
            rest_cal = int(calories * 0.9)
        else:
            training_cal = int(calories * 0.95)
            rest_cal = int(calories * 0.85)

        return cls(
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            protein_g_per_kg=protein_multiplier,
            carbs_g_per_kg=carbs_g / bodyweight_kg,
            fat_percent=fat_cal / calories,
            training_day_calories=training_cal,
            rest_day_calories=rest_cal
        )
