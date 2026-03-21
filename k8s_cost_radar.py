#!/usr/bin/env python3
"""
k8s-cost-radar: Kubernetes resource & cost analysis CLI tool
Author: Dipo Oginni (https://dipops.com)
"""

import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import random

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

try:
    from kubernetes import client, config
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False


@dataclass
class PodResourceInfo:
    """Pod resource and cost information."""
    namespace: str
    name: str
    status: str
    cpu_request: float  # vCPU cores
    cpu_limit: Optional[float]
    memory_request: float  # GB
    memory_limit: Optional[float]
    monthly_cost: float
    issues: List[str]
    recommendations: List[str]


@dataclass
class NamespaceSummary:
    """Namespace-level summary."""
    namespace: str
    pod_count: int
    total_cpu_request: float
    total_memory_request: float
    monthly_cost: float
    potential_savings: float
    issue_count: int


@dataclass
class ClusterSummary:
    """Cluster-wide summary."""
    total_namespaces: int
    total_pods: int
    total_cpu_request: float
    total_memory_request: float
    monthly_cost: float
    potential_savings: float
    total_issues: int


console = Console()


def parse_resource_value(value: str, resource_type: str) -> float:
    """Parse Kubernetes resource values (e.g., '100m', '1Gi') to standard units."""
    if not value:
        return 0.0

    if resource_type == "cpu":
        # Convert to vCPU cores
        if value.endswith("m"):
            return float(value[:-1]) / 1000.0
        return float(value)

    elif resource_type == "memory":
        # Convert to GB
        if value.endswith("Ki"):
            return float(value[:-2]) / (1024 ** 2)
        elif value.endswith("Mi"):
            return float(value[:-2]) / 1024
        elif value.endswith("Gi"):
            return float(value[:-2])
        elif value.endswith("Ti"):
            return float(value[:-2]) * 1024
        # Assume bytes if no suffix
        return float(value) / (1024 ** 3)

    return 0.0


def calculate_monthly_cost(cpu_cores: float, memory_gb: float, cpu_price: float, mem_price: float) -> float:
    """Calculate estimated monthly cost."""
    hours_per_month = 730  # Average hours per month
    cpu_cost = cpu_cores * cpu_price * hours_per_month
    mem_cost = memory_gb * mem_price * hours_per_month
    return cpu_cost + mem_cost


def detect_waste_and_recommendations(
    pod_info: PodResourceInfo,
    cpu_waste_threshold: float = 0.5,
    mem_waste_threshold: float = 0.5
) -> Tuple[List[str], List[str], float]:
    """
    Detect waste and generate recommendations.

    Returns: (issues, recommendations, potential_savings)
    """
    issues = []
    recommendations = []
    potential_savings = 0.0

    # Check pod status
    if pod_info.status in ["Pending", "Error", "CrashLoopBackOff", "Failed"]:
        issues.append(f"Pod in unhealthy state: {pod_info.status}")
        recommendations.append(f"Investigate and fix pod in {pod_info.status} state")

    # No resource requests
    if pod_info.cpu_request == 0.0 and pod_info.memory_request == 0.0:
        issues.append("No resource requests set")
        recommendations.append("Set resource requests to enable proper scheduling and cost tracking")
        return issues, recommendations, potential_savings

    if pod_info.cpu_request == 0.0:
        issues.append("No CPU request set")
        recommendations.append("Set CPU request (start with 100m-500m depending on workload)")

    if pod_info.memory_request == 0.0:
        issues.append("No memory request set")
        recommendations.append("Set memory request (start with 128Mi-512Mi depending on workload)")

    # CPU waste detection (limit >> request suggests over-provisioning)
    if pod_info.cpu_request > 0 and pod_info.cpu_limit:
        limit_to_request_ratio = pod_info.cpu_limit / pod_info.cpu_request
        if limit_to_request_ratio > 4.0:
            issues.append(f"CPU limit {limit_to_request_ratio:.1f}x higher than request")
            recommendations.append(f"Consider reducing CPU request from {pod_info.cpu_request:.2f} to {pod_info.cpu_request * 0.5:.2f} cores")
            # Estimate 50% savings on CPU
            potential_savings += pod_info.monthly_cost * 0.25  # Rough estimate

    # High CPU request (potential over-provisioning)
    if pod_info.cpu_request >= 2.0:
        issues.append(f"High CPU request: {pod_info.cpu_request:.2f} cores")
        recommendations.append("Review if workload actually needs this much CPU")

    # Memory waste detection
    if pod_info.memory_request > 0 and pod_info.memory_limit:
        limit_to_request_ratio = pod_info.memory_limit / pod_info.memory_request
        if limit_to_request_ratio > 4.0:
            issues.append(f"Memory limit {limit_to_request_ratio:.1f}x higher than request")
            recommendations.append(f"Consider aligning memory limit closer to request or review actual usage")

    # High memory request (potential over-provisioning)
    if pod_info.memory_request >= 8.0:
        issues.append(f"High memory request: {pod_info.memory_request:.1f}GB")
        recommendations.append("Review if workload actually needs this much memory")

    return issues, recommendations, potential_savings


def scan_kubernetes_cluster(cpu_price: float, mem_price: float, namespace_filter: str = "all") -> List[PodResourceInfo]:
    """Scan real Kubernetes cluster."""
    if not KUBERNETES_AVAILABLE:
        console.print("[red]kubernetes library not installed. Use 'demo' mode or install requirements.[/red]")
        raise click.Abort()

    try:
        config.load_kube_config()
    except Exception as e:
        console.print(f"[red]Error loading kubeconfig: {e}[/red]")
        console.print("[yellow]Tip: Try 'k8s-cost-radar demo' to see a demo without a real cluster[/yellow]")
        raise click.Abort()

    v1 = client.CoreV1Api()
    pods_data = []

    try:
        if namespace_filter == "all":
            pods = v1.list_pod_for_all_namespaces(watch=False)
        else:
            pods = v1.list_namespaced_pod(namespace=namespace_filter, watch=False)
    except Exception as e:
        console.print(f"[red]Error scanning cluster: {e}[/red]")
        raise click.Abort()

    for pod in pods.items:
        namespace = pod.metadata.namespace
        name = pod.metadata.name
        status = pod.status.phase

        # Aggregate resources from all containers
        total_cpu_request = 0.0
        total_cpu_limit = 0.0
        total_memory_request = 0.0
        total_memory_limit = 0.0
        has_limits = False

        for container in pod.spec.containers:
            if container.resources.requests:
                if "cpu" in container.resources.requests:
                    total_cpu_request += parse_resource_value(container.resources.requests["cpu"], "cpu")
                if "memory" in container.resources.requests:
                    total_memory_request += parse_resource_value(container.resources.requests["memory"], "memory")

            if container.resources.limits:
                has_limits = True
                if "cpu" in container.resources.limits:
                    total_cpu_limit += parse_resource_value(container.resources.limits["cpu"], "cpu")
                if "memory" in container.resources.limits:
                    total_memory_limit += parse_resource_value(container.resources.limits["memory"], "memory")

        monthly_cost = calculate_monthly_cost(total_cpu_request, total_memory_request, cpu_price, mem_price)

        pod_info = PodResourceInfo(
            namespace=namespace,
            name=name,
            status=status,
            cpu_request=total_cpu_request,
            cpu_limit=total_cpu_limit if has_limits and total_cpu_limit > 0 else None,
            memory_request=total_memory_request,
            memory_limit=total_memory_limit if has_limits and total_memory_limit > 0 else None,
            monthly_cost=monthly_cost,
            issues=[],
            recommendations=[]
        )

        issues, recommendations, _ = detect_waste_and_recommendations(pod_info)
        pod_info.issues = issues
        pod_info.recommendations = recommendations

        pods_data.append(pod_info)

    return pods_data


def generate_mock_data(cpu_price: float, mem_price: float) -> List[PodResourceInfo]:
    """Generate realistic mock data for demo mode."""
    namespaces = ["production", "staging", "development", "monitoring", "kube-system"]
    apps = ["web-api", "worker", "cache", "database", "frontend", "backend", "scheduler"]
    statuses = ["Running", "Running", "Running", "Running", "Pending", "CrashLoopBackOff"]

    pods_data = []

    for _ in range(30):
        namespace = random.choice(namespaces)
        app = random.choice(apps)
        name = f"{app}-{random.randint(1000, 9999)}"
        status = random.choice(statuses)

        # Simulate different resource patterns
        pattern = random.choice(["normal", "no_requests", "wasteful", "high_resources"])

        if pattern == "no_requests":
            cpu_request = 0.0
            memory_request = 0.0
            cpu_limit = None
            memory_limit = None
        elif pattern == "wasteful":
            cpu_request = random.uniform(0.1, 0.5)
            memory_request = random.uniform(0.5, 2.0)
            cpu_limit = cpu_request * random.uniform(5.0, 10.0)
            memory_limit = memory_request * random.uniform(5.0, 10.0)
        elif pattern == "high_resources":
            cpu_request = random.uniform(2.0, 4.0)
            memory_request = random.uniform(8.0, 16.0)
            cpu_limit = cpu_request * random.uniform(1.2, 2.0)
            memory_limit = memory_request * random.uniform(1.2, 2.0)
        else:  # normal
            cpu_request = random.uniform(0.1, 1.0)
            memory_request = random.uniform(0.256, 4.0)
            cpu_limit = cpu_request * random.uniform(1.5, 3.0) if random.random() > 0.3 else None
            memory_limit = memory_request * random.uniform(1.5, 3.0) if random.random() > 0.3 else None

        monthly_cost = calculate_monthly_cost(cpu_request, memory_request, cpu_price, mem_price)

        pod_info = PodResourceInfo(
            namespace=namespace,
            name=name,
            status=status,
            cpu_request=round(cpu_request, 3),
            cpu_limit=round(cpu_limit, 3) if cpu_limit else None,
            memory_request=round(memory_request, 3),
            memory_limit=round(memory_limit, 3) if memory_limit else None,
            monthly_cost=round(monthly_cost, 2),
            issues=[],
            recommendations=[]
        )

        issues, recommendations, _ = detect_waste_and_recommendations(pod_info)
        pod_info.issues = issues
        pod_info.recommendations = recommendations

        pods_data.append(pod_info)

    return pods_data


def calculate_namespace_summaries(pods: List[PodResourceInfo], cpu_price: float, mem_price: float) -> List[NamespaceSummary]:
    """Calculate namespace-level summaries."""
    namespace_data = {}

    for pod in pods:
        if pod.namespace not in namespace_data:
            namespace_data[pod.namespace] = {
                "pods": [],
                "total_cpu": 0.0,
                "total_memory": 0.0,
                "total_cost": 0.0,
                "total_issues": 0
            }

        ns = namespace_data[pod.namespace]
        ns["pods"].append(pod)
        ns["total_cpu"] += pod.cpu_request
        ns["total_memory"] += pod.memory_request
        ns["total_cost"] += pod.monthly_cost
        ns["total_issues"] += len(pod.issues)

    summaries = []
    for namespace, data in namespace_data.items():
        # Calculate potential savings (rough estimate)
        potential_savings = sum(
            detect_waste_and_recommendations(pod)[2] for pod in data["pods"]
        )

        summaries.append(NamespaceSummary(
            namespace=namespace,
            pod_count=len(data["pods"]),
            total_cpu_request=round(data["total_cpu"], 2),
            total_memory_request=round(data["total_memory"], 2),
            monthly_cost=round(data["total_cost"], 2),
            potential_savings=round(potential_savings, 2),
            issue_count=data["total_issues"]
        ))

    return sorted(summaries, key=lambda x: x.monthly_cost, reverse=True)


def calculate_cluster_summary(pods: List[PodResourceInfo], namespace_summaries: List[NamespaceSummary]) -> ClusterSummary:
    """Calculate cluster-wide summary."""
    return ClusterSummary(
        total_namespaces=len(namespace_summaries),
        total_pods=len(pods),
        total_cpu_request=round(sum(ns.total_cpu_request for ns in namespace_summaries), 2),
        total_memory_request=round(sum(ns.total_memory_request for ns in namespace_summaries), 2),
        monthly_cost=round(sum(ns.monthly_cost for ns in namespace_summaries), 2),
        potential_savings=round(sum(ns.potential_savings for ns in namespace_summaries), 2),
        total_issues=sum(ns.issue_count for ns in namespace_summaries)
    )


def render_table_output(pods: List[PodResourceInfo], namespace_summaries: List[NamespaceSummary], cluster_summary: ClusterSummary):
    """Render rich terminal table output."""
    # Cluster overview panel
    overview = f"""[bold]Total Pods:[/bold] {cluster_summary.total_pods}
[bold]Namespaces:[/bold] {cluster_summary.total_namespaces}
[bold]Total CPU Requests:[/bold] {cluster_summary.total_cpu_request} cores
[bold]Total Memory Requests:[/bold] {cluster_summary.total_memory_request:.1f} GB
[bold]Estimated Monthly Cost:[/bold] ${cluster_summary.monthly_cost:,.2f}
[bold]Potential Savings:[/bold] ${cluster_summary.potential_savings:,.2f}
[bold]Total Issues Found:[/bold] {cluster_summary.total_issues}"""

    console.print(Panel(overview, title="[bold cyan]Cluster Overview[/bold cyan]", box=box.ROUNDED))
    console.print()

    # Namespace summary table
    ns_table = Table(title="Namespace Cost Summary", box=box.ROUNDED)
    ns_table.add_column("Namespace", style="cyan")
    ns_table.add_column("Pods", justify="right")
    ns_table.add_column("CPU (cores)", justify="right")
    ns_table.add_column("Memory (GB)", justify="right")
    ns_table.add_column("Monthly Cost", justify="right", style="green")
    ns_table.add_column("Potential Savings", justify="right", style="yellow")
    ns_table.add_column("Issues", justify="right", style="red")

    for ns in namespace_summaries:
        ns_table.add_row(
            ns.namespace,
            str(ns.pod_count),
            f"{ns.total_cpu_request:.2f}",
            f"{ns.total_memory_request:.1f}",
            f"${ns.monthly_cost:,.2f}",
            f"${ns.potential_savings:,.2f}",
            str(ns.issue_count)
        )

    console.print(ns_table)
    console.print()

    # Wasteful pods table (pods with issues)
    wasteful_pods = [p for p in pods if p.issues]
    if wasteful_pods:
        waste_table = Table(title=f"Wasteful/Problematic Pods ({len(wasteful_pods)} found)", box=box.ROUNDED)
        waste_table.add_column("Namespace", style="cyan")
        waste_table.add_column("Pod", style="yellow")
        waste_table.add_column("Status")
        waste_table.add_column("CPU Req", justify="right")
        waste_table.add_column("Mem Req (GB)", justify="right")
        waste_table.add_column("Cost/mo", justify="right")
        waste_table.add_column("Issues", style="red")

        for pod in sorted(wasteful_pods, key=lambda x: len(x.issues), reverse=True)[:20]:  # Top 20
            status_style = "green" if pod.status == "Running" else "red"
            waste_table.add_row(
                pod.namespace,
                pod.name[:30],
                f"[{status_style}]{pod.status}[/{status_style}]",
                f"{pod.cpu_request:.2f}",
                f"{pod.memory_request:.1f}",
                f"${pod.monthly_cost:.2f}",
                f"{len(pod.issues)}"
            )

        console.print(waste_table)


def render_json_output(pods: List[PodResourceInfo], namespace_summaries: List[NamespaceSummary], cluster_summary: ClusterSummary):
    """Render JSON output."""
    output = {
        "cluster_summary": asdict(cluster_summary),
        "namespace_summaries": [asdict(ns) for ns in namespace_summaries],
        "pods": [asdict(pod) for pod in pods]
    }
    console.print(json.dumps(output, indent=2))


def render_markdown_output(pods: List[PodResourceInfo], namespace_summaries: List[NamespaceSummary], cluster_summary: ClusterSummary):
    """Render Markdown output."""
    md = f"""# Kubernetes Cost Radar Report

## Cluster Overview
- **Total Pods:** {cluster_summary.total_pods}
- **Namespaces:** {cluster_summary.total_namespaces}
- **Total CPU Requests:** {cluster_summary.total_cpu_request} cores
- **Total Memory Requests:** {cluster_summary.total_memory_request:.1f} GB
- **Estimated Monthly Cost:** ${cluster_summary.monthly_cost:,.2f}
- **Potential Savings:** ${cluster_summary.potential_savings:,.2f}
- **Total Issues Found:** {cluster_summary.total_issues}

## Namespace Cost Summary

| Namespace | Pods | CPU (cores) | Memory (GB) | Monthly Cost | Potential Savings | Issues |
|-----------|------|-------------|-------------|--------------|-------------------|--------|
"""

    for ns in namespace_summaries:
        md += f"| {ns.namespace} | {ns.pod_count} | {ns.total_cpu_request:.2f} | {ns.total_memory_request:.1f} | ${ns.monthly_cost:,.2f} | ${ns.potential_savings:,.2f} | {ns.issue_count} |\n"

    wasteful_pods = [p for p in pods if p.issues]
    if wasteful_pods:
        md += f"\n## Wasteful/Problematic Pods ({len(wasteful_pods)} found)\n\n"
        md += "| Namespace | Pod | Status | CPU Req | Mem Req (GB) | Cost/mo | Issues |\n"
        md += "|-----------|-----|--------|---------|--------------|---------|--------|\n"

        for pod in sorted(wasteful_pods, key=lambda x: len(x.issues), reverse=True)[:20]:
            md += f"| {pod.namespace} | {pod.name} | {pod.status} | {pod.cpu_request:.2f} | {pod.memory_request:.1f} | ${pod.monthly_cost:.2f} | {len(pod.issues)} |\n"

    console.print(md)


@click.group()
def cli():
    """k8s-cost-radar: Kubernetes resource & cost analysis CLI tool"""
    pass


@cli.command()
@click.option("--namespace", default="all", help="Namespace to scan (default: all)")
@click.option("--output", type=click.Choice(["table", "json", "md"]), default="table", help="Output format")
@click.option("--cpu-price", default=0.048, type=float, help="CPU price per vCPU-hour (default: $0.048)")
@click.option("--mem-price", default=0.006, type=float, help="Memory price per GB-hour (default: $0.006)")
def scan(namespace: str, output: str, cpu_price: float, mem_price: float):
    """Scan cluster and analyze resource usage & costs."""
    console.print(f"[cyan]Scanning Kubernetes cluster (namespace: {namespace})...[/cyan]")

    pods = scan_kubernetes_cluster(cpu_price, mem_price, namespace)
    namespace_summaries = calculate_namespace_summaries(pods, cpu_price, mem_price)
    cluster_summary = calculate_cluster_summary(pods, namespace_summaries)

    if output == "table":
        render_table_output(pods, namespace_summaries, cluster_summary)
    elif output == "json":
        render_json_output(pods, namespace_summaries, cluster_summary)
    elif output == "md":
        render_markdown_output(pods, namespace_summaries, cluster_summary)


@cli.command()
@click.option("--output", type=click.Choice(["table", "json", "md"]), default="table", help="Output format")
@click.option("--cpu-price", default=0.048, type=float, help="CPU price per vCPU-hour")
@click.option("--mem-price", default=0.006, type=float, help="Memory price per GB-hour")
def summary(output: str, cpu_price: float, mem_price: float):
    """Show high-level cluster cost overview."""
    console.print("[cyan]Generating cluster summary...[/cyan]")

    pods = scan_kubernetes_cluster(cpu_price, mem_price, "all")
    namespace_summaries = calculate_namespace_summaries(pods, cpu_price, mem_price)
    cluster_summary = calculate_cluster_summary(pods, namespace_summaries)

    if output == "table":
        overview = f"""[bold]Total Pods:[/bold] {cluster_summary.total_pods}
[bold]Namespaces:[/bold] {cluster_summary.total_namespaces}
[bold]Total CPU Requests:[/bold] {cluster_summary.total_cpu_request} cores
[bold]Total Memory Requests:[/bold] {cluster_summary.total_memory_request:.1f} GB
[bold]Estimated Monthly Cost:[/bold] ${cluster_summary.monthly_cost:,.2f}
[bold]Potential Savings:[/bold] ${cluster_summary.potential_savings:,.2f}
[bold]Total Issues Found:[/bold] {cluster_summary.total_issues}"""

        console.print(Panel(overview, title="[bold cyan]Cluster Summary[/bold cyan]", box=box.ROUNDED))
    elif output == "json":
        console.print(json.dumps(asdict(cluster_summary), indent=2))
    elif output == "md":
        console.print(f"""# Cluster Summary
- **Total Pods:** {cluster_summary.total_pods}
- **Namespaces:** {cluster_summary.total_namespaces}
- **Total CPU Requests:** {cluster_summary.total_cpu_request} cores
- **Total Memory Requests:** {cluster_summary.total_memory_request:.1f} GB
- **Estimated Monthly Cost:** ${cluster_summary.monthly_cost:,.2f}
- **Potential Savings:** ${cluster_summary.potential_savings:,.2f}
- **Total Issues Found:** {cluster_summary.total_issues}""")


@cli.command()
@click.option("--output", type=click.Choice(["table", "json", "md"]), default="table", help="Output format")
@click.option("--cpu-price", default=0.048, type=float, help="CPU price per vCPU-hour")
@click.option("--mem-price", default=0.006, type=float, help="Memory price per GB-hour")
def wasteful(output: str, cpu_price: float, mem_price: float):
    """Show only wasteful/problematic workloads."""
    console.print("[cyan]Finding wasteful workloads...[/cyan]")

    pods = scan_kubernetes_cluster(cpu_price, mem_price, "all")
    wasteful_pods = [p for p in pods if p.issues]

    if not wasteful_pods:
        console.print("[green]No wasteful workloads found! Cluster looks healthy.[/green]")
        return

    if output == "table":
        table = Table(title=f"Wasteful/Problematic Pods ({len(wasteful_pods)} found)", box=box.ROUNDED)
        table.add_column("Namespace", style="cyan")
        table.add_column("Pod", style="yellow")
        table.add_column("Issues", style="red")
        table.add_column("Recommendations", style="green")

        for pod in sorted(wasteful_pods, key=lambda x: len(x.issues), reverse=True):
            table.add_row(
                pod.namespace,
                pod.name,
                "\n".join(f"• {issue}" for issue in pod.issues),
                "\n".join(f"• {rec}" for rec in pod.recommendations)
            )

        console.print(table)
    elif output == "json":
        console.print(json.dumps([asdict(p) for p in wasteful_pods], indent=2))
    elif output == "md":
        md = f"# Wasteful/Problematic Pods ({len(wasteful_pods)} found)\n\n"
        for pod in wasteful_pods:
            md += f"## {pod.namespace}/{pod.name}\n"
            md += f"**Issues:**\n"
            for issue in pod.issues:
                md += f"- {issue}\n"
            md += f"\n**Recommendations:**\n"
            for rec in pod.recommendations:
                md += f"- {rec}\n"
            md += "\n"
        console.print(md)


@cli.command()
@click.option("--output", type=click.Choice(["table", "json", "md"]), default="table", help="Output format")
@click.option("--cpu-price", default=0.048, type=float, help="CPU price per vCPU-hour")
@click.option("--mem-price", default=0.006, type=float, help="Memory price per GB-hour")
def demo(output: str, cpu_price: float, mem_price: float):
    """Run with mock data (no cluster required) - great for demos!"""
    console.print("[yellow]Running in DEMO mode with mock data...[/yellow]\n")

    pods = generate_mock_data(cpu_price, mem_price)
    namespace_summaries = calculate_namespace_summaries(pods, cpu_price, mem_price)
    cluster_summary = calculate_cluster_summary(pods, namespace_summaries)

    if output == "table":
        render_table_output(pods, namespace_summaries, cluster_summary)
    elif output == "json":
        render_json_output(pods, namespace_summaries, cluster_summary)
    elif output == "md":
        render_markdown_output(pods, namespace_summaries, cluster_summary)


if __name__ == "__main__":
    cli()
