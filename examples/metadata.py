"""
Example to get metadata from configured cdr_manager
"""
import asterisk.manager
import sys


def handle_cdr_event(event, manager):
   print(event.get_header("BillableSeconds"))
   print(event.get_header("Disposition"))
   print(event.get_header("UniqueID"))
   manager.close()

manager = asterisk.manager.Manager()

try:
    try:
        manager.connect(host='localhost')
        manager.login('admin', 'ami-secret')
        
        manager.originate(
            channel="PJSIP/6001",
            exten=100,
            context="from-internal",
            priority=1,
            variables={"CALLERID(all)": "6001", "CALLERID(dnid)": "100"}
        )

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
    manager.close()
