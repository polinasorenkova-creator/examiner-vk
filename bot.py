import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import logging
import requests
import json
import time
import threading
import random
import download_model
from config import VK_TOKEN, ADMIN_IDS
from database import (init_db, save_ticket, get_random_ticket,
                      get_ticket_count, save_result, get_user_stats,
                      clear_tickets, clear_user_results)
from ai_client import recognize_ticket, transcribe_audio, evaluate_answer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sessions = {}
processed_ids = {}
lock = threading.Lock()

def get_keyboard(is_admin: bool) -> VkKeyboard:
    kb = VkKeyboard(one_time=False)
    kb.add_button("Сдать экзамен", color=VkKeyboardColor.POSITIVE)
    kb.add_button("Статистика", color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("Загрузить билет", color=VkKeyboardColor.SECONDARY)
    kb.add_button("Удалить все билеты", color=VkKeyboardColor.NEGATIVE)
    return kb

def send(vk, user_id: int, text: str, keyboard=None):
    params = {
        "user_id": user_id,
        "message": text,
        "random_id": random.randint(1, 2**31)
    }
    if keyboard:
        params["keyboard"] = keyboard.get_keyboard()
    vk.messages.send(**params)

def get_photo_url(vk, attachments: dict, message_id: int = None) -> str | None:
    i = 1
    while f"attach{i}_type" in attachments:
        if attachments[f"attach{i}_type"] == "photo":
            try:
                if message_id:
                    msgs = vk.messages.getById(message_ids=message_id)
                    if msgs["items"]:
                        for att in msgs["items"][0].get("attachments", []):
                            if att["type"] == "photo":
                                sizes = att["photo"].get("sizes", [])
                                if sizes:
                                    return max(
                                        sizes,
                                        key=lambda s: s.get("width", 0)
                                    )["url"]
            except Exception as e:
                logger.error(f"Ошибка фото: {e}")
        i += 1
    return None

def get_audio_url(attachments: dict) -> str | None:
    raw = attachments.get("attachments", "")
    if not raw:
        return None
    try:
        att_list = json.loads(raw)
        for att in att_list:
            if att.get("type") == "audio_message":
                return att["audio_message"].get("link_ogg", "")
    except Exception as e:
        logger.error(f"Ошибка парсинга аудио: {e}")
    return None

def is_duplicate(msg_id) -> bool:
    if not msg_id:
        return False
    now = time.time()
    with lock:
        old_keys = [k for k, t in processed_ids.items() if now - t > 120]
        for k in old_keys:
            del processed_ids[k]
        if msg_id in processed_ids:
            return True
        processed_ids[msg_id] = now
        return False

def handle(vk, event):
    msg_id = getattr(event, 'message_id', None) or getattr(event, 'id', None)
    if is_duplicate(msg_id):
        return

    user_id = event.user_id
    msg = (event.text or "").strip()
    msg_lower = msg.lower()
    is_admin = user_id in ADMIN_IDS

    with lock:
        session = dict(sessions.get(user_id, {"state": "idle"}))
    state = session["state"]

    logger.info(f"user={user_id} state={state} msg_id={msg_id} msg={msg_lower[:40]}")

    # ── УДАЛИТЬ ВСЕ БИЛЕТЫ ───────────────────────────────────────
    if "удалить все билеты" in msg_lower:
        clear_tickets(user_id)
        with lock:
            sessions.pop(user_id, None)
        send(vk, user_id,
             "Все ваши билеты удалены.",
             get_keyboard(is_admin))
        return

    # ── СБРОСИТЬ СТАТИСТИКУ ──────────────────────────────────────
    if "сбросить статистику" in msg_lower:
        clear_user_results(user_id)
        send(vk, user_id,
             "Ваша статистика сброшена.",
             get_keyboard(is_admin))
        return

    # ── ЗАГРУЗИТЬ БИЛЕТ ──────────────────────────────────────────
    if "загрузить билет" in msg_lower:
        with lock:
            sessions[user_id] = {"state": "waiting_ticket"}
        send(vk, user_id,
             "Отправьте фото билета или напишите текст вопроса.")
        return

    # ── ОБРАБОТКА БИЛЕТА ─────────────────────────────────────────
    if state == "waiting_ticket":

        if get_audio_url(event.attachments):
            send(vk, user_id,
                 "Пришлите фото билета или напишите текст вопроса.")
            return

        photo_url = get_photo_url(
            vk, event.attachments, event.message_id
        ) if event.attachments else None

        if photo_url:
            with lock:
                sessions[user_id] = {"state": "processing"}
            send(vk, user_id, "Распознаю билет, подожди...")
            try:
                img_bytes = requests.get(photo_url, timeout=15).content
                result = recognize_ticket(img_bytes)
                question = result.get("question", "")
                keywords = ", ".join(result.get("keywords", []))
                number = save_ticket(question, keywords, user_id)
                with lock:
                    sessions.pop(user_id, None)
                send(vk, user_id,
                     f"Билет №{number} сохранён!\n\n"
                     f"Вопрос:\n{question}\n\n"
                     f"Ключевые слова: {keywords}",
                     get_keyboard(is_admin))
            except Exception as e:
                logger.error(f"Ошибка OCR: {e}")
                with lock:
                    sessions.pop(user_id, None)
                send(vk, user_id,
                     "Не удалось распознать фото. "
                     "Попробуй ещё раз или напиши текстом.")
            return

        if msg and "загрузить билет" not in msg_lower:
            with lock:
                sessions[user_id] = {"state": "processing"}
            send(vk, user_id, "Анализирую вопрос...")
            try:
                result = recognize_ticket(msg.encode("utf-8"))
                question = result.get("question", msg)
                keywords = ", ".join(result.get("keywords", []))
                number = save_ticket(question, keywords, user_id)
                with lock:
                    sessions.pop(user_id, None)
                send(vk, user_id,
                     f"Билет №{number} сохранён!\n\n"
                     f"Вопрос:\n{question}\n\n"
                     f"Ключевые слова: {keywords}",
                     get_keyboard(is_admin))
            except Exception as e:
                logger.error(f"Ошибка анализа: {e}")
                with lock:
                    sessions.pop(user_id, None)
                send(vk, user_id, "Ошибка. Попробуй ещё раз.")
            return

        send(vk, user_id,
             "Пришлите фото билета или напишите текст вопроса.")
        return

    # ── СДАТЬ ЭКЗАМЕН ────────────────────────────────────────────
    if "сдать экзамен" in msg_lower or "начать экзамен" in msg_lower:
        with lock:
            cur = sessions.get(user_id, {})
            if cur.get("state") in ["waiting_answer", "processing"]:
                return
            sessions[user_id] = {"state": "processing"}

        count = get_ticket_count(user_id)
        if count == 0:
            with lock:
                sessions.pop(user_id, None)
            send(vk, user_id,
                 "У вас нет загруженных билетов.\n\n"
                 "Загрузите билеты через кнопку «Загрузить билет», "
                 "затем нажмите «Сдать экзамен».")
            return

        last_ticket_id = session.get("last_ticket_id")
        ticket = get_random_ticket(user_id, exclude_id=last_ticket_id)
        with lock:
            sessions[user_id] = {
                "state": "waiting_answer",
                "ticket": ticket,
                "last_ticket_id": ticket["id"]
            }
        send(vk, user_id,
             f"Вам достался Билет №{ticket['number']}\n\n"
             f"Вопрос: {ticket['text']}\n\n"
             f"Ответьте текстом или голосовым сообщением.")
        return

    # ── ОТВЕТ СТУДЕНТА ───────────────────────────────────────────
    if state == "waiting_answer":
        with lock:
            ticket = session.get("ticket")
            if not ticket:
                sessions.pop(user_id, None)
                return
            sessions[user_id] = {"state": "processing", "ticket": ticket}

        answer_text = ""

        audio_url = get_audio_url(event.attachments)
        if audio_url:
            send(vk, user_id, "Распознаю голос...")
            try:
                audio_bytes = requests.get(audio_url, timeout=15).content
                answer_text = transcribe_audio(audio_bytes)
                if answer_text:
                    send(vk, user_id, f"Распознал:\n{answer_text}")
                else:
                    send(vk, user_id,
                         "Не удалось распознать голос. Напиши текстом.")
                    with lock:
                        sessions[user_id] = {
                            "state": "waiting_answer", "ticket": ticket
                        }
                    return
            except Exception as e:
                logger.error(f"Ошибка транскрипции: {e}")
                send(vk, user_id,
                     "Не удалось распознать голос. Напиши текстом.")
                with lock:
                    sessions[user_id] = {
                        "state": "waiting_answer", "ticket": ticket
                    }
                return

        if not answer_text and msg:
            answer_text = msg

        if not answer_text:
            send(vk, user_id,
                 "Не понял ответа. Напиши текстом или голосовым.")
            with lock:
                sessions[user_id] = {
                    "state": "waiting_answer", "ticket": ticket
                }
            return

        send(vk, user_id, "Оцениваю ответ...")
        try:
            result = evaluate_answer(
                answer_text, ticket["keywords"], ticket["text"]
            )
            score = result.get("score", 0)
            max_score = result.get("max_score", 1)
            feedback = result.get("feedback", "")
            percent = round(score / max_score * 100) if max_score > 0 else 0

            if percent >= 80:
                verdict = "Зачтено!"
                grade = "5"
            elif percent >= 60:
                verdict = "Зачтено"
                grade = "4"
            elif percent >= 40:
                verdict = "Не зачтено"
                grade = "3"
            else:
                verdict = "Не зачтено"
                grade = "2"

            save_result(user_id, ticket["id"], score, max_score)
            with lock:
                sessions[user_id] = {
                    "state": "idle",
                    "last_ticket_id": ticket["id"]
                }
            send(vk, user_id,
                 f"Результат:\n\n"
                 f"{verdict}\n"
                 f"Оценка: {grade}\n"
                 f"Баллов: {score}/{max_score} ({percent}%)\n\n"
                 f"Комментарий: {feedback}",
                 get_keyboard(is_admin))
        except Exception as e:
            logger.error(f"Ошибка оценки: {e}")
            with lock:
                sessions.pop(user_id, None)
            send(vk, user_id,
                 "Ошибка оценки. Попробуй ещё раз.",
                 get_keyboard(is_admin))
        return

    # ── СТАТИСТИКА ───────────────────────────────────────────────
    if "статистика" in msg_lower or "мои результаты" in msg_lower:
        rows = get_user_stats(user_id)
        if not rows:
            send(vk, user_id,
                 "Вы ещё не сдавали экзамены.",
                 get_keyboard(is_admin))
            return
        lines = ["Последние результаты:\n"]
        for row in rows:
            pct = round(row[1] / row[2] * 100) if row[2] > 0 else 0
            lines.append(f"Билет №{row[0]}: {row[1]}/{row[2]} ({pct}%)")
        send(vk, user_id, "\n".join(lines), get_keyboard(is_admin))
        return

    # ── СТАРТ ────────────────────────────────────────────────────
    if any(x in msg_lower for x in ["начать", "start", "привет", "помощь"]) or msg == "":
        role = "Преподаватель" if is_admin else "Студент"
        send(vk, user_id,
             f"Привет! Я бот-Экзаменатор.\n"
             f"Роль: {role}\n\n"
             f"Нажми кнопку чтобы начать.",
             get_keyboard(is_admin))
        return

    send(vk, user_id, "Используй кнопки меню.", get_keyboard(is_admin))

def main():
    init_db()
    logger.info("БД инициализирована")
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    longpoll = VkLongPoll(vk_session)

    logger.info("Собираю старые сообщения...")
    start_ts = int(time.time())
    old_ids = set()
    try:
        deadline = time.time() + 8
        for event in longpoll.listen():
            if time.time() > deadline:
                break
            msg_id = getattr(event, 'message_id', None) or getattr(event, 'id', None)
            if msg_id:
                old_ids.add(msg_id)
    except Exception:
        pass

    longpoll = VkLongPoll(vk_session)
    with lock:
        processed_ids.clear()
        for mid in old_ids:
            processed_ids[mid] = time.time()

    logger.info(f"Пропущено старых сообщений: {len(old_ids)}")
    logger.info("Бот запущен!")

    for event in longpoll.listen():
        if (event.type == VkEventType.MESSAGE_NEW
                and event.to_me
                and not event.from_me):
            event_ts = getattr(event, 'timestamp', 0)
            if event_ts and event_ts < start_ts - 5:
                continue
            try:
                handle(vk, event)
            except Exception as e:
                logger.error(f"Ошибка: {e}", exc_info=True)

if __name__ == "__main__":
    main()