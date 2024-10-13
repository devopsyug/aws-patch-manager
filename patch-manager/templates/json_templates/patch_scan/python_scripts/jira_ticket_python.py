import json
import urllib.request
import base64
import os
import boto3
import csv
from io import StringIO

# Environment Variables
JIRA_URL = os.environ['JIRA_URL']
JIRA_USER = os.environ['JIRA_USERNAME']
JIRA_API_TOKEN = os.environ['JIRA_API_TOKEN']
JIRA_PROJECT = os.environ['JIRA_PROJECT']
PATCH_GROUP_NAME = os.environ['PatchGroupName']
S3_BUCKET_NAME = os.environ['S3_BUCKET_NAME']
Customer_Name = os.environ['Customer_Name']

# AWS Clients
ssm_client = boto3.client('ssm')
ec2_client = boto3.client('ec2')
s3_client = boto3.client('s3')

def lambda_handler(event, context):
    sns_message = event['Records'][0]['Sns']['Message']
    sns_message_json = json.loads(sns_message)
    print('SNS Message: ', json.dumps(sns_message_json, indent=2))
    task_command_id = sns_message_json.get('commandId', '')

    # If command ID exists, retrieve the list of instance IDs
    if task_command_id and len(task_command_id) == 36:
        instance_ids = get_instances_from_command_invocation(task_command_id)
    else:
        print(f'Invalid or missing Command ID: {task_command_id}')
        instance_ids = []

    scheduled_time = sns_message_json.get('eventTime', '')

    # Fetch instance names based on instance IDs
    instance_name_map = get_instance_name_map(instance_ids)

    # Create a JIRA ticket and get the ticket number
    jira_ticket_number = create_jira_ticket(instance_ids, instance_name_map, scheduled_time, task_command_id)

    # Tag instances with the JIRA ticket number
    if jira_ticket_number and instance_ids:
        tag_instances_with_jira_ticket(instance_ids, jira_ticket_number)

    # Generate and upload the compliance report
    if instance_ids:
        compliance_report = generate_compliance_report(instance_ids)
        upload_report_to_s3(compliance_report, jira_ticket_number)

    return {'statusCode': 200, 'body': json.dumps('JIRA ticket created, instances tagged, and compliance report uploaded.')}

def get_instances_from_command_invocation(command_id):
    instance_ids = []
    response = ssm_client.list_command_invocations(
        CommandId=command_id,
        Details=True
    )
    for invocation in response['CommandInvocations']:
        instance_ids.append(invocation['InstanceId'])
    return instance_ids

def get_instance_name_map(instance_ids):
    instance_name_map = {}
    if instance_ids:
        response = ec2_client.describe_instances(InstanceIds=instance_ids)
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                instance_name = next(
                    (tag['Value'] for tag in instance.get('Tags', []) if tag['Key'] == 'Name'),
                    'Unnamed'
                )
                instance_name_map[instance_id] = instance_name
    return instance_name_map

def create_jira_ticket(instance_ids, instance_name_map, scheduled_time, task_command_id):
    instances_info = '\n'.join([f"{instance_id} ({instance_name_map.get(instance_id, 'Unnamed')})" for instance_id in instance_ids])
    jira_data = {
        'fields': {
            'project': {'key': JIRA_PROJECT},
            'summary': f'Patch Scan Status Success for Customer - {Customer_Name}',
            'description': (
                f'*PatchGroup Name:* {PATCH_GROUP_NAME}\n\n'
                f'*Instances:*\n{instances_info}\n\n'
                f'*Scheduled Time:*\n{scheduled_time}\n\n'
                f'*Task Command ID:*\n{task_command_id}\n'
            ),
            'issuetype': {'name': 'Task'}
        }
    }

    auth_string = f'{JIRA_USER}:{JIRA_API_TOKEN}'
    auth_encoded = base64.b64encode(auth_string.encode()).decode('utf-8')
    req = urllib.request.Request(f'{JIRA_URL}/rest/api/2/issue', data=json.dumps(jira_data).encode(), headers={'Authorization': f'Basic {auth_encoded}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as response:
        jira_response = response.read().decode()
        print('JIRA Response: ', jira_response)
        jira_response_json = json.loads(jira_response)
        jira_ticket_number = jira_response_json.get('key')
        return jira_ticket_number

def tag_instances_with_jira_ticket(instance_ids, jira_ticket_number):
    tag = {
        'Key': 'JiraTicket',
        'Value': jira_ticket_number
    }
    ec2_client.create_tags(Resources=instance_ids, Tags=[tag])
    print(f'Tagged instances {instance_ids} with JIRA ticket: {jira_ticket_number}')



def generate_compliance_report(instance_ids):
    compliance_data = []
    
    for instance_id in instance_ids:
        response = ssm_client.list_compliance_items(
            ResourceIds=[instance_id],
            ResourceTypes=['ManagedInstance']
        )
        for item in response['ComplianceItems']:
            compliance_data.append({
                'InstanceId': instance_id,
                'ComplianceType': item['ComplianceType'],
                'ExecutionSummary': item.get('ExecutionSummary', {}).get('ExecutionTime', 'N/A'),
                'Status': item['Status'],
                'Title': item.get('Title', 'N/A'),
                'Severity': item.get('Severity', 'N/A')
            })

    # Create CSV from compliance data
    csv_output = StringIO()
    csv_writer = csv.DictWriter(csv_output, fieldnames=['InstanceId', 'ComplianceType', 'ExecutionSummary', 'Status', 'Title', 'Severity'])
    csv_writer.writeheader()
    csv_writer.writerows(compliance_data)
    
    return csv_output.getvalue()

def upload_report_to_s3(compliance_report, jira_ticket_number):
    file_name = f'compliance-report-{jira_ticket_number}.csv'
    
    s3_client.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=file_name,
        Body=compliance_report,
        ContentType='text/csv'
    )
    
    print(f'Compliance report uploaded to S3: s3://{S3_BUCKET_NAME}/{file_name}')
