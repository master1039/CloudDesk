<!-- Written by Euron Code after each task. It is rewritten automatically: put your own rules in
     another file in .euron/rules/. -->

# Learned in this project


## Security (from .euron/security/assessment.md)
- This code base has had: api token in the code (SEC003). Revoke/rotate the token and read it from an environment variable (keep .env out of git). Do not add more; fix the existing ones when you touch those files.
- This code base has had: aws access key in the code (SEC002). Rotate the key in AWS IAM now and read credentials from the environment or a role. Do not add more; fix the existing ones when you touch those files.
- This code base has had: private key in the code (SEC001). Remove it, rotate the key, load it from a secret store or file outside the repo. Do not add more; fix the existing ones when you touch those files.
- This code base has had: hard-coded password or secret (SEC004). Move the value to an environment variable or secret manager; never commit real credentials. Do not add more; fix the existing ones when you touch those files.
