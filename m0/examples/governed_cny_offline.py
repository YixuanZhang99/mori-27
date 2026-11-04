"""Standalone offline CNY bridge example: loopback HTTP and a temporary fixture ledger.

No real model request, real campaign migration, or invoice claim. Use a new
--workdir; the script demonstrates pause, resume and recorded replay together.
"""
from __future__ import annotations
import argparse
import json
import re
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from core.composition.defaults import composed_profile, default_registry
from core.composition.evaluation import EvaluationContract, binding_for
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.loop import Framework, LoopConfig
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.governed_currency import CNYInvocationBridge
from zoo.mle_bench_lite.governed_provider import GovernedCNYProvider

TASK = "Return candidate_value=N, where N is an integer from 0 through 100. Aim for 73."
MEASURED_UNITS = ("token", "node", "eval_count")
BOUND = 1048580

class IntegerDomain:
    """Canonical development evaluation with an explicit content identity."""

    evaluator_version = "integer-distance-v1"
    evaluation_context = "sha256:" + hashlib.sha256(b"integer-distance-v1;target=73;range=0..100").hexdigest()
    measured_cost_units = MEASURED_UNITS

    def validate_request(self, request):
        request.validate()
        if request.fidelity != "dev" or request.split_id != "dev" or request.resume_from is not None:
            raise ValueError("integer fixture supports only development evaluation")

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        match = re.fullmatch(r"candidate_value=(\d{1,3})", proposal.artifact.strip())
        value = int(match.group(1)) if match else None
        valid = value is not None and 0 <= value <= 100
        metrics = {"dev/score": 1.0 - abs(value - 73) / 100.0} if valid else {}
        return EvalResult(
            EvalStatus.OK if valid else EvalStatus.INVALID,
            metrics=metrics, cost=CostVec(eval_count=1), fidelity=request.fidelity,
            text_feedback=f"Development target is 73; candidate value is {value}.",
            contract=EvaluationContract(binding_for(proposal, request,
                evaluator_version=self.evaluator_version,
                evaluation_context=self.evaluation_context), MEASURED_UNITS))

class CountedProvider(GovernedCNYProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http_attempts = 0

    def perform_request(self, body):
        self.http_attempts += 1
        return super().perform_request(body)

def campaign_fixture(path):
    campaign = CampaignBudget.create(path / 'campaign.db', limit_micro_cny=200000000)
    campaign.enable_governance(expected_policy_sha256=campaign.manifest_binding()['policy_sha256'],
                               expected_head=campaign.snapshot()['journal_head'])
    return campaign

def framework(path, campaign, endpoint, *, pause=None, resume=False, tokens=10000000):
    bridge_type = CNYInvocationBridge
    registry = default_registry()
    registry.install_external_bridge('cny_invocation_v1', lambda: bridge_type(campaign))
    sessions = []
    frozen_campaign = campaign.manifest_binding()
    def fresh():
        value = CountedProvider('deepseek-flash', endpoint.url,
            campaign_binding=frozen_campaign, max_completion_tokens=4,
            timeout=2, api_key='fixture-only-secret')
        sessions.append(value)
        return value
    main = fresh()
    registry.register('provider', 'governed-cny-fixture', lambda ctx, opts: fresh(),
                      governance=main.governance_binding())
    registry.register('domain', 'integer-fixture', lambda ctx, opts: IntegerDomain(),
                      governance={'schema_version': 1, 'fresh_session': True, 'state_independent': True})
    profile = composed_profile(name='governed-cny-loopback-fixture')
    profile['domain'] = {'name': 'native'}
    profile['budget'] = {'name': 'hierarchical', 'options': {
        'limits': {'global': {'token': tokens, 'node': 20, 'eval_count': 20},
                   'direction': {'token': 10000000, 'node': 20, 'eval_count': 20},
                   'candidate': {'token': 10000000, 'node': 20, 'eval_count': 20}},
        'reservation': {'token': 0, 'node': 0, 'eval_count': 1},
        'operation_reservations': {
            'planning': {'token': 0, 'node': 0, 'eval_count': 0},
            'operator': {'token': BOUND, 'node': 1, 'eval_count': 0}},
        'fidelity_rungs': [{'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [1]}]}}
    profile['governance'] = {'schema_version': 1, 'controls': {
        'after_main_cycles': [0, 2], 'seed': 7,
        'provider': {'name': 'governed-cny-fixture'},
        'domain': {'name': 'integer-fixture'},
        'operator': {'name': 'draft'},
        'request': {'fidelity': 'dev', 'split_id': 'dev', 'seed_set': [1]},
        'reservations': {'operator': {'token': BOUND, 'node': 1, 'eval_count': 0},
                         'evaluation': {'token': 0, 'node': 0, 'eval_count': 1}}}}
    config = LoopConfig(max_generations=1, total_budget=tokens, reeval_floor=0,
                        stop_after_generation=pause, resume_from_checkpoint=resume)
    fw = Framework.from_profile(profile, main, IntegerDomain(), config, str(path),
                                component_registry=registry)
    return fw, sessions

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workdir', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.workdir.exists() and any(args.workdir.iterdir()):
        parser.error('offline example requires a new empty workdir')
    args.workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.rfile.read(int(self.headers['Content-Length'])))
            response = {'model': 'deepseek-flash',
                'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7},
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'candidate_value=73'}}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        endpoint = SimpleNamespace(url=f'http://127.0.0.1:{server.server_port}/v1')
        campaign = campaign_fixture(args.workdir)
        paused, _ = framework(args.workdir / 'run', campaign, endpoint, pause=0)
        paused.evolve(TASK)
        assert paused.inspect()['governance']['pending'] == 1
        resumed, _ = framework(args.workdir / 'run', campaign, endpoint, resume=True)
        result = resumed.evolve(TASK)
        before = campaign.snapshot()
        count = len(requests)
        replay = resumed.replay(TASK)['replay_certificate']
        assert replay['passed'] and replay['external_calls'] == 0
        assert count == len(requests) == 4
        assert campaign.snapshot() == before
        assert before['settled_upper_bound_micro_cny'] == 152
        assert not before['pending_calls']
        assert result['governance']['completed'] == 2
        print(json.dumps({'runtime': result['runtime'], 'controls_completed': 2,
            'loopback_http_requests': count, 'external_model_requests': 0,
            'fixture_settled_micro_cny': 152, 'recorded_replay_passed': True,
            'replay_new_http_requests': 0, 'replay_currency_events_changed': False,
            'workdir': str(args.workdir.resolve()),
            'notice': 'Synthetic usage on a new fixture ledger; no real spend or invoice certification.'},
            indent=2, sort_keys=True))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
