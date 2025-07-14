import os
import re
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import logging
import threading
from datetime import datetime, timedelta, timezone
from slack_sdk.errors import SlackApiError
from database import SheetManager
import pytz
import json
import uuid

load_dotenv()

creds_dict = {
    "type": os.getenv("GOOGLE_CREDENTIALS_TYPE"),
    "project_id": os.getenv("GOOGLE_PROJECT_ID"),
    "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
    "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
    "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_CERT_URL"),
    "universe_domain": os.getenv("GOOGLE_UNIVERSE_DOMAIN"),
}

app = App(token=os.getenv("SLACK_BOT_TOKEN"))
sheet_manager = SheetManager(creds_dict, "1dPXiGBN2dDyyQ9TnO6Hi8cQtmbkFBU4O7sI5ztbXT90")

emergency_reflected_cn = "C056S606NGM"
ops_cn = "C079J897A49"
reflected_cn = "C032B89UK36"
piket_reflected_cn = "C056S606NGM"
helpdesk_cn = "C081NA747D0"
helpdesk_support_id = "U08NTAUVD2P"
testing_cn = "C0719R3NQ91"

greetings_response = {
    "morning": "Good Morning",
    "hello": "Hello",
    "hi": "Hi",
    "hai": "Hai",
    "hej": "Hej",
    "assalamu'alaikum": "Wa'alaikumussalam",
    "assalamualaikum": "Wa'alaikumussalam",
    "hey": "Hey",
    "afternoon": "Good Afternoon",
    "evening": "Good Evening",
    "shalom": "Shalom",
    "pagi": "Selamat Pagi",
    "siang": "Selamat Siang",
    "malam": "Selamat Malam",
}

thank_you_response = {
    "makasih": "Iyaa, sama sama :pray:",
    "thank you": "yap, my pleasure :pray:",
    "thx": "yuhu, you're welcome",
    "maaci": "hihi iaa, maaciw juga :wink:",
    "suwun": "enggeh, sami sami :pray:",
    "nuhun": "muhun, sami sami :pray:",
}

greeting_pattern = re.compile(
    r".*(morning|hello|hi|assalamu'alaikum|evening|hey|assalamualaikum|afternoon|shalom|hai|hej|pagi|siang|malam).*",
    re.IGNORECASE,
)

thank_you_pattern = re.compile(
    r".*(makasih|thank|thx|maaci|suwun|nuhun).*", re.IGNORECASE
)


def convert_utc_to_jakarta(time):
    utc_time = time.replace(tzinfo=pytz.utc)
    jakarta_tz = pytz.timezone("Asia/Jakarta")
    changed_timezone = utc_time.astimezone(jakarta_tz)
    return changed_timezone.strftime("%Y-%m-%d %H:%M:%S")


class TicketManager:
    def __init__(self):
        self.reflected_timestamps = {}
        self.user_inputs = {}
        self.ticket_status = {}
        self.files = {}
        self.unique_id = {}

    def store_reflected_ts(self, thread_ts, reflected_ts):
        self.reflected_timestamps[thread_ts] = reflected_ts

    def get_reflected_ts(self, thread_ts):
        return self.reflected_timestamps.get(thread_ts)

    def clear_reflected_ts(self, thread_ts):
        if thread_ts in self.reflected_timestamps:
            del self.reflected_timestamps[thread_ts]

    def store_unique_id(self, thread_ts, id):
        self.unique_id[thread_ts] = id

    def get_unique_id(self, thread_ts):
        return self.unique_id.get(thread_ts)

    def store_user_input(self, thread_ts, user_input):
        self.user_inputs[thread_ts] = user_input

    def get_user_input(self, thread_ts):
        return self.user_inputs.get(thread_ts)

    def clear_user_input(self, thread_ts):
        if thread_ts in self.user_inputs:
            del self.user_inputs[thread_ts]

    def update_ticket_status(self, thread_ts, status):
        self.ticket_status[thread_ts] = status

    def get_ticket_status(self, thread_ts):
        return self.ticket_status.get(thread_ts, "unassigned")

    def clear_ticket_status(self, thread_ts):
        if thread_ts in self.ticket_status:
            del self.ticket_status[thread_ts]

    def store_files(self, thread_ts, files):
        self.files[thread_ts] = files

    def get_files(self, thread_ts):
        files = self.files.get(thread_ts)
        return files


ticket_manager = TicketManager()


def schedule_reminder(client, channel_id, thread_ts, reminder_time, ticket_ts):
    def remind():
        if not is_ticket_assigned(ticket_ts):
            omar_id = "U020SH7JJF3"
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Ribbit! 🐸 Pepe’s getting impatient, and this ticket's feeling lonely! Can you <@{omar_id}> hop in and rescue it within the next 2 minutes before Pepe starts croaking louder? 🐸⏳",
            )

    threading.Timer(reminder_time.total_seconds(), remind).start()


def is_ticket_assigned(ticket_ts):
    status = ticket_manager.get_ticket_status(ticket_ts)
    return status != "unassigned"


def truncate_value(value, max_length=25):
    return (
        value
        if len(value) <= max_length
        else value[:max_length] + "...(continued in thread)"
    )


def get_chat_history(client, channel_id, start_ts):
    try:
        response = client.conversations_history(
            channel=channel_id, oldest=start_ts, inclusive=True
        )
        messages = response["messages"]
        procceed_message = []

        for message in messages:
            user_id = message.get("user", "Unknown User")
            real_name = get_real_name(client, user_id)
            text = message.get("text", "")
            timestamp = convert_utc_to_jakarta(
                datetime.fromtimestamp(float(message["ts"]), timezone.utc)
            )
            if "files" in message:
                for file in message["files"]:
                    if file.get("mimetype", "").startswith("image/"):
                        image_url = file.get("url_private", "the url is not available")
                        text += f"[shared image: {image_url}]"
            if not text and "files" in message:
                text += "[File shared]"

            procceed_message.append(f"[{timestamp}] {real_name}: {text}")

        return procceed_message
    except SlackApiError as e:
        logging.error(f"Error fetching chat history: {str(e)}")
        return None


def inserting_imgs_thread(client, channel_id, ts, files):
    blocks = []

    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Here are the uploaded images from user:",
            },
        }
    )

    for file in files:
        img_url = file.get("url_private", file.get("thumb_360", file.get("thumb_64")))
        if img_url:
            img_block = {
                "type": "image",
                "image_url": img_url,
                "alt_text": "user_attachment",
            }
            blocks.append(img_block)

    if blocks:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=ts,
            blocks=blocks,
            text="Here are the uploaded images",
        )


def inserting_chat_history_to_thread(client, channel_id, ts, messages):
    combined_messages = "\n".join(messages)

    if len(combined_messages) > 3001:
        combined_messages = combined_messages[:2500] + "...."

    blocks = []

    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Here are the chat history:",
            },
        }
    )

    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{combined_messages}```",
            },
        }
    )

    if len(combined_messages) > 3000:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=ts,
            blocks=blocks,
            text="Here’s the chat history (full messages stored in our database).",
        )
    else:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=ts,
            blocks=blocks,
            text="Here are the chat history and attachments",
        )


def get_real_name(client, user_id):
    try:
        user_info = client.users_info(user=user_id)
        return user_info["user"]["real_name"]
    except Exception as e:
        return user_id


def coloring_the_button(issue_type):
    if issue_type == "Emergency":
        return "danger"
    elif issue_type == "Piket":
        return "primary"
    else:
        return None


def conditional_indexing(blocks):
    if len(blocks) > 5:
        return [6, 0]
    elif len(blocks) <= 3:
        return [2, 1]
    else:
        return [4, 1]


@app.event("message")
def handle_message_events(body, say, client):
    event = body.get("event", {})
    user_id = event.get("user")
    chat_timestamp = event["ts"]
    timestamp_utc = datetime.now(timezone.utc)

    try:
        user_info = client.users_info(user=user_id)
        text = event.get("text", "").strip().lower()
        email = user_info["user"].get("name", "unknown") + "@colearn.id"
        full_name = user_info["user"]["profile"].get("real_name", "unknown")
        phone_number = user_info["user"]["profile"].get("phone", "unknown")
        match_greeting = greeting_pattern.search(text)
        match_thank_you = thank_you_pattern.search(text)

        if match_greeting:
            greeting = match_greeting.group(1)
            if greeting in greetings_response:
                response = greetings_response[greeting]
                say(f"{response} <@{event['user']}>, Pepe is ready to help :frog:")
                say(
                    f"Please type your issue with the following pattern: `/hiops [write your issue/inquiry]`"
                )
        elif match_thank_you:
            thank_you = match_thank_you.group(1)
            if thank_you in thank_you_response:
                response = thank_you_response[thank_you]
                say(response)
        else:
            say(f"Hi <@{event['user']}>, Pepe is ready to help :frog:")
            say(
                f"Please type your issue with this following pattern: `/hiops [write your issue/inquiry]`"
            )
        sheet_manager.log_ticket(
            chat_timestamp,
            timestamp_utc,
            user_id,
            full_name,
            email,
            phone_number,
            text,
        )
    except Exception as e:
        logging.error(f"Error handling message: {str(e)}")


@app.command("/hiops")
def slash_input(ack, body, client):
    ack()
    categories = ["Piket", "Emergency", "IT Helpdesk", "Kakak Siaga", "Others"]
    user_input = body.get("text", "No message provided.")
    category_options = [
        {
            "text": {"type": "plain_text", "text": category},
            "value": f"{category}",
        }
        for category in categories
    ]
    trigger_id = body["trigger_id"]
    channel_id = ops_cn

    modal = {
        "type": "modal",
        "callback_id": "slash_input",
        "title": {
            "type": "plain_text",
            "text": "Don’t Overthink It!",
        },
        "blocks": [
            {
                "type": "section",
                "block_id": "category_block",
                "text": {
                    "type": "mrkdwn",
                    "text": "Please select the category of the issue:",
                },
            },
            {
                "type": "actions",
                "block_id": "category_buttons",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": category["text"]["text"],
                            "emoji": True,
                        },
                        "value": category["value"],
                        "action_id": f"button_{category['value']}",
                        **(
                            {"style": coloring_the_button(category["value"])}
                            if coloring_the_button(category["value"])
                            else {}
                        ),
                    }
                    for category in category_options
                ],
            },
        ],
        "private_metadata": f"{channel_id}@@{user_input}",
    }

    try:
        client.views_open(trigger_id=trigger_id, view=modal)
    except SlackApiError as e:
        logging.error(
            f"Error opening modal: {str(e)} | Response: {e.response['error']}"
        )


@app.action("button_Piket")
def handling_replacement(ack, body, client):
    ack()

    categories = [
        "I need help finding a replacement",
        "No Mentor",
        "I have had a replacement",
    ]

    category_options = [
        {
            "text": {"type": "plain_text", "text": category},
            "value": category,
        }
        for category in categories
    ]

    channel_id = ops_cn
    channel_id = ops_cn
    view_id = body["view"]["id"]

    modal = {
        "type": "modal",
        "callback_id": "slash_input",
        "title": {
            "type": "plain_text",
            "text": "Don’t Overthink It!",
        },
        "blocks": [
            {
                "type": "section",
                "block_id": "category_block",
                "text": {
                    "type": "mrkdwn",
                    "text": "Teacher Replacement Options",
                },
                "accessory": {
                    "type": "static_select",
                    "action_id": "handle_category_selection",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a category",
                    },
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": category_option["text"]["text"],
                            },
                            "value": category_option["value"],
                        }
                        for category_option in category_options
                    ],
                },
            },
        ],
        "private_metadata": f"{channel_id}@@Piket",
    }

    try:
        client.views_update(view_id=view_id, view=modal)
    except SlackApiError as e:
        logging.error(
            f"Error updating modal: {str(e)} | Response: {e.response['error']}"
        )


@app.action("handle_category_selection")
@app.action("button_Others")
@app.action("button_IT Helpdesk")
@app.action("button_Kakak Siaga")
def handle_category_selection(ack, body, client):
    ack()
    [channel_id, user_input] = body["view"]["private_metadata"].split("@@")
    piket_category = (
        body.get("view", {})
        .get("state", {})
        .get("values", {})
        .get("category_block", {})
        .get("handle_category_selection", {})
        .get("selected_option", {})
        .get("value", {})
    )
    selected_category = body["actions"][0].get("value", user_input)
    trigger_id = body["trigger_id"]
    if selected_category == "Piket":
        modal_blocks = [
            {
                "type": "input",
                "block_id": "date_block",
                "label": {"type": "plain_text", "text": "Date"},
                "element": {
                    "type": "datepicker",
                    "action_id": "date_picker_action",
                    "placeholder": {"type": "plain_text", "text": "Select a date"},
                },
            },
            {
                "type": "input",
                "block_id": "teacher_request_block",
                "label": {"type": "plain_text", "text": "Teacher who requested"},
                "element": {
                    "action_id": "teacher_request_action",
                    "type": "users_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select Teacher Who Requested",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "teacher_replace_block",
                "label": {"type": "plain_text", "text": "Teacher who replaces"},
                "element": {
                    "action_id": "teacher_replace_action",
                    "type": (
                        "users_select"
                        if piket_category == "I have had a replacement"
                        else "plain_text_input"
                    ),
                    **(
                        {
                            "initial_value": (
                                "I need help finding a replacement"
                                if piket_category == "I need help finding a replacement"
                                else (
                                    "No Mentor"
                                    if piket_category == "No Mentor"
                                    else None
                                )
                            )
                        }
                        if piket_category != "I have had a replacement"
                        else {}
                    ),
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select Teacher Who Replaces",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "grade_block",
                "label": {"type": "plain_text", "text": "Grade"},
                "element": {
                    "type": "number_input",
                    "action_id": "grade_action",
                    "is_decimal_allowed": False,
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Generate Slots"},
                        "action_id": "generate_slot_list",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Additional Classes"},
                        "action_id": "generate_additional_classes",
                    },
                ],
            },
            {
                "type": "input",
                "block_id": "time_class_block",
                "label": {"type": "plain_text", "text": "Class Time"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "time_class_action",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g., 19:15",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "reason_block",
                "label": {"type": "plain_text", "text": "Reason"},
                "element": {
                    "type": "plain_text_input",
                    "multiline": True,
                    "action_id": "reason_action",
                },
            },
            {
                "type": "input",
                "block_id": "direct_lead_block",
                "label": {"type": "plain_text", "text": "Direct Lead"},
                "element": {
                    "action_id": "direct_lead_action",
                    "type": "users_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select Your Direct Lead",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "stem_lead_block",
                "label": {"type": "plain_text", "text": "STEM Lead"},
                "element": {
                    "action_id": "stem_lead_action",
                    "type": "users_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select Your STEM Lead",
                    },
                },
            },
        ]

    elif selected_category == "Others":
        modal_blocks = [
            {
                "type": "input",
                "block_id": "issue_name",
                "label": {"type": "plain_text", "text": "Your Issue"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "user_issue",
                    "multiline": True,
                    "initial_value": user_input,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Describe your issue...",
                    },
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "file_upload_block",
                "label": {"type": "plain_text", "text": "File Upload"},
                "element": {
                    "type": "file_input",
                    "action_id": "file_input_action",
                    "filetypes": ["jpg", "png"],
                    "max_files": 5,
                },
            },
        ]
    elif selected_category == "IT Helpdesk":
        issue_types = ["laptop issue", "network issue", "software issue", "others"]
        urgency_levels = ["low", "medium", "high"]

        issue_type_options = [
            {"text": {"type": "plain_text", "text": type}, "value": type}
            for type in issue_types
        ]

        urgency_level_options = [
            {"text": {"type": "plain_text", "text": level}, "value": level}
            for level in urgency_levels
        ]

        modal_blocks = [
            {
                "type": "input",
                "block_id": "full_name_block",
                "label": {"type": "plain_text", "text": "Full Name"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "full_name_action",
                    "placeholder": {"type": "plain_text", "text": "Your Full Name"},
                },
            },
            {
                "type": "input",
                "block_id": "issue_type_id",
                "label": {"type": "plain_text", "text": "Issue Type"},
                "element": {
                    "type": "static_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Your Issue Type",
                    },
                    "action_id": "handle_issue_type",
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": issue_type_option["text"]["text"],
                            },
                            "value": issue_type_option["value"],
                        }
                        for issue_type_option in issue_type_options
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "issue_description",
                "label": {"type": "plain_text", "text": "Description"},
                "element": {
                    "type": "plain_text_input",
                    "multiline": True,
                    "action_id": "issue_description_action",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Describe Your Issue",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "urgency_id",
                "label": {"type": "plain_text", "text": "Urgency Level"},
                "element": {
                    "type": "static_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Determine Your Issue Level",
                    },
                    "action_id": "handle_urgency_level",
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": urgency_level_option["text"]["text"],
                            },
                            "value": urgency_level_option["value"],
                        }
                        for urgency_level_option in urgency_level_options
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "datetime_id",
                "label": {"type": "plain_text", "text": "Incident Date and Time"},
                "element": {
                    "type": "datetimepicker",
                    "action_id": "datetimepicker_action",
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "file_upload_id",
                "label": {"type": "plain_text", "text": "File Upload"},
                "element": {
                    "type": "file_input",
                    "action_id": "file_input_action",
                    "filetypes": ["jpg", "png"],
                    "max_files": 5,
                },
            },
        ]
    elif selected_category == "Kakak Siaga":
        modal_blocks = [
            {
                "type": "section",
                "block_id": "bantuan_block",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Apakah sudah diarahkan tombol Bantuan?*",
                },
                "accessory": {
                    "type": "radio_buttons",
                    "action_id": "kakak_siaga_bantuan_radio",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Yes"}, "value": "Yes"},
                        {"text": {"type": "plain_text", "text": "No"}, "value": "No"},
                    ],
                },
            }
        ]

    modal_titles = {
        "IT Helpdesk": "Submit a Helpdesk Ticket",
        "Kakak Siaga": "Kakak Siaga Assistance",
    }

    modal_title = modal_titles.get(selected_category, "Think Wisely!")

    if selected_category == "Kakak Siaga":
        updated_modal = {
            "type": "modal",
            "callback_id": "slash_input",
            "title": {
                "type": "plain_text",
                "text": modal_title,
            },
            "blocks": modal_blocks,
            "private_metadata": f"{channel_id}@@{selected_category}",
        }
    else:
        updated_modal = {
            "type": "modal",
            "callback_id": "slash_input",
            "title": {
                "type": "plain_text",
                "text": modal_title,
            },
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": modal_blocks,
            "private_metadata": f"{channel_id}@@{user_input}",
        }

    try:
        client.views_update(view_id=body["view"]["id"], view=updated_modal)
    except SlackApiError as e:
        logging.error(
            f"Error updating modal: {str(e)} | Response: {e.response['error']}"
        )


@app.action("kakak_siaga_bantuan_radio")
def handle_kakak_siaga_bantuan_radio(ack, body, client):
    ack()
    selected = body["actions"][0]["selected_option"]["value"]
    user_id = body["user"]["id"]
    view_id = body["view"]["id"]
    private_metadata = body["view"]["private_metadata"]

    if selected == "No":
        # Jika No, kirim pesan dan tutup modal
        client.chat_postMessage(
            channel=user_id,
            text="Kami sarankan untuk diarahkan dulu ya ke tombol bantuan :pray:",
        )
        client.views_update(
            view_id=view_id,
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Kakak Siaga"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Terima Kasih! Silahkan arahkan hubungi Kakak Siaga atau klik tombol Bantuan terlebih dahulu.",
                        },
                    }
                ],
                "close": {"type": "plain_text", "text": "Close"},
            },
        )
    else:
        # Jika Yes, lanjut ke form kedua
        modal_blocks = [
            {
                "type": "input",
                "block_id": "user_id_block",
                "label": {"type": "plain_text", "text": "User ID"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "user_id_action",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Masukkan User ID murid",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "nama_murid_block",
                "label": {"type": "plain_text", "text": "Nama Murid"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "nama_murid_action",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Masukkan nama murid",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "grade_block",
                "label": {"type": "plain_text", "text": "Grade"},
                "element": {
                    "type": "number_input",
                    "action_id": "grade_action",
                    "is_decimal_allowed": False,
                },
            },
            {
                "type": "input",
                "block_id": "isu_murid_block",
                "label": {"type": "plain_text", "text": "Isu yang dialami murid"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "isu_murid_action",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Jelaskan isu murid"},
                },
            },
            {
                "type": "input",
                "optional": True,
                "block_id": "file_upload_block",
                "label": {"type": "plain_text", "text": "File Upload"},
                "element": {
                    "type": "file_input",
                    "action_id": "file_input_action",
                    "filetypes": ["jpg", "png"],
                    "max_files": 5,
                },
            },
        ]
        client.views_update(
            view_id=view_id,
            view={
                "type": "modal",
                "callback_id": "kakak_siaga_form",
                "title": {"type": "plain_text", "text": "Form Kakak Siaga"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": modal_blocks,
                "private_metadata": private_metadata,
            },
        )


import uuid


@app.view("kakak_siaga_form")
def handle_kakak_siaga_form_submission(ack, body, view, client):
    ack()
    submitter_id = body["user"]["id"]
    state = view["state"]["values"]
    user_id = state["user_id_block"]["user_id_action"]["value"]
    nama_murid = state["nama_murid_block"]["nama_murid_action"]["value"]
    grade = state["grade_block"]["grade_action"]["value"]
    isu_murid = state["isu_murid_block"]["isu_murid_action"]["value"]
    files = (
        state.get("file_upload_block", {}).get("file_input_action", {}).get("files", [])
    )
    timestamp_utc = datetime.now(timezone.utc)
    timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)

    # Generate unique ID
    kakak_siaga_id = str(uuid.uuid4())

    # 1. Simpan ke Google Sheet
    try:
        sheet_manager.init_kakak_siaga_row(
            kakak_siaga_id,  # tambahkan ID di sini
            submitter_id,
            user_id,
            nama_murid,
            grade,
            isu_murid,
            json.dumps(files),
            timestamp_jakarta,
        )
    except Exception as e:
        logging.error(f"Failed to write Kakak Siaga to sheet: {str(e)}")

    # 2. Kirim info ke channel ops_cn
    try:
        result = client.chat_postMessage(
            channel=reflected_cn,
            text=f"Halo <@Kakak-siaga>,\n"
            f"mohon bantuannya, ada murid dari kelas {grade} (<@{submitter_id}>) yang mengalami kendala dengan Ticket-ID: {kakak_siaga_id}. Berikut detailnya:\n"
            f"UserID: {user_id}\n"
            f"Nama Murid: {nama_murid}\n"
            f"Isu: {isu_murid}\n"
            f"Waktu: {timestamp_jakarta}\n"
            f"Gambar tertera pada thread ini.",
        )
        if files and result["ok"]:
            inserting_imgs_thread(client, reflected_cn, result["ts"], files)
    except Exception as e:
        logging.error(f"Failed to send Kakak Siaga info to channel: {str(e)}")


@app.action("generate_slot_list")
def handle_generate_slot_list(ack, body, client):
    ack()
    state = body["view"]["state"]["values"]
    teacher_replace_block = state["teacher_replace_block"]["teacher_replace_action"]
    teacher_who_replaces_val = teacher_replace_block.get(
        "selected_user"
    ) or teacher_replace_block.get("value")
    selected_cat_on_piket = (
        teacher_who_replaces_val
        if teacher_who_replaces_val == "No Mentor"
        or teacher_who_replaces_val == "I need help finding a replacement"
        else "I have had a replacement"
    )

    grade = state["grade_block"]["grade_action"]["value"]

    slots = sheet_manager.get_slots_by_grade(grade)

    if slots and len(slots) > 0:
        dropdown_options = [
            {"text": {"type": "plain_text", "text": slot}, "value": slot}
            for slot in slots
        ]
    else:
        dropdown_options = [
            {
                "text": {"type": "plain_text", "text": "No slots available"},
                "value": "no_slots",
            }
        ]

    client.views_update(
        view_id=body["view"]["id"],
        view={
            "type": "modal",
            "callback_id": "slash_input",
            "title": {"type": "plain_text", "text": "Piket Request"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "date_block",
                    "label": {"type": "plain_text", "text": "Date"},
                    "element": {
                        "type": "datepicker",
                        "action_id": "date_picker_action",
                        "placeholder": {"type": "plain_text", "text": "Select a date"},
                    },
                },
                {
                    "type": "input",
                    "block_id": "teacher_request_block",
                    "label": {"type": "plain_text", "text": "Teacher who requested"},
                    "element": {
                        "action_id": "teacher_request_action",
                        "type": "users_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Teacher Who Requested",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "teacher_replace_block",
                    "label": {"type": "plain_text", "text": "Teacher who replaces"},
                    "element": {
                        "action_id": "teacher_replace_action",
                        "type": (
                            "users_select"
                            if selected_cat_on_piket == "I have had a replacement"
                            else "plain_text_input"
                        ),
                        **(
                            {
                                "initial_value": (
                                    "I need help finding a replacement"
                                    if selected_cat_on_piket
                                    == "I need help finding a replacement"
                                    else (
                                        "No Mentor"
                                        if selected_cat_on_piket == "No Mentor"
                                        else None
                                    )
                                )
                            }
                            if selected_cat_on_piket != "I have had a replacement"
                            else {}
                        ),
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Teacher Who Replaces",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "grade_block",
                    "label": {"type": "plain_text", "text": "Grade"},
                    "element": {
                        "type": "number_input",
                        "action_id": "grade_action",
                        "is_decimal_allowed": False,
                        "initial_value": grade,
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Generate Slots"},
                            "action_id": "generate_slot_list",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Additional Classes",
                            },
                            "action_id": "generate_additional_classes",
                        },
                    ],
                },
                {
                    "type": "input",
                    "block_id": "slot_name_block",
                    "label": {"type": "plain_text", "text": "Slot Name"},
                    "element": {
                        "type": "static_select",
                        "action_id": "slot_name_action",
                        "placeholder": {"type": "plain_text", "text": "Select a slot"},
                        "options": dropdown_options,
                    },
                },
                {
                    "type": "input",
                    "block_id": "time_class_block",
                    "label": {"type": "plain_text", "text": "Class Time"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "time_class_action",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "e.g., 19:15",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "reason_block",
                    "label": {"type": "plain_text", "text": "Reason"},
                    "element": {
                        "type": "plain_text_input",
                        "multiline": True,
                        "action_id": "reason_action",
                    },
                },
                {
                    "type": "input",
                    "block_id": "direct_lead_block",
                    "label": {"type": "plain_text", "text": "Direct Lead"},
                    "element": {
                        "action_id": "direct_lead_action",
                        "type": "users_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Your Direct Lead",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "stem_lead_block",
                    "label": {"type": "plain_text", "text": "STEM Lead"},
                    "element": {
                        "action_id": "stem_lead_action",
                        "type": "users_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Your STEM Lead",
                        },
                    },
                },
            ],
            "private_metadata": body["view"]["private_metadata"],
        },
    )


@app.action("generate_additional_classes")
def handle_generate_additional_classes(ack, body, client):
    """Handle the Additional Classes button click action"""
    ack()

    state = body["view"]["state"]["values"]

    teacher_replace_block = state["teacher_replace_block"]["teacher_replace_action"]
    teacher_who_replaces_val = teacher_replace_block.get(
        "selected_user"
    ) or teacher_replace_block.get("value")

    selected_cat_on_piket = (
        teacher_who_replaces_val
        if teacher_who_replaces_val == "No Mentor"
        or teacher_who_replaces_val == "I need help finding a replacement"
        else "I have had a replacement"
    )

    grade = state["grade_block"]["grade_action"].get("value", "")

    alternative_slots = [
        "Math Club",
        "Kelas Pengganti - Matematika",
        "Kelas Pengganti - IPA",
        "Kelas Pengganti - Fisika",
        "Kelas Pengganti - Kimia",
    ]

    dropdown_options = [
        {"text": {"type": "plain_text", "text": slot}, "value": slot}
        for slot in alternative_slots
    ]

    client.views_update(
        view_id=body["view"]["id"],
        view={
            "type": "modal",
            "callback_id": "slash_input",
            "title": {"type": "plain_text", "text": "Piket Request"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "date_block",
                    "label": {"type": "plain_text", "text": "Date"},
                    "element": {
                        "type": "datepicker",
                        "action_id": "date_picker_action",
                        "placeholder": {"type": "plain_text", "text": "Select a date"},
                    },
                },
                {
                    "type": "input",
                    "block_id": "teacher_request_block",
                    "label": {"type": "plain_text", "text": "Teacher who requested"},
                    "element": {
                        "action_id": "teacher_request_action",
                        "type": "users_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Teacher Who Requested",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "teacher_replace_block",
                    "label": {"type": "plain_text", "text": "Teacher who replaces"},
                    "element": {
                        "action_id": "teacher_replace_action",
                        "type": (
                            "users_select"
                            if selected_cat_on_piket == "I have had a replacement"
                            else "plain_text_input"
                        ),
                        **(
                            {
                                "initial_value": (
                                    "I need help finding a replacement"
                                    if selected_cat_on_piket
                                    == "I need help finding a replacement"
                                    else (
                                        "No Mentor"
                                        if selected_cat_on_piket == "No Mentor"
                                        else None
                                    )
                                )
                            }
                            if selected_cat_on_piket != "I have had a replacement"
                            else {}
                        ),
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Teacher Who Replaces",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "grade_block",
                    "label": {"type": "plain_text", "text": "Grade"},
                    "element": {
                        "type": "number_input",
                        "action_id": "grade_action",
                        "is_decimal_allowed": False,
                        "initial_value": grade,
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Generate Slots"},
                            "action_id": "generate_slot_list",
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Additional Classes",
                            },
                            "action_id": "generate_additional_classes",
                            "style": "primary",
                        },
                    ],
                },
                {
                    "type": "input",
                    "block_id": "slot_name_block",
                    "label": {
                        "type": "plain_text",
                        "text": "Please choose your class",
                    },
                    "element": {
                        "type": "static_select",
                        "action_id": "slot_name_action",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select a slot type",
                        },
                        "options": dropdown_options,
                    },
                },
                {
                    "type": "input",
                    "block_id": "time_class_block",
                    "label": {"type": "plain_text", "text": "Class Time"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "time_class_action",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "e.g., 19:15",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "reason_block",
                    "label": {"type": "plain_text", "text": "Reason"},
                    "element": {
                        "type": "plain_text_input",
                        "multiline": True,
                        "action_id": "reason_action",
                    },
                },
                {
                    "type": "input",
                    "block_id": "direct_lead_block",
                    "label": {"type": "plain_text", "text": "Direct Lead"},
                    "element": {
                        "action_id": "direct_lead_action",
                        "type": "users_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Your Direct Lead",
                        },
                    },
                },
                {
                    "type": "input",
                    "block_id": "stem_lead_block",
                    "label": {"type": "plain_text", "text": "STEM Lead"},
                    "element": {
                        "action_id": "stem_lead_action",
                        "type": "users_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select Your STEM Lead",
                        },
                    },
                },
            ],
            "private_metadata": body["view"]["private_metadata"],
        },
    )


@app.action("button_Emergency")
def handle_emergency_button(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    user_name = get_real_name(client, user_id)
    timestamp_utc = datetime.now(timezone.utc)
    timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)
    feedback_block = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":mailbox_with_mail: *We've Received Your Alert!* :mailbox_with_mail:",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Hi <@{user_id}>, thank you for reporting the emergency in your class at `{timestamp_jakarta}`. The Ops team has been notified and is reviewing the situation.",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "We'll keep you updated as soon as there’s progress.",
            },
        },
    ]

    info_channel_block = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":rotating_light: *Emergency Reported!* :rotating_light:",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"An emergency has been reported by <@{user_id}> in their class at `{timestamp_jakarta}`. The Ops team has been notified and is taking action.",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "This message is for your information. If you have any relevant details to assist the Ops team, please contact them directly.",
            },
        },
    ]

    try:
        response = client.chat_postMessage(
            channel=user_id,
            text="Your emergency alert has been received.",
            blocks=feedback_block,
        )
        if response["ok"]:
            user_ts = response["ts"]
            value_key = f"{user_id}@@{user_ts}@@Emergency"
            emergency_block = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":rotating_light: Emergency Alert! :rotating_light:",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Hi Ops team @tim_ajar!\nA critical situation has been reported at `{timestamp_jakarta}` in <@{user_id}>'s class.\nPlease check it immediately and provide assistance as soon as possible.",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "emoji": True,
                                "text": "Resolve",
                            },
                            "style": "primary",
                            "value": value_key,
                            "action_id": "emergency_resolve",
                        },
                    ],
                },
            ]
            client.chat_postMessage(
                channel=ops_cn,
                text="Emergency Alert! A critical situation has been reported. Please check immediately.",
                blocks=emergency_block,
            )
            reflected_response = client.chat_postMessage(
                channel=emergency_reflected_cn,
                text="Emergency Alert reported. Please refer to the main alert.",
                blocks=info_channel_block,
            )
            if reflected_response["ok"]:
                reflected_ts = reflected_response["ts"]
                ticket_manager.store_reflected_ts(user_ts, reflected_ts)
                sheet_manager.init_emergency(
                    f"emergency-{user_ts}", user_name, timestamp_utc
                )

            client.views_update(
                view_id=body["view"]["id"],
                view={
                    "type": "modal",
                    "title": {"type": "plain_text", "text": "Processing..."},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "Thank you! Your emergency alert has been submitted.",
                            },
                        },
                    ],
                    "close": {"type": "plain_text", "text": "Close"},
                },
            )
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")


@app.view("slash_input")
def send_the_user_input(ack, body, client, say, view):
    ack()
    private_metadata = view["private_metadata"].split("@@")
    category = private_metadata[1]
    channel_id = private_metadata[0]
    view_state = body["view"]["state"]["values"]
    user_id = body["user"]["id"]
    reporter_name = body["user"]["username"]
    unique_id = str(uuid.uuid4())
    timestamp_utc = datetime.now(timezone.utc)
    timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)

    if category == "Piket":
        class_date = view["state"]["values"]["date_block"]["date_picker_action"][
            "selected_date"
        ]
        teacher_requested = view["state"]["values"]["teacher_request_block"][
            "teacher_request_action"
        ]["selected_user"]
        teacher_replace_block = view["state"]["values"]["teacher_replace_block"][
            "teacher_replace_action"
        ]
        teacher_replace = teacher_replace_block.get(
            "selected_user"
        ) or teacher_replace_block.get("value")

        grade = view["state"]["values"]["grade_block"]["grade_action"]["value"]
        slot_name = view["state"]["values"]["slot_name_block"]["slot_name_action"][
            "selected_option"
        ]["value"]
        time_class = view["state"]["values"]["time_class_block"]["time_class_action"][
            "value"
        ]
        reason = view["state"]["values"]["reason_block"]["reason_action"]["value"]
        direct_lead = view["state"]["values"]["direct_lead_block"][
            "direct_lead_action"
        ]["selected_user"]
        stem_lead = view["state"]["values"]["stem_lead_block"]["stem_lead_action"][
            "selected_user"
        ]

        teacher_requested_name = get_real_name(client, teacher_requested)
        teacher_replaces_name = get_real_name(client, teacher_replace)
        direct_lead_name = get_real_name(client, direct_lead)
        stem_lead_name = get_real_name(client, stem_lead)

        piket_channel_id = channel_id

        piket_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hi <@{user_id}> :blob-wave:\nYour piket request have been received with this following number: `piket.{unique_id}`",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Your Name:*\n{reporter_name}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Requested at:*\n{timestamp_jakarta}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Ticket Category:*\n`{category}`",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Please wait ya, we will give the update in this thread.",
                },
            },
        ]

        response_for_user = client.chat_postMessage(
            channel=user_id,
            blocks=piket_blocks,
            text=f"We are sending the ticket information to <@{user_id}>",
        )

        piket_data = f"{class_date}@@{teacher_requested}@@{teacher_replace}@@{grade}@@{slot_name}@@{time_class}@@{reason}@@{direct_lead}@@{stem_lead}"
        ticket_key_for_user = f"{user_id}@@{response_for_user['ts']}@@{timestamp_jakarta}@@{piket_data}@@{category}"
        ticket_key_for_request_teacher = f"{user_id}@@{response_for_user['ts']}@@{timestamp_jakarta}@@{class_date}@@{teacher_requested}@@{grade}@@{slot_name}@@{time_class}@@{reason}@@{direct_lead}@@{stem_lead}"
        teacher_replace_state = (
            f"<@{teacher_replace}>"
            if teacher_replace != "No Mentor"
            and teacher_replace != "I need help finding a replacement"
            else f"`{teacher_replace}`"
        )

        piket_message = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hi @tim_ajar\nWe've got a request from <@{teacher_requested}> with detail as below:",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Class Date:*\n`{class_date}`"},
                    {"type": "mrkdwn", "text": f"*Time of Class:*\n`{time_class}`"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Teacher Requested:*\n<@{teacher_requested}>",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Teacher Replaces:*\n{teacher_replace_state}",
                    },
                    {"type": "mrkdwn", "text": f"*Slot Name:*\n`{grade}-{slot_name}`"},
                    {"type": "mrkdwn", "text": f"*Reason:*\n```{reason}```"},
                    {"type": "mrkdwn", "text": f"*Direct Lead:*\n<@{direct_lead}>"},
                    {"type": "mrkdwn", "text": f"*STEM Lead:*\n<@{stem_lead}>"},
                ],
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Piket Ticket Number:* piket.{unique_id}",
                    }
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Resolve",
                        },
                        "style": "primary",
                        "value": ticket_key_for_user,
                        "action_id": "resolve_button",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Reject",
                        },
                        "style": "danger",
                        "value": ticket_key_for_user,
                        "action_id": "reject_button",
                    },
                ],
            },
        ]

        if teacher_replace == "I need help finding a replacement":
            if len(piket_message) > 4:
                piket_message[4]["elements"].clear()
                piket_message[4]["elements"] = [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Edit",
                        },
                        "value": ticket_key_for_request_teacher,
                        "action_id": "edit_piket_msg",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Reject",
                        },
                        "style": "danger",
                        "value": ticket_key_for_user,
                        "action_id": "reject_button",
                    },
                ]

        result = client.chat_postMessage(
            channel=piket_channel_id,
            text=f"please check the piket request from <@{teacher_requested}>",
            blocks=piket_message,
        )
        if result["ok"]:
            ticket_manager.store_unique_id(result["ts"], unique_id)
        sheet_manager.init_piket_row(
            f"piket.{unique_id}",
            teacher_requested_name,
            teacher_replaces_name,
            grade,
            slot_name,
            class_date,
            time_class,
            reason,
            direct_lead_name,
            stem_lead_name,
            timestamp_utc,
        )
    elif category == "IT Helpdesk":
        ticket_id = f"it-helpdesk.{unique_id}"
        full_name = view_state["full_name_block"]["full_name_action"]["value"]
        issue_type = view_state["issue_type_id"]["handle_issue_type"][
            "selected_option"
        ]["value"]
        helpdesk_issue_description = view_state["issue_description"][
            "issue_description_action"
        ]["value"]
        urgency_level = view_state["urgency_id"]["handle_urgency_level"][
            "selected_option"
        ]["value"]
        incident_date_time = view_state["datetime_id"]["datetimepicker_action"][
            "selected_date_time"
        ]
        date_time = convert_utc_to_jakarta(
            datetime.fromtimestamp(incident_date_time, timezone.utc)
        )
        helpdesk_files = (
            view_state.get("file_upload_id", {})
            .get("file_input_action", {})
            .get("files", [])
        )
        compiled_files_json = {
            "files": [
                {
                    "id": file.get("id"),
                    "name": file.get("name"),
                    "url": file.get("url_private"),
                }
                for file in helpdesk_files
            ]
        }

        compiled_files_str = json.dumps(compiled_files_json, indent=4)
        sheet_manager.init_it_helpdesk(
            ticket_id,
            get_real_name(client, user_id),
            issue_type,
            helpdesk_issue_description,
            urgency_level,
            date_time,
            compiled_files_str,
            timestamp_utc,
        )

        try:
            if helpdesk_files:
                ticket_manager.store_files(unique_id, helpdesk_files)
            user_response = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Hi <@{user_id}> :wave:!\nYour helpdesk ticket has been submitted successfully :rocket:",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Your Ticket Number:*\n`{ticket_id}`",
                        },
                        {"type": "mrkdwn", "text": f"*Your Name:*\n{full_name}"},
                        {"type": "mrkdwn", "text": f"*Issue Type:*\n{issue_type}"},
                        {
                            "type": "mrkdwn",
                            "text": f"*Issue Description:*\n```{helpdesk_issue_description}```",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Urgency Level:*\n{urgency_level}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Incident Date and Time:*\n`{date_time}`",
                        },
                    ],
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Please ensure you have installed Teamviewer. If have not, click below.",
                        }
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "emoji": True,
                                "text": "Download for Windows",
                            },
                            "style": "primary",
                            "value": "click_me",
                            "url": "https://download.teamviewer.com/download/TeamViewerQS_x64.exe?coupon=CMP-PR-BF24",
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "emoji": True,
                                "text": "Download for Mac",
                            },
                            "style": "primary",
                            "value": "click_me",
                            "url": "https://download.teamviewer.com/download/TeamViewerQS.dmg?coupon=CMP-PR-BF24",
                        },
                    ],
                },
            ]

            user_msg = client.chat_postMessage(
                channel=user_id,
                text="Your request has been sent. We will send a ticket soon.",
                blocks=user_response,
            )
            if user_msg["ok"]:
                user_ts = user_msg["ts"]
                values = f"{ticket_id}@@{user_id}@@{user_ts}@@{full_name}@@{timestamp_jakarta}@@{issue_type}@@{helpdesk_issue_description}@@{urgency_level}@@{date_time}@@{category}"
                helpdesk_ticket_blocks = [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"New Helpdesk Ticket: {ticket_id}",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*User Name:*\n{full_name}"},
                            {
                                "type": "mrkdwn",
                                "text": f"*Requested by:*\n<@{user_id}>",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Requested at:*\n`{timestamp_jakarta}`",
                            },
                            {"type": "mrkdwn", "text": f"*Issue Type:*\n{issue_type}"},
                            {
                                "type": "mrkdwn",
                                "text": f"*Issue Description:*\n```{helpdesk_issue_description}```",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Urgency Level:*\n{urgency_level}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Incident Date and Time:*\n`{date_time}`",
                            },
                            {"type": "mrkdwn", "text": f"*Status:*\nPending"},
                        ],
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Resolve"},
                                "style": "primary",
                                "value": values,
                                "action_id": "helpdesk_resolve",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Reject"},
                                "style": "danger",
                                "value": values,
                                "action_id": "helpdesk_reject",
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Start Chatting",
                                },
                                "value": f"{ticket_id}@@{user_id}@@{user_ts}",
                                "action_id": "start_chat",
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Queue",
                                },
                                "value": f"{ticket_id}@@{user_id}@@{user_ts}",
                                "action_id": "set_queue",
                            },
                        ],
                    },
                ]
                response_for_staff = client.chat_postMessage(
                    channel=helpdesk_cn,
                    text=f"We just received a helpdesk request from {full_name}",
                    blocks=helpdesk_ticket_blocks,
                )
                if response_for_staff["ok"]:
                    response_ts = response_for_staff["ts"]
                    if helpdesk_files:
                        inserting_imgs_thread(
                            client, helpdesk_cn, response_ts, helpdesk_files
                        )
                else:
                    say("Failed to post the message")
            else:
                say("Failed to post message to the user")
        except Exception as e:
            logging.error(f"An error occured on helpdesk {str(e)}")

    elif category == "Others":
        issue_description = view_state["issue_name"]["user_issue"]["value"]
        files = (
            view_state.get("file_upload_block", {})
            .get("file_input_action", {})
            .get("files", [])
        )
        try:
            ticket = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Your ticket number: *live-ops.{unique_id}*",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Your Name:*\n{reporter_name}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Reported at:*\n{timestamp_jakarta}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Problem:*\n`{truncate_value(issue_description)}`",
                        },
                    ],
                },
            ]

            response_for_user = client.chat_postMessage(channel=user_id, blocks=ticket)
            ticket_key_for_user = f"{user_id}@@{response_for_user['ts']}@@{truncate_value(issue_description)}@@{timestamp_jakarta}@@{category}"

            members_result = client.conversations_members(channel=channel_id)
            if members_result["ok"]:
                members = members_result["members"]
            else:
                members = []

            group_mentions = ["S05RYHJ41C6", "S02R59UL0RH", helpdesk_support_id]
            members.extend(group_mentions)
            members.sort()

            user_options = [
                {
                    "text": {
                        "type": "plain_text",
                        "text": (
                            f"<@{member}>"
                            if not member.startswith("S")
                            else f"<!subteam^{member}>"
                        ),
                    },
                    "value": f"{member}@@{user_id}@@{response_for_user['ts']}@@{truncate_value(issue_description)}@@{timestamp_jakarta}@@{category}",
                }
                for member in members
            ]

            if response_for_user["ok"]:
                ts = response_for_user["ts"]
                if len(issue_description) > 25:
                    client.chat_postMessage(
                        channel=user_id,
                        thread_ts=ts,
                        text=f"For the problem details: ```{issue_description}```",
                    )

            if response_for_user["ok"]:
                ts = response_for_user["ts"]
                blocks = [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"We just received a ticket from <@{user_id}> at `{timestamp_jakarta}`",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Problem:*\n`{truncate_value(issue_description)}`",
                            },
                        ],
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Please pick a person:",
                        },
                        "accessory": {
                            "type": "static_select",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Select a person...",
                                "emoji": True,
                            },
                            "options": user_options,
                            "action_id": "user_select_action",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "emoji": True,
                                    "text": "Resolve",
                                },
                                "style": "primary",
                                "value": ticket_key_for_user,
                                "action_id": "resolve_button",
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "emoji": True,
                                    "text": "Reject",
                                },
                                "style": "danger",
                                "value": ticket_key_for_user,
                                "action_id": "reject_button",
                            },
                        ],
                    },
                ]

            result = client.chat_postMessage(
                channel=channel_id,
                text=f"We received the ticket from <@{user_id}>",
                blocks=blocks,
            )

            sheet_manager.init_ticket_row(
                f"live-ops.{unique_id}",
                user_id,
                reporter_name,
                issue_description,
                timestamp_utc,
            )
            if result["ok"]:
                ticket_manager.store_user_input(result["ts"], issue_description)
                ticket_manager.store_unique_id(result["ts"], unique_id)
                if files:
                    inserting_imgs_thread(client, channel_id, result["ts"], files)
                    ticket_manager.store_files(result["ts"], files)
                if len(issue_description) > 37:
                    client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=result["ts"],
                        text=f"For the problem details: ```{issue_description}```",
                    )
            else:
                say("Failed to post message")

            reminder_time = timedelta(minutes=3)
            schedule_reminder(
                client, channel_id, result["ts"], reminder_time, result["ts"]
            )
        except Exception as e:
            logging.error(f"An error occurred: {str(e)}")


@app.action("set_queue")
def handle_queue_ticket(ack, client, body):
    ack()
    [ticket_id, user_id, user_ts] = body["actions"][0]["value"].split("@@")

    try:
        client.chat_postMessage(
            channel=user_id,
            thread_ts=user_ts,
            text=f"please wait, your issue is being on hold because <@{helpdesk_support_id}> is handling another issue at this moment :pray:",
        )
        message = body["message"]
        blocks = message["blocks"]

        blocks[1]["fields"][7]["text"] = "*Status:*\nOn Hold :pray:"

        blocks[2]["elements"] = [
            button
            for button in blocks[2]["elements"]
            if button["action_id"]
            in ["helpdesk_resolve", "helpdesk_reject", "start_chat"]
        ]

        client.chat_update(
            channel=body["channel"]["id"],
            ts=message["ts"],
            text="We are updating this block.",
            blocks=blocks,
        )
    except Exception as e:
        logging.error(f"Any error when starting chat with error: {str(e)}")


@app.action("start_chat")
def handle_start_chat(ack, client, body):
    ack()
    [ticket_id, user_id, user_ts] = body["actions"][0]["value"].split("@@")
    staff_ts = body["message"]["ts"]

    try:
        conversation = client.conversations_open(
            users=f"{user_id},{helpdesk_support_id}"
        )
        channel_id = conversation["channel"]["id"]
        client.chat_postMessage(
            channel=user_id,
            thread_ts=user_ts,
            text=f"Hi <@{user_id}>!\n<@{helpdesk_support_id}> will be reaching out to assist you shortly.\nWe’re here to help and will facilitate this conversation for a smooth resolution. Please hang tight! :wave:",
        )
        greeting = client.chat_postMessage(
            channel=channel_id,
            text="We are starting to chat our beloved user..",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"🎫 *IT Support Chat for Ticket: {ticket_id}*\n\nHi <@{user_id}>, <@{helpdesk_support_id}> will assist you with your ticket.",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "This is a direct communication channel for your IT support ticket. Please describe your issue in detail.",
                        }
                    ],
                },
            ],
        )
        start_ts = greeting["ts"]
        message = body["message"]
        blocks = message["blocks"]

        blocks[1]["fields"][7]["text"] = "*Status:*\nIn Progress 💬"

        blocks[2]["elements"] = [
            button
            for button in blocks[2]["elements"]
            if button["action_id"] in ["helpdesk_resolve"]
        ]

        blocks[2]["elements"][0]["action_id"] = "helpdesk_resolve_post_chatting"

        blocks[2]["elements"][0][
            "value"
        ] = f"{ticket_id}@@{user_id}@@{user_ts}@@{channel_id}@@{helpdesk_support_id}@@{staff_ts}@@{start_ts}"

        client.chat_update(
            channel=body["channel"]["id"],
            ts=message["ts"],
            text="We are updating this block.",
            blocks=blocks,
        )
    except Exception as e:
        logging.error(f"Any error when starting chat with error: {str(e)}")


@app.action("edit_piket_msg")
def edit_piket_msg(ack, body, client):
    ack()
    [
        reporter_id,
        report_ts,
        timestamp,
        class_date,
        teacher_requested,
        grade,
        slot_name,
        time_class,
        reason,
        direct_lead,
        stem_lead,
    ] = body["message"]["blocks"][4]["elements"][0]["value"].split("@@")
    previous_values = {
        "date": class_date,
        "teacher_requested": teacher_requested,
        "grade": grade,
        "slot_name": slot_name,
        "time_class": time_class,
        "reason": reason,
        "direct_lead": direct_lead,
        "stem_lead": stem_lead,
    }
    thread_ts = body["container"]["message_ts"]
    channel_id = body["channel"]["id"]
    trigger_id = body["trigger_id"]
    unique_id = ticket_manager.get_unique_id(thread_ts)

    modal_blocks = [
        {
            "type": "input",
            "block_id": "date_block",
            "label": {"type": "plain_text", "text": "Date"},
            "element": {
                "type": "datepicker",
                "action_id": "date_picker_action",
                "initial_date": previous_values.get("date", None),
                "placeholder": {"type": "plain_text", "text": "Select a date"},
            },
        },
        {
            "type": "input",
            "block_id": "teacher_request_block",
            "label": {"type": "plain_text", "text": "Teacher who requested"},
            "element": {
                "action_id": "teacher_request_action",
                "type": "users_select",
                "initial_user": previous_values.get("teacher_requested", None),
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select Teacher Who Requested",
                },
            },
        },
        {
            "type": "input",
            "block_id": "teacher_replace_block",
            "label": {"type": "plain_text", "text": "Teacher who replaces"},
            "element": {
                "action_id": "teacher_replace_action",
                "type": "users_select",
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select Teacher Who Replaces",
                },
            },
        },
        {
            "type": "input",
            "block_id": "grade_block",
            "label": {"type": "plain_text", "text": "Grade"},
            "element": {
                "type": "number_input",
                "action_id": "grade_action",
                "initial_value": str(previous_values.get("grade", "")),
                "is_decimal_allowed": False,
            },
        },
        {
            "type": "input",
            "block_id": "slot_name_block",
            "label": {"type": "plain_text", "text": "Slot Name"},
            "element": {
                "type": "plain_text_input",
                "action_id": "slot_name_action",
                "initial_value": previous_values.get("slot_name", ""),
                "placeholder": {
                    "type": "plain_text",
                    "text": "please input grade first and click generate button",
                },
            },
        },
        {
            "type": "input",
            "block_id": "time_class_block",
            "label": {"type": "plain_text", "text": "Time of Class"},
            "element": {
                "type": "plain_text_input",
                "action_id": "time_class_action",
                "initial_value": previous_values.get("time_class", ""),
                "placeholder": {"type": "plain_text", "text": "contoh: 19:15"},
            },
        },
        {
            "type": "input",
            "block_id": "reason_block",
            "label": {"type": "plain_text", "text": "Reason"},
            "element": {
                "type": "plain_text_input",
                "multiline": True,
                "action_id": "reason_action",
                "initial_value": previous_values.get("reason", ""),
            },
        },
        {
            "type": "input",
            "block_id": "direct_lead_block",
            "label": {"type": "plain_text", "text": "Direct Lead"},
            "element": {
                "action_id": "direct_lead_action",
                "type": "users_select",
                "initial_user": previous_values.get("direct_lead", None),
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select Your Direct Lead",
                },
            },
        },
        {
            "type": "input",
            "block_id": "stem_lead_block",
            "label": {"type": "plain_text", "text": "STEM Lead"},
            "element": {
                "action_id": "stem_lead_action",
                "type": "users_select",
                "initial_user": previous_values.get("stem_lead", None),
                "placeholder": {
                    "type": "plain_text",
                    "text": "Select Your STEM Lead",
                },
            },
        },
    ]

    modal = {
        "type": "modal",
        "callback_id": "modal_edit_msg",
        "title": {
            "type": "plain_text",
            "text": "Piket!",
        },
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": modal_blocks,
        "private_metadata": f"{reporter_id}@@{report_ts}@@{timestamp}@@{thread_ts}@@{channel_id}@@{unique_id}",
    }

    try:
        client.views_open(trigger_id=trigger_id, view=modal)
    except SlackApiError as e:
        logging.error(f"Error opening modal: {str(e)}")


@app.view("modal_edit_msg")
def show_editted_piket_msg(ack, body, client, view, logger):
    ack()
    try:
        user_id = body["user"]["id"]
        user_info = client.users_info(user=user_id)
        user_name = user_info["user"]["real_name"]
        [reporter_id, report_ts, timestamp, thread_ts, channel_id, unique_id] = view[
            "private_metadata"
        ].split("@@")
        class_date = view["state"]["values"]["date_block"]["date_picker_action"][
            "selected_date"
        ]
        teacher_requested = view["state"]["values"]["teacher_request_block"][
            "teacher_request_action"
        ]["selected_user"]
        teacher_replace = view["state"]["values"]["teacher_replace_block"][
            "teacher_replace_action"
        ]["selected_user"]
        grade = view["state"]["values"]["grade_block"]["grade_action"]["value"]
        slot_name = view["state"]["values"]["slot_name_block"]["slot_name_action"][
            "value"
        ]
        time_class = view["state"]["values"]["time_class_block"]["time_class_action"][
            "value"
        ]
        reason = view["state"]["values"]["reason_block"]["reason_action"]["value"]
        direct_lead = view["state"]["values"]["direct_lead_block"][
            "direct_lead_action"
        ]["selected_user"]
        stem_lead = view["state"]["values"]["stem_lead_block"]["stem_lead_action"][
            "selected_user"
        ]
        timestamp_utc = datetime.now(timezone.utc)
        timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)

        piket_message = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hi @tim_ajar\nWe've got a request from <@{teacher_requested}> with detail as below:",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Class Date:*\n`{class_date}`"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Time of Class:*\n`{time_class}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Teacher Requested:*\n<@{teacher_requested}>",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Teacher Replaces:*\n<@{teacher_replace}>",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Slot Name:*\n`{grade}-{slot_name}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Reason:*\n```{reason}```",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Direct Lead:*\n<@{direct_lead}>",
                    },
                    {"type": "mrkdwn", "text": f"*STEM Lead:*\n<@{stem_lead}>"},
                ],
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Piket Ticket Number:* piket.{unique_id}\nEditted at `{timestamp_jakarta}`",
                    }
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: <@{user_id}> approved the request",
                },
            },
        ]

        response = client.chat_update(
            channel=channel_id,
            ts=thread_ts,
            text=f"Thank you for choosing <@{teacher_replace} as replacement.",
            blocks=piket_message,
        )
        if response["ok"]:
            client.chat_postMessage(
                channel=reporter_id,
                thread_ts=report_ts,
                text=f"Your request approved. Your class on `{class_date}` at `{time_class}`, the teacher replacement is <@{teacher_replace}>",
            )

            client.chat_postMessage(channel=piket_reflected_cn, blocks=piket_message)

            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"This request has been approved at `{timestamp_jakarta}` by <@{user_id}>",
            )

            sheet_manager.update_piket(
                f"piket.{unique_id}",
                {
                    "status": "Approved",
                    "approved_by": user_name,
                    "teacher_replaces": get_real_name(client, teacher_replace),
                    "approved_at": timestamp_utc,
                    "teacher_requested": get_real_name(client, teacher_requested),
                    "grade": str(grade),
                    "slot_name": slot_name,
                    "class_date": str(class_date),
                    "class_time": str(time_class),
                    "reason": reason,
                    "direct_lead": get_real_name(client, direct_lead),
                    "stem_lead": get_real_name(client, stem_lead),
                    "edited_at": timestamp_utc,
                },
            )

    except Exception as e:
        logger.error(f"Error handling modal submission: {str(e)}")


@app.action("user_select_action")
def handle_user_selection(ack, body, client):
    ack()
    person_who_assigns = body["user"]["id"]
    person_who_assigns_name = get_real_name(client, person_who_assigns)
    [
        selected_user,
        user_who_requested,
        response_ts,
        user_input,
        reported_at,
        ticket_category,
    ] = body["actions"][0]["selected_option"]["value"].split("@@")
    channel_id = body["channel"]["id"]
    thread_ts = body["container"]["message_ts"]
    categories = [
        "Ajar",
        "Cuti",
        "Data related",
        "Observasi",
        "Polling",
        "Recording Video",
        "Zoom",
        "Others",
    ]
    timestamp_utc = datetime.now(timezone.utc)
    timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)
    ticket_key_for_user = f"{user_who_requested}@@{response_ts}@@{truncate_value(user_input)}@@{reported_at}@@{selected_user}@@{ticket_category}"
    category_options = [
        {
            "text": {"type": "plain_text", "text": category},
            "value": f"{category}@@{ticket_key_for_user}",
        }
        for category in categories
    ]

    files = ticket_manager.get_files(thread_ts)
    ticket_manager.update_ticket_status(thread_ts, "assigned")
    unique_id = ticket_manager.get_unique_id(thread_ts)

    if selected_user in ["S05RYHJ41C6", "S02R59UL0RH", helpdesk_support_id]:
        user_info = client.users_info(user=body["user"]["id"])
        selected_user_name = user_info["user"]["real_name"]
        other_div_mention = (
            f"<@{selected_user}>"
            if selected_user == helpdesk_support_id
            else f"<!subteam^{selected_user}>"
        )
        client.chat_postMessage(
            channel=user_who_requested,
            thread_ts=response_ts,
            text=f"Sorry <@{user_who_requested}>, your issue isn't within Live Ops's domain. But don't worry, {other_div_mention} will take care of it soon.",
        )
        handover_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"We've officially handed off this hot potato to {other_div_mention}. Now, let's dive back into our awesome work!",
        )
        sheet_manager.update_ticket(
            f"live-ops.{unique_id}",
            {
                "handed_over_by": selected_user_name,
                "handed_over_at": timestamp_utc,
                "assigned_by": person_who_assigns_name,
            },
        )
        if handover_response["ok"]:
            updated_blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"We just received a ticket from <@{user_who_requested}> at `{reported_at}`",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                        },
                    ],
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":handshake: Handover to {other_div_mention}",
                    },
                },
            ]

            reflected_msg = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"We just received an issue from <@{user_who_requested}> at `{reported_at}`",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Current Progress:*\n:handshake: Handover to {other_div_mention}",
                        },
                    ],
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Please pay attention, if this issue related to you :point_up_2:",
                    },
                },
            ]

            client.chat_update(
                channel=channel_id,
                ts=thread_ts,
                text=None,
                blocks=updated_blocks,
            )
            reflected_post = client.chat_postMessage(
                channel=reflected_cn, blocks=reflected_msg
            )
            if reflected_post["ok"]:
                ts = reflected_post["ts"]
                if files:
                    inserting_imgs_thread(client, reflected_cn, ts, files)

                full_user_input = ticket_manager.get_user_input(thread_ts)
                client.chat_postMessage(
                    channel=reflected_cn,
                    thread_ts=ts,
                    text=f"Hi {other_div_mention},\nCould you lend a hand to <@{user_who_requested}> with the following problem? ```{full_user_input}```\nMuch appreciated!",
                )
    else:
        user_info = client.users_info(user=selected_user)
        selected_user_name = user_info["user"]["real_name"]
        client.chat_postMessage(
            channel=user_who_requested,
            thread_ts=response_ts,
            text=f"<@{user_who_requested}> your issue will be handled by <@{selected_user}>. We will check and text you asap. Please wait ya.",
        )

        response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"<@{selected_user}> is on the case and will tackle this issue starting at `{timestamp_jakarta}`. (Assigned by: <@{person_who_assigns}>)",
        )

        sheet_manager.update_ticket(
            f"live-ops.{unique_id}",
            {
                "handled_by": selected_user_name,
                "handled_at": timestamp_utc,
                "assigned_by": person_who_assigns_name,
            },
        )

        if response["ok"]:
            updated_blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"We just received a ticket from <@{user_who_requested}> at `{reported_at}`",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Picked Up By:*\n<@{selected_user}>",
                        },
                    ],
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Please select the category of the issue:",
                    },
                    "accessory": {
                        "type": "static_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select category...",
                            "emoji": True,
                        },
                        "options": category_options,
                        "action_id": "category_select_action",
                    },
                },
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "emoji": True,
                                "text": "Resolve",
                            },
                            "style": "primary",
                            "value": ticket_key_for_user,
                            "action_id": "resolve_button",
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "emoji": True,
                                "text": "Reject",
                            },
                            "style": "danger",
                            "value": ticket_key_for_user,
                            "action_id": "reject_button",
                        },
                    ],
                },
            ]

            reflected_msg = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"We just received an issue from <@{user_who_requested}> at `{reported_at}`",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Current Progress:*\n:pray: On checking",
                        },
                    ],
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Please pay attention, if this issue related to you :point_up_2:",
                    },
                },
            ]

            client.chat_update(
                channel=channel_id,
                ts=thread_ts,
                text=f"<@{selected_user}> picked up the issue.",
                blocks=updated_blocks,
            )

            reflected_post = client.chat_postMessage(
                channel=reflected_cn,
                text="sending the ticket to #guru_kakaksiaga_ops",
                blocks=reflected_msg,
            )

            if reflected_post["ok"]:
                reflected_ts = reflected_post["ts"]
                ticket_manager.store_reflected_ts(thread_ts, reflected_ts)
                if files:
                    inserting_imgs_thread(client, reflected_cn, reflected_ts, files)
                full_user_input = ticket_manager.get_user_input(thread_ts)
                if len(full_user_input) > 37:
                    client.chat_postMessage(
                        channel=reflected_cn,
                        thread_ts=reflected_ts,
                        text=f"For the full details: ```{full_user_input}```",
                    )
                client.chat_postMessage(
                    channel=reflected_cn,
                    thread_ts=reflected_ts,
                    text=f"This issue will be handled by <@{selected_user}>, starting from `{timestamp_jakarta}`",
                )
            else:
                logging.error(
                    f"Failed to post reflected message: {reflected_post['error']}"
                )

        else:
            logging.error(f"Failed to post message: {response['error']}")

        if not response["ok"]:
            logging.error(f"Failed to post message: {response['error']}")


@app.action("category_select_action")
def handle_category_selection(ack, body, client):
    ack()
    channel_id = body["channel"]["id"]
    [
        selected_category_name,
        user_who_requested,
        response_ts,
        user_input,
        reported_at,
        selected_user,
        ticket_category,
    ] = body["actions"][0]["selected_option"]["value"].split("@@")
    thread_ts = body["container"]["message_ts"]
    reflected_ts = ticket_manager.get_reflected_ts(thread_ts)
    unique_id = ticket_manager.get_unique_id(thread_ts)
    ticket_key_for_user = f"{user_who_requested}@@{response_ts}@@{truncate_value(user_input)}@@{reported_at}@@{selected_user}@@{selected_category_name}@@{ticket_category}"

    if selected_category_name.lower() == "others":
        trigger_id = body["trigger_id"]
        modal_view = {
            "type": "modal",
            "callback_id": "custom_category_modal",
            "title": {"type": "plain_text", "text": "Custom Category"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "custom_category_block",
                    "label": {
                        "type": "plain_text",
                        "text": "Please specify your category",
                    },
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "custom_category_input",
                    },
                }
            ],
            "private_metadata": f"{thread_ts}@@{user_who_requested}@@{reported_at}@@{truncate_value(user_input)}@@{selected_user}@@{channel_id}@@{response_ts}@@{ticket_category}",
            "submit": {"type": "plain_text", "text": "Submit"},
        }
        client.views_open(trigger_id=trigger_id, view=modal_view)
    else:
        updated_blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"We just received a ticket from <@{user_who_requested}> at `{reported_at}`",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                    },
                    {"type": "mrkdwn", "text": f"*Picked up by:*\n<@{selected_user}>"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Category:*\n{selected_category_name}",
                    },
                ],
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Resolve",
                        },
                        "style": "primary",
                        "value": ticket_key_for_user,
                        "action_id": "resolve_button",
                    },
                ],
            },
        ]

        reflected_msg = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"We just received an issue from <@{user_who_requested}> at `{reported_at}`",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Current Progress:*\nBeing resolved",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Issue Category:*\n{selected_category_name}",
                    },
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Please pay attention, if this issue related to you :point_up_2:",
                },
            },
        ]

        client.chat_update(
            channel=channel_id, ts=thread_ts, text=None, blocks=updated_blocks
        )

        client.chat_update(
            channel=reflected_cn, ts=reflected_ts, text=None, blocks=reflected_msg
        )

        sheet_manager.update_ticket(
            f"live-ops.{unique_id}",
            {"category_issue": selected_category_name},
        )


@app.view("custom_category_modal")
def handle_custom_category_modal_submission(ack, body, client, view, logger):
    ack()
    user_id = body["user"]["id"]
    custom_category = view["state"]["values"]["custom_category_block"][
        "custom_category_input"
    ]["value"]
    [
        thread_ts,
        user_who_requested,
        reported_at,
        user_input,
        selected_user,
        channel_id,
        response_ts,
        ticket_category,
    ] = view["private_metadata"].split("@@")
    reflected_ts = ticket_manager.get_reflected_ts(thread_ts)
    unique_id = ticket_manager.get_unique_id(thread_ts)
    ticket_key_for_user = f"{user_who_requested}@@{response_ts}@@{truncate_value(user_input)}@@{reported_at}@@{selected_user}@@{custom_category}@@{ticket_category}"

    try:
        updated_blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"We just received a ticket from <@{user_who_requested}> at `{reported_at}`",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                    },
                    {"type": "mrkdwn", "text": f"*Picked up by:*\n<@{selected_user}>"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Category:*\n{custom_category}",
                    },
                ],
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "emoji": True,
                            "text": "Resolve",
                        },
                        "style": "primary",
                        "value": ticket_key_for_user,
                        "action_id": "resolve_button",
                    },
                ],
            },
        ]

        reflected_msg = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"We just received an issue from <@{user_who_requested}> at `{reported_at}`",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Current Progress:*\nBeing resolved",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Issue Category:*\n{custom_category}",
                    },
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Please pay attention, if this issue related to you :point_up_2:",
                },
            },
        ]

        client.chat_update(
            channel=channel_id, ts=thread_ts, text=None, blocks=updated_blocks
        )

        client.chat_update(
            channel=reflected_cn, ts=reflected_ts, text=None, blocks=reflected_msg
        )

        sheet_manager.update_ticket(
            f"live-ops.{unique_id}",
            {"category_issue": custom_category},
        )
    except Exception as e:
        logger.error(f"Failed to update ticket with custom category: {str(e)}")
        client.chat_postMessage(
            channel=user_id,
            text="Failed to record the custom category. Please try again.",
        )


@app.action("helpdesk_resolve_post_chatting")
def resolve_button_post_chatting(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    [ticket_id, user_reported, user_ts, conv_id, support_id, staff_ts, start_ts] = body[
        "actions"
    ][0]["value"].split("@@")
    timestamp_utc = datetime.now(timezone.utc)
    timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)

    try:
        messages = get_chat_history(client, conv_id, float(start_ts))

        updates = {
            "resolved_by": get_real_name(client, user_id),
            "resolved_at": timestamp_jakarta,
            "history_chat": "\n".join(messages),
        }

        sheet_manager.update_helpdesk(ticket_id, updates)

        blocks = body["message"]["blocks"]
        blocks[1]["fields"][7]["text"] = "*Status:*\n:white_check_mark: Resolved"
        blocks[1]["fields"].append(
            {"type": "mrkdwn", "text": f"*Resolved At:*\n`{timestamp_jakarta}`"}
        )
        blocks.pop(2)

        client.chat_update(channel=helpdesk_cn, ts=staff_ts, text=None, blocks=blocks)

        client.chat_postMessage(
            channel=user_reported,
            thread_ts=user_ts,
            text=f":white_check_mark: Your ticket: *{ticket_id}* has been resolved by <@{support_id}> at `{timestamp_jakarta}`",
        )

        client.chat_postMessage(
            channel=conv_id,
            text=f"Thanks so much for chatting with us! 🎉 We’re happy we could help. This conversation is all wrapped up now, but don’t hesitate to reach out again if you need anything else.\n\nHave an awesome day, <@{user_reported}>! 🌟",
        )

        if messages:
            inserting_chat_history_to_thread(client, helpdesk_cn, staff_ts, messages)

        logger.info(f"Ticket {ticket_id} resolved successfully.")
    except Exception as e:
        logging.error(f"Error resolving post chatting: {str(e)}")


@app.action("helpdesk_resolve")
@app.action("emergency_resolve")
@app.action("resolve_button")
def resolve_button(ack, body, client, logger):
    ack()
    try:
        user_id = body["user"]["id"]
        user_info = client.users_info(user=user_id)
        user_name = user_info["user"]["real_name"]
        channel_id = body["channel"]["id"]
        thread_ts = body["container"]["message_ts"]
        reflected_ts = ticket_manager.get_reflected_ts(thread_ts)
        conditional_index = 2 if len(body["message"]["blocks"]) <= 3 else 4
        elements = body["message"]["blocks"][conditional_index]["elements"]
        resolve_button_value = elements[0]["value"].split("@@")
        category_ticket = resolve_button_value[-1]
        timestamp_utc = datetime.now(timezone.utc)
        timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)

        if category_ticket == "Piket":
            [
                reporter_piket,
                response_ts,
                timestamp,
                date,
                teacher_requested,
                teacher_replace,
                grade,
                slot_name,
                time_class,
                reason,
                direct_lead,
                stem_lead,
            ] = resolve_button_value[:-1]
            ticket_manager.update_ticket_status(thread_ts, "assigned")
            unique_id = ticket_manager.get_unique_id(thread_ts)
            teacher_replace_state = (
                f"<@{teacher_replace}>"
                if teacher_replace != "No Mentor"
                and teacher_replace != "I need help finding a replacement"
                else f"`{teacher_replace}`"
            )
            piket_message = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Hi @tim_ajar\nWe've got a request from <@{teacher_requested}> with detail as below:",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Class Date:*\n`{date}`"},
                        {
                            "type": "mrkdwn",
                            "text": f"*Time of Class:*\n`{time_class}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Teacher Requested:*\n<@{teacher_requested}>",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Teacher Replaces:*\n{teacher_replace_state}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Slot Name:*\n`{grade}-{slot_name}`",
                        },
                        {"type": "mrkdwn", "text": f"*Reason:*\n```{reason}```"},
                        {
                            "type": "mrkdwn",
                            "text": f"*Direct Lead:*\n<@{direct_lead}>",
                        },
                        {"type": "mrkdwn", "text": f"*STEM Lead:*\n<@{stem_lead}>"},
                    ],
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Piket Ticket Number:* piket.{unique_id}",
                        }
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: <@{user_id}> approved the request",
                    },
                },
            ]
            response = client.chat_update(
                channel=channel_id, ts=thread_ts, text=None, blocks=piket_message
            )
            if response["ok"]:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"This request has been approved at `{timestamp_jakarta}` by <@{user_id}>",
                )

                client.chat_postMessage(
                    channel=piket_reflected_cn,
                    blocks=piket_message,
                )

                client.chat_postMessage(
                    channel=reporter_piket,
                    thread_ts=response_ts,
                    text=f"<@{reporter_piket}> your piket request has been approved at `{timestamp_jakarta}`. Thank you :blob-bear-dance:",
                )

            sheet_manager.update_piket(
                f"piket.{unique_id}",
                {
                    "status": "Approved",
                    "approved_by": user_name,
                    "approved_at": timestamp_utc,
                },
            )
        elif category_ticket == "Emergency":
            reflected_ts = ticket_manager.get_reflected_ts(thread_ts)
            user_who_requested_ticket_id = resolve_button_value[0]
            user_message_ts = resolve_button_value[1]
            emergency_reflected_ts = ticket_manager.get_reflected_ts(user_message_ts)
            resolved_emergency_block = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":rotating_light: *Emergency Update* :rotating_light:\n\nHi Ops team @tim_ajar, here’s an update regarding the critical situation reported earlier.",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Reported by:*\n<@{user_who_requested_ticket_id}>",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Timestamp:*\n`{timestamp_jakarta}`",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: *Status:* The issue has been successfully resolved by <@{user_id}>!",
                    },
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "_Great teamwork, everyone! Let's continue to stay vigilant._",
                        }
                    ],
                },
            ]

            resolved_response = client.chat_update(
                channel=channel_id,
                ts=thread_ts,
                text="Emergency resolved. Details updated in the thread.",
                blocks=resolved_emergency_block,
            )

            if resolved_response["ok"]:
                client.reactions_add(
                    channel=emergency_reflected_cn,
                    timestamp=emergency_reflected_ts,
                    name="white_check_mark",
                )

                client.chat_postMessage(
                    channel=emergency_reflected_cn,
                    thread_ts=emergency_reflected_ts,
                    text=f"The emergency issue has been resolved by <@{user_id}> at `{timestamp_jakarta}`",
                )

                client.chat_postMessage(
                    channel=user_who_requested_ticket_id,
                    thread_ts=user_message_ts,
                    text=f"Your emergency issue has been resolved by <@{user_id}> at `{timestamp_jakarta}`",
                )

                sheet_manager.update_emergency_row(
                    f"emergency-{user_message_ts}",
                    {
                        "resolved_by": get_real_name(client, user_id),
                        "resolved_at": timestamp_utc,
                    },
                )

        elif category_ticket == "IT Helpdesk":
            [ticket_id, user_reported, user_ts] = resolve_button_value[0:3]
            blocks = body["message"]["blocks"]
            blocks[1]["fields"][7]["text"] = "*Status:*\n:white_check_mark: Resolved"
            blocks[1]["fields"].append(
                {"type": "mrkdwn", "text": f"*Resolved At:*\n`{timestamp_jakarta}`"}
            )
            blocks.pop(2)

            client.chat_update(
                channel=channel_id, ts=thread_ts, text=None, blocks=blocks
            )

            client.chat_postMessage(
                channel=user_reported,
                thread_ts=user_ts,
                text=f":white_check_mark: Your ticket: *{ticket_id}* has been resolved by <@{helpdesk_support_id}> at `{timestamp_jakarta}`",
            )

            sheet_manager.update_helpdesk(
                ticket_id,
                {
                    "resolved_by": get_real_name(client, user_id),
                    "resolved_at": timestamp_jakarta,
                },
            )

        elif category_ticket == "Others":
            user_who_requested_ticket_id = resolve_button_value[0]
            user_message_ts = resolve_button_value[1]
            user_input = resolve_button_value[2]
            ticket_reported_at = resolve_button_value[3]
            selected_user = resolve_button_value[4]
            selected_category = resolve_button_value[5]
            category_ticket = resolve_button_value[6]
            unique_id = ticket_manager.get_unique_id(thread_ts)
            response = client.chat_update(
                channel=channel_id,
                ts=thread_ts,
                text=None,
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"We just received a message from <@{user_who_requested_ticket_id}> at `{ticket_reported_at}`",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Ticket Number:*\nlive.ops.{unique_id}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Picked up by:*\n<@{selected_user}>",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Category:*\n{selected_category}",
                            },
                        ],
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":white_check_mark: <@{user_id}> resolved this issue",
                        },
                    },
                ],
            )
            sheet_manager.update_ticket(
                f"live-ops.{unique_id}",
                {"resolved_by": user_name, "resolved_at": timestamp_utc},
            )

            if response["ok"]:
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"<@{user_id}> has resolved the issue at `{timestamp_jakarta}`.",
                )

                reflected_msg = [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"We just received an issue from <@{user_who_requested_ticket_id}> at `{ticket_reported_at}`",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Current Progress:*\n:white_check_mark: Resolved",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Issue Category:*\n{selected_category}",
                            },
                        ],
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Please pay attention, if this issue related to you :point_up_2:",
                        },
                    },
                ]

                client.chat_update(
                    channel=reflected_cn,
                    ts=reflected_ts,
                    text=f"we are resolving this ticket: live-ops.{unique_id}",
                    blocks=reflected_msg,
                )

                client.chat_postMessage(
                    channel=reflected_cn,
                    thread_ts=reflected_ts,
                    text=f"This issue has been resolved at `{timestamp_jakarta}` by <@{user_id}>",
                )

                client.chat_postMessage(
                    channel=user_who_requested_ticket_id,
                    thread_ts=user_message_ts,
                    text=f"<@{user_who_requested_ticket_id}> your issue has been resolved at `{timestamp_jakarta}`. Thank you :blob-bear-dance:",
                )

            else:
                logging.error(f"Failed to post message: {response['error']}")
    except Exception as e:
        logger.error(f"Error resolve function: {str(e)}")


@app.action("helpdesk_reject")
@app.action("reject_button")
def handle_reject_button(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]
    message_ts = body["container"]["message_ts"]
    unique_id = ticket_manager.get_unique_id(message_ts)
    channel_id = body["channel"]["id"]
    user_info = client.users_info(user=body["user"]["id"])
    user_name = user_info["user"]["real_name"]
    blocks = body["message"]["blocks"]
    conditional_index = conditional_indexing(blocks)
    elements = blocks[conditional_index[0]]["elements"]
    reject_button_value = elements[conditional_index[1]]["value"]
    timestamp_utc = datetime.now(timezone.utc)
    sheet_manager.update_ticket(
        f"live-ops.{unique_id}",
        {"rejected_by": user_name, "rejected_at": timestamp_utc},
    )
    sheet_manager.update_piket(
        f"piket.{unique_id}",
        {"status": "Rejected", "rejected_by": user_name, "rejected_at": timestamp_utc},
    )
    modal = {
        "type": "modal",
        "callback_id": "modal_reject",
        "title": {"type": "plain_text", "text": "Reject Issue"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "reject_reason",
                "label": {"type": "plain_text", "text": "Reason for Rejection"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reason_input",
                    "multiline": True,
                },
            },
        ],
        "private_metadata": f"{channel_id}@@{message_ts}@@{reject_button_value}",
    }

    try:
        client.views_open(trigger_id=trigger_id, view=modal)
    except SlackApiError as e:
        logging.error(f"Error opening modal: {str(e)}")


@app.view("modal_reject")
def show_reject_modal(ack, body, client, view, logger, say):
    ack()
    try:
        user_id = body["user"]["id"]
        [channel_id, message_ts, *reject_button_value] = view["private_metadata"].split(
            "@@"
        )
        reflected_ts = ticket_manager.get_reflected_ts(message_ts)
        unique_id = ticket_manager.get_unique_id(message_ts)
        reason = view["state"]["values"]["reject_reason"]["reason_input"]["value"]
        timestamp_utc = datetime.now(timezone.utc)
        timestamp_jakarta = convert_utc_to_jakarta(timestamp_utc)
        ticket_category = reject_button_value[-1]
        ticket_manager.update_ticket_status(message_ts, "assigned")

        if ticket_category == "Others":
            [
                user_requested_id,
                user_message_ts,
                user_input,
                ticket_reported_at,
            ] = reject_button_value[0:4]
            response = client.chat_postMessage(
                channel=channel_id,
                thread_ts=message_ts,
                text=f"<@{user_id}> has rejected the issue at `{timestamp_jakarta}` due to: ```{reason}```",
            )
            if response["ok"]:
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=None,
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"We just received a message from <@{user_requested_id}> at `{ticket_reported_at}`",
                            },
                        },
                        {
                            "type": "section",
                            "fields": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Ticket Number:*\nlive.ops.{unique_id}",
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                                },
                            ],
                        },
                        {"type": "divider"},
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f":x: This issue was rejected by <@{user_id}>. Please ignore this",
                            },
                        },
                    ],
                )

                reflected_msg = [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "Hi Team :wave:"},
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"We just received an issue from <@{user_requested_id}> at `{ticket_reported_at}`",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Ticket Number:*\nlive-ops.{unique_id}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Problem:*\n`{truncate_value(user_input)}`",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Current Progress:*\n:x: Issue Rejected",
                            },
                        ],
                    },
                ]

                client.chat_postMessage(
                    channel=user_requested_id,
                    thread_ts=user_message_ts,
                    text=f"We are sorry :smiling_face_with_tear: your issue was rejected due to ```{reason}``` at `{timestamp_jakarta}`. Let's put another question.",
                )

                if reflected_cn:
                    client.chat_update(
                        channel=reflected_cn,
                        ts=reflected_ts,
                        text=f"ticket: live-ops.{unique_id} just rejected by <@{user_id}",
                        blocks=reflected_msg,
                    )
                if reflected_cn:
                    client.chat_update(
                        channel=reflected_cn,
                        ts=reflected_ts,
                        text=f"ticket: live-ops.{unique_id} just rejected by <@{user_id}",
                        blocks=reflected_msg,
                    )

                client.chat_postMessage(
                    channel=reflected_cn,
                    thread_ts=reflected_ts,
                    text=f"We are sorry, this issue was rejected by <@{user_id}> at `{timestamp_jakarta}` due to ```{reason}```",
                )

            else:
                logger.error("No value information available for this channel.")
        elif ticket_category == "IT Helpdesk":
            helpdesk_rejection_text = f"<@{user_id}> has rejected the helpdesk request at `{timestamp_jakarta}` due to: ```{reason}```"
            [
                ticket_id,
                helpdesk_reporter,
                reporter_ts,
                full_name,
                timestamp_jakarta,
                issue_type,
                issue_desc,
                urgency_level,
                incident_time,
            ] = reject_button_value[:-1]
            helpdesk_user_response = client.chat_postMessage(
                channel=channel_id, thread_ts=message_ts, text=helpdesk_rejection_text
            )
            if helpdesk_user_response["ok"]:
                helpdesk_ticket_blocks = [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"New Helpdesk Ticket: {ticket_id}",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*User Name:*\n{full_name}"},
                            {
                                "type": "mrkdwn",
                                "text": f"*Requested by:*\n<@{helpdesk_reporter}>",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Requested at:*\n`{timestamp_jakarta}`",
                            },
                            {"type": "mrkdwn", "text": f"*Issue Type:*\n{issue_type}"},
                            {
                                "type": "mrkdwn",
                                "text": f"*Issue Description:*\n```{issue_desc}```",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Urgency Level:*\n{urgency_level}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Incident Date and Time:*\n`{incident_time}`",
                            },
                            {"type": "mrkdwn", "text": f"*Status:*\n:x: Rejected"},
                        ],
                    },
                ]

                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text="Sorry, We reject this helpdesk request.",
                    blocks=helpdesk_ticket_blocks,
                )

                client.chat_postMessage(
                    channel=helpdesk_reporter,
                    thread_ts=reporter_ts,
                    text=f":smiling_face_with_tear: Your request got the boot due to ```{reason}``` at `{timestamp_jakarta}`. But hey, no worries! You can always throw another helpdesk request our way soon!",
                )
                updates = {
                    "rejected_by": get_real_name(client, user_id),
                    "rejected_at": timestamp_jakarta,
                    "rejection_reason": reason,
                }

                sheet_manager.update_helpdesk(ticket_id, updates)
            else:
                say(
                    "Failed to send message to thread after reject the helpdesk request"
                )

        elif ticket_category == "Piket":
            [
                reporter_piket,
                response_ts,
                timestamp,
                date,
                teacher_requested,
                teacher_replace,
                grade,
                slot_name,
                time_class,
                reason_on_piket_replacement,
                direct_lead,
                stem_lead,
            ] = reject_button_value[:-1]
            general_rejection_text = f"<@{user_id}> has rejected the request at `{timestamp_jakarta}` due to: ```{reason}```"
            response = client.chat_postMessage(
                channel=channel_id,
                thread_ts=message_ts,
                text=general_rejection_text,
            )
            teacher_replace_state = (
                f"<@{teacher_replace}>"
                if teacher_replace != "No Mentor"
                and teacher_replace != "I need help finding a replacement"
                else f"`{teacher_replace}`"
            )
            if response["ok"]:
                piket_message = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Hi @tim_ajar\nWe've got a request from <@{teacher_requested}> with detail as below:",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Class Date:*\n`{date}`"},
                            {
                                "type": "mrkdwn",
                                "text": f"*Time of Class:*\n`{time_class}`",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Teacher Requested:*\n<@{teacher_requested}>",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Teacher Replaces:*\n{teacher_replace_state}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Slot Name:*\n`{grade}-{slot_name}`",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Reason:*\n```{reason_on_piket_replacement}```",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Direct Lead:*\n<@{direct_lead}>",
                            },
                            {"type": "mrkdwn", "text": f"*STEM Lead:*\n<@{stem_lead}>"},
                        ],
                    },
                    {"type": "divider"},
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Piket Ticket Number:* piket.{unique_id}",
                            }
                        ],
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":x: This request was rejected by <@{user_id}>. Please ignore this",
                        },
                    },
                ]
                client.chat_update(
                    channel=channel_id, ts=message_ts, text=None, blocks=piket_message
                )

                client.chat_postMessage(
                    channel=reporter_piket,
                    thread_ts=response_ts,
                    text=f"Uh-oh! :smiling_face_with_tear: Your request got the boot due to ```{reason}``` at `{timestamp_jakarta}`. But hey, no worries! You can always throw another piket request our way soon!",
                )

                ref_post = client.chat_postMessage(
                    channel=piket_reflected_cn, blocks=piket_message
                )

                if ref_post["ok"]:
                    ref_ts = ref_post["ts"]
                    client.chat_postMessage(
                        channel=piket_reflected_cn,
                        thread_ts=ref_ts,
                        text=general_rejection_text,
                    )

            else:
                logger.error("No value information available for this channel.")
    except Exception as e:
        logger.error(f"Error handling modal submission: {str(e)}")


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
