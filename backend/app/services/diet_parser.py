"""
Custom Diet PDF Parser - Enhanced for Portuguese/Brazilian diets
Extracts nutrition info from user-uploaded diet plans
"""
import re
from typing import Dict, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DietPDFParser:
    """
    Parses user-uploaded diet PDFs to extract:
    - Daily calories
    - Macros (protein, carbs, fat)
    - Meal times
    - Food items per meal
    Supports Portuguese/Brazilian diet plans
    """

    def __init__(self, pdf_text: str):
        self.text = pdf_text
        self.lower_text = pdf_text.lower()

    def parse(self) -> Dict:
        """
        Parse PDF and return structured diet data
        """
        return {
            "daily_calories": self._extract_calories(),
            "macros": self._extract_macros(),
            "meals": self._extract_meals(),
            "supplements": self._extract_supplements(),
            "goals": self._extract_goals(),
            "notes": self._extract_notes(),
            "parsed_at": datetime.utcnow().isoformat()
        }

    def _extract_calories(self) -> Optional[int]:
        """Extract daily calorie target - supports PT/EN"""
        # Try English patterns first
        patterns_en = [
            r'(\d{4,5})\s*(?:kcal|calories|cal)',
            r'calories[:\s]*(\d{4,5})',
        ]

        for pattern in patterns_en:
            match = re.search(pattern, self.lower_text)
            if match:
                return int(match.group(1))

        # Try Portuguese patterns
        patterns_pt = [
            r'(\d{3,4})\s*(?:kcal|calorias|calorias\/dia)',
            r'calorias[:\s]*(\d{3,4})',
            r'(\d{3,4})\s*kcal\s*\/?\s*dia',
            r'energia[:\s]*(\d{3,4})',
        ]

        for pattern in patterns_pt:
            match = re.search(pattern, self.lower_text)
            if match:
                return int(match.group(1))

        # Calculate from macros if available
        macros = self._extract_macros()
        if all(macros.values()):
            # Calories = protein*4 + carbs*4 + fat*9
            cal = macros["protein_g"] * 4 + macros["carbs_g"] * 4 + macros["fat_g"] * 9
            if cal > 1000:
                return cal

        return None

    def _extract_macros(self) -> Dict[str, Optional[int]]:
        """Extract macro targets (protein, carbs, fat) - PT/EN"""
        macros = {"protein_g": None, "carbs_g": None, "fat_g": None}

        # Look for macro pattern like "(Carboidrato: 200g/Gordura: 45g/ Proteína: 215g)"
        combined_pattern = r'\(?carboidrato[:\s]*(\d{2,3})\s*g?\s*[\/,]\s*gordura[:\s]*(\d{2,3})\s*g?\s*[\/,]\s*prote[ií]na[:\s]*(\d{2,3})\s*g\)?'
        match = re.search(combined_pattern, self.lower_text)
        if match:
            macros["carbs_g"] = int(match.group(1))
            macros["fat_g"] = int(match.group(2))
            macros["protein_g"] = int(match.group(3))
            return macros

        # English patterns
        protein_patterns_en = [
            r'protein[:\s]*(\d{2,3})\s*g',
            r'(\d{2,3})\s*g\s*(?:of\s*)?protein',
        ]
        carbs_patterns_en = [
            r'carbs[:\s]*(\d{2,3})\s*g',
            r'carbohydrates[:\s]*(\d{2,3})\s*g',
        ]
        fat_patterns_en = [
            r'fat[:\s]*(\d{2,3})\s*g',
        ]

        # Portuguese patterns
        protein_patterns_pt = [
            r'prote[ií]na[:\s]*(\d{2,3})\s*g',
            r'(\d{2,3})\s*g\s*de\s*prote[ií]na',
        ]
        carbs_patterns_pt = [
            r'carboidrato[:\s]*(\d{2,3})\s*g',
            r'(\d{2,3})\s*g\s*de\s*carboidrato',
        ]
        fat_patterns_pt = [
            r'gordura[:\s]*(\d{2,3})\s*g',
            r'(\d{2,3})\s*g\s*de\s*gordura',
        ]

        # Try English first
        for pattern in protein_patterns_en:
            match = re.search(pattern, self.lower_text)
            if match:
                macros["protein_g"] = int(match.group(1))
                break

        for pattern in carbs_patterns_en:
            match = re.search(pattern, self.lower_text)
            if match:
                macros["carbs_g"] = int(match.group(1))
                break

        for pattern in fat_patterns_en:
            match = re.search(pattern, self.lower_text)
            if match:
                macros["fat_g"] = int(match.group(1))
                break

        # Try Portuguese if not found
        if not macros["protein_g"]:
            for pattern in protein_patterns_pt:
                match = re.search(pattern, self.lower_text)
                if match:
                    macros["protein_g"] = int(match.group(1))
                    break

        if not macros["carbs_g"]:
            for pattern in carbs_patterns_pt:
                match = re.search(pattern, self.lower_text)
                if match:
                    macros["carbs_g"] = int(match.group(1))
                    break

        if not macros["fat_g"]:
            for pattern in fat_patterns_pt:
                match = re.search(pattern, self.lower_text)
                if match:
                    macros["fat_g"] = int(match.group(1))
                    break

        return macros

    def _extract_meals(self) -> List[Dict]:
        """Extract meal times and food items - PT/EN"""
        # Portuguese meal patterns
        meal_patterns_pt = [
            (r'caf[eé]\s*da\s*manh[ãa][:\s–-]*refei[cç][ãa]o\s*\d*[:\s]*(\d{1,2}:\d{2})', 'breakfast', 'Café da manhã'),
            (r'lanche\s*da\s*manh[ãa][:\s–-]*refei[cç][ãa]o\s*\d*[:\s]*(\d{1,2}:\d{2})', 'morning_snack', 'Lanche da manhã'),
            (r'almo[cç]o[:\s–-]*refei[cç][ãa]o\s*\d*[:\s]*(\d{1,2}:\d{2})', 'lunch', 'Almoço'),
            (r'lanche\s*da\s*tarde[:\s–-]*refe[iç][ãa]o\s*\d*[:\s]*(\d{1,2}:\d{2})', 'afternoon_snack', 'Lanche da tarde'),
            (r'jantar[:\s–-]*refe[iç][ãa]o\s*\d*[:\s]*(\d{1,2}:\d{2})', 'dinner', 'Jantar'),
            (r'lanche\s*da\s*noite[:\s–-]*refe[iç][ãa]o\s*\d*[:\s]*(\d{1,2}:\d{2})', 'night_snack', 'Lanche da noite'),
            (r'pre[ -]*treino[:\s–-]*(\d{1,2}:\d{2})', 'pre_workout', 'Pré-treino'),
            (r'p[oó]s[ -]*treino[:\s–-]*(\d{1,2}:\d{2})', 'post_workout', 'Pós-treino'),
        ]

        # English patterns
        meal_patterns_en = [
            (r'breakfast[:\s–-]*meal\s*\d*[:\s]*(\d{1,2}:\d{2})', 'breakfast', 'Breakfast'),
            (r'morning\s*snack[:\s–-]*meal\s*\d*[:\s]*(\d{1,2}:\d{2})', 'morning_snack', 'Morning Snack'),
            (r'lunch[:\s–-]*meal\s*\d*[:\s]*(\d{1,2}:\d{2})', 'lunch', 'Lunch'),
            (r'afternoon\s*snack[:\s–-]*meal\s*\d*[:\s]*(\d{1,2}:\d{2})', 'afternoon_snack', 'Afternoon Snack'),
            (r'dinner[:\s–-]*meal\s*\d*[:\s]*(\d{1,2}:\d{2})', 'dinner', 'Dinner'),
            (r'night\s*snack[:\s–-]*meal\s*\d*[:\s]*(\d{1,2}:\d{2})', 'night_snack', 'Night Snack'),
            (r'pre[ -]*workout[:\s–-]*(\d{1,2}:\d{2})', 'pre_workout', 'Pre-workout'),
            (r'post[ -]*workout[:\s–-]*(\d{1,2}:\d{2})', 'post_workout', 'Post-workout'),
        ]

        found_meals = []

        for pattern, meal_type, meal_name in meal_patterns_pt + meal_patterns_en:
            match = re.search(pattern, self.lower_text)
            if match:
                time = match.group(1)

                # Find foods after this time
                start_pos = match.start()
                foods = self._extract_foods_after(start_pos)

                found_meals.append({
                    "name": meal_type,
                    "label": meal_name,
                    "time": time,
                    "foods": foods,
                    "calories": self._estimate_meal_calories(foods)
                })

        # Sort by time
        found_meals.sort(key=lambda x: x["time"])

        return found_meals

    def _extract_foods_after(self, position: int) -> List[str]:
        """Extract food items mentioned after a position"""
        # Look for a reasonable window of text
        window_size = 500
        text_chunk = self.lower_text[position:position + window_size]

        # Stop at next meal or end marker
        meal_markers = ['café da manhã', 'lanche da manhã', 'almoço', 'lanche da tarde', 'jantar', 'lanche da noite',
                       'breakfast', 'morning snack', 'lunch', 'afternoon snack', 'dinner', 'night snack',
                       'refeição 1', 'refeição 2', 'refeição 3', 'refeição 4', 'refeição 5', 'refeição 6']

        for marker in meal_markers:
            if marker in text_chunk[50:]:  # Skip if it's the current meal
                idx = text_chunk[50:].find(marker)
                if idx > 0:
                    text_chunk = text_chunk[:50 + idx]

        foods = []

        # Common food patterns in Portuguese diets
        food_patterns = [
            r'([\w\s]+)\s*[-–]\s*(\d+\s*g)',  # "Arroz - 160g"
            r'([\w\s]+)\s*(\d+\s*(?:g|ml|unidades?|colheres?|copos?))',  # "Ovo 2 unidades"
            r'((?:frango|salmon|carne|peixe|atum|ovos?|arroz|feijão|batata|aipim|milho|aveia|tapioca)\s*[\w\s]*)',
            r'(whey\s*protein)',
            r'(oleaginosas|sementes)',
        ]

        for pattern in food_patterns:
            matches = re.findall(pattern, text_chunk)
            for match in matches:
                if isinstance(match, tuple):
                    food = match[0].strip()
                else:
                    food = match.strip()

                # Clean up
                food = re.sub(r'\s+', ' ', food)
                if len(food) > 3 and len(food) < 60:
                    foods.append(food)

        # Deduplicate and limit
        foods = list(dict.fromkeys(foods))[:8]

        return foods

    def _estimate_meal_calories(self, foods: List[str]) -> Optional[int]:
        """Rough estimate of meal calories based on food items"""
        if not foods:
            return None

        # Rough calorie estimates per 100g/serving
        calorie_map = {
            'arroz': 130, 'arroz integral': 110, 'macarrão': 131, 'batata doce': 90,
            'batata': 85, 'aipim': 125, 'milho': 85, 'aveia': 68, 'tapioca': 55,
            'frango': 165, 'carne': 250, 'peixe': 130, 'atum': 130, 'ovos': 155,
            'whey': 120, 'feijão': 77, 'vegetais': 25, 'fruta': 60,
            'leite': 42, 'iogurte': 60, 'pasta de amendoim': 130,
        }

        total = 0
        for food in foods:
            food_lower = food.lower()
            for keyword, cal_per_100g in calorie_map.items():
                if keyword in food_lower:
                    # Estimate 1 serving
                    total += cal_per_100g * 1.0
                    break

        return total if total > 50 else None

    def _extract_supplements(self) -> List[str]:
        """Extract supplement recommendations"""
        supplements = []

        # Common supplements PT/EN
        supplement_patterns = [
            r'(whey\s*protein)',
            r'(creatine|creatina)',
            r'(bcaas?|eaa)',
            r'(vitamin[as]?\s*[ddeb12]|vitamina\s*[ddeb12])',
            r'(ómega\s*3|omega\s*3|fish\s*oil)',
            r'(café[i]?na|pre[ -]*workout)',
            r'(magnésio|magnesium|zinco|zinc)',
            r'(termogênico|thermogenic)',
        ]

        for pattern in supplement_patterns:
            matches = re.findall(pattern, self.lower_text)
            for match in matches:
                supp = match.strip().title()
                if supp not in supplements:
                    supplements.append(supp)

        return supplements[:10]

    def _extract_goals(self) -> Dict:
        """Extract diet goals and targets"""
        goals = {}

        # Weight loss/fat reduction
        if 'redução' in self.lower_text or 'defin' in self.lower_text:
            goals['type'] = 'cut'
            match = re.search(r'redução[:\s]*(\d+)\s*kg', self.lower_text)
            if match:
                goals['target_loss_kg'] = int(match.group(1))

        # Water
        water_match = re.search(r'(\d+)\s*ml\s*ao\s*dia', self.lower_text)
        if water_match:
            goals['water_ml'] = int(water_match.group(1))

        # Cardio
        cardio_match = re.search(r'c[áa]rdio[:\s]*(\d+)\s*minutos', self.lower_text)
        if cardio_match:
            goals['cardio_minutes_week'] = int(cardio_match.group(1))

        # Weekly reduction
        reduction_match = re.search(r'redução[:\s]*(\d+)\s*g?\s*[-–]\s*(\d+)\s*g', self.lower_text)
        if reduction_match:
            goals['weekly_reduction_g'] = (int(reduction_match.group(1)) + int(reduction_match.group(2))) // 2

        return goals

    def _extract_notes(self) -> str:
        """Extract any general notes or warnings"""
        notes = []

        note_patterns = [
            r'obs[:\s]([^\.]+\.)',
            r'observação[:\s]([^\.]+\.)',
            r'nota[:\s]([^\.]+\.)',
            r'importante[:\s]([^\.]+\.)',
            r'recomendação[:\s]([^\.]+\.)',
        ]

        for pattern in note_patterns:
            matches = re.findall(pattern, self.lower_text)
            for m in matches:
                note = m.strip()
                if len(note) > 10:
                    notes.append(note)

        return " | ".join(notes[:3]) if notes else ""


def parse_diet_pdf(pdf_text: str) -> Dict:
    """
    Main entry point for parsing a diet PDF

    Args:
        pdf_text: Extracted text from PDF

    Returns:
        Dict with calories, macros, meals, supplements, notes
    """
    parser = DietPDFParser(pdf_text)
    return parser.parse()
