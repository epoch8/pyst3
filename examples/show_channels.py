"""
Example to get list of active channels
"""
import asterisk.manager
import sys

manager = asterisk.manager.Manager()

try:
    # connect to the manager
    try:
        manager.connect(host='localhost')
        manager.login('admin', 'ami-secret')

        response = manager.status()
        print(response.data)
        
        response = manager.originate(
            channel="PJSIP/6001",
            exten=100,
            context="from-internal",
            priority=1
        )
        print(response)

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
    # remember to clean up
    manager.close()

