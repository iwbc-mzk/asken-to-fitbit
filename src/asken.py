from typing import Optional
from decimal import Decimal

from bs4 import BeautifulSoup
import requests

from .utils import remove_unit, get_logger
from .const import MEAL_TYPES, NUTRITIONS
from .models.asken import FoodLog


logger = get_logger(__name__)


class Asken:
    def __init__(self, email: str, password: str):
        self._url = "https://www.asken.jp"
        self._session = self.login(email, password)

    @staticmethod
    def _headers() -> dict:
        """Return headers for requests."""
        return {
            # User-Agentでアクセス制限をしているようで指定しないと403エラーが返ってくる
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
        }

    def login(self, email: str, password: str) -> requests.Session:
        """Login to Asken and return a session."""

        login_url = f"{self._url}/login/"
        session = requests.Session()

        payload = {
            "_method": "POST",
            "data[_Token][key]": "b5e46df4f20835456a0e20c07bc0d05fab17bceae4869081bddb3e419d8a476b5d465721a6fdb998e379eedb1f813d4f4accc4b4ccce5c9ce7e07746c2a02846",
            "data[CustomerMember][email]": email,
            "data[CustomerMember][passwd_plain]": password,
            "data[CustomerMember][autologin]": 1,
            "data[Submit][submit][x]": 102,
            "data[Submit][submit][x]": 19,
        }

        response = session.post(login_url, headers=self._headers(), data=payload)
        response.raise_for_status()  # Check if the request was successful

        logger.info("Logged in to Asken successfully.")

        return session

    def fetch_food_log(
        self, date: str, meal_type_id: Optional[int] = None
    ) -> Optional[FoodLog]:
        """
        Fetch food log for a specific date.
        Args:
            date (str): Date in the format 'YYYY-MM-DD'.
            meal_type_id (Optional[int]): Meal type ID (1: 朝食, 2: 昼食, 3: 夕食, 4: 間食, 5: 1日分). If None, fetches all total food log.
        Returns:
            FoodLog: Parsed food log data.
        """
        if meal_type_id in [1, 2, 3]:
            return self.fetch_one_meal_log(date, meal_type_id)
        elif meal_type_id == 4:
            return self.fetch_snack_log(date)
        elif meal_type_id == 5:
            return self.fetch_daily_food_log(date)
        else:
            return None

    def fetch_one_meal_log(self, date: str, meal_type_id: int) -> Optional[FoodLog]:
        """
        Fetch one meal log for a specific date and meal type.
        Args:
            date (str): Date in the format 'YYYY-MM-DD'.
            meal_type_id (int): Meal type ID (1: 朝食, 2: 昼食, 3: 夕食).
        Returns:
            FoodLog: Parsed food log data.
        """
        advice_url = (
            f"{self._url}/wsp/advice/{date}/{MEAL_TYPES[meal_type_id]['asken_id']}"
        )

        response = self._session.get(url=advice_url, headers=self._headers())
        response.raise_for_status()

        html = response.text
        if "食事記録が無いためアドバイスが計算できません" in html:
            return None

        nutritions = self._scrape_food_log(html)
        nutritions["meal_type_id"] = meal_type_id
        nutritions["date"] = date

        food_log = FoodLog(**nutritions)
        food_log.logged = True

        return food_log

    def fetch_daily_food_log(self, date: str) -> Optional[FoodLog]:
        """
        Fetch daily food log for a specific date.
        Args:
            date (str): Date in the format 'YYYY-MM-DD'.
        Returns:
            FoodLog: Parsed food log data.
        """
        advice_url = f"{self._url}/wsp/advice/{date}"
        response = self._session.get(url=advice_url, headers=self._headers())
        response.raise_for_status()

        html = response.text
        if "食事記録が無いためアドバイスが計算できません" in html:
            return None

        nutritions = self._scrape_food_log(html)
        nutritions["meal_type_id"] = 5  # Set meal type ID for daily log
        nutritions["date"] = date

        food_log = FoodLog(**nutritions)
        food_log.logged = True

        return food_log

    def fetch_snack_log(self, date: str) -> Optional[FoodLog]:
        """
        Fetch snack log for a specific date.
        Args:
            date (str): Date in the format 'YYYY-MM-DD'.
        Returns:
            FoodLog: Parsed snack log data.
        """
        float_to_decimal = lambda x: Decimal(str(x)) if type(x) == float else x

        daily_log = self.fetch_daily_food_log(date)
        if not daily_log:
            return None

        nutritions = {
            key: float_to_decimal(val) for key, val in daily_log.model_dump().items()
        }
        nutritions["meal_type_id"] = 4  # Set meal type ID for snack log

        for meal_type_id in [1, 2, 3]:
            one_meal_log_raw = self.fetch_one_meal_log(date, meal_type_id)
            if one_meal_log_raw is None:
                continue

            one_meal_log = one_meal_log_raw.model_dump()
            one_meal_log = {
                key: float_to_decimal(val) for key, val in one_meal_log.items()
            }

            nutritions["calories"] -= one_meal_log["calories"]
            nutritions["protein"] -= one_meal_log["protein"]
            nutritions["fat"] -= one_meal_log["fat"]
            nutritions["carbs"] -= one_meal_log["carbs"]
            nutritions["calcium"] -= one_meal_log["calcium"]
            nutritions["magnesium"] -= one_meal_log["magnesium"]
            nutritions["iron"] -= one_meal_log["iron"]
            nutritions["zinc"] -= one_meal_log["zinc"]
            nutritions["vitamin_a"] -= one_meal_log["vitamin_a"]
            nutritions["vitamin_d"] -= one_meal_log["vitamin_d"]
            nutritions["vitamin_b1"] -= one_meal_log["vitamin_b1"]
            nutritions["vitamin_b2"] -= one_meal_log["vitamin_b2"]
            nutritions["vitamin_b6"] -= one_meal_log["vitamin_b6"]
            nutritions["vitamin_c"] -= one_meal_log["vitamin_c"]
            nutritions["fiber"] -= one_meal_log["fiber"]
            nutritions["saturatedFat"] -= one_meal_log["saturatedFat"]
            nutritions["solt"] -= one_meal_log["solt"]

        # あすけんでは1日分の栄養素表示は１日分の栄養素を合計してから小数点１桁まで丸める
        # 朝食等ではその食事のみの栄養素を小数点１桁で丸めて表示している
        # そのため１日分の栄養素から各食事分の栄養素を引くと負の値になることがあるため以下で補正する
        correct = lambda x: Decimal(0.0) if type(x) == Decimal and -1.0 <= x < 0 else x
        nutritions = {key: correct(val) for key, val in nutritions.items()}

        # カロリーまたはPFCが登録されていれば間食ログあり
        exists_log = (
            nutritions["calories"]
            or nutritions["protein"]
            or nutritions["fat"]
            or nutritions["carbs"]
        )

        return FoodLog(**nutritions) if exists_log else None  # type: ignore

    def _scrape_food_log(self, html: str) -> dict:
        """
        Scrape food log data from HTML content.
        Args:
            html (str): HTML content of the food log page.
        Returns:
            FoodLog: Parsed food log data.
        """
        soup = BeautifulSoup(html, "html.parser")
        nutritions: dict[str, str | float] = {"date": ""}
        nutritions_ele = soup.find_all("li", class_="line_left")
        for nutrition_ele in nutritions_ele:
            nutrition_name = nutrition_ele.find("li", class_="title").text.strip()  # type: ignore
            nutrition_value: str = nutrition_ele.find("li", class_="val").text.strip()  # type: ignore

            if nutrition_name in NUTRITIONS:
                nutritions[NUTRITIONS[nutrition_name]] = remove_unit(nutrition_value)

        return nutritions
