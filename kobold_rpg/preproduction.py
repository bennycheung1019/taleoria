"""Local pre-production router for the experimental action workflow."""

from .condition_state_trial import make_condition_gm, UnsupportedSocialInteraction
from .engine import RuleError
from .gm import reply as legacy_reply


# These outcomes mean the experimental workflow has not adjudicated the turn.
# Other errors, especially failed validation after a decision, must stay errors.
UNSUPPORTED = frozenset({
    '此試驗目前只接通單一步驟。',
    '此動作尚未有安全的裁定及敘述流程。',
    '完整度只適用於已裁定的單一動作。',
})


def make_preproduction_gm(library, *, trial_factory=make_condition_gm,
                          fallback=legacy_reply):
    """Resolve the active campaign on each request, including after save loads."""
    def gm(state, text, base_url, recent=None, state_provenance=None):
        try:
            return trial_factory(library.engine)(
                state, text, base_url, recent=recent,
                state_provenance=state_provenance)
        except RuleError as exc:
            if not isinstance(exc,UnsupportedSocialInteraction) and str(exc) not in UNSUPPORTED:
                raise
        return fallback(state, text, base_url, recent=recent,
                        state_provenance=state_provenance)

    return gm
