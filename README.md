# k8s-cost-radar

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)

A Kubernetes resource & cost analysis CLI tool for SREs and FinOps teams. Scan your cluster, detect waste, estimate costs, and get actionable recommendations — all from your terminal.

**Author:** Dipo Oginni ([https://dipops.com](https://dipops.com))

## What It Does

k8s-cost-radar helps you answer critical questions about your Kubernetes cluster:

- **How much is my cluster costing me per month?** Get instant cost estimates based on resource requests
- **Where is my money going?** See cost breakdown by namespace
- **Am I wasting resources?** Detect over-provisioned pods, missing resource requests, and unhealthy workloads
- **What should I fix first?** Get prioritized, actionable recommendations

### Key Features

- **Cluster Scanning** — Connects to your current kubeconfig context and analyzes all pods
- **Waste Detection** — Identifies:
  - Pods with no resource requests (dangerous for scheduling)
  - Over-provisioned CPU/memory (requests far below limits)
  - High resource requests that may be excessive
  - Pods in unhealthy states (Pending, CrashLoopBackOff, etc.)
- **Cost Estimation** — Rough monthly cost estimates using configurable AWS pricing
  - Default: $0.048/vCPU-hour, $0.006/GB-hour (roughly m5.xlarge equivalents)
- **Multiple Output Formats** — Table (pretty terminal output), JSON, or Markdown
- **Demo Mode** — Try it without a cluster using realistic mock data
- **Actionable Recommendations** — Get specific suggestions for each issue found

## Installation

```bash
# Clone the repository
git clone https://github.com/dipops/k8s-cost-radar.git
cd k8s-cost-radar

# Install dependencies
pip install -r requirements.txt

# Or use make
make install
```

## Quick Start

### Try Demo Mode (No Cluster Required)

Perfect for testing or demos:

```bash
python k8s_cost_radar.py demo

# Or with make
make demo
```

### Scan Your Real Cluster

Make sure your kubeconfig is set up:

```bash
# Scan entire cluster
python k8s_cost_radar.py scan

# Scan specific namespace
python k8s_cost_radar.py scan --namespace production

# Get JSON output
python k8s_cost_radar.py scan --output json

# Custom pricing (e.g., for different cloud/region)
python k8s_cost_radar.py scan --cpu-price 0.06 --mem-price 0.008
```

## Usage Examples

### 1. Full Cluster Scan

```bash
python k8s_cost_radar.py scan
```

**Output:**
```
╭─────────────────────── Cluster Overview ───────────────────────╮
│ Total Pods: 47                                                 │
│ Namespaces: 8                                                  │
│ Total CPU Requests: 23.4 cores                                 │
│ Total Memory Requests: 45.2 GB                                 │
│ Estimated Monthly Cost: $1,089.50                              │
│ Potential Savings: $243.20                                     │
│ Total Issues Found: 18                                         │
╰────────────────────────────────────────────────────────────────╯

                    Namespace Cost Summary
╭──────────────┬──────┬──────────────┬──────────────┬───────────╮
│ Namespace    │ Pods │ CPU (cores)  │ Memory (GB)  │ Monthly   │
│              │      │              │              │ Cost      │
├──────────────┼──────┼──────────────┼──────────────┼───────────┤
│ production   │ 15   │ 8.50         │ 16.4         │ $385.20   │
│ staging      │ 12   │ 6.20         │ 12.1         │ $298.40   │
│ monitoring   │ 8    │ 4.30         │ 8.5          │ $189.60   │
│ kube-system  │ 6    │ 2.10         │ 4.8          │ $108.50   │
│ development  │ 6    │ 2.30         │ 3.4          │ $107.80   │
╰──────────────┴──────┴──────────────┴──────────────┴───────────╯
```

### 2. Show Only Wasteful Workloads

```bash
python k8s_cost_radar.py wasteful
```

**Output:**
```
                Wasteful/Problematic Pods (12 found)
╭───────────┬─────────────────┬──────────────────────────────────╮
│ Namespace │ Pod             │ Issues                           │
├───────────┼─────────────────┼──────────────────────────────────┤
│ staging   │ worker-4521     │ • No resource requests set       │
│           │                 │ • Pod in unhealthy state         │
│ production│ api-7834        │ • CPU limit 8.0x higher than req │
│           │                 │ • High CPU request: 3.50 cores   │
│ dev       │ cache-2341      │ • Memory limit 6.2x higher       │
╰───────────┴─────────────────┴──────────────────────────────────╯
```

### 3. High-Level Summary

```bash
python k8s_cost_radar.py summary
```

### 4. Export to Markdown Report

```bash
python k8s_cost_radar.py scan --output md > cluster-report.md
```

### 5. Export to JSON for Further Processing

```bash
python k8s_cost_radar.py scan --output json > cluster-data.json
```

## Commands

| Command | Description |
|---------|-------------|
| `scan` | Scan cluster and analyze resource usage & costs |
| `summary` | Show high-level cluster cost overview |
| `wasteful` | Show only wasteful/problematic workloads |
| `demo` | Run with mock data (no cluster required) |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--namespace` | `all` | Namespace to scan (or `all` for entire cluster) |
| `--output` | `table` | Output format: `table`, `json`, or `md` |
| `--cpu-price` | `0.048` | CPU price per vCPU-hour (USD) |
| `--mem-price` | `0.006` | Memory price per GB-hour (USD) |

## Configuration

### Pricing

Default pricing is based on AWS on-demand m5.xlarge equivalents:
- **CPU:** $0.048 per vCPU-hour
- **Memory:** $0.006 per GB-hour

Adjust for your cloud provider and region:

```bash
# GCP pricing example
python k8s_cost_radar.py scan --cpu-price 0.052 --mem-price 0.007

# Azure pricing example
python k8s_cost_radar.py scan --cpu-price 0.050 --mem-price 0.0065
```

## What Gets Detected

### Resource Issues
- No CPU/memory requests set
- CPU limit significantly higher than request (4x+)
- Memory limit significantly higher than request (4x+)
- High absolute resource requests (CPU ≥ 2 cores, Memory ≥ 8GB)

### Pod Health Issues
- Pods in Pending state
- Pods in CrashLoopBackOff
- Pods in Error/Failed state

### Recommendations
For each issue, you'll get specific, actionable recommendations:
- "Set CPU request (start with 100m-500m depending on workload)"
- "Consider reducing CPU request from 2.00 to 1.00 cores"
- "Investigate and fix pod in CrashLoopBackOff state"
- "Review if workload actually needs this much CPU"

## Development

### Makefile Commands

```bash
make install    # Install dependencies
make demo       # Run demo mode
make lint       # Run linting (requires flake8, pylint)
```

## Use Cases

- **Cost Optimization** — Identify over-provisioned workloads before they impact your budget
- **Resource Planning** — Understand current resource usage patterns
- **Health Monitoring** — Detect pods in unhealthy states
- **FinOps Reporting** — Generate cost reports for stakeholders
- **CI/CD Integration** — Run in pipelines to catch resource issues early
- **Cluster Audits** — Regular scans to maintain cluster health

## Limitations

- Cost estimates are based on resource **requests**, not actual usage (requires metrics-server for real usage)
- Pricing is configurable but uses simplified hourly rates (doesn't account for reserved instances, spot, etc.)
- Waste detection uses heuristics and thresholds (may need tuning for your workloads)
- Does not account for storage, network, or other cloud costs

## Contributing

This is a weekend fun project! PRs welcome for:
- Additional waste detection heuristics
- Integration with metrics-server for actual usage data
- Support for more cloud provider pricing models
- Export to additional formats (CSV, HTML, etc.)

## License

MIT License — see LICENSE file for details

## Author

**Dipo Oginni**
[https://dipops.com](https://dipops.com)

---

**Built with:** Python, Click, Rich, Kubernetes Python Client
