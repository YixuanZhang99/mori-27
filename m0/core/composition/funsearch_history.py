"""Reconstruct island state from ordered, independently authenticated events."""
from core.funsearch_population import FunSearchPopulation
from core.funsearch_selection import draw_selection
from core.x1.checkpoint import payload_digest


class FunSearchHistory:
    def __init__(self, config):
        self.population = FunSearchPopulation(**config)
        self.pending = None
        self.candidate_id = None
        self.evidence_refs = {}

    def consume(self, kind, value, *, eligible=None):
        if kind == 'funsearch_selection':
            if (self.pending is not None or type(value) is not dict or
                    set(value) != {'candidate_id', 'selection'} or
                    type(value['candidate_id']) is not str or not value['candidate_id'] or
                    value['candidate_id'] in self.evidence_refs):
                raise ValueError('invalid FunSearch historical selection')
            selection = value['selection']
            if type(selection) is not dict or set(selection) != {'receipt', 'before', 'after'}:
                raise ValueError('invalid FunSearch historical draw')
            receipt = selection['receipt']
            supplied = receipt.get('eligible') if type(receipt) is dict else None
            if (type(supplied) is not list or any(type(x) is not str for x in supplied) or
                    supplied != sorted(set(supplied)) or not set(supplied) <= set(self.evidence_refs) or
                    eligible is not None and supplied != sorted(eligible)):
                raise ValueError('FunSearch historical eligible parents differ')
            before = self.population.checkpoint_state()
            actual = draw_selection(self.population, None, eligible=set(supplied), max_parents=2)
            expected = {'before': before, 'receipt': actual, 'after': self.population.checkpoint_state()}
            if payload_digest(selection) != payload_digest(expected):
                raise ValueError('FunSearch draw differs from reconstructed history')
            self.pending, self.candidate_id = expected, value['candidate_id']
            return actual['ancestry']
        if kind == 'funsearch_public_candidate':
            if (type(value) is not dict or set(value) != {
                    'candidate_id', 'program_ref', 'program_length', 'scores', 'evidence_ref'} or
                    value['candidate_id'] in self.evidence_refs or
                    self.pending is not None and value['candidate_id'] != self.candidate_id):
                raise ValueError('invalid FunSearch historical registration')
            receipt = self.pending['receipt'] if self.pending is not None else None
            self.population.register_projection(value['candidate_id'],
                **{key: value[key] for key in ('program_ref', 'program_length', 'scores')},
                island=receipt['island'] if receipt else None, epoch=receipt['epoch'] if receipt else None)
            self.evidence_refs[value['candidate_id']] = value['evidence_ref']
            self.pending, self.candidate_id = None, None
        elif kind == 'funsearch_reset':
            if self.pending is not None:
                raise ValueError('FunSearch historical reset overlaps selection')
            before = self.population.checkpoint_state()
            events = self.population.reset_weaker_half()
            expected = {'before': before, 'events': events, 'after': self.population.checkpoint_state()}
            if payload_digest(value) != payload_digest(expected):
                raise ValueError('FunSearch reset differs from reconstructed history')
        elif kind == 'funsearch_abandonment':
            if (self.pending is None or type(value) is not dict or
                    set(value) != {'selection_ref', 'reason'} or
                    value['reason'] not in {'evaluation_failed', 'stale_epoch'} or
                    value['selection_ref'] != 'sha256:' + payload_digest(self.pending)):
                raise ValueError('FunSearch abandonment differs from reconstructed history')
            self.pending, self.candidate_id = None, None

    def verify_policy(self, policy):
        actual = policy.checkpoint_state()
        expected = {'population': self.population.checkpoint_state(), 'pending': self.pending,
                    'evidence_refs': self.evidence_refs, 'pending_reset': None, 'pending_abandonment': None}
        if payload_digest({key: actual[key] for key in expected}) != payload_digest(expected):
            raise ValueError('FunSearch policy differs from reconstructed history')
