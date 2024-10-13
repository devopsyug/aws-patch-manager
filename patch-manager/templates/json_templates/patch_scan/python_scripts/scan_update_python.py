import boto3
import os
import json
import time
def lambda_handler(event, context):
    ec2 = boto3.client('ec2')
    # Filter to get instances with the tag 'env=dev'
    filters = [
        {
            'Name': 'tag:Environment',
            'Values': [os.environ['Environment']]
        }
    ]
    # Describe instances that match the filter
    instances = ec2.describe_instances(Filters=filters)
    # List to store instance IDs that need tagging
    instance_ids = []
    for reservation in instances['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            instance_ids.append(instance_id)
    # Check if there are instances to tag
    if instance_ids:
        # Apply PatchGroup tag to all filtered instances
        ec2.create_tags(
            Resources=instance_ids,
            Tags=[
                {'Key': 'PatchGroup', 'Value': os.environ['PatchGroupName']}
            ]
        )
       # Sleep for 30 seconds to allow the tags to propagate
        time.sleep(30)
        print(f"Applied PatchGroup=test tag to instances: {instance_ids}")
    else:
        print("No instances found with Environment=os.environ['Environment'] tag")
    return {
        'statusCode': 200,
        'body': f"Tagged {len(instance_ids)} instance(s) with PatchGroup=os.environ['PatchGroupName']"
    }