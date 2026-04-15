"""Benchmark: Time to interact with Celesto computers.

Measures end-to-end latency from API call to usable result:
- Time to create (API call → computer running)
- Time to first exec (running → command result)
- Time to interactive (create → first command output)
- Exec latency (on a warm, running computer)
- Cleanup time

Usage:
    python benchmarks/time_to_interact.py
    python benchmarks/time_to_interact.py --runs 5 --cpus 2 --memory 2048
    python benchmarks/time_to_interact.py --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

from celesto.sdk import Celesto


def measure(fn, label: str = "") -> tuple[float, any]:
    """Run fn, return (elapsed_seconds, result)."""
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    return elapsed, result


def wait_for_status(client: Celesto, computer_id: str, target: str, timeout: float = 120) -> float:
    """Poll until computer reaches target status. Returns wait time."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        info = client.computers.get(computer_id)
        if info["status"] == target:
            return time.perf_counter() - start
        time.sleep(0.5)
    raise TimeoutError(f"Computer {computer_id} did not reach {target} in {timeout}s (status: {info['status']})")


def run_benchmark(client: Celesto, cpus: int, memory: int, run_index: int, verbose: bool = True) -> dict:
    """Run a single benchmark iteration."""
    results = {}

    if verbose:
        print(f"\n--- Run {run_index + 1} ---")

    # 1. Create computer
    if verbose:
        print("  Creating computer...", end=" ", flush=True)
    create_time, computer = measure(lambda: client.computers.create(cpus=cpus, memory=memory))
    computer_id = computer["id"]
    computer_name = computer.get("name", computer_id)
    results["create_api"] = round(create_time, 3)
    if verbose:
        print(f"{computer_name} ({create_time:.2f}s)")

    # 2. Wait for running
    if verbose:
        print("  Waiting for running...", end=" ", flush=True)
    if computer["status"] != "running":
        boot_time = wait_for_status(client, computer_id, "running")
    else:
        boot_time = 0.0
    results["boot_wait"] = round(boot_time, 3)
    results["time_to_running"] = round(create_time + boot_time, 3)
    if verbose:
        print(f"{boot_time:.2f}s (total: {create_time + boot_time:.2f}s)")

    # 3. First exec (cold — includes any startup latency)
    if verbose:
        print("  First exec...", end=" ", flush=True)
    first_exec_time, first_result = measure(
        lambda: client.computers.exec(computer_id, "echo hello")
    )
    results["first_exec"] = round(first_exec_time, 3)
    results["time_to_interact"] = round(create_time + boot_time + first_exec_time, 3)
    first_ok = first_result.get("exit_code") == 0 and "hello" in first_result.get("stdout", "")
    if verbose:
        status = "✓" if first_ok else "✗"
        print(f"{first_exec_time:.2f}s {status}")

    # 4. Warm exec (multiple iterations for avg latency)
    exec_times = []
    for i in range(5):
        t, r = measure(lambda: client.computers.exec(computer_id, "echo pong"))
        exec_times.append(t)
    results["exec_avg"] = round(statistics.mean(exec_times), 3)
    results["exec_p50"] = round(statistics.median(exec_times), 3)
    results["exec_min"] = round(min(exec_times), 3)
    results["exec_max"] = round(max(exec_times), 3)
    if verbose:
        print(f"  Warm exec (5x): avg={results['exec_avg']:.3f}s p50={results['exec_p50']:.3f}s min={results['exec_min']:.3f}s max={results['exec_max']:.3f}s")

    # 5. Complex exec (real workload)
    complex_time, complex_result = measure(
        lambda: client.computers.exec(computer_id, "python3 -c \"import json; print(json.dumps({'ok': True}))\"")
    )
    results["complex_exec"] = round(complex_time, 3)
    if verbose:
        print(f"  Complex exec (python3): {complex_time:.2f}s")

    # 6. Delete
    if verbose:
        print("  Deleting...", end=" ", flush=True)
    delete_time, _ = measure(lambda: client.computers.delete(computer_id))
    results["delete_api"] = round(delete_time, 3)
    if verbose:
        print(f"{delete_time:.2f}s")

    results["computer_name"] = computer_name
    results["computer_id"] = computer_id
    return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark Celesto computer time-to-interact")
    parser.add_argument("--runs", type=int, default=3, help="Number of benchmark iterations")
    parser.add_argument("--cpus", type=int, default=1, help="vCPUs per computer")
    parser.add_argument("--memory", type=int, default=1024, help="Memory in MB per computer")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--api-key", type=str, default=None, help="Celesto API key")
    args = parser.parse_args()

    verbose = not args.json

    if verbose:
        print("=" * 60)
        print("Celesto Computer — Time to Interact Benchmark")
        print("=" * 60)
        print(f"  Runs:   {args.runs}")
        print(f"  CPUs:   {args.cpus}")
        print(f"  Memory: {args.memory} MB")

    with Celesto(api_key=args.api_key) as client:
        all_results = []
        for i in range(args.runs):
            try:
                result = run_benchmark(client, args.cpus, args.memory, i, verbose=verbose)
                all_results.append(result)
            except Exception as e:
                if verbose:
                    print(f"  ✗ Run {i + 1} failed: {e}")
                all_results.append({"error": str(e)})

    # Aggregate
    successful = [r for r in all_results if "error" not in r]
    if not successful:
        if args.json:
            print(json.dumps({"error": "All runs failed", "runs": all_results}, indent=2))
        else:
            print("\n✗ All runs failed.")
        sys.exit(1)

    summary = {}
    for key in ["time_to_running", "time_to_interact", "first_exec", "exec_avg", "exec_p50", "complex_exec", "create_api", "boot_wait", "delete_api"]:
        values = [r[key] for r in successful if key in r]
        if values:
            summary[key] = {
                "avg": round(statistics.mean(values), 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
            }

    if args.json:
        print(json.dumps({"summary": summary, "runs": all_results, "config": {"cpus": args.cpus, "memory": args.memory, "runs": args.runs}}, indent=2))
    else:
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"  {'Metric':<25} {'Avg':>8} {'Min':>8} {'Max':>8}")
        print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8}")
        labels = {
            "time_to_running": "Time to running",
            "time_to_interact": "Time to interact",
            "first_exec": "First exec latency",
            "exec_avg": "Warm exec latency",
            "exec_p50": "Warm exec p50",
            "complex_exec": "Complex exec (python3)",
            "create_api": "Create API call",
            "boot_wait": "Boot wait",
            "delete_api": "Delete API call",
        }
        for key, label in labels.items():
            if key in summary:
                s = summary[key]
                print(f"  {label:<25} {s['avg']:>7.3f}s {s['min']:>7.3f}s {s['max']:>7.3f}s")

        print(f"\n  Successful runs: {len(successful)}/{len(all_results)}")


if __name__ == "__main__":
    main()
