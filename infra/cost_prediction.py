#!/usr/bin/env python3
"""
AWS Cost Prediction for cmdcode platform.

This script estimates the monthly AWS bill for running the full cmdcode stack:
  - cmdcode-server    (FastAPI backend)     → ECS Fargate
  - cmdcode-frontend  (Next.js)             → ECS Fargate
  - judge0-server     (code execution API)  → EC2 (requires privileged mode)
  - judge0-worker     (sandboxed runner)    → EC2 (requires privileged mode)
  - judge0-db         (PostgreSQL)          → EC2 (co-located with judge0)
  - judge0-redis      (queue / cache)       → EC2 (co-located with judge0)
  - ECR               (container registry)
  - ALB               (Application Load Balancer)
  - CloudWatch        (logs + metrics)
  - Data Transfer     (outbound internet)
  - EBS               (EC2 root volume)

Note: judge0 requires `privileged: true` which is NOT supported on ECS Fargate.
It must run on ECS with an EC2 launch type, or directly on EC2.
All judge0 services are co-located on a single EC2 instance.

Usage:
    python infra/cost_prediction.py
    python infra/cost_prediction.py --region eu-west-1 --traffic-gb 50
    python infra/cost_prediction.py --judge0-instance c5.xlarge --help
"""

import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Pricing tables  (US dollars, us-east-1 unless noted)
# Prices reflect on-demand rates as of early 2026.
# ---------------------------------------------------------------------------

# ECS Fargate – Linux/x86-64
FARGATE_VCPU_PER_HOUR = 0.04048   # $/vCPU-hour
FARGATE_GB_PER_HOUR   = 0.004445  # $/GB-hour
HOURS_PER_MONTH       = 730       # 730 hours = 30.4 days

# EC2 on-demand instance prices (us-east-1, Linux)
EC2_INSTANCE_PRICES: dict[str, float] = {
    "t3.small":   0.0208,
    "t3.medium":  0.0416,
    "t3.large":   0.0832,
    "t3.xlarge":  0.1664,
    "c5.large":   0.0850,
    "c5.xlarge":  0.1700,
    "c5.2xlarge": 0.3400,
    "m5.large":   0.0960,
    "m5.xlarge":  0.1920,
}

# EBS gp3 storage
EBS_GP3_PER_GB_MONTH = 0.08  # $/GB-month

# ECR
ECR_STORAGE_PER_GB_MONTH = 0.10  # $/GB-month (first 500 MB free)
ECR_FREE_TIER_GB          = 0.5

# ALB
ALB_FIXED_PER_HOUR  = 0.008   # $/hour
ALB_LCU_PER_HOUR    = 0.008   # $/LCU-hour

# CloudWatch Logs
CW_INGEST_PER_GB  = 0.50   # $/GB ingested
CW_STORAGE_PER_GB = 0.03   # $/GB-month stored
CW_FREE_INGEST_GB = 5.0    # free tier: 5 GB/month ingest

# Data transfer out to internet (us-east-1)
DTX_FREE_GB  = 1.0     # first 1 GB/month free
DTX_PER_GB   = 0.09    # $/GB after free tier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fargate_monthly(vcpu: float, ram_gb: float) -> float:
    """Monthly cost for one ECS Fargate task running 24/7."""
    return (vcpu * FARGATE_VCPU_PER_HOUR + ram_gb * FARGATE_GB_PER_HOUR) * HOURS_PER_MONTH


def ec2_monthly(instance_type: str) -> float:
    if instance_type not in EC2_INSTANCE_PRICES:
        raise ValueError(
            f"Unknown instance type '{instance_type}'. "
            f"Known types: {', '.join(EC2_INSTANCE_PRICES)}"
        )
    return EC2_INSTANCE_PRICES[instance_type] * HOURS_PER_MONTH


def data_transfer_monthly(outbound_gb: float) -> float:
    billable = max(0.0, outbound_gb - DTX_FREE_GB)
    return billable * DTX_PER_GB


def ecr_monthly(image_gb: float) -> float:
    billable = max(0.0, image_gb - ECR_FREE_TIER_GB)
    return billable * ECR_STORAGE_PER_GB_MONTH


def alb_monthly(lcu_avg: float = 1.0) -> float:
    return (ALB_FIXED_PER_HOUR + lcu_avg * ALB_LCU_PER_HOUR) * HOURS_PER_MONTH


def cloudwatch_monthly(ingest_gb: float, retain_gb: float) -> float:
    billable_ingest = max(0.0, ingest_gb - CW_FREE_INGEST_GB)
    return billable_ingest * CW_INGEST_PER_GB + retain_gb * CW_STORAGE_PER_GB


def ebs_monthly(size_gb: float) -> float:
    return size_gb * EBS_GP3_PER_GB_MONTH


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

@dataclass
class CostConfig:
    # ECS Fargate – cmdcode-server
    server_vcpu:    float = 0.5
    server_ram_gb:  float = 1.0

    # ECS Fargate – cmdcode-frontend
    frontend_vcpu:   float = 0.25
    frontend_ram_gb: float = 0.5

    # EC2 instance for all judge0 services (server + worker + db + redis)
    judge0_instance: str  = "t3.medium"
    judge0_ebs_gb:   float = 20.0

    # ECR image storage (server image ~500 MB, judge0 image cached from Docker Hub)
    ecr_image_gb: float = 1.0

    # ALB: average LCU load (1 LCU ≈ 25 new connections/s or 3000 active connections/min)
    alb_lcu: float = 1.0

    # CloudWatch Logs
    cw_ingest_gb:  float = 5.0   # per month across all services
    cw_retain_gb:  float = 5.0   # retained log storage

    # Outbound data transfer (API responses, frontend assets served from ALB)
    outbound_gb: float = 10.0


@dataclass
class ServiceCost:
    name:        str
    monthly_usd: float
    notes:       str = ""


def predict(cfg: CostConfig) -> list[ServiceCost]:
    services: list[ServiceCost] = []

    # --- ECS Fargate: cmdcode-server ---
    cost = fargate_monthly(cfg.server_vcpu, cfg.server_ram_gb)
    services.append(ServiceCost(
        name="ECS Fargate – cmdcode-server",
        monthly_usd=cost,
        notes=f"{cfg.server_vcpu} vCPU · {cfg.server_ram_gb} GB RAM · 24/7",
    ))

    # --- ECS Fargate: cmdcode-frontend ---
    cost = fargate_monthly(cfg.frontend_vcpu, cfg.frontend_ram_gb)
    services.append(ServiceCost(
        name="ECS Fargate – cmdcode-frontend",
        monthly_usd=cost,
        notes=f"{cfg.frontend_vcpu} vCPU · {cfg.frontend_ram_gb} GB RAM · 24/7",
    ))

    # --- EC2: judge0 stack (server + worker + db + redis) ---
    cost = ec2_monthly(cfg.judge0_instance)
    services.append(ServiceCost(
        name=f"EC2 ({cfg.judge0_instance}) – judge0 stack",
        monthly_usd=cost,
        notes="judge0-server, judge0-worker, PostgreSQL, Redis (privileged mode)",
    ))

    # --- EBS: judge0 EC2 root + data volume ---
    cost = ebs_monthly(cfg.judge0_ebs_gb)
    services.append(ServiceCost(
        name="EBS gp3 – judge0 EC2 volume",
        monthly_usd=cost,
        notes=f"{cfg.judge0_ebs_gb} GB gp3 @ ${EBS_GP3_PER_GB_MONTH}/GB-month",
    ))

    # --- ECR ---
    cost = ecr_monthly(cfg.ecr_image_gb)
    services.append(ServiceCost(
        name="ECR – container image storage",
        monthly_usd=cost,
        notes=f"{cfg.ecr_image_gb} GB stored (first 0.5 GB free)",
    ))

    # --- ALB ---
    cost = alb_monthly(cfg.alb_lcu)
    services.append(ServiceCost(
        name="Application Load Balancer",
        monthly_usd=cost,
        notes=f"Fixed + {cfg.alb_lcu} avg LCU",
    ))

    # --- CloudWatch ---
    cost = cloudwatch_monthly(cfg.cw_ingest_gb, cfg.cw_retain_gb)
    services.append(ServiceCost(
        name="CloudWatch Logs",
        monthly_usd=cost,
        notes=f"{cfg.cw_ingest_gb} GB/month ingested · {cfg.cw_retain_gb} GB retained",
    ))

    # --- Data Transfer ---
    cost = data_transfer_monthly(cfg.outbound_gb)
    services.append(ServiceCost(
        name="Data Transfer Out",
        monthly_usd=cost,
        notes=f"{cfg.outbound_gb} GB outbound (first 1 GB free)",
    ))

    return services


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

COL_W = 45

def print_report(cfg: CostConfig, services: list[ServiceCost]) -> None:
    total = sum(s.monthly_usd for s in services)
    border = "=" * 80

    print()
    print(border)
    print("  cmdcode – AWS Monthly Cost Prediction  (region: us-east-1, on-demand)")
    print(border)
    print()

    header = f"  {'Service':<{COL_W}} {'$/month':>10}   Notes"
    print(header)
    print("  " + "-" * 76)

    for svc in services:
        cost_str = f"${svc.monthly_usd:>8.2f}"
        line = f"  {svc.name:<{COL_W}} {cost_str:>10}"
        if svc.notes:
            line += f"   {svc.notes}"
        print(line)

    print("  " + "-" * 76)
    print(f"  {'TOTAL ESTIMATED MONTHLY COST':<{COL_W}} ${total:>8.2f}")
    print()
    print(border)

    print()
    print("  ASSUMPTIONS")
    print("  " + "-" * 76)
    assumptions = [
        "All services run 24/7 (730 hours/month).",
        "judge0 uses EC2 because Fargate does not support privileged containers.",
        f"judge0 instance: {cfg.judge0_instance} (runs server + worker + PostgreSQL + Redis).",
        "Prices are on-demand; Reserved Instances can cut EC2/Fargate costs ~30–40%.",
        "ECR data transfer within the same AWS region is free.",
        "ALB LCU estimate assumes light traffic (<25 new connections/second).",
        "CloudWatch Logs free tier: 5 GB/month ingestion, 5 GB storage/month.",
        f"Outbound data transfer: {cfg.outbound_gb} GB/month assumed.",
        "Does not include Route53 ($0.50/hosted zone), ACM (free), VPC NAT Gateway",
        "  (if used: ~$32/month + $0.045/GB), or Secrets Manager ($0.40/secret).",
        "GitHub Actions CI/CD runs on GitHub-hosted runners (billed by GitHub, not AWS).",
    ]
    for note in assumptions:
        print(f"  • {note}")
    print()

    print("  COST OPTIMISATION TIPS")
    print("  " + "-" * 76)
    tips = [
        "Use ECS Fargate Spot for the frontend (up to 70% savings; stateless).",
        "Use EC2 Savings Plan or Reserved Instance for the judge0 host.",
        "Enable ECR image tag immutability + lifecycle policy to auto-delete old images.",
        "Add a CloudFront distribution in front of ALB to reduce data transfer costs.",
        "Set CloudWatch log retention to 7–30 days instead of indefinite.",
        "Use Graviton (arm64) Fargate tasks for ~20% cheaper compute.",
    ]
    for tip in tips:
        print(f"  • {tip}")
    print()
    print(border)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> CostConfig:
    parser = argparse.ArgumentParser(
        description="Predict monthly AWS cost for the cmdcode platform.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    defaults = CostConfig()

    parser.add_argument("--server-vcpu",      type=float, default=defaults.server_vcpu,
                        help="vCPU for cmdcode-server Fargate task")
    parser.add_argument("--server-ram",       type=float, default=defaults.server_ram_gb,
                        help="RAM (GB) for cmdcode-server Fargate task")
    parser.add_argument("--frontend-vcpu",    type=float, default=defaults.frontend_vcpu,
                        help="vCPU for cmdcode-frontend Fargate task")
    parser.add_argument("--frontend-ram",     type=float, default=defaults.frontend_ram_gb,
                        help="RAM (GB) for cmdcode-frontend Fargate task")
    parser.add_argument("--judge0-instance",  type=str,   default=defaults.judge0_instance,
                        help=f"EC2 instance for judge0 stack. Options: {', '.join(EC2_INSTANCE_PRICES)}")
    parser.add_argument("--judge0-ebs-gb",    type=float, default=defaults.judge0_ebs_gb,
                        help="EBS gp3 volume size (GB) for judge0 EC2 instance")
    parser.add_argument("--ecr-gb",           type=float, default=defaults.ecr_image_gb,
                        help="Total ECR image storage (GB)")
    parser.add_argument("--alb-lcu",          type=float, default=defaults.alb_lcu,
                        help="Average ALB LCU load")
    parser.add_argument("--logs-ingest-gb",   type=float, default=defaults.cw_ingest_gb,
                        help="CloudWatch Logs ingestion per month (GB)")
    parser.add_argument("--logs-retain-gb",   type=float, default=defaults.cw_retain_gb,
                        help="CloudWatch Logs retained storage (GB)")
    parser.add_argument("--traffic-gb",       type=float, default=defaults.outbound_gb,
                        help="Estimated outbound data transfer per month (GB)")

    args = parser.parse_args()

    return CostConfig(
        server_vcpu     = args.server_vcpu,
        server_ram_gb   = args.server_ram,
        frontend_vcpu   = args.frontend_vcpu,
        frontend_ram_gb = args.frontend_ram,
        judge0_instance = args.judge0_instance,
        judge0_ebs_gb   = args.judge0_ebs_gb,
        ecr_image_gb    = args.ecr_gb,
        alb_lcu         = args.alb_lcu,
        cw_ingest_gb    = args.logs_ingest_gb,
        cw_retain_gb    = args.logs_retain_gb,
        outbound_gb     = args.traffic_gb,
    )


def main() -> None:
    cfg = parse_args()
    try:
        services = predict(cfg)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print_report(cfg, services)


if __name__ == "__main__":
    main()
