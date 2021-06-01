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
            headers={'Content-Type': 'application/json'}
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
            headers={'Content-Type': 'application/json'}
        )
        if response.status_code != 200:
            raise ValueError(
                'Request to slack returned an error %s, the response is:\n%s'
                % (response.status_code, response.text)
            )
    except Exception:
        pass
