"""
AI-Powered Training Programmer - Enhanced with Nutrition and Health Integration
Generates progressive training programs using LLM with full athlete context
"""
from datetime import date
from typing import List, Dict, Optional
from uuid import UUID
import json
import logging
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.training import (
    WorkoutTemplate,
    Movement,
    WorkoutType,
    Methodology,
    DayOfWeek
)

logger = logging.getLogger(__name__)


class AITrainingProgrammerV2:
    """
    Enhanced AI training programmer with full athlete context:
    - Physical assessment data
    - Training history
    - Nutrition data and restrictions
    - Health metrics (HRV, recovery, sleep)
    - Goals and preferences
    """

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None

    async def generate_weekly_program(
        self,
        user_profile: dict,
        methodology: Methodology,
        training_days: List[DayOfWeek],
        session_durations: Dict[DayOfWeek, int],
        week_number: int = 1,
        focus_movements: Optional[List[str]] = None,
        previous_week_data: Optional[dict] = None,
        nutrition_data: Optional[dict] = None,
        health_metrics: Optional[dict] = None,
        user_restrictions: Optional[dict] = None
    ) -> Dict[DayOfWeek, WorkoutTemplate]:
        """
        Generate complete weekly training program using AI with full context

        Args:
            user_profile: User fitness level, goals, weaknesses, PRs, dietary restrictions
            methodology: HWPO, Mayhem, CompTrain, Custom
            training_days: List of days to train
            session_durations: Duration for each day
            week_number: Current week in mesocycle
            focus_movements: Movements to emphasize
            previous_week_data: Results from previous week
            nutrition_data: Recent nutrition intake and macros
            health_metrics: HRV, sleep, recovery scores
            user_restrictions: Dietary restrictions (vegan, etc.)
        """
        if not self.client:
            logger.warning("OpenAI API key not configured, using fallback templates")
            return self._generate_fallback_program(training_days, session_durations)

        context = self._build_enhanced_context(
            user_profile=user_profile,
            methodology=methodology,
            training_days=training_days,
            session_durations=session_durations,
            week_number=week_number,
            focus_movements=focus_movements,
            previous_week_data=previous_week_data,
            nutrition_data=nutrition_data,
            health_metrics=health_metrics,
            user_restrictions=user_restrictions
        )

        prompt = self._build_enhanced_prompt(context)

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": self._get_enhanced_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )

            program_json = json.loads(response.choices[0].message.content)
            weekly_program = self._parse_ai_response(program_json, training_days)

            logger.info(f"Generated weekly program for week {week_number}")
            return weekly_program

        except Exception as e:
            logger.error(f"Failed to generate AI program: {e}", exc_info=True)
            return self._generate_fallback_program(training_days, session_durations)

    def _get_enhanced_system_prompt(self) -> str:
        """
        Enhanced system prompt with nutrition and health integration
        """
        return """You are an elite CrossFit programming coach with expertise in HWPO (Mat Fraser), Mayhem (Rich Froning), and CompTrain (Ben Bergeron) methodologies.

You take a HOLISTIC approach to programming, considering:
1. **Physical Assessment**: Movement patterns, strengths, weaknesses, PRs
2. **Training History**: Recent performance, fatigue accumulation, progressions
3. **Nutrition & Recovery**: Using nutrition data to optimize training adaptation
4. **Health Metrics**: HRV, sleep quality, readiness scores for auto-regulation
5. **Dietary Restrictions**: Vegan, vegetarian, allergies - adjusting recommendations accordingly

Your programming philosophy balances:
- Strength vs. Conditioning (based on goals)
- Volume vs. Intensity (based on recovery capacity)
- Skill vs. Work Capacity (based on weaknesses)
- Nutrition timing & recovery (based on dietary patterns)

**Key Principles:**

1. **Periodization** (4-week cycles):
   - Week 1-3: Accumulation (volume + intensity builds)
   - Week 4: Deload (40% volume reduction)
   - Week 5-7: Intensification (peak performance)
   - Week 8: Test/Competition

2. **Auto-Regulation** (adjust based on readiness):
   - Readiness > 80%: Full intensity
   - Readiness 60-80%: Reduce intensity 10-15%
   - Readiness < 60%: Focus on skill/mobility, reduce metcon

3. **Nutrition Integration**:
   - Protein intake affects recovery capacity
   - Carb availability affects high-intensity performance
   - Low energy availability → reduce volume
   - Vegan/vegetarian: Ensure protein adequacy, consider BCAAs

4. **Movement Selection**:
   - Prioritize compound movements
   - Address weaknesses with targeted accessory work
   - Balance push/pull, squat/hinge patterns

**Session Structure:**

*Short Sessions (≤60min):*
- Warm-up: 10min
- Skill/Strength: 15-20min
- MetCon: 15-20min
- Cooldown: 5min

*Long Sessions (>60min):*
- Warm-up: 15min
- Strength: 30min
- Accessory: 15min
- MetCon: 20-25min
- Cooldown: 10min

**Nutrition Recommendations Format:**
When suggesting nutrition, ALWAYS consider:
- User's dietary restrictions (vegan, vegetarian, allergies)
- Protein needs based on training volume and body weight
- Carb needs based on training intensity
- Timing around workouts (pre/intra/post)
- Supplementation considerations (especially for vegan athletes)

**Output Format:**
Return valid JSON with:
1. Weekly program (workouts for each day)
2. Nutrition recommendations (meal timing, macro targets, supplements)
3. Recovery suggestions (sleep targets, mobility, stress management)

IMPORTANT:
- Always specify reps_unit for calorie/distance work
- Never put meters or calories in "reps" field without unit
- Include scaling options for all fitness levels
- Add mobility/recovery recommendations
- Give specific, actionable nutrition advice"""

    def _build_enhanced_context(
        self,
        user_profile: dict,
        methodology: Methodology,
        training_days: List[DayOfWeek],
        session_durations: Dict[DayOfWeek, int],
        week_number: int,
        focus_movements: Optional[List[str]],
        previous_week_data: Optional[dict],
        nutrition_data: Optional[dict],
        health_metrics: Optional[dict],
        user_restrictions: Optional[dict]
    ) -> dict:
        """Build comprehensive context for AI prompt"""

        # Extract user info
        fitness_level = user_profile.get("fitness_level", "intermediate")
        weight_kg = user_profile.get("weight_kg", 80)
        height_cm = user_profile.get("height_cm", 175)
        goals = user_profile.get("preferences", {}).get("goals", ["strength", "conditioning"])
        weaknesses = user_profile.get("preferences", {}).get("weaknesses", [])
        prs = user_profile.get("personal_records", [])

        # Dietary restrictions
        diet_type = user_restrictions.get("diet_type", "omnivore") if user_restrictions else "omnivore"
        allergies = user_restrictions.get("allergies", []) if user_restrictions else []
        supplements = user_restrictions.get("supplements", []) if user_restrictions else []

        # Nutrition data
        avg_daily_protein = 0
        avg_daily_carbs = 0
        avg_daily_fat = 0
        avg_calories = 0
        protein_adequacy = "unknown"

        if nutrition_data:
            avg_daily_protein = nutrition_data.get("avg_daily_protein_g", 0)
            avg_daily_carbs = nutrition_data.get("avg_daily_carbs_g", 0)
            avg_daily_fat = nutrition_data.get("avg_daily_fat_g", 0)
            avg_calories = nutrition_data.get("avg_daily_calories", 0)

            # Calculate protein adequacy (g per kg bodyweight)
            protein_per_kg = avg_daily_protein / weight_kg if weight_kg else 0
            if protein_per_kg < 1.2:
                protein_adequacy = "LOW - may impair recovery"
            elif protein_per_kg < 1.6:
                protein_adequacy = "ADEQUATE"
            elif protein_per_kg < 2.2:
                protein_adequacy = "OPTIMAL for muscle growth"
            else:
                protein_adequacy = "HIGH - may be excessive"

        # Health metrics
        avg_hrv = 0
        avg_sleep_hours = 0
        avg_readiness = 0
        avg_muscle_soreness = 0
        recovery_status = "unknown"

        if health_metrics:
            avg_hrv = health_metrics.get("avg_hrv", 0)
            avg_sleep_hours = health_metrics.get("avg_sleep_hours", 0)
            avg_readiness = health_metrics.get("avg_readiness", 0)
            avg_muscle_soreness = health_metrics.get("avg_muscle_soreness", 0)

            # Determine recovery status
            if avg_readiness >= 80 and avg_sleep_hours >= 7:
                recovery_status = "OPTIMAL - Ready for high intensity"
            elif avg_readiness >= 65 and avg_sleep_hours >= 6:
                recovery_status = "GOOD - Normal training"
            elif avg_readiness >= 50:
                recovery_status = "MODERATE - Consider reducing intensity"
            else:
                recovery_status = "COMPROMISED - Focus on recovery, reduce volume"

        # Calculate mesocycle phase
        if week_number <= 3:
            phase = "accumulation"
            phase_description = "Building volume and work capacity"
        elif week_number == 4:
            phase = "deload"
            phase_description = "Recovery week - reduce volume 40%"
        elif week_number <= 7:
            phase = "intensification"
            phase_description = "Building intensity and strength"
        else:
            phase = "test_week"
            phase_description = "Test fitness gains"

        # Calculate recommended training adjustments based on recovery
        intensity_adjustment = "maintain"
        volume_adjustment = "maintain"

        if recovery_status == "COMPROMISED":
            intensity_adjustment = "reduce_by_15%"
            volume_adjustment = "reduce_by_25%"
        elif recovery_status == "MODERATE":
            intensity_adjustment = "reduce_by_5%"
            volume_adjustment = "reduce_by_10%"
        elif recovery_status == "OPTIMAL":
            intensity_adjustment = "increase_by_5%"
            volume_adjustment = "maintain"

        # Calculate protein targets based on diet
        if diet_type == "vegan":
            protein_recommendation = "1.8-2.2g/kg bodyweight (focus on complete proteins: tofu, tempeh, seitan + leucine-rich foods)"
            bcaas_recommendation = "CONSIDER BCAA supplement (5-10g pre/post workout)"
            iron_zinc_note = "Monitor iron and zinc levels (common deficiencies in vegan athletes)"
        elif diet_type == "vegetarian":
            protein_recommendation = "1.6-2.0g/kg bodyweight (combine legumes + grains for complete proteins)"
            bcaas_recommendation = "Optional BCAA 3-5g if plant protein timing is difficult"
            iron_zinc_note = "Ensure adequate iron (legumes, fortified foods) and zinc"
        else:
            protein_recommendation = "1.6-2.0g/kg bodyweight (animal sources complete)"
            bcaas_recommendation = "Not necessary with adequate protein intake"
            iron_zinc_note = ""

        context = {
            "athlete": {
                "profile": {
                    "fitness_level": fitness_level,
                    "bodyweight_kg": weight_kg,
                    "height_cm": height_cm,
                    "goals": goals,
                    "weaknesses": weaknesses,
                    "personal_records": prs[:5] if prs else []  # Top 5 PRs
                },
                "diet": {
                    "diet_type": diet_type,
                    "allergies": allergies,
                    "supplements": supplements,
                    "avg_daily_protein_g": avg_daily_protein,
                    "avg_daily_carbs_g": avg_daily_carbs,
                    "avg_daily_fat_g": avg_daily_fat,
                    "avg_calories": avg_calories,
                    "protein_adequacy": protein_adequacy,
                    "protein_recommendation": protein_recommendation,
                    "bcaas_recommendation": bcaas_recommendation,
                    "iron_zinc_note": iron_zinc_note
                },
                "health": {
                    "avg_hrv": avg_hrv,
                    "avg_sleep_hours": avg_sleep_hours,
                    "avg_readiness": avg_readiness,
                    "avg_muscle_soreness": avg_muscle_soreness,
                    "recovery_status": recovery_status
                }
            },
            "program": {
                "methodology": methodology.value,
                "week_number": week_number,
                "phase": phase,
                "phase_description": phase_description,
                "training_days": [day.value for day in training_days],
                "session_durations": {day.value: duration for day, duration in session_durations.items()},
                "focus_movements": focus_movements or [],
                "intensity_adjustment": intensity_adjustment,
                "volume_adjustment": volume_adjustment
            },
            "previous_week": previous_week_data
        }

        return context

    def _build_enhanced_prompt(self, context: dict) -> str:
        """Build enhanced prompt with nutrition and health integration"""

        athlete = context["athlete"]
        profile = athlete["profile"]
        diet = athlete["diet"]
        health = athlete["health"]
        program = context["program"]

        prompt = f"""Generate a COMPLETE weekly training program with holistic recommendations.

## ATHLETE PROFILE
- **Fitness Level:** {profile['fitness_level']}
- **Bodyweight:** {profile['bodyweight_kg']}kg
- **Height:** {profile['height_cm']}cm
- **Goals:** {', '.join(profile['goals'])}
- **Weaknesses:** {', '.join(profile['weaknesses']) if profile['weaknesses'] else 'None specified'}
- **Top PRs:** {', '.join([f"{pr.get('movement')}: {pr.get('weight_kg', pr.get('time'))}" for pr in profile.get('personal_records', [])]) or 'No PRs recorded'}

## DIETARY INFORMATION
- **Diet Type:** {diet['diet_type'].upper()}
- **Allergies:** {', '.join(diet['allergies']) if diet['allergies'] else 'None'}
- **Supplements:** {', '.join(diet['supplements']) if diet['supplements'] else 'None reported'}

### Current Nutrition (Last 7 Days Average):
- **Protein:** {diet['avg_daily_protein_g']:.0f}g/day
- **Carbs:** {diet['avg_daily_carbs_g']:.0f}g/day
- **Fat:** {diet['avg_daily_fat_g']:.0f}g/day
- **Calories:** {diet['avg_calories']:.0f} kcal/day

### Protein & Recovery Recommendations:
- **Target:** {diet['protein_recommendation']}
- **BCAAs:** {diet['bcaas_recommendation']}
{diet['iron_zinc_note'] if diet['iron_zinc_note'] else ''}

## HEALTH & RECOVERY METRICS (Last 7 Days):
- **Average HRV:** {health['avg_hrv']:.0f} ms
- **Average Sleep:** {health['avg_sleep_hours']:.1f} hours
- **Average Readiness:** {health['avg_readiness']:.0f}/100
- **Muscle Soreness:** {health['avg_muscle_soreness']:.1f}/10
- **Recovery Status:** {health['recovery_status']}

## TRAINING PROGRAM
- **Methodology:** {program['methodology'].upper()}
- **Week:** {program['week_number']} ({program['phase_description']})
- **Training Days:** {', '.join(program['training_days'])}
- **Session Durations:** {json.dumps(program['session_durations'])}
- **Focus Movements:** {', '.join(program['focus_movements']) if program['focus_movements'] else 'None'}

### Recommended Adjustments Based on Recovery:
- **Intensity:** {program['intensity_adjustment']}
- **Volume:** {program['volume_adjustment']}

## PREVIOUS WEEK PERFORMANCE:
{json.dumps(context.get('previous_week', {}), indent=2) if context.get('previous_week') else 'First week - no previous data'}

---

## YOUR TASK:

Generate a complete weekly program with the following JSON structure:

```json
{{
  "program_summary": "Brief overview of the week's focus",
  "nutrition_recommendations": {{
    "daily_targets": {{
      "protein_g_per_kg": 2.0,
      "carbs_g_per_kg": 5.0,
      "fat_g_per_kg": 1.0,
      "calories": 2800
    }},
    "meal_timing": [
      {{
        "timing": "Pre-workout (2h before)",
        "suggestion": "50g protein + moderate carbs (banana, oats)",
        "example": "Greek yogurt bowl with berries and honey"
      }},
      {{
        "timing": "Intra-workout (if >60min)",
        "suggestion": "30g carbs + electrolytes",
        "example": "White rice cakes + sports drink"
      }},
      {{
        "timing": "Post-workout (within 2h)",
        "suggestion": "25-40g protein + fast carbs",
        "example": "Protein shake with banana and maltodextrin"
      }}
    ],
    "diet_specific": {{
      "vegan": {{
        "protein_sources": ["Tofu scramble breakfast", "Tempeh stir-fry", "Seitan strength training meals", "Legume-based dinners"],
        "recovery_snacks": ["Edamame", "Hummus with pita", "Protein smoothie with pea protein"],
        "key_supplements": ["B12", "Iron", "Zinc", "Omega-3", "Vitamin D", "BCAAs"]
      }},
      "vegetarian": {{
        "protein_sources": ["Eggs + dairy", "Paneer dishes", "Legume combos", "Greek yogurt"],
        "recovery_snacks": ["Whey protein", "Cheese + crackers", "Yogurt parfaits"],
        "key_supplements": ["B12", "Iron", "Omega-3"]
      }}
    }},
    "supplements": [
      {{
        "name": "Creatine",
        "dose": "5g/day",
        "timing": "Any time, consistent daily",
        "benefit": "Strength and power output"
      }},
      {{
        "name": "Caffeine",
        "dose": "3-6mg/kg",
        "timing": "30-60min pre-workout",
        "benefit": "Performance, focus"
      }}
    ]
  }},
  "workouts": {{
    "monday": {{
      "name": "Workout Name",
      "duration_minutes": 90,
      "workout_type": "strength",
      "recovery_focus": "Why this workout is appropriate given current recovery status",
      "parts": [
        {{
          "part_name": "Warm-up",
          "duration_minutes": 15,
          "movements": []
        }},
        {{
          "part_name": "Strength",
          "duration_minutes": 30,
          "movements": [
            {{
              "movement": "back_squat",
              "sets": 5,
              "reps": 5,
              "intensity": "80% 1RM",
              "rest": "3min",
              "notes": "Cues for technique"
            }}
          ]
        }}
      ],
      "nutrition_notes": "Specific pre/post meal suggestions for this workout",
      "scaling_options": {{
        "rx": "As written",
        "scaled": "Modified load/movements",
        "beginner": "Further simplified"
      }}
    }}
  }},
  "recovery_plan": {{
    "sleep_target_hours": 8,
    "mobility_work": "10-15min daily",
    "stress_management": "Meditation, cold exposure, etc."
  }}
}}
```

**IMPORTANT:**
1. For vegan athletes: ALWAYS recommend complete protein combinations and key supplements (B12, iron, zinc, omega-3)
2. Adjust workout intensity based on recovery status
3. Include specific nutrition timing around workouts
4. Give scaling options for all fitness levels
5. Consider dietary restrictions in meal suggestions

Generate the complete program now."""

        return prompt

    def _parse_ai_response(
        self,
        program_json: dict,
        training_days: List[DayOfWeek]
    ) -> Dict[DayOfWeek, WorkoutTemplate]:
        """Parse AI response into WorkoutTemplate objects"""
        # Same as original implementation
        weekly_program = {}
        workouts = program_json.get("workouts", {})

        for day in training_days:
            day_key = day.value
            if day_key not in workouts:
                continue

            workout_data = workouts[day_key]
            all_movements = []

            for part in workout_data.get("parts", []):
                for mov in part.get("movements", []):
                    movement = Movement(
                        movement=mov.get("movement"),
                        sets=mov.get("sets"),
                        reps=mov.get("reps"),
                        reps_unit=mov.get("reps_unit", "reps"),
                        weight_kg=mov.get("weight_kg"),
                        distance_meters=mov.get("distance_meters"),
                        duration_seconds=mov.get("duration_seconds"),
                        intensity=mov.get("intensity"),
                        rest=mov.get("rest"),
                        notes=mov.get("notes")
                    )
                    all_movements.append(movement)

            workout_type = self._normalize_workout_type(workout_data.get("workout_type", "mixed"))

            template = WorkoutTemplate(
                id=UUID("00000000-0000-0000-0000-000000000000"),
                name=workout_data.get("name", f"{day_key.title()} Workout"),
                description=workout_data.get("description", ""),
                methodology=Methodology.CUSTOM,
                difficulty_level="rx",
                workout_type=workout_type,
                duration_minutes=workout_data.get("duration_minutes"),
                movements=all_movements,
                target_stimulus=workout_data.get("target_stimulus"),
                tags=["ai_generated_v2", day_key],
                equipment_required=[],
                created_at=date.today(),
                is_public=False
            )

            weekly_program[day] = template

        return weekly_program

    def _normalize_workout_type(self, raw_type: str) -> WorkoutType:
        """Map workout type strings to valid enum values"""
        raw = raw_type.lower().strip()

        for wt in WorkoutType:
            if wt.value == raw:
                return wt

        if any(k in raw for k in ["strength", "squat", "deadlift", "press", "heavy"]):
            return WorkoutType.MIXED if any(k in raw for k in ["metcon", "wod"]) else WorkoutType.STRENGTH
        if any(k in raw for k in ["metcon", "wod", "amrap", "emom", "chipper", "for time"]):
            return WorkoutType.METCON
        if any(k in raw for k in ["skill", "gymnastic", "handstand", "muscle-up"]):
            return WorkoutType.SKILL
        if any(k in raw for k in ["conditioning", "cardio", "aerobic", "run", "row", "bike"]):
            return WorkoutType.CONDITIONING

        return WorkoutType.MIXED

    def _generate_fallback_program(
        self,
        training_days: List[DayOfWeek],
        session_durations: Dict[DayOfWeek, int]
    ) -> Dict[DayOfWeek, WorkoutTemplate]:
        """Fallback if AI unavailable"""
        return {}


# Global instance
ai_programmer_v2 = AITrainingProgrammerV2()
