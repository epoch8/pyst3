"""Call-manager that get tasks for origination, originate and manage calls."""
import asyncio
import logging
import os
import time
import typing as tp
from concurrent.futures import ThreadPoolExecutor
from string import Template

import aiohttp
import structlog
from dotenv import load_dotenv

import asterisk.manager

load_dotenv()

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)
logger = structlog.get_logger()

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
        self.client_session = aiohttp.ClientSession()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._loop = None

    def _run_in_thread(self, func: tp.Callable, *args) -> asyncio.futures.Future:
        return asyncio.get_event_loop().run_in_executor(self._executor, func, *args)

    async def prepare_manager(self):
        await self._run_in_thread(self.__manager.connect, AMI_HOST)
        await self._run_in_thread(self.__manager.login, AMI_USERNAME, AMI_SECRET)

    async def add_tasks_banch_from_dispatcher(self) -> None:
        params = {"token": CHATBOT_ADMIN_API_KEY}
        data = {"amount": self.tasks_banch_size}
        async with self.client_session.post(url=tasks_url, json=data, params=params) as response:
            response.raise_for_status()
            raw_new_tasks, new_tasks = await response.json(), []
            for raw_new_task in raw_new_tasks:
                campaign = raw_new_task.get("campaign")
                new_task = {
                    "task_id": int(raw_new_task.get("id")),
                    "campaign": campaign,
                    "bot_phone_number": int(campaign.get("bot_phone_number")),
                    "timeout": int(campaign.get("subscriber_response_waiting_limit")),
                    "contact_phone_number": int(raw_new_task.get("contact").get("phone")),
                }
                new_tasks.append(new_task)
            await logger.ainfo(f"Added {len(new_tasks)} new tasks")
            self.tasks_to_run += new_tasks

    async def update_task_status_in_admin(self, data: dict) -> None:
        params = {"token": CHATBOT_ADMIN_API_KEY}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        async with self.client_session.patch(url=tasks_url, json=data, params=params, headers=headers) as response:
            response.raise_for_status()

    def handle_cdr_event(self, event, _) -> None:
        """Получаем метаданные и передаем в админку."""
        task_id = event.get_header("UserField")
        if len(task_id) < 1:
            return
        task_id = int(task_id)
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

        async def _update_task_status_in_admin(data: tp.List[tp.Dict]):
            await logger.ainfo(f"Call finished: {data}")
            await self.update_task_status_in_admin(data)

        asyncio.run_coroutine_threadsafe(_update_task_status_in_admin(data), self._loop)
        tasks_to_monitor.remove(task_id)

    async def originate_call_with_callback_from_task(self, task: dict):
        await logger.ainfo(f"Originating call from task: {task}")
        self.__manager.originate(
            channel=self.channel_template.substitute(contact_phone_number=task["contact_phone_number"]),
            exten=task["bot_phone_number"],
            context=self.context,
            priority=1,
            timeout=task["timeout"],
            caller_id=task["bot_phone_number"],
            variables={
                "CALLERID(all)": task["contact_phone_number"],
                "CALLERID(dnid)": task["bot_phone_number"],
                "CDR(userfield)": task["task_id"],
            },
        )
        tasks_to_monitor.append(task["task_id"])

    async def monitor_cdr_events(self):
        await self._run_in_thread(self.__manager.register_event, "Cdr", self.handle_cdr_event)

    async def manager_close(self):
        await self._run_in_thread(self.__manager.close)


async def main():
    try:
        await logger.ainfo("Starting")
        originate_manager = OriginateManager(
            manager=manager,
            channel_template=channel_template,
            context=context,
            tasks_banch_size=TASKS_BANCH_SIZE,
        )
        originate_manager._loop = asyncio.get_running_loop()
        await originate_manager.prepare_manager()
        await originate_manager.monitor_cdr_events()
        await logger.ainfo("OriginateManager prepared and monitor cdr events")
        while True:
            try:
                await logger.ainfo("Cycle started")
                await originate_manager.add_tasks_banch_from_dispatcher()

                for _ in originate_manager.tasks_to_run:
                    await originate_manager.originate_call_with_callback_from_task(
                        originate_manager.tasks_to_run.pop(0)
                    )
                await logger.ainfo("Cycle finished")
            except asterisk.manager.ManagerSocketException as reason:
                await logger.aexception("Error connecting to the manager: %s" % reason)
                # TODO originate_manager.prepare_manager()
            except asterisk.manager.ManagerAuthException as reason:
                await logger.aexception("Error logging in to the manager: %s" % reason)
            except asterisk.manager.ManagerException as reason:
                await logger.aexception("Error: %s" % reason)

            except Exception as e:
                await logger.aexception(f"Unexpected error ocured: {e}")
            time.sleep(CYCLE_PERIOD)
    finally:
        try:
            await originate_manager.manager_close()
        except Exception as e:
            await logger.aexception(f"While closing the manager error ocured: {e}")


if __name__ == "__main__":
    asyncio.run(main())
