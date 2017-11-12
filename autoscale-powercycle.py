#!/usr/bin/python
import argparse
import sys
import logging
import json
from boto.ec2.autoscale import Tag
from datetime import datetime
from datetime import timedelta
import boto.ec2.autoscale
from croniter import croniter
from boto.utils import get_instance_metadata

__authors__ = 'Adam Gold <adambalali@gmail.com>'
__description__ = """Tool for stop and start ASG"""
__license__ = 'MIT'


def get_roles(connection, role=None):
    """ Get Roles of Components
    :type connection: boto.ec2.autoscale.AutoScaleConnection
    :param connection: AutoScale connection object
    :type role: str
    :param role: Role Name
    :returns: list
    """
    if role is not None:
        return [role]

    groups = connection.get_all_groups()
    roles = [tag.value for group in groups for tag in group.tags if tag.key == 'role']

    return list(set(roles))


def set_auto_scaling_group_state(autoscale, group):
    """ Set The Last Auto Scaling Group State
    :type autoscale: boto.ec2.autoscale.AutoScaleConnection
    :param autoscale: AutoScale Connection Object
    :type group: boto.ec2.autoscale.group
    :param group: Auto Scaling Group Object
    :returns: None
    """

    state_tag = Tag(key='scaling_state',
                    value=dict(min=group.min_size, desired=group.desired_capacity, max=group.max_size),
                    resource_id=group.name)

    autoscale.create_or_update_tags([state_tag])


def get_auto_scaling_group_state(group, group_tags):
    """ Get The Last Auto Scaling Group State
    :type group: boto.ec2.autoscale.group
    :param group: Auto Scaling Group Object
    :type group_tags: dict
    :param group_tags: Auto Scaling Group Tags
    :returns: dict
    """

    group_scaling_state = group_tags['scaling_state']
    json_acceptable_string = group_scaling_state.replace("'", "\"")
    scaling_state = json.loads(json_acceptable_string)  # reading the scaling state from tag
    min_size = 1  # default value for min
    desired_capacity = 1  # default value for desired state
    max_size = group.max_size  # keep the current set max size

    if 'min' in scaling_state:
        min_size = int(scaling_state['min'])
    if 'desired' in scaling_state:
        desired_capacity = int(scaling_state['desired'])

    if min_size > desired_capacity:
        logging.info('Min size %s was bigger than desired capacity %s. Setting minimum size to desired capacity' %
                     (str(min_size), str(desired_capacity)))
        min_size = desired_capacity
    if desired_capacity > max_size:
        logging.info('Desired capacity %s is set bigger than the current maximum value %s. Setting maximum size to '
                     'desired capacity' %
                     (str(desired_capacity), str(max_size)))
        max_size = desired_capacity

    return dict(min=min_size, desired=desired_capacity, max=max_size)


def handle_auto_scaling_group(autoscale, environment, roles, state, scheduled_time):
    """ Handle Auto-Scaling-Group Instances
    :type autoscale: boto.ec2.autoscale.AutoScaleConnection
    :param autoscale: AutoScale connection object
    :type environment: str
    :param environment: Environment name
    :type roles: list
    :param roles: Role Name
    :type state: str
    :param state: Desired State
    :type scheduled_time: datetime
    :param scheduled_time: Scheduled Time
    :returns: None
    """

    logging.info("Started Processing Auto Scaling Groups")
    groups = autoscale.get_all_groups()

    all_roles = get_roles(autoscale)
    roles_size = len(roles)
    kept_role = None

    if roles_size >= len(all_roles):
        kept_role = roles.pop()

    is_role_legal = any(role in all_roles for role in roles)

    if not is_role_legal:
        logging.error("Role: %s is not a legal role" % roles[0])
        sys.exit(1)

    for group in groups:
        try:
            group_tags = dict()
            for tag in group.tags:
                group_tags[tag.key] = tag.value

            group_role = group_tags['role']
            group_environment = group_tags['environment']

            if kept_role == group_role and environment == group_environment:
                _bring_auto_scaling_group_to_desired_state(autoscale, group, group_tags, state, scheduled_time, 1)

            if environment == group_environment and group_role in roles:
                logging.info("Found AutoScaling Group %s with role: %s." %
                             (group.name, group_role))
                _bring_auto_scaling_group_to_desired_state(autoscale, group, group_tags, state, scheduled_time)
        except Exception, e:
            logging.error("Error while processing Auto-Scaling Group %s: %s" %
                          (group.name, e))


def _bring_auto_scaling_group_to_desired_state(autoscale, group, group_tags, desired_state, scheduled_time,
                                               capacity_size=0):
    """ Bring Auto Scaling Group to Desired State
    :type autoscale: boto.ec2.autoscale.AutoScaleConnection
    :param autoscale: AutoScale connection object
    :type group: boto.ec2.autoscale.group
    :param group: Auto Scaling Group Object
    :type group_tags: dict
    :param group_tags: Auto Scaling Group Tags
    :type desired_state: str
    :param desired_state: Desired State
    :type scheduled_time: datetime
    :param scheduled_time: Scheduled Time
    :type capacity_size: int
    :param capacity_size: Capacity Size
    :returns: None
    """

    group_name = str(group.name)

    logging.info("Auto-Scaling Group: %s. Current state: { min: %s, desired: %s }." %
                 (group_name, group.min_size, group.desired_capacity))

    if desired_state == 'stop' and is_auto_scaling_group_up(group):
        logging.info("Scaling down AutoScaling Group: %s" % group_name)
        set_auto_scaling_group_state(autoscale, group)
        autoscale.create_scheduled_group_action(
            as_group=group_name,
            name="stop schedule of %s" % group_name,
            time=scheduled_time,
            desired_capacity=capacity_size,
            min_size=capacity_size,
            max_size=group.max_size
        )

        group.update()
    elif desired_state == 'start' and not is_auto_scaling_group_up(group):
        desired_scaling_state = get_auto_scaling_group_state(group, group_tags)
        logging.info('Scaling Up Auto-Scaling Group %s to %s' %
                     (group_name, str(desired_scaling_state)))
        autoscale.create_scheduled_group_action(
            as_group=group_name,
            name="start schedule of %s" % group_name,
            time=scheduled_time,
            desired_capacity=desired_scaling_state['desired'],
            min_size=desired_scaling_state['min'],
            max_size=desired_scaling_state['max']
        )

        group.update()
    else:
        logging.info('Auto-Scaling Group: %s is already in the desired state: %s' %
                     (group_name, desired_state))


def revive_environment(autoscale, environment):
    """Revive Environment on demand
    :type autoscale: boto.ec2.autoscale.AutoScaleConnection
    :param autoscale: AutoScale connection object
    :type environment: str
    :param environment: Environment Name
    """

    logging.info("Started Reviving Environment: %s" % environment)
    groups = autoscale.get_all_groups()
    for group in groups:
        try:
            group_tags = dict()
            for tag in group.tags:
                group_tags[tag.key] = tag.value

            group_environment = group_tags['environment']

            if environment == group_environment:
                desired_scaling_state = get_auto_scaling_group_state(group, group_tags)
                logging.info("Reviving Auto-Scaling Group: %s. Current state: { min: %s, desired: %s }." %
                             (group.name, group.min_size, group.desired_capacity))
                autoscale.create_scheduled_group_action(
                    as_group=group.name,
                    name="reviving now %s" % group.name,
                    time=(datetime.utcnow() + timedelta(seconds=1*60)),
                    desired_capacity=desired_scaling_state['desired'],
                    min_size=desired_scaling_state['min'],
                    max_size=desired_scaling_state['max']
                )

                group.update()
        except Exception as e:
            logging.error("Error while reviving environment: %s with Auto-Scaling Group %s: %s" %
                          (environment, group.name, e))


def is_auto_scaling_group_up(group):
    return group.min_size > 0 and group.desired_capacity > 0


def _get_desired_state(start_time, stop_time):
    """ Get Desired State
    :type start_time: str
    :param start_time: Desired Start Time
    :type stop_time: str
    :param stop_time: Desired Stop Time
    """

    now = datetime.now()

    try:
        cron_start_time = croniter(start_time, now)
        cron_stop_time = croniter(stop_time, now)

        if cron_stop_time.get_prev(datetime) > cron_start_time.get_prev(datetime):
            logging.info('Stop event %s is more recent than start event %s' %
                         (str(cron_stop_time.get_prev(datetime)), str(cron_start_time.get_prev(datetime))))
            return 'stop', cron_stop_time.get_next(datetime)
        else:
            logging.info('Start event %s is more recent than stop event %s' %
                         (str(cron_start_time.get_prev(datetime)), str(cron_stop_time.get_prev(datetime))))
            return 'start', cron_start_time.get_next(datetime)
    except Exception, e:
        logging.error('Encountered with an error: %s' % e)
        return None


def _ensure_args(parser):
    args = parser.parse_args()

    if args.environment.lower() not in ('staging', 'performance'):
        logging.error("%s is an illegal environment name. Please choose between staging or performance" %
                      args.environment)
        parser.print_help()
        parser.exit()

    return args


def define_arguments():
    ret_val = argparse.ArgumentParser(description=__description__,
                                      formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    ret_val.add_argument(
        '--start',
        help='Start Time',
        default='0 9 * * 0-4',
        dest='start_time'
    )

    ret_val.add_argument(
        '--stop',
        help='Stop Time',
        default='0 18 * * 0-4',
        dest='stop_time'
    )

    ret_val.add_argument(
        '-r', '--role',
        help='Role Name',
        default=None,
        dest='role'
    )

    ret_val.add_argument(
        '-e', '--environment',
        help='Environment Name',
        required=True,
        dest='environment'
    )

    ret_val.add_argument(
        '--revive',
        help='Revive Environment',
        default=False,
        action='store_true'
    )

    ret_val.add_argument(
        '--access-key-id',
        help='AWS Access Key',
        default=None
    )

    ret_val.add_argument(
        '--secret-access-key',
        help='AWS Secret Access Key',
        default=None
    )

    ret_val.add_argument(
        '--region',
        default='eu-central-1',
        help='AWS region'
    )

    return ret_val


def connect_to_autoscale(region, access_key=None, secret_key=None):
    """ Connect to AWS AutoScale
    :type region: str
    :param region: AWS region to connect to
    :type access_key: str
    :param access_key: AWS access key id
    :type secret_key: str
    :param secret_key: AWS secret access key
    :returns: boto.ec2.autoscale.AutoScaleConnection
    """

    if access_key:
        # Connect using supplied credentials
        logging.info('Connecting to AWS EC2 in {}'.format(region))
        connection = boto.ec2.autoscale.connect_to_region(
            region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key)
    else:
        # Fetch instance metadata
        metadata = get_instance_metadata(timeout=1, num_retries=1)
        if metadata:
            try:
                region = metadata['placement']['availability-zone'][:-1]
            except KeyError:
                pass

        # Connect using env vars or boto credentials
        logging.info('Connecting to AWS AutoScalingGroup in {}'.format(region))
        connection = boto.ec2.autoscale.connect_to_region(region)

    if not connection:
        logging.error('An error occurred while connecting to AutoScalingGroup')
        sys.exit(1)

    return connection


logging.basicConfig(
    stream=sys.stdout,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def run():
    start_message = 'Started power-cycle procedure at %s' % datetime.today().strftime('%d-%m-%Y %H:%M:%S')

    logging.info(start_message)

    parser = define_arguments()

    if len(sys.argv[1:]) == 0:
        parser.print_help()
        parser.exit()

    args = _ensure_args(parser)

    access_key_id = args.access_key_id
    secret_access_key = args.secret_access_key
    region = args.region
    role = args.role
    environment = args.environment
    start_time = args.start_time
    stop_time = args.stop_time
    is_revive_environment = args.revive

    # Connect to AWS AutoScale
    aws_autoscale = connect_to_autoscale(
        region,
        access_key_id,
        secret_access_key
    )

    if is_revive_environment:
        revive_environment(aws_autoscale, environment)
    else:
        state, scheduled_time = _get_desired_state(start_time, stop_time)
        roles = get_roles(aws_autoscale, role)
        handle_auto_scaling_group(aws_autoscale, environment, roles, state, scheduled_time)


if __name__ == '__main__':
    run()
