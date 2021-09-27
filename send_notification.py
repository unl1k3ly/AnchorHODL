import config
import requests
import json


def slack_webhook(msg):
    slack_data = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": msg
                }
            }
        ]
    }

    try:
        response = requests.post(
            config.SLACK_WEBHOOK_URL, data=json.dumps(slack_data),
            headers={'Content-Type': 'application/json'}, timeout=5
        )
        if response.status_code != 200:
            raise ValueError(
                'Request to slack returned an error %s, the response is:\n%s'
                % (response.status_code, response.text)
            )
    except Exception:
        pass


def telegram_notification(msg):
    tg_data = {"chat_id": str(config.TELEGRAM_CHAT_ID), "text": msg, "parse_mode": 'Markdown'}

    try:
        response = requests.post('https://api.telegram.org/bot' + config.TELEGRAM_TOKEN + '/sendMessage', data=json.dumps(tg_data),
            headers={'Content-Type': 'application/json'}, timeout=5
        )
        if response.status_code != 200:
            raise ValueError(
                'Request to slack returned an error %s, the response is:\n%s'
                % (response.status_code, response.text)
            )
    except Exception:
        pass

def discord_notification(msg):
    headers = {
        "Authorization": "Bot {}".format(config.DISCORD_BOT_TOKEN),
        "Content-Type": "application/json",
    }
    channel_id = config.DISCORD_CHANNEL_ID
    r = requests.post(
        "https://discordapp.com/api/channels/" + config.DISCORD_CHANNEL_ID + "/messages",
        headers=headers,
        json={"content": msg},
    )

    try:
        r.raise_for_status()
    except Exception:
        pass
