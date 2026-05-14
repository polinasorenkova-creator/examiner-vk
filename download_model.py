import os
import urllib.request
import zipfile

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODEL_PATH = "model"

if not os.path.exists(MODEL_PATH):
    print("Скачиваю модель Vosk...")
    urllib.request.urlretrieve(MODEL_URL, "model.zip")
    with zipfile.ZipFile("model.zip", "r") as z:
        z.extractall(".")
    os.rename("vosk-model-small-ru-0.22", MODEL_PATH)
    os.remove("model.zip")
    print("Модель загружена!")
else:
    print("Модель уже есть.")