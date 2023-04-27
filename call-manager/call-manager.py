"""Call-manager that get tasks for origination, originate and manage calls."""
import json
import logging
import os
import time
from string import Template

import requests
from dotenv import load_dotenv

import asterisk.manager

load_dotenv()
logging.basicConfig(format="%(name)s - %(levelname)s - %(message)s", level=logging.INFO)

LOCAL = bool(os.getenv("LOCAL"))

CHATBOT_ADMIN_URL = os.getenv("CHATBOT_ADMIN_URL", "http://call-manager:8001")
CHATBOT_ADMIN_API_KEY = os.getenv("CHATBOT_ADMIN_API_KEY", "whozKC8meyPDiEVGRDp7lGxClQY28tyQ")

AMI_HOST = os.getenv("AMI_HOST", "asterisk")
AMI_USERNAME = os.getenv("AMI_USERNAME", "admin")
AMI_SECRET = os.getenv("AMI_SECRET", "secret")

TASKS_BANCH_SIZE = int(os.getenv("TASKS_BANCH_SIZE", 5))
CYCLE_PERIOD = int(os.getenv("CYCLE_PERIOD", 60))

manager = asterisk.manager.Manager()

tasks_url = f"{CHATBOT_ADMIN_URL}/api/v1/tasks/"
channel_template, context = Template("SIP/$contact_phone_number@OPER"), "client"
if LOCAL:
    channel_template, context = Template("PJSIP/$contact_phone_number"), "from-internal"
tasks_to_monitor = []


class OriginateManager:
    def __init__(
        self,
        manager: asterisk.manager.Manager,
        channel_template: Template,
        context: str,
        tasks_banch_size: int,
    ) -> None:
        self.__manager = manager
        self.channel_template = channel_template
        self.context = context
        self.tasks_banch_size = tasks_banch_size
        self.tasks_to_run = []

    def prepare_manager(self):
        self.__manager.connect(host=AMI_HOST)
        self.__manager.login(AMI_USERNAME, AMI_SECRET)

    def add_tasks_banch_from_dispatcher(self) -> None:
        params = {"token": CHATBOT_ADMIN_API_KEY}
        data = {"amount": self.tasks_banch_size}
        response = requests.post(url=tasks_url, params=params, data=data)
        response.raise_for_status()
        raw_new_tasks, new_tasks = response.json(), []
        for raw_new_task in raw_new_tasks:
            campaign = raw_new_task.get("campaign")
            new_task = {
                "task_id": int(raw_new_task.get("id")),
                "campaign": campaign,
                "bot_phone_number": int(campaign.get("bot_phone_number")[0]),
                "timeout": int(campaign.get("subscriber_response_waiting_limit")),
                "contact_phone_number": int(raw_new_task.get("contact").get("phone")),
            }
            new_tasks.append(new_task)
        logging.info(f"Added {len(new_tasks)} new tasks")
        self.tasks_to_run += new_tasks

    @staticmethod
    def handle_cdr_event(event, _) -> None:
        """Получаем метаданные и передаем в админку."""
        task_id = int(event.get_header("UserField"))
        if task_id not in tasks_to_monitor:
            return
        metadata = {
            "TaskID": task_id,
            "Duration": event.get_header("Duration"),
            "BillableSeconds": event.get_header("BillableSeconds"),
            "Disposition": event.get_header("Disposition"),
            "UniqueID": event.get_header("UniqueID"),
            "CallerID": event.get_header("CallerID"),
            "StartTime": event.get_header("StartTime"),
            "AnswerTime": event.get_header("AnswerTime"),
            "EndTime": event.get_header("EndTime"),
        }

        data = [
            {
                "id": int(metadata["TaskID"]),
                "status": metadata["Disposition"],
                "data": {
                    "UniqueID": metadata["UniqueID"],
                    "CallerID": metadata["CallerID"],
                    "StartTime": metadata["StartTime"],
                },
                "result": {
                    "Duration": metadata["Duration"],
                    "AnswerTime": metadata["AnswerTime"],
                    "BillableSeconds": metadata["BillableSeconds"],
                    "EndTime": metadata["EndTime"],
                },
            },
        ]
        logging.info(f"Call finished: {data}")
        params = {"token": CHATBOT_ADMIN_API_KEY}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        response = requests.patch(url=tasks_url, params=params, data=json.dumps(data), headers=headers)
        response.raise_for_status()
        tasks_to_monitor.remove(task_id)

    def originate_call_with_callback_from_task(self, task: dict):
        logging.info(f"Originateing call from task: {task}")
        self.__manager.originate(
            channel=self.channel_template.substitute(contact_phone_number=task["contact_phone_number"]),
            exten=task["bot_phone_number"],
            context=self.context,
            priority=1,
            timeout=task["timeout"],
            variables={
                "CALLERID(all)": task["contact_phone_number"],
                "CALLERID(dnid)": task["bot_phone_number"],
                "CDR(userfield)": task["task_id"],
            },
        )
        tasks_to_monitor.append(task["task_id"])

    def join_originated_call(self):
        self.__manager.close()

    def monitor_cdr_events(self):
        self.__manager.register_event("Cdr", self.handle_cdr_event)


def main():
    try:
        logging.info("Starting")
        originate_manager = OriginateManager(
            manager=manager,
            channel_template=channel_template,
            context=context,
            tasks_banch_size=TASKS_BANCH_SIZE,
        )
        originate_manager.prepare_manager()
        originate_manager.monitor_cdr_events()
        logging.info("OriginateManager prepared and monitor cdr events")
        while True:
            try:
                logging.info("Cycle started")
                originate_manager.add_tasks_banch_from_dispatcher()

                for _ in range(len(originate_manager.tasks_to_run)):
                    originate_manager.originate_call_with_callback_from_task(originate_manager.tasks_to_run.pop(0))
                logging.info("Cycle finished")
            except asterisk.manager.ManagerSocketException as reason:
                logging.exception("Error connecting to the manager: %s" % reason)
            except asterisk.manager.ManagerAuthException as reason:
                logging.exception("Error logging in to the manager: %s" % reason)
            except asterisk.manager.ManagerException as reason:
                logging.exception("Error: %s" % reason)
            except Exception as e:
                logging.exception(f"Unexpected error ocured: {e}")
            time.sleep(CYCLE_PERIOD)
    finally:
        try:
            manager.close()
        except Exception as e:
            logging.exception(f"While closing the manager error ocured: {e}")


if __name__ == "__main__":
    main()
