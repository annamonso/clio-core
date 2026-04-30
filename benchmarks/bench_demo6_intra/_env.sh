#!/usr/bin/env bash
# Source this to load the bench_demo6_intra env.
# Allocation 12514: ares-comp-[12-16]. Reuses the star sweep's allocation.
# Single planner agent runs on ares-comp-13.
export LEADER_HOST=ares-comp-12
export LEADER_PORT=5050
export LEADER_JOB=12514
export PLANNER_HOST=ares-comp-13
export PLANNER_JOB=12514
export ANTHROPIC_API_KEY="$(cat "$HOME/.anthropic_key")"
export PYTHONUNBUFFERED=1
