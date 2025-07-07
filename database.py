import gspread
import logging
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz
import re


class SheetManager:
    def __init__(self, creds_dict, sheet_key):
        try:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            self.chat_sheet = client.open_by_key(sheet_key).worksheet("chit_chat")
            self.ticket_sheet = client.open_by_key(sheet_key).worksheet("ticket")
            self.piket_sheet = client.open_by_key(sheet_key).worksheet("piket")
            self.slot_data = client.open_by_key(sheet_key).worksheet("slot_data")
            self.emergency = client.open_by_key(sheet_key).worksheet("emergency")
            self.it_helpdesk = client.open_by_key(sheet_key).worksheet("it_helpdesk")
            self.kakak_siaga = client.open_by_key(sheet_key).worksheet("kakak_siaga")
        except Exception as e:
            logging.error(f"Failed to initialize SheetManager: {str(e)}")

    def get_slots_by_grade(self, grade):
        try:
            grade_values = self.slot_data.col_values(1)
            slot_values = self.slot_data.col_values(3)

            slots_for_grade = [
                slot_values[i] for i, g in enumerate(grade_values) if g == str(grade)
            ]

            # Define a sorting key function
            def sorting_key(slot):
                match = re.search(r"(\D+)\s(\d+)", slot)
                if match:
                    subject = match.group(1).strip()
                    number = int(match.group(2))
                    return (subject, number)
                else:
                    return (slot, 0)

            sorted_slots = sorted(slots_for_grade, key=sorting_key)

            return sorted_slots

        except Exception as e:
            logging.error(f"Failed to fetch slots for grade {grade}: {str(e)}")
            return []

    def convert_utc_to_jakarta(self, time):
        utc_time = time.replace(tzinfo=pytz.utc)
        jakarta_tz = pytz.timezone("Asia/Jakarta")
        changed_timezone = utc_time.astimezone(jakarta_tz)
        return changed_timezone.strftime("%Y-%m-%d %H:%M:%S")

    def log_ticket(
        self,
        chat_timestamp,
        timestamp_utc,
        user_id,
        user_name,
        email,
        phone_number,
        text,
    ):
        try:
            timestamp_local = self.convert_utc_to_jakarta(timestamp_utc)
            data = [
                chat_timestamp,
                timestamp_local,
                user_id,
                user_name,
                email,
                phone_number,
                text,
            ]
            self.chat_sheet.append_row(data)
        except Exception as e:
            logging.error(f"Failed to log chat: {str(e)}")

    def init_emergency(self, emergency_id, user_requested, timestamp_utc):
        try:
            timestamp_local = self.convert_utc_to_jakarta(timestamp_utc)
            data = [emergency_id, timestamp_local, user_requested]
            self.emergency.append_row(data)
        except Exception as e:
            logging.error(f"Failed to initialize emergency row: {str(e)}")

    def init_it_helpdesk(
        self,
        it_helpdesk_id,
        user_reported,
        issue_type,
        issue_description,
        urgency_level,
        incident_date_time,
        attachment_files,
        timestamp_utc,
    ):
        try:
            timestamp_local = self.convert_utc_to_jakarta(timestamp_utc)
            data = [
                it_helpdesk_id,
                timestamp_local,
                user_reported,
                issue_type,
                issue_description,
                urgency_level,
                incident_date_time,
                attachment_files,
            ]
            self.it_helpdesk.append_row(data)
        except Exception as e:
            logging.error(f"Failed to populate the data on it_helpdesk: {str(e)}")

    def init_piket_row(
        self,
        piket_id,
        teacher_requested,
        teacher_replaces,
        grade,
        slot_name,
        class_date,
        class_time,
        reason,
        direct_lead,
        stem_lead,
        timestamp_utc,
    ):
        try:
            timestamp_local = self.convert_utc_to_jakarta(timestamp_utc)
            data = [
                piket_id,
                timestamp_local,
                teacher_requested,
                teacher_replaces,
                grade,
                slot_name,
                class_date,
                class_time,
                reason,
                direct_lead,
                stem_lead,
            ]
            self.piket_sheet.append_row(data)
        except Exception as e:
            logging.error(f"Failed to initialize piket row: {str(e)}")

    def init_ticket_row(self, ticket_id, user_id, user_name, user_input, timestamp_utc):
        try:
            timestamp_local = self.convert_utc_to_jakarta(timestamp_utc)
            data = [
                timestamp_local,
                ticket_id,
                user_id,
                user_name,
                user_input,
                "",
                "",
                "",
                "",
                "",
                "",
            ]
            self.ticket_sheet.append_row(data)
        except Exception as e:
            logging.error(f"Failed to initialize ticket row: {str(e)}")

    def update_ticket(self, ticket_id, updates):
        try:
            row = self.find_ticket_row(ticket_id)
            if row:
                for key, value in updates.items():
                    col = self.column_mappings[key]
                    if "at" in key and isinstance(value, datetime):
                        value = self.convert_utc_to_jakarta(value)
                    self.ticket_sheet.update_cell(row, col, value)
        except Exception as e:
            logging.error(f"Failed to update ticket: {str(e)}")

    def find_ticket_row(self, ticket_id):
        ticket_id_col = 2
        col_values = self.ticket_sheet.col_values(ticket_id_col)
        for i, val in enumerate(col_values):
            if val == ticket_id:
                return i + 1
        return None

    @property
    def column_mappings(self):
        return {
            "timestamp": 1,
            "ticket_ids": 2,
            "user_ids": 3,
            "user_names": 4,
            "user_issue": 5,
            "category_issue": 6,
            "handled_by": 7,
            "handled_at": 8,
            "resolved_by": 9,
            "resolved_at": 10,
            "rejected_by": 11,
            "rejected_at": 12,
            "handed_over_by": 13,
            "handed_over_at": 14,
            "assigned_by": 15,
        }

    def update_piket(self, piket_id, updates):
        try:
            row = self.find_piket_row(piket_id)
            if row:
                for key, value in updates.items():
                    col = self.piket_col_mapping[key]
                    if "at" in key and isinstance(value, datetime):
                        value = self.convert_utc_to_jakarta(value)
                    self.piket_sheet.update_cell(row, col, value)
        except Exception as e:
            logging.error(f"Failed to update ticket: {str(e)}")

    def find_piket_row(self, piket_id):
        piket_id_col = 1
        col_values = self.piket_sheet.col_values(piket_id_col)
        for i, val in enumerate(col_values):
            if val == piket_id:
                return i + 1
        return None

    @property
    def piket_col_mapping(self):
        return {
            "piket_id": 1,
            "timestamp": 2,
            "teacher_requested": 3,
            "teacher_replaces": 4,
            "grade": 5,
            "slot_name": 6,
            "class_date": 7,
            "class_time": 8,
            "reason": 9,
            "direct_lead": 10,
            "stem_lead": 11,
            "status": 12,
            "approved_by": 13,
            "approved_at": 14,
            "rejected_by": 15,
            "rejected_at": 16,
            "edited_at": 17,
        }

    def update_emergency_row(self, emergency_id, updates):
        try:
            row = self.find_emergency_id(emergency_id)
            if row:
                for key, value in updates.items():
                    col = self.emergency_col_mapping[key]
                    if "at" in key and isinstance(value, datetime):
                        value = self.convert_utc_to_jakarta(value)
                    self.emergency.update_cell(row, col, value)
        except Exception as e:
            logging.error(f"Failed to update row: {str(e)}")

    def find_emergency_id(self, emergency_id):
        emergency_id_col = 1
        col_values = self.emergency.col_values(emergency_id_col)
        for i, val in enumerate(col_values):
            if val == emergency_id:
                return i + 1
        return None

    @property
    def emergency_col_mapping(self):
        return {
            "emergency_id": 1,
            "timestamp": 2,
            "user_reported": 3,
            "resolved_by": 4,
            "resolved_at": 5,
        }

    def update_helpdesk(self, it_helpdesk_id, updates):
        try:
            row = self.find_it_helpdesk_id(it_helpdesk_id)
            if row:
                for key, value in updates.items():
                    col = self.helpdesk_col_mapping[key]
                    if "at" in key and isinstance(value, datetime):
                        value = self.convert_utc_to_jakarta(value)
                    self.it_helpdesk.update_cell(row, col, value)
        except Exception as e:
            logging.error(f"Failed to update row: {str(e)}")

    def find_it_helpdesk_id(self, it_helpdesk_id):
        it_helpdesk_id_col = 1
        col_values = self.it_helpdesk.col_values(it_helpdesk_id_col)
        for i, val in enumerate(col_values):
            if val == it_helpdesk_id:
                return i + 1
        return None

    @property
    def helpdesk_col_mapping(self):
        return {
            "it_helpdesk_id": 1,
            "timestamp": 2,
            "user_reported": 3,
            "issue_type": 4,
            "issue_description": 5,
            "urgency_level": 6,
            "incident_date_time": 7,
            "attachment_files": 8,
            "resolved_by": 9,
            "resolved_at": 10,
            "rejected_by": 11,
            "rejected_at": 12,
            "rejection_reason": 13,
            "history_chat": 14,
        }

    def init_kakak_siaga_row(
            self, 
            kakak_siaga_id, 
            submitter_id,
            user_id, 
            nama_murid, 
            grade, 
            isu_murid, 
            files, 
            timestamp
    ):
        try:
            self.kakak_siaga.append_row([
                kakak_siaga_id,  # ID sebagai kolom pertama
                submitter_id,
                user_id,
                nama_murid,
                grade,
                isu_murid,
                files,
                str(timestamp)
            ])
        except Exception as e:
            logging.error(f"Failed to append Kakak Siaga row: {str(e)}")
