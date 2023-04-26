"""Example to get metadata from configured cdr_manager."""
import json
import sys
import time
from string import Template

import requests

import asterisk.manager

CHATBOT_ADMIN_URL = "http://localhost:8001"
CHATBOT_ADMIN_API_KEY = "whozKC8meyPDiEVGRDp7lGxClQY28tyQ"
LOCAL = True
AMI_HOST = "localhost"
AMI_USERNAME = "admin"
AMI_SECRET = "secret"
TASKS_BANCH_SIZE = 5

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
        self.__manager.connect(host="localhost")
        self.__manager.login("admin", "ami-secret")

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
        params = {"token": CHATBOT_ADMIN_API_KEY}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        response = requests.patch(url=tasks_url, params=params, data=json.dumps(data), headers=headers)
        response.raise_for_status()
        tasks_to_monitor.remove(task_id)
        print("sent")

    def originate_call_with_callback_from_task(self, task: dict):
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
        originate_manager = OriginateManager(
            manager=manager,
            channel_template=channel_template,
            context=context,
            tasks_banch_size=TASKS_BANCH_SIZE,
        )
        originate_manager.prepare_manager()
        originate_manager.monitor_cdr_events()
        while True:
            print("cycle")
            try:
                originate_manager.add_tasks_banch_from_dispatcher()

                for _ in range(len(originate_manager.tasks_to_run)):
                    originate_manager.originate_call_with_callback_from_task(originate_manager.tasks_to_run.pop())
                print("finish")

            except asterisk.manager.ManagerSocketException as reason:
                print("Error connecting to the manager: %s" % reason)
                sys.exit(1)
            except asterisk.manager.ManagerAuthException as reason:
                print("Error logging in to the manager: %s" % reason)
                sys.exit(1)
            except asterisk.manager.ManagerException as reason:
                print("Error: %s" % reason)
                sys.exit(1)
            time.sleep(30)
    finally:
        manager.close()


if __name__ == "__main__":
    main()
