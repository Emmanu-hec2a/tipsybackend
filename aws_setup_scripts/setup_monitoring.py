#!/usr/bin/env python3
"""
CloudWatch Monitoring & Alerts Setup for TipsyTheoryy Payment Processing

Sets up comprehensive monitoring for Phase 1 critical fixes:
1. Certificate Pinning monitoring
2. Phone validation rate limiting
3. AWS Secrets Manager access logging
4. Admin audit logging
5. Payment flow metrics

Usage:
    python setup_monitoring.py --environment staging --email admin@tipsytheoryy.com
    python setup_monitoring.py --environment production --sns-topic-arn arn:aws:sns:us-east-1:...

Author: TipsyTheoryy DevOps
Date: 2026-08-24
"""

import argparse
import json
import sys
from typing import List, Dict, Any
import boto3
from botocore.exceptions import ClientError


class MonitoringSetup:
    """Sets up CloudWatch monitoring for payment security"""

    def __init__(self, environment: str, region: str = "us-east-1"):
        self.environment = environment
        self.region = region
        self.cloudwatch_client = boto3.client("cloudwatch", region_name=region)
        self.sns_client = boto3.client("sns", region_name=region)
        self.logs_client = boto3.client("logs", region_name=region)
        
        self.namespace = "TipsyTheoryy/Payment"
        self.log_group_prefix = f"/tipsytheoryy/payment/{environment}"

    def create_log_groups(self) -> Dict[str, str]:
        """Create CloudWatch Log Groups for monitoring"""
        print(f"\n[1/4] Creating Log Groups")
        
        log_groups = {
            "certificate_pinning": f"{self.log_group_prefix}/certificate-pinning",
            "phone_validation": f"{self.log_group_prefix}/phone-validation",
            "audit_logging": f"{self.log_group_prefix}/audit-logging",
            "secrets_manager": f"{self.log_group_prefix}/secrets-manager",
            "payment_flow": f"{self.log_group_prefix}/payment-flow",
        }
        
        for group_name, log_group_path in log_groups.items():
            try:
                self.logs_client.create_log_group(logGroupName=log_group_path)
                print(f"  ✓ Created log group: {log_group_path}")
            except ClientError as e:
                if "ResourceAlreadyExistsException" in str(e):
                    print(f"  ℹ Log group already exists: {log_group_path}")
                else:
                    print(f"  ✗ Failed to create log group: {e}")
            
            # Set retention policy (30 days)
            try:
                self.logs_client.put_retention_policy(
                    logGroupName=log_group_path,
                    retentionInDays=30
                )
                print(f"    → Set retention: 30 days")
            except ClientError as e:
                print(f"    ⚠ Failed to set retention: {e}")
        
        return log_groups

    def create_dashboards(self) -> Dict[str, str]:
        """Create CloudWatch Dashboards"""
        print(f"\n[2/4] Creating CloudWatch Dashboards")
        
        dashboards = {}
        
        # 1. Payment Health Dashboard
        dashboard_body = {
            "widgets": [
                {
                    "type": "metric",
                    "properties": {
                        "metrics": [
                            [self.namespace, "CertificatePinningFailures", {"stat": "Sum"}],
                            [".", "PhoneValidationFailures", {"stat": "Sum"}],
                            [".", "RateLimitExceeded", {"stat": "Sum"}],
                            [".", "PaymentInitiationErrors", {"stat": "Sum"}],
                            [".", "PaymentSuccessRate", {"stat": "Average"}],
                        ],
                        "period": 300,
                        "stat": "Sum",
                        "region": self.region,
                        "title": "Payment Security Metrics"
                    }
                },
                {
                    "type": "metric",
                    "properties": {
                        "metrics": [
                            [self.namespace, "AuditLogEntries", {"stat": "Sum"}],
                            [".", "AdminActionCount", {"stat": "Sum"}],
                            [".", "ManualReviewCount", {"stat": "Sum"}],
                        ],
                        "period": 300,
                        "stat": "Sum",
                        "region": self.region,
                        "title": "Admin Audit Activity"
                    }
                },
                {
                    "type": "log",
                    "properties": {
                        "query": f"""
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() by bin(5m)
                        """,
                        "region": self.region,
                        "title": "Error Rate (5m bins)"
                    }
                },
            ]
        }
        
        try:
            self.cloudwatch_client.put_dashboard(
                DashboardName=f"TipsyTheoryy-Payment-Health-{self.environment}",
                DashboardBody=json.dumps(dashboard_body)
            )
            print(f"  ✓ Dashboard created: TipsyTheoryy-Payment-Health-{self.environment}")
            dashboards["health"] = f"TipsyTheoryy-Payment-Health-{self.environment}"
        except ClientError as e:
            print(f"  ✗ Failed to create dashboard: {e}")
        
        return dashboards

    def create_alarms(self, sns_topic_arn: str) -> List[str]:
        """Create CloudWatch Alarms for critical metrics"""
        print(f"\n[3/4] Creating CloudWatch Alarms")
        
        alarms = []
        
        # Alarm 1: Certificate Pinning Failures
        try:
            self.cloudwatch_client.put_metric_alarm(
                AlarmName=f"TipsyTheoryy-CertificatePinningFailure-{self.environment}",
                ComparisonOperator="GreaterThanOrEqualToThreshold",
                EvaluationPeriods=1,
                MetricName="CertificatePinningFailures",
                Namespace=self.namespace,
                Period=300,
                Statistic="Sum",
                Threshold=1.0,
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                AlarmDescription="Alert when certificate pinning fails on M-Pesa API calls",
                TreatMissingData="notBreaching"
            )
            print(f"  ✓ Created alarm: CertificatePinningFailure")
            alarms.append("CertificatePinningFailure")
        except ClientError as e:
            print(f"  ✗ Failed to create alarm: {e}")
        
        # Alarm 2: Phone Validation Rate Limit Abuse
        try:
            self.cloudwatch_client.put_metric_alarm(
                AlarmName=f"TipsyTheoryy-RateLimitAbuse-{self.environment}",
                ComparisonOperator="GreaterThanOrEqualToThreshold",
                EvaluationPeriods=1,
                MetricName="RateLimitExceeded",
                Namespace=self.namespace,
                Period=300,
                Statistic="Sum",
                Threshold=10.0,
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                AlarmDescription="Alert when 10+ rate limit violations in 5 minutes (potential attack)",
                TreatMissingData="notBreaching"
            )
            print(f"  ✓ Created alarm: RateLimitAbuse")
            alarms.append("RateLimitAbuse")
        except ClientError as e:
            print(f"  ✗ Failed to create alarm: {e}")
        
        # Alarm 3: Query Parameter JWT Attempts
        try:
            self.cloudwatch_client.put_metric_alarm(
                AlarmName=f"TipsyTheoryy-SecurityViolation-{self.environment}",
                ComparisonOperator="GreaterThanOrEqualToThreshold",
                EvaluationPeriods=1,
                MetricName="QueryParamJWTAttempts",
                Namespace=self.namespace,
                Period=300,
                Statistic="Sum",
                Threshold=5.0,
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                AlarmDescription="Alert when 5+ query parameter JWT auth attempts (old clients or attack)",
                TreatMissingData="notBreaching"
            )
            print(f"  ✓ Created alarm: SecurityViolation")
            alarms.append("SecurityViolation")
        except ClientError as e:
            print(f"  ✗ Failed to create alarm: {e}")
        
        # Alarm 4: Admin Audit Log Activity
        try:
            self.cloudwatch_client.put_metric_alarm(
                AlarmName=f"TipsyTheoryy-UnusualAdminActivity-{self.environment}",
                ComparisonOperator="GreaterThanThreshold",
                EvaluationPeriods=1,
                MetricName="AdminActionCount",
                Namespace=self.namespace,
                Period=3600,
                Statistic="Sum",
                Threshold=20.0,
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                AlarmDescription="Alert when 20+ admin actions in 1 hour (unusual activity)",
                TreatMissingData="notBreaching"
            )
            print(f"  ✓ Created alarm: UnusualAdminActivity")
            alarms.append("UnusualAdminActivity")
        except ClientError as e:
            print(f"  ✗ Failed to create alarm: {e}")
        
        # Alarm 5: Secrets Manager Errors
        try:
            self.cloudwatch_client.put_metric_alarm(
                AlarmName=f"TipsyTheoryy-SecretsManagerError-{self.environment}",
                ComparisonOperator="GreaterThanOrEqualToThreshold",
                EvaluationPeriods=1,
                MetricName="SecretsManagerErrors",
                Namespace=self.namespace,
                Period=300,
                Statistic="Sum",
                Threshold=1.0,
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                AlarmDescription="Alert when credential retrieval from Secrets Manager fails",
                TreatMissingData="notBreaching"
            )
            print(f"  ✓ Created alarm: SecretsManagerError")
            alarms.append("SecretsManagerError")
        except ClientError as e:
            print(f"  ✗ Failed to create alarm: {e}")
        
        # Alarm 6: Payment Success Rate Drop
        try:
            self.cloudwatch_client.put_metric_alarm(
                AlarmName=f"TipsyTheoryy-PaymentSuccessRateDrop-{self.environment}",
                ComparisonOperator="LessThanThreshold",
                EvaluationPeriods=2,
                MetricName="PaymentSuccessRate",
                Namespace=self.namespace,
                Period=600,
                Statistic="Average",
                Threshold=90.0,
                ActionsEnabled=True,
                AlarmActions=[sns_topic_arn],
                AlarmDescription="Alert when payment success rate drops below 90%",
                TreatMissingData="notBreaching"
            )
            print(f"  ✓ Created alarm: PaymentSuccessRateDrop")
            alarms.append("PaymentSuccessRateDrop")
        except ClientError as e:
            print(f"  ✗ Failed to create alarm: {e}")
        
        return alarms

    def create_log_filters(self, sns_topic_arn: str):
        """Create metric filters from logs"""
        print(f"\n[4/4] Creating Log-based Metric Filters")
        
        filters = [
            {
                "name": "CertificatePinningFailures",
                "pattern": "[... SSL, Certificate, Pinning, Failure ...]",
                "log_group": f"{self.log_group_prefix}/certificate-pinning"
            },
            {
                "name": "PhoneValidationFailures",
                "pattern": "[... ERROR, phone_validation, Invalid ...]",
                "log_group": f"{self.log_group_prefix}/phone-validation"
            },
            {
                "name": "RateLimitExceeded",
                "pattern": "[... STK, rate, limit, exceeded ...]",
                "log_group": f"{self.log_group_prefix}/phone-validation"
            },
            {
                "name": "QueryParamJWTAttempts",
                "pattern": "[... SECURITY, VIOLATION, Query, parameter, JWT ...]",
                "log_group": f"{self.log_group_prefix}/payment-flow"
            },
            {
                "name": "SecretsManagerErrors",
                "pattern": "[... ERROR, Secrets Manager, Failed ...]",
                "log_group": f"{self.log_group_prefix}/secrets-manager"
            },
            {
                "name": "AdminActionCount",
                "pattern": "[... PaymentAuditLog, action ...]",
                "log_group": f"{self.log_group_prefix}/audit-logging"
            },
        ]
        
        for filter_config in filters:
            try:
                self.logs_client.put_metric_filter(
                    logGroupName=filter_config["log_group"],
                    filterName=filter_config["name"],
                    filterPattern=filter_config["pattern"],
                    metricTransformations=[
                        {
                            "metricName": filter_config["name"],
                            "metricNamespace": self.namespace,
                            "metricValue": "1",
                            "defaultValue": 0
                        }
                    ]
                )
                print(f"  ✓ Metric filter created: {filter_config['name']}")
            except ClientError as e:
                if "ResourceAlreadyExistsException" in str(e):
                    print(f"  ℹ Metric filter already exists: {filter_config['name']}")
                else:
                    print(f"  ✗ Failed to create metric filter: {e}")

    def create_sns_topic(self, email: str = None, topic_arn: str = None) -> str:
        """Create or verify SNS topic for alerts"""
        if topic_arn:
            print(f"\n  ℹ Using provided SNS topic: {topic_arn}")
            return topic_arn
        
        print(f"\n  Creating SNS topic for alerts...")
        
        topic_name = f"TipsyTheoryy-Payment-Alerts-{self.environment}"
        
        try:
            response = self.sns_client.create_topic(Name=topic_name)
            topic_arn = response["TopicArn"]
            print(f"  ✓ SNS topic created: {topic_arn}")
            
            if email:
                self.sns_client.subscribe(
                    TopicArn=topic_arn,
                    Protocol="email",
                    Endpoint=email
                )
                print(f"  ✓ Subscribed {email} to alerts")
                print(f"    → Check email for SNS confirmation")
            
            return topic_arn
        except ClientError as e:
            if "TopicLimitExceeded" in str(e):
                print(f"  ℹ SNS topic already exists")
                response = self.sns_client.list_topics()
                for topic in response["Topics"]:
                    if topic_name in topic["TopicArn"]:
                        return topic["TopicArn"]
            print(f"  ✗ Failed to create SNS topic: {e}")
            return None

    def generate_monitoring_docs(self, dashboards: Dict, alarms: List, log_groups: Dict):
        """Generate monitoring documentation"""
        docs = f"""
# CloudWatch Monitoring Setup - TipsyTheoryy Payment Processing

## Environment: {self.environment}
## Region: {self.region}

### Dashboards
Dashboard Name: {list(dashboards.values())[0] if dashboards else 'N/A'}
Access URL: https://console.aws.amazon.com/cloudwatch/home?region={self.region}

### Active Alarms
{chr(10).join(f"- {alarm}" for alarm in alarms)}

### Log Groups
{chr(10).join(f"- {log_group}" for log_group in log_groups.values())}

### Key Metrics to Monitor
1. **Certificate Pinning**
   - Metric: CertificatePinningFailures
   - Alert Threshold: >= 1 failure per 5 minutes
   - Action: Immediate escalation (potential MITM attack)

2. **Phone Validation & Rate Limiting**
   - Metric: RateLimitExceeded
   - Alert Threshold: >= 10 violations per 5 minutes
   - Action: Investigate for brute force attack

3. **Security Violations**
   - Metric: QueryParamJWTAttempts
   - Alert Threshold: >= 5 attempts per 5 minutes
   - Action: Check for old mobile app clients

4. **Admin Audit Activity**
   - Metric: AdminActionCount
   - Alert Threshold: >= 20 actions per hour
   - Action: Review admin activity log

5. **Secrets Manager**
   - Metric: SecretsManagerErrors
   - Alert Threshold: >= 1 error per 5 minutes
   - Action: Check AWS Secrets Manager connectivity

6. **Payment Success Rate**
   - Metric: PaymentSuccessRate
   - Alert Threshold: < 90% average
   - Action: Investigate payment processing issues

### Daily Review Checklist
- [ ] Review CloudWatch dashboard for anomalies
- [ ] Check alert history for any triggered alarms
- [ ] Verify audit log entries for suspicious admin activity
- [ ] Monitor certificate pinning health
- [ ] Review rate limiting statistics

### Monthly Review
- [ ] Export metrics for compliance report
- [ ] Verify retention policies (30 days minimum)
- [ ] Test alert delivery (SNS)
- [ ] Update thresholds based on traffic patterns
"""
        return docs

    def run_setup(self, email: str = None, sns_topic_arn: str = None) -> bool:
        """Execute full monitoring setup"""
        print(f"\n{'='*70}")
        print(f"TipsyTheoryy Payment Processing - Monitoring Setup")
        print(f"Environment: {self.environment}")
        print(f"Region: {self.region}")
        print(f"{'='*70}")
        
        try:
            # 1. Create log groups
            log_groups = self.create_log_groups()
            
            # 2. Create SNS topic
            topic_arn = self.create_sns_topic(email, sns_topic_arn)
            if not topic_arn:
                print(f"✗ Failed to create SNS topic. Alarms will not be configured.")
                return False
            
            # 3. Create dashboards
            dashboards = self.create_dashboards()
            
            # 4. Create alarms
            alarms = self.create_alarms(topic_arn)
            
            # 5. Create log filters
            self.create_log_filters(topic_arn)
            
            # 6. Generate documentation
            docs = self.generate_monitoring_docs(dashboards, alarms, log_groups)
            
            print(f"\n{'='*70}")
            print(f"✓ Monitoring Setup Complete!")
            print(f"{'='*70}")
            print(docs)
            
            return True
        except Exception as e:
            print(f"\n✗ Setup failed: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Set up CloudWatch monitoring and alerts for TipsyTheoryy payment processing"
    )
    parser.add_argument(
        "--environment",
        required=True,
        choices=["staging", "production"],
        help="Deployment environment"
    )
    parser.add_argument(
        "--email",
        help="Email for alert notifications"
    )
    parser.add_argument(
        "--sns-topic-arn",
        help="Existing SNS topic ARN for alerts"
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region"
    )
    
    args = parser.parse_args()
    
    setup = MonitoringSetup(
        environment=args.environment,
        region=args.region
    )
    
    success = setup.run_setup(
        email=args.email,
        sns_topic_arn=args.sns_topic_arn
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
