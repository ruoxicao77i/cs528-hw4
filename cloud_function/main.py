"""
Cloud Function: stop the HW5 Cloud SQL instance if it is running.

Cloud Scheduler publishes a message to a Pub/Sub topic once an hour,
and that message triggers this function.
"""
import functions_framework
from googleapiclient import discovery

 
PROJECT_ID = "tonal-plateau-508118-g0"
INSTANCE = "hw5-db"

@functions_framework.cloud_event
def stop_db(cloud_event):
    sqladmin = discovery.build("sqladmin", "v1beta4", cache_discovery=False)

    inst = sqladmin.instances().get(project=PROJECT_ID, instance=INSTANCE).execute()
    policy = inst["settings"]["activationPolicy"]
    state = inst.get("state")
    print(f"{INSTANCE}: state={state}, activationPolicy={policy}")

    # ALWAYS = the instance is running
    # NEVER means stop
    if policy == "ALWAYS":
        body = {"settings": {"activationPolicy": "NEVER"}}
        sqladmin.instances().patch(project=PROJECT_ID, instance=INSTANCE, body=body).execute()
        print(f"{INSTANCE} was running, stop requested.")
    else:
        print(f"{INSTANCE} is already stopped, nothing to do.")