# Deploying the shadow paper trader on AWS (ap-south-1, Mumbai)

The paper trader is a short job: about a minute of work every 4 hours. It places **no orders** and needs **no exchange API keys**; it reads Delta India's public API.

## Choice: a scheduled ECS task on Fargate (not EC2)

| | **ECS scheduled task on Fargate (chosen)** | Small EC2 instance (t4g.nano) |
|---|---|---|
| What runs | A fresh container every 4h, started by EventBridge Scheduler, then gone | A server running 24/7 with cron + Docker |
| Maintenance | None: no OS to patch, no disk to fill, no SSH | You patch the OS, rotate logs, watch the disk |
| Restart safety | Each run is a clean start; state lives in S3 with versioning (every past state recoverable) | State on the instance disk; need your own backups |
| Logs | Built in: `awslogs` → CloudWatch Logs | Install and configure the CloudWatch agent |
| Monthly cost (estimate) | **about $0.20–0.60** | **about $6–7** (instance ≈ $2.0 + 8 GB disk ≈ $0.7 + public IPv4 ≈ $3.6) |

Fargate wins on cost, maintenance and restart safety for a job that runs 6 times a day. Its one extra piece is the SQLite file living in S3. The entrypoint downloads it, runs, and uploads it with a **conditional write** (`IfMatch` on the downloaded ETag), so two overlapping runs can never overwrite each other's state.

### Cost estimate (ap-south-1, USD, per month)

| Item | Usage | Estimate |
|---|---|---|
| Fargate (Linux/ARM64, 0.25 vCPU, 1 GB) | 6 runs/day × ~1.5 min ≈ 4.5 task-hours | ≈ $0.05 |
| Public IPv4 while a task runs | ≈ 4.5 hours × $0.005 | ≈ $0.02 |
| CloudWatch Logs | well under 100 MB ingested and stored | ≈ $0.05 |
| S3 state (a few MB; noncurrent versions expire after 30 days) | ~180 versions/month | ≈ $0.03 |
| ECR image storage | ~0.4 GB | ≈ $0.04 |
| EventBridge Scheduler, SSM Parameter Store (standard) | ~180 invocations; 2 parameters | free |
| **Total** | | **≈ $0.20–0.60** |

**Pricing assumption (flagged):** I could not retrieve AWS's Mumbai Fargate ARM rate, so the Fargate line uses the published US East ARM rates ($0.03238 per vCPU-hour, $0.00356 per GB-hour) as a proxy; Mumbai's rates are similar. Even at double those rates the total stays well under $1. EC2 figures are from third-party price trackers (t4g.nano ≈ $0.0028/hour in Mumbai). Confirm both in the [AWS Pricing Calculator](https://calculator.aws/) before relying on them.

## 0. Before you start

- **Tools:** an AWS account, the AWS CLI v2 configured for it, Docker with `buildx`, and this repository.
- **Telegram (optional but recommended):**
  1. Talk to `@BotFather` in Telegram and send `/newbot`. Copy the **bot token**.
  2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in your browser and copy `"chat":{"id": ...}`. That is your **chat id**.
  3. **Never** put the token in git, in `paper_config.json` or in the image. It goes into SSM Parameter Store below.
- **Region:** everything below is in **ap-south-1**. An Indian region also keeps your IP local to Delta India's public API. The first manual run checks the API is reachable from AWS.

Set these once in your shell (replace the bucket name with a globally unique one):

```bash
export AWS_REGION=ap-south-1
```

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

```bash
export BUCKET=paper-trader-state-$ACCOUNT_ID
```

## 1. S3 bucket for the state (private, versioned)

```bash
aws s3api create-bucket --bucket $BUCKET --create-bucket-configuration LocationConstraint=$AWS_REGION
```

```bash
aws s3api put-public-access-block --bucket $BUCKET --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

```bash
aws s3api put-bucket-versioning --bucket $BUCKET --versioning-configuration Status=Enabled
```

```bash
aws s3api put-bucket-lifecycle-configuration --bucket $BUCKET --lifecycle-configuration '{"Rules":[{"ID":"expire-old-state-versions","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":30}}]}'
```

## 2. Container image in ECR (ARM64)

```bash
aws ecr create-repository --repository-name paper-trader --image-scanning-configuration scanOnPush=true
```

```bash
aws ecr get-login-password | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

```bash
docker buildx build --platform linux/arm64 -t $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/paper-trader:v1 --push .
```

Use a new tag (`v2`, …) for every change, and record which commit each tag was built from. The image contains `frozen_rules.md`, `paper_trading_plan.md` and `paper_config.json` as they were when built.

## 3. Logs and secrets

```bash
aws logs create-log-group --log-group-name /ecs/paper-trader
```

```bash
aws logs put-retention-policy --log-group-name /ecs/paper-trader --retention-in-days 400
```

```bash
aws ssm put-parameter --name /paper-trader/TELEGRAM_BOT_TOKEN --type SecureString --value 'PASTE_TOKEN_HERE'
```

```bash
aws ssm put-parameter --name /paper-trader/TELEGRAM_CHAT_ID --type SecureString --value 'PASTE_CHAT_ID_HERE'
```

Run the two `put-parameter` commands yourself and paste the values only into your own terminal, not into chat or files.

## 4. IAM roles

Three roles are needed:
- **Execution role:** lets ECS pull the image, write logs and read the two SSM parameters.
- **Task role:** lets the container read and write only its own state object.
- **Scheduler role:** lets EventBridge Scheduler start the task.

```bash
cat > /tmp/ecs-trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
```

```bash
aws iam create-role --role-name paperTraderExecutionRole --assume-role-policy-document file:///tmp/ecs-trust.json
```

```bash
aws iam attach-role-policy --role-name paperTraderExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

```bash
aws iam put-role-policy --role-name paperTraderExecutionRole --policy-name read-telegram-params --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"ssm:GetParameters\",\"Resource\":\"arn:aws:ssm:$AWS_REGION:$ACCOUNT_ID:parameter/paper-trader/*\"}]}"
```

```bash
aws iam create-role --role-name paperTraderTaskRole --assume-role-policy-document file:///tmp/ecs-trust.json
```

```bash
aws iam put-role-policy --role-name paperTraderTaskRole --policy-name state-object-only --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\"],\"Resource\":\"arn:aws:s3:::$BUCKET/paper.db\"},{\"Effect\":\"Allow\",\"Action\":\"s3:ListBucket\",\"Resource\":\"arn:aws:s3:::$BUCKET\",\"Condition\":{\"StringEquals\":{\"s3:prefix\":\"paper.db\"}}}]}"
```

`s3:ListBucket` (limited to the state key) is needed so a missing state file reads as "not found" (first run) rather than "access denied".

```bash
cat > /tmp/scheduler-trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"scheduler.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
```

```bash
aws iam create-role --role-name paperTraderSchedulerRole --assume-role-policy-document file:///tmp/scheduler-trust.json
```

```bash
aws iam put-role-policy --role-name paperTraderSchedulerRole --policy-name run-paper-task --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"ecs:RunTask\",\"Resource\":\"arn:aws:ecs:$AWS_REGION:$ACCOUNT_ID:task-definition/paper-trader:*\"},{\"Effect\":\"Allow\",\"Action\":\"iam:PassRole\",\"Resource\":[\"arn:aws:iam::$ACCOUNT_ID:role/paperTraderExecutionRole\",\"arn:aws:iam::$ACCOUNT_ID:role/paperTraderTaskRole\"]}]}"
```

## 5. ECS cluster and task definition

```bash
aws ecs create-cluster --cluster-name paper-trader
```

```bash
cat > /tmp/taskdef.json <<EOF
{
  "family": "paper-trader",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "256",
  "memory": "1024",
  "runtimePlatform": {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
  "executionRoleArn": "arn:aws:iam::$ACCOUNT_ID:role/paperTraderExecutionRole",
  "taskRoleArn": "arn:aws:iam::$ACCOUNT_ID:role/paperTraderTaskRole",
  "containerDefinitions": [{
    "name": "paper-trader",
    "image": "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/paper-trader:v1",
    "essential": true,
    "environment": [
      {"name": "PAPER_STATE_S3", "value": "s3://$BUCKET/paper.db"},
      {"name": "PAPER_DB", "value": "/state/paper.db"}
    ],
    "secrets": [
      {"name": "TELEGRAM_BOT_TOKEN", "valueFrom": "arn:aws:ssm:$AWS_REGION:$ACCOUNT_ID:parameter/paper-trader/TELEGRAM_BOT_TOKEN"},
      {"name": "TELEGRAM_CHAT_ID", "valueFrom": "arn:aws:ssm:$AWS_REGION:$ACCOUNT_ID:parameter/paper-trader/TELEGRAM_CHAT_ID"}
    ],
    "logConfiguration": {"logDriver": "awslogs", "options": {
      "awslogs-group": "/ecs/paper-trader", "awslogs-region": "$AWS_REGION", "awslogs-stream-prefix": "run"}}
  }]
}
EOF
```

```bash
aws ecs register-task-definition --cli-input-json file:///tmp/taskdef.json
```

## 6. Networking (default VPC, outbound only)

```bash
export VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
```

```bash
export SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID Name=default-for-az,Values=true --query 'Subnets[].SubnetId' --output text | tr '\t' ',')
```

```bash
export SG_ID=$(aws ec2 create-security-group --group-name paper-trader-egress --description "paper trader: outbound only" --vpc-id $VPC_ID --query GroupId --output text)
```

The new security group has no inbound rules, and its default outbound rule allows the HTTPS calls to Delta, Telegram, S3 and SSM.

## 7. First run by hand (initialises the state)

```bash
aws ecs run-task --cluster paper-trader --launch-type FARGATE --task-definition paper-trader --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}"
```

```bash
aws logs tail /ecs/paper-trader --follow
```

A good first run prints:
- the five coins with their contract sizes;
- `processed 4h close …`;
- any entries;
- `state uploaded to s3://…`.

You should also get the entry alerts in Telegram. If the logs show Delta requests failing, Delta's public API is not reachable from AWS: stop and tell me before scheduling.

## 8. Schedule: every 4 hours, 5 minutes after the bar closes (UTC)

```bash
cat > /tmp/target.json <<EOF
{
  "Arn": "arn:aws:ecs:$AWS_REGION:$ACCOUNT_ID:cluster/paper-trader",
  "RoleArn": "arn:aws:iam::$ACCOUNT_ID:role/paperTraderSchedulerRole",
  "RetryPolicy": {"MaximumRetryAttempts": 2, "MaximumEventAgeInSeconds": 1800},
  "EcsParameters": {
    "TaskDefinitionArn": "arn:aws:ecs:$AWS_REGION:$ACCOUNT_ID:task-definition/paper-trader",
    "LaunchType": "FARGATE",
    "NetworkConfiguration": {"awsvpcConfiguration": {"Subnets": ["${SUBNETS//,/\",\"}"], "SecurityGroups": ["$SG_ID"], "AssignPublicIp": "ENABLED"}}
  }
}
EOF
```

```bash
aws scheduler create-schedule --name paper-trader-4h --schedule-expression "cron(5 0/4 * * ? *)" --schedule-expression-timezone UTC --flexible-time-window Mode=OFF --target file:///tmp/target.json
```

A retried or duplicated start is harmless: a bar that is already processed is skipped, and the conditional S3 upload rejects a stale copy.

## 9. Alarm when a run fails (recommended)

The entrypoint logs `RUN FAILED` and sends it to Telegram. To also get an email:

```bash
aws sns create-topic --name paper-trader-alarms
```

```bash
aws sns subscribe --topic-arn arn:aws:sns:$AWS_REGION:$ACCOUNT_ID:paper-trader-alarms --protocol email --notification-endpoint YOUR_EMAIL
```

```bash
aws logs put-metric-filter --log-group-name /ecs/paper-trader --filter-name run-failed --filter-pattern '"RUN FAILED"' --metric-transformations metricName=PaperRunFailed,metricNamespace=PaperTrader,metricValue=1
```

```bash
aws cloudwatch put-metric-alarm --alarm-name paper-trader-run-failed --namespace PaperTrader --metric-name PaperRunFailed --statistic Sum --period 3600 --evaluation-periods 1 --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold --treat-missing-data notBreaching --alarm-actions arn:aws:sns:$AWS_REGION:$ACCOUNT_ID:paper-trader-alarms
```

## 10. Day-to-day operations

The trader runs itself. For a manual check, start a one-off task with a different command:

```bash
aws ecs run-task --cluster paper-trader --launch-type FARGATE --task-definition paper-trader --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" --overrides '{"containerOverrides":[{"name":"paper-trader","command":["status"]}]}'
```

- **Other commands:** use `"command":["reconcile"]` (weekly report on demand) or `"command":["resume"]` (only after a written review of a pause).
- **Output:** read it with `aws logs tail /ecs/paper-trader --since 10m`.
- **Download the database for analysis** (e.g. with the `sqlite3` CLI):

```bash
aws s3 cp s3://$BUCKET/paper.db ./paper.db
```

- **Pause:** temporarily stop the schedule (open positions then wait):

```bash
aws scheduler update-schedule --name paper-trader-4h --state DISABLED --schedule-expression "cron(5 0/4 * * ? *)" --flexible-time-window Mode=OFF --target file:///tmp/target.json
```

## What this deployment must never contain

- Exchange API keys of any kind. This phase uses public data only.
- The Telegram token anywhere except SSM Parameter Store.
- Edits to `frozen_rules.md` or `paper_trading_plan.md`. A change means a new plan, a new commit and a new paper period.
