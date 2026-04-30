#!/usr/bin/env bash
# Source this to load the bench_demo6_star env.
# Allocation 12514: ares-comp-[12-16]
export LEADER_HOST=ares-comp-12
export LEADER_PORT=5050
export LEADER_JOB=12514
export CONTROLLER_HOST=ares-comp-13
export CONTROLLER_JOB=12514
export WORKER_HOSTS=ares-comp-14,ares-comp-15,ares-comp-16
export WORKER_JOB=12514
export ANTHROPIC_API_KEY="$(cat "$HOME/.anthropic_key")"
export PYTHONUNBUFFERED=1
