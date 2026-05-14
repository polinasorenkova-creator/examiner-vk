import os
from dotenv import load_dotenv

load_dotenv()

VK_TOKEN = os.getenv("VK_TOKEN")
ROUTERAI_API_KEY = os.getenv("ROUTERAI_API_KEY")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

ROUTERAI_URL = "https://routerai.ru/api/v1/chat/completions"
MODEL = "qwen/qwen3.6-plus"