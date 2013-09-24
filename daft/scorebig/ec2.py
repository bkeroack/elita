import boto.ec2

__author__ = 'bkeroack'

aws_access_key_id = ''
aws_secret_access_key = ''

class EC2Service:
    def __init__(self, region="us-west-2"):
        self.con = boto.ec2.connect_to_region(region, aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_access_key_id)

    def launch_instance(self, ami, security_group, keyname='tech-ops', instance_type='m1.large'):
        return self.con.run_instances(ami, security_groups=[security_group], key_name=keyname, instance_type=instance_type)

