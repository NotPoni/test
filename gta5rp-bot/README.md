# GTA 5RP Discord Bot

Бот для серверов организаций/семей/фракций GTA 5RP: заявки, тикеты, кадры, смены, сборы, модерация и анти-краш.

## Запуск
1. `pip install -r requirements.txt`
2. Скопируйте `.env.example` в `.env`, впишите `DISCORD_TOKEN` (и `GUILD_ID` для мгновенных команд).
3. В Discord Developer Portal → Bot включите **Server Members Intent** и **Message Content Intent**.
4. Пригласите бота с правами Administrator (или: Manage Roles/Channels/Nicknames/Messages, Ban/Kick/Moderate Members, View Audit Log). **Роль бота должна быть выше выдаваемых ролей.**
5. `python main.py`

## Первая настройка на сервере
1. `/настройка` — роль сотрудников, роль после принятия, каналы заявок/логов/кадров/приветствий, категория тикетов.
2. В нужных каналах: `/панель_заявок`, `/панель_тикетов`, `/панель_смен`.

## Оформление
Цвета — `config.py`, логотип и баннер — `LOGO_URL` / `BANNER_URL` в `.env`, общий шаблон эмбедов — `ui.py`.
