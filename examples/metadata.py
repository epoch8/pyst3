"""Example to get metadata from configured cdr_manager."""
import sys

import asterisk.manager


def handle_cdr_event(event, manager):
    """Получаем и выводим необходимые метаданные и завершаем потоки."""
    print(event.get_header("BillableSeconds"))
    print(event.get_header("Disposition"))
    print(event.get_header("UniqueID"))
    manager.close()


manager = asterisk.manager.Manager()

try:
    try:
        # Подключаемся в AMI
        manager.connect(host="localhost")
        manager.login("admin", "ami-secret")

        # Инициируем звонок (локально)
        manager.originate(
            channel="PJSIP/6001",
            exten=100,
            context="from-internal",
            priority=1,
            variables={"CALLERID(all)": "6001", "CALLERID(dnid)": "100"},
        )

        # Регистрируем callback на Event с именем Cdr и вызывам join() чтобы дождаться callback
        # т к Event с именем Cdr приходит в самом конце звонка и т к в нем находятся все необходимые метаданные
        # логично его дождать и в самой функции handle_cdr_event вызывать manager.close() для завершения потоков
        manager.register_event("Cdr", handle_cdr_event)
        manager.message_thread.join()

    except asterisk.manager.ManagerSocketException as reason:
        print("Error connecting to the manager: %s" % reason)
        sys.exit(1)
    except asterisk.manager.ManagerAuthException as reason:
        print("Error logging in to the manager: %s" % reason)
        sys.exit(1)
    except asterisk.manager.ManagerException as reason:
        print("Error: %s" % reason)
        sys.exit(1)
finally:
    # перестраховываемся
    manager.close()
