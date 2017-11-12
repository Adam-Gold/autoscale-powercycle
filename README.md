# AUTOSCALE-POWERCYCLE

_AWS tool to stop and start ASG based on roles tag using crontab-like expressions_

## Usage

AWS tool to stop and start ASG based on roles tag and environment tag using crontab-like expressions

### Examples
1. AutoScalingGroup stop/start schedule: Sun 9:00
    ```
    ./autoscale-powercycle.py --start="0 9 * * 0" --access-key-id=<ACCESS_KEY> --secret-access-key=<SECRET_ACCESS_KEY> --region=<REGION> --environment=<ENVIRONMENT>
    ```
1. Auto Scaling Group stop schedule at: Sun 18:00, with role specified.
    ```
    ./autoscale-powercycle.py --role <ROLE_NAME> --stop="00 18 * * 0" --access-key-id=<ACCESS_KEY> --secret-access-key=<SECRET_ACCESS_KEY> --region=<REGION> --environment=<ENVIRONMENT>
    ```

Contributing
------------

1. Fork the repository on Github
2. Create a named feature branch (like `add_component_x`)
3. Write your changes
4. Write tests for your changes (if applicable)
5. Run the tests, ensuring they all pass
6. Submit a Pull Request using Github

License and Authors
-------------------
- Author:: Adam Gold Balali (adamba@johnbox.net)