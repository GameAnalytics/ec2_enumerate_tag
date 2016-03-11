#!/usr/bin/python
#
# This is a free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This Ansible library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this library.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: ec2_enumerate_tag
short_description: Enumerate instances with ec2 tags
description:
    - Filter instances with certain tags and enumerate them
author: "Jon Elverkilde (github.com/elverkilde)"
options:
  tag:
    description:
      - The target tag, e.g. Name
    required: true
    aliases: []
  pattern:
    description:
      - The target pattern, e.g. myhost[01:99]
    required: true
    aliases: []
  filters:
    description:
      - EC2 tags to filter on
    required: true
    aliases: []
extends_documentation_fragment:
    - aws
    - ec2
'''

try:
    import boto.ec2
    from boto.exception import BotoServerError
    HAS_BOTO = True
except ImportError:
    HAS_BOTO = False

import re

class PatternError(Exception):
    def __init__(self, pattern):
        self.pattern = pattern
    def __str__(self):
        return repr(self.pattern)

def range_pattern(range_str):
    pattern = "("
    for char in range_str:
        pattern += "\d"
    return pattern + ")"

def parse_pattern(raw_pattern):
    m = re.match("(?P<hostname>[a-zA-Z0-9_-]*)\[(?P<range_start>\d+):(?P<range_end>\d+)\]", raw_pattern)
    if m:
        return m.groupdict()
    else:
        raise PatternError("Invalid pattern: %s" % raw_pattern)

def check_pattern(pattern, tag, taken):
    pattern_dict = parse_pattern(pattern)
    hostname = pattern_dict['hostname']
    range_start_str = pattern_dict['range_start']
    range_start = int(range_start_str)
    range_end = int(pattern_dict['range_end'])

    m = re.match(hostname + range_pattern(range_start_str), tag)
    if m:
        current_id = int(m.group(1))
        return range_start <= current_id <= range_end
    else:
        return False

def fresh_names(pattern, taken, no_requested):
    pattern_dict = parse_pattern(pattern)
    hostname = pattern_dict['hostname']
    range_start_str = pattern_dict['range_start']
    range_start = int(range_start_str)
    range_end = int(pattern_dict['range_end'])

    current_id = range_start
    if len(taken) > 0:
        max_taken = max(taken)
        m = re.match(hostname + range_pattern(range_start_str), max_taken)
        max_id = int(m.group(1))
        current_id = max_id+1

    names = []
    for i in range(0, no_requested):
        suffix = str(current_id + i)
        while len(suffix) < len(range_start_str):
            suffix = "0" + suffix

        names.append(hostname + suffix)

    return names

def format_return(instances):
    ret = []
    for item in instances:
        instance = item["instance"]
        ret.append({"id" : instance.id,
                    "public_dns" : instance.public_dns_name,
                    "public_ip" : instance.ip_address,
                    "value" : item['val']
                    })
    return ret

def main():
    argument_spec = ec2_argument_spec()
    argument_spec.update(
        dict(
            tag={'type': 'str'},
            filters={'type': 'dict'},
            pattern={'type': 'str'}
        )
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
    )

    if not HAS_BOTO:
        module.fail_json(msg='boto required for this module')


    # TODO: Move to specific functions
    ec2 = ec2_connect(module)

    tag = module.params.get("tag")
    filters = module.params.get("filters")
    pattern = module.params.get("pattern")

    formatted = {"tag:" + k: v for k, v in filters.items()}

    try:
        instances = ec2.get_only_instances(filters=formatted)
    except BotoServerError as e:
        module.fail_json(msg=e.message)
    except PatternError as e:
        module.fail_json(msg=e.message)

    valid_instances = []
    invalid_instances = []

    for instance in instances:
        if tag in instance.tags:
            current_val = instance.tags[tag]
            if check_pattern(pattern, current_val, valid_instances):
                valid_instances.append({"instance" : instance,
                                        "val" : current_val})
            else:
                invalid_instances.append({"instance" : instance,
                                          "val" : current_val})
        else:
            invalid_instances.append({"instance" : instance,
                                      "val" : None})

    invalid_instances_len = len(invalid_instances)
    tag_changes = []
    for i in enumerate(invalid_instances, start=0):
        print i
    if invalid_instances_len > 0:
        new_names = fresh_names(pattern, valid_instances, invalid_instances_len)
        for idx, item in enumerate(invalid_instances, start=0):
            new_name = new_names[idx]
            bad_instance = item["instance"]
            bad_instance.add_tag(tag, new_name)
            tag_changes.append({"id" : bad_instance.id,
                                "tag" : tag,
                                "before" : old_name,
                                "after" : new_name
                                })
        module.exit_json(changed=True, tag_changes=tag_changes, current=new_names.append(valid_instances))
    else:
        module.exit_json(changed=False, current=format_return(valid_instances))



from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

if __name__ == '__main__':
    main()
