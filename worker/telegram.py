"""Отправка сообщений из воркера напрямую через Bot API (синхронно)."""

import json

import requests

from bot.config import BOT_TOKEN

_API = f'https://api.telegram.org/bot{BOT_TOKEN}'


def send_message(chat_id: int, text: str, reply_markup: dict = None):
    payload = {'chat_id': chat_id, 'text': text[:4096]}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    r = requests.post(f'{_API}/sendMessage', json=payload, timeout=30)
    r.raise_for_status()


def send_photo(chat_id: int, png: bytes, caption: str = '', reply_markup: dict = None):
    data = {'chat_id': chat_id, 'caption': caption[:1024]}
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    r = requests.post(f'{_API}/sendPhoto', data=data,
                      files={'photo': ('ocr.png', png, 'image/png')}, timeout=60)
    r.raise_for_status()
