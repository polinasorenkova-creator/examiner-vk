import aiohttp
import asyncio
import base64
import json
import logging
import wave
import io
from config import ROUTERAI_API_KEY, ROUTERAI_URL, MODEL

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Bearer {ROUTERAI_API_KEY}",
    "Content-Type": "application/json"
}

# Vosk для голосовых
try:
    from vosk import Model, KaldiRecognizer
    from pydub import AudioSegment
    vosk_model = Model("model")
    logger.info("Vosk модель загружена")
except Exception as e:
    vosk_model = None
    logger.warning(f"Vosk не загружен: {e}. Голосовые не будут работать.")

async def recognize_ticket_async(image_bytes: bytes) -> dict:
    # Пробуем декодировать как текст
    try:
        text_content = image_bytes.decode("utf-8")
        # Это текст — отправляем без картинки
        payload = {
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": (
                    f"Это текст экзаменационного билета:\n{text_content}\n\n"
                    "Выдели суть вопроса и 3-5 ключевых терминов. "
                    "Верни ТОЛЬКО JSON без пояснений:\n"
                    '{"question": "текст вопроса", "keywords": ["слово1", "слово2", "слово3"]}'
                )
            }],
            "max_tokens": 1000
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(ROUTERAI_URL, json=payload, headers=HEADERS) as resp:
                data = await resp.json()
        logger.info(f"recognize_ticket text: {data}")
        if "error" in data:
            raise Exception(f"RouterAI error: {data['error']}")
        text = data["choices"][0]["message"]["content"]
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except UnicodeDecodeError:
        pass  # Бинарные данные — значит это картинка

    # Конвертируем картинку в JPEG
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO()
        img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=85)
        image_bytes = buf.getvalue()
    except Exception as e:
        logger.warning(f"Конвертация фото не удалась: {e}")

    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                },
                {
                    "type": "text",
                    "text": (
                        "Распознай текст на русском языке с изображения экзаменационного билета. "
                        "Выдели суть вопроса и 3-5 ключевых терминов. "
                        "Верни ТОЛЬКО JSON без пояснений:\n"
                        '{"question": "текст вопроса", "keywords": ["слово1", "слово2", "слово3"]}'
                    )
                }
            ]
        }],
        "max_tokens": 1000
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(ROUTERAI_URL, json=payload, headers=HEADERS) as resp:
            data = await resp.json()
    logger.info(f"recognize_ticket image: {data}")
    if "error" in data:
        raise Exception(f"RouterAI error: {data['error']}")
    text = data["choices"][0]["message"]["content"]
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            ROUTERAI_URL, json=payload, headers=HEADERS
        ) as resp:
            data = await resp.json()

    logger.info(f"recognize_ticket: {data}")

    if "error" in data:
        raise Exception(f"RouterAI error: {data['error']}")

    text = data["choices"][0]["message"]["content"]
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

async def evaluate_answer_async(
    user_answer: str, keywords: str, question: str
) -> dict:
    keywords_list = [k.strip() for k in keywords.split(",")]
    max_score = len(keywords_list)
    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": (
                f"Вопрос: {question}\n"
                f"Ключевые слова эталона: {keywords}\n"
                f"Ответ студента: {user_answer}\n\n"
                f"Оцени ответ студента. За каждое ключевое слово "
                f"или его синоним — 1 балл. "
                f"Максимум {max_score} баллов. "
                f"Верни ТОЛЬКО JSON без пояснений:\n"
                f'{{"score": <число>, "max_score": {max_score}, '
                f'"feedback": "короткий комментарий на русском"}}'
            )
        }],
        "max_tokens": 300
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            ROUTERAI_URL, json=payload, headers=HEADERS
        ) as resp:
            data = await resp.json()

    logger.info(f"evaluate_answer: {data}")

    if "error" in data:
        raise Exception(f"RouterAI error: {data['error']}")

    text = data["choices"][0]["message"]["content"]
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

def transcribe_audio(audio_bytes: bytes) -> str:
    """Транскрибируем голос локально через Vosk."""
    if not vosk_model:
        logger.error("Vosk модель не загружена")
        return ""
    try:
        audio = AudioSegment.from_ogg(io.BytesIO(audio_bytes))
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        wav_buf = io.BytesIO()
        audio.export(wav_buf, format="wav")
        wav_buf.seek(0)

        wf = wave.open(wav_buf)
        rec = KaldiRecognizer(vosk_model, wf.getframerate())
        rec.SetWords(True)

        results = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                results.append(res.get("text", ""))

        res = json.loads(rec.FinalResult())
        results.append(res.get("text", ""))
        return " ".join(r for r in results if r).strip()
    except Exception as e:
        logger.error(f"Ошибка Vosk: {e}")
        return ""

def recognize_ticket(image_bytes: bytes) -> dict:
    return asyncio.run(recognize_ticket_async(image_bytes))

def evaluate_answer(user_answer: str, keywords: str, question: str) -> dict:
    return asyncio.run(evaluate_answer_async(user_answer, keywords, question))