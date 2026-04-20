# src/aws_clients.py
import boto3


def make_client(service, region):
    return boto3.client(service, region_name=region)
